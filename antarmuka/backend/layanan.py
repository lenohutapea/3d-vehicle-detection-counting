"""
layanan.py - logika antarmuka. Tidak bergantung pada FastAPI, sehingga bisa diuji sendiri.

Bagian:
  1. Setelan server        data/setelan.json (jadwal otomatis, daftar node, token node) - diubah dengan tangan
  2. Profil kamera         data/kamera/<node>.json - kalibrasi dan garis hitung per node (halaman Kalibrasi)
  3. Rekaman               ~/projects/video_rekaman/<node>/<tanggal>_<jam>_<mode>.mp4
  4. Node (Raspberry Pi)   node menanyakan tugas, merekam, lalu mengunggah (lihat ../node/node_kamera.py)
  5. Pekerjaan (job)       satu video diproses run.py; satu per satu (antrean)
  6. Ringkasan hasil       dari counting_log.csv

Folder tiap job: ~/projects/hasil/antarmuka/<id>/  (status.json, hasil.mp4, counting_log.csv, ringkasan.json, keluaran.txt)
"""

import csv
import hmac
import importlib.util
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time

PROYEK = os.path.expanduser(os.environ.get("ANTARMUKA_PROYEK", "~/projects"))
PIPELINE = os.environ.get("ANTARMUKA_PIPELINE", os.path.join(PROYEK, "uji_session0_pipeline"))
ANTARMUKA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_APP = os.environ.get("ANTARMUKA_DATA", os.path.join(ANTARMUKA, "data"))
DATA = os.path.join(PROYEK, "hasil", "antarmuka")          # hasil tiap job
VIDEO_DIR = os.path.join(PROYEK, "video_uji")              # video contoh
REKAMAN = os.path.join(PROYEK, "video_rekaman")            # rekaman dari node
MODEL_DIR = os.path.join(PROYEK, "bobot", "detektor")
MODEL_BAWAAN = "centernet_dari_baru.pth"
PYTHON = sys.executable
EKSTENSI = (".mp4", ".avi", ".mov", ".mkv")
MAKS_UNGGAH = 500 * 1024 * 1024
CACHE_KHUSUS = {("uji_val_720p.mp4", MODEL_BAWAAN): "det_session0.pkl"}   # cache deteksi yang sudah ada
ID_SAH = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
NODE_SAH = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
NAMA_REKAMAN = re.compile(r"^(\d{8})_(\d{6})_(otomatis|manual)\.mp4$")
POLA_PROGRES = re.compile(rb"(\d+)/(\d+) \[")
KUNCI_PROFIL = ("PITCH_DEG", "CAM_HEIGHT_M", "FOCAL_PX", "LANE_HALF_WIDTH_M", "MAX_TRACK_DEPTH_M",
                "LINE_Y_DEFAULT_M", "LINE_Y_AWAY_M", "MEDIAN_X_M")
BATAS_PROFIL = {"PITCH_DEG": (0.0, 89.0), "CAM_HEIGHT_M": (1.0, 60.0), "FOCAL_PX": (100.0, 20000.0),
                "LANE_HALF_WIDTH_M": (2.0, 60.0), "MAX_TRACK_DEPTH_M": (10.0, 400.0),
                "LINE_Y_DEFAULT_M": (3.0, 300.0), "LINE_Y_AWAY_M": (3.0, 300.0), "MEDIAN_X_M": (-60.0, 60.0)}

_kunci = threading.RLock()
_jobs = {}                 # id -> status
_antrean = queue.Queue()
_pekerja = None
_terlihat = {}             # node -> waktu terakhir node menghubungi server
_permintaan = []           # permintaan rekam manual: {id, node, durasi_detik, status, dibuat}


def _muat_config():
    """config.py milik pipeline, TANPA profil kamera (nilai bawaan pipeline)."""
    lama = os.environ.pop("PROFIL_KAMERA", None)
    try:
        spec = importlib.util.spec_from_file_location("config_pipeline", os.path.join(PIPELINE, "config.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if lama is not None:
            os.environ["PROFIL_KAMERA"] = lama
    return mod


cfg = _muat_config()


class Salah(ValueError):
    """Masukan tidak sah; pesannya ditampilkan ke pengguna."""


def _tulis_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _baca_json(path, bawaan=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return bawaan


def _hex(bgr):
    b, g, r = bgr
    return "#%02x%02x%02x" % (r, g, b)


# ====================================================================== 1. setelan server
def setelan():
    """Setelan tetap server. Dibuat sekali dengan nilai bawaan; ubah dengan menyunting berkasnya."""
    p = os.path.join(DATA_APP, "setelan.json")
    s = _baca_json(p)
    if s is None:
        s = {
            "_keterangan": "Setelan tetap. Sunting berkas ini lalu mulai ulang server. Halaman web hanya menampilkan.",
            "izinkan_jaringan": False,
            "token_node": secrets.token_hex(16),
            "jadwal": {"video_per_hari": 6, "durasi_detik": 60, "jam_mulai": "06:00", "jam_selesai": "18:00"},
            "node": [{"id": "session0_right", "nama": "Latihan session0_right"},
                     {"id": "kamera1", "nama": "Kamera 1 (Raspberry Pi)"}],
        }
        _tulis_json(p, s)
    return s


def _menit(jam):
    h, m = jam.split(":")
    return int(h) * 60 + int(m)


def jadwal_harian():
    """Daftar jam mulai rekaman otomatis ('HH:MM'), tersebar rata di antara jam_mulai dan jam_selesai."""
    j = setelan()["jadwal"]
    n = max(0, int(j["video_per_hari"]))
    a, b = _menit(j["jam_mulai"]), _menit(j["jam_selesai"])
    if n == 0 or b <= a:
        return []
    return ["%02d:%02d" % divmod(int(a + i * (b - a) / n), 60) for i in range(n)]


def daftar_node():
    out = []
    for n in setelan()["node"]:
        t = _terlihat.get(n["id"])
        out.append({"id": n["id"], "nama": n.get("nama", n["id"]),
                    "terhubung": bool(t and time.time() - t < 20),
                    "terakhir": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else None,
                    "ada_profil": os.path.exists(_jalur_profil(n["id"]))})
    return out


def _cek_node(node_id):
    if not node_id or not NODE_SAH.match(node_id) or node_id not in [n["id"] for n in setelan()["node"]]:
        raise Salah("Node tidak dikenal: %s (daftarkan di data/setelan.json)." % node_id)
    return node_id


def daftar_model():
    if not os.path.isdir(MODEL_DIR):
        return []
    m = sorted(n for n in os.listdir(MODEL_DIR) if n.endswith(".pth"))
    return sorted(m, key=lambda n: n != MODEL_BAWAAN)       # bawaan di depan


def daftar_contoh():
    if not os.path.isdir(VIDEO_DIR):
        return []
    return sorted(n for n in os.listdir(VIDEO_DIR) if n.lower().endswith(EKSTENSI))


def info():
    run_py = open(os.path.join(PIPELINE, "run.py"), encoding="utf-8").read()
    cfg_py = open(os.path.join(PIPELINE, "config.py"), encoding="utf-8").read()
    masalah = []
    if '"--out"' not in run_py:
        masalah.append("run.py belum bisa menyimpan video (jalankan alat/pasang_video.py di folder pipeline).")
    if "PROFIL_KAMERA" not in cfg_py:
        masalah.append("config.py pipeline belum membaca profil kamera (jalankan ulang alat/pasang_antarmuka.py).")
    if not daftar_model():
        masalah.append("Tidak ada bobot .pth di " + MODEL_DIR)
    if not shutil.which("ffmpeg"):
        masalah.append("ffmpeg belum terpasang; video hasil mungkin tidak bisa diputar di peramban (sudo apt install ffmpeg).")
    warna = getattr(cfg, "CLASS_COLORS", {})
    s = setelan()
    return {
        "kelas": [{"nama": c, "warna": _hex(warna.get(c, (200, 200, 200)))} for c in cfg.CLASSES],
        "bawaan": {"conf": 0.4, "conf_low": 0.2},
        "model": daftar_model(),
        "contoh": daftar_contoh(),
        "node": daftar_node(),
        "jadwal": dict(s["jadwal"], jam=jadwal_harian()),
        "berkas_setelan": os.path.join(DATA_APP, "setelan.json"),
        "masalah": masalah,
    }


# ====================================================================== 2. profil kamera
def _jalur_profil(node_id):
    return os.path.join(DATA_APP, "kamera", node_id + ".json")


def _profil_bawaan():
    p = {k: float(getattr(cfg, k)) for k in KUNCI_PROFIL if hasattr(cfg, k)}
    p.setdefault("LINE_Y_AWAY_M", p.get("LINE_Y_DEFAULT_M", 50.0))
    p.setdefault("MEDIAN_X_M", 0.0)
    xml = getattr(cfg, "CALIB_XML", None)
    p["mode"] = "xml" if xml else "nilai"
    p["CALIB_XML"] = xml
    p["tersimpan"] = None
    return p


def profil(node_id):
    _cek_node(node_id)
    p = _profil_bawaan()
    p.update(_baca_json(_jalur_profil(node_id), {}))
    p["ada_xml"] = bool(p.get("CALIB_XML") and os.path.exists(p["CALIB_XML"]))
    return p


def _rapikan_profil(node_id, data, dasar):
    """Gabungkan nilai dari formulir ke profil `dasar`, dengan pemeriksaan batas."""
    p = dict(dasar)
    for k in KUNCI_PROFIL:
        if k in data and data[k] not in ("", None):
            try:
                v = float(data[k])
            except (TypeError, ValueError):
                raise Salah("Nilai %s bukan angka." % k)
            lo, hi = BATAS_PROFIL[k]
            if not lo <= v <= hi:
                raise Salah("Nilai %s harus di antara %g dan %g." % (k, lo, hi))
            p[k] = v
    mode = data.get("mode") or p.get("mode", "nilai")
    if mode not in ("nilai", "xml"):
        raise Salah("Mode kalibrasi tidak dikenal.")
    p["mode"] = mode
    return p


def simpan_profil(node_id, data, xml=None):
    """data: nilai formulir; xml: isi berkas kalibrasi (bytes) bila diunggah."""
    _cek_node(node_id)
    p = _rapikan_profil(node_id, data, profil(node_id))
    if xml:
        _cek_xml(xml)
        jalur = os.path.join(DATA_APP, "kamera", node_id + ".xml")
        os.makedirs(os.path.dirname(jalur), exist_ok=True)
        with open(jalur, "wb") as f:
            f.write(xml)
        p["CALIB_XML"] = jalur
    if p["mode"] == "xml" and not (p.get("CALIB_XML") and os.path.exists(p["CALIB_XML"])):
        raise Salah("Mode berkas kalibrasi dipilih, tetapi berkasnya belum diunggah.")
    p["tersimpan"] = time.strftime("%Y-%m-%d %H:%M:%S")
    p.pop("ada_xml", None)
    _tulis_json(_jalur_profil(node_id), p)
    return profil(node_id)


def _cek_xml(isi):
    import xml.etree.ElementTree as ET
    if len(isi) > 1024 * 1024:
        raise Salah("Berkas kalibrasi terlalu besar.")
    try:
        akar = ET.fromstring(isi)
        float(akar.findtext("f"))
        float(akar.findtext("h"))
        if len(akar.findtext("vanishPoints").split()) < 4:
            raise ValueError
    except Exception:
        raise Salah("Berkas kalibrasi tidak dikenali. Yang didukung: XML dengan <f>, <h>, dan <vanishPoints> "
                    "(format calibParams BrnoCompSpeed).")


def _profil_pipeline(p):
    """Bentuk yang dibaca config.py pipeline lewat variabel lingkungan PROFIL_KAMERA."""
    out = {k: p[k] for k in KUNCI_PROFIL if k in p}
    out["CALIB_XML"] = p.get("CALIB_XML") if p.get("mode") == "xml" else None
    return out


def _sumber_video(sumber):
    """sumber = 'contoh/<nama>' atau 'rekaman/<node>/<nama>' -> jalur berkas."""
    bagian = (sumber or "").split("/")
    if len(bagian) == 2 and bagian[0] == "contoh" and bagian[1] in daftar_contoh():
        return os.path.join(VIDEO_DIR, bagian[1])
    if len(bagian) == 3 and bagian[0] == "rekaman" and NODE_SAH.match(bagian[1]) and NAMA_REKAMAN.match(bagian[2]):
        p = os.path.join(REKAMAN, bagian[1], bagian[2])
        if os.path.exists(p):
            return p
    raise Salah("Video tidak ditemukan.")


def pratinjau(node_id, data, sumber, posisi=0.5, xml=None):
    """Gambar PNG: frame video dengan kisi jalan, garis hitung, dan kotak mobil acuan untuk profil yang
    sedang disunting (belum tentu tersimpan). Geometri dihitung oleh kode pipeline sendiri."""
    import cv2
    _cek_node(node_id)
    p = _rapikan_profil(node_id, data, profil(node_id))
    video = _sumber_video(sumber)
    with tempfile.TemporaryDirectory() as d:
        if xml:
            _cek_xml(xml)
            p["CALIB_XML"] = os.path.join(d, "kalibrasi.xml")
            open(p["CALIB_XML"], "wb").write(xml)
        if p["mode"] == "xml" and not (p.get("CALIB_XML") and os.path.exists(p["CALIB_XML"])):
            raise Salah("Mode berkas kalibrasi dipilih, tetapi berkasnya belum diunggah.")
        cap = cv2.VideoCapture(video)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(n - 1, int(n * min(max(float(posisi), 0.0), 1.0)))))
        ok, fr = cap.read()
        cap.release()
        if not ok:
            raise Salah("Frame video tidak bisa dibaca.")
        fr = cv2.resize(fr, (cfg.IMG_W, cfg.IMG_H), interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(d, "frame.jpg"), fr)
        _tulis_json(os.path.join(d, "profil.json"), _profil_pipeline(p))
        r = subprocess.run(
            [PYTHON, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pratinjau_kalibrasi.py"),
             os.path.join(d, "frame.jpg"), os.path.join(d, "hasil.jpg")],
            cwd=PIPELINE, env=dict(os.environ, PROFIL_KAMERA=os.path.join(d, "profil.json")),
            capture_output=True, timeout=60)
        if r.returncode != 0:
            raise Salah("Pratinjau gagal: " + r.stderr.decode(errors="replace")[-300:])
        return open(os.path.join(d, "hasil.jpg"), "rb").read()


# ====================================================================== 3. rekaman
def daftar_rekaman(node_id=None):
    dipakai = {}
    with _kunci:
        for j in _jobs.values():
            if j.get("sumber", "").startswith("rekaman/"):
                dipakai.setdefault(j["sumber"], []).append({"id": j["id"], "status": j["status"]})
    out = []
    for n in ([node_id] if node_id else [x["id"] for x in setelan()["node"]]):
        d = os.path.join(REKAMAN, n)
        if not NODE_SAH.match(n) or not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            m = NAMA_REKAMAN.match(f)
            if not m:
                continue
            tgl, jam, mode = m.groups()
            sumber = "rekaman/%s/%s" % (n, f)
            out.append({"sumber": sumber, "node": n, "nama": f, "mode": mode,
                        "waktu": "%s-%s-%s %s:%s:%s" % (tgl[:4], tgl[4:6], tgl[6:], jam[:2], jam[2:4], jam[4:]),
                        "ukuran_mb": round(os.path.getsize(os.path.join(d, f)) / 1048576, 1),
                        "job": dipakai.get(sumber, [])})
    return sorted(out, key=lambda r: r["waktu"], reverse=True)


def simpan_rekaman(node_id, berkas, mode, nama_asli="rekaman.mp4"):
    """Simpan rekaman (dari node atau unggahan manual di peramban). Mengembalikan 'rekaman/<node>/<nama>'."""
    _cek_node(node_id)
    if mode not in ("otomatis", "manual"):
        raise Salah("Mode rekaman tidak dikenal.")
    if os.path.splitext(nama_asli or "")[1].lower() not in EKSTENSI:
        raise Salah("Jenis berkas tidak didukung. Pakai: " + ", ".join(EKSTENSI))
    d = os.path.join(REKAMAN, node_id)
    os.makedirs(d, exist_ok=True)
    while True:
        nama = time.strftime("%Y%m%d_%H%M%S_") + mode + ".mp4"
        if not os.path.exists(os.path.join(d, nama)):
            break
        time.sleep(1)
    sementara = os.path.join(d, nama + ".bagian")
    total = 0
    try:
        with open(sementara, "wb") as f:
            while True:
                potong = berkas.read(1024 * 1024)
                if not potong:
                    break
                total += len(potong)
                if total > MAKS_UNGGAH:
                    raise Salah("Berkas terlalu besar (maksimum %d MB)." % (MAKS_UNGGAH // 1048576))
                f.write(potong)
        if total == 0:
            raise Salah("Berkas kosong.")
        tujuan = os.path.join(d, nama)
        if os.path.splitext(nama_asli)[1].lower() == ".mp4" or not shutil.which("ffmpeg"):
            os.replace(sementara, tujuan)
        else:                                   # samakan wadah menjadi mp4
            r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", sementara, "-an", "-c:v", "libx264",
                                "-preset", "veryfast", "-pix_fmt", "yuv420p", tujuan])
            if r.returncode != 0:
                raise Salah("Video tidak bisa dibaca.")
    finally:
        if os.path.exists(sementara):
            os.remove(sementara)
    return "rekaman/%s/%s" % (node_id, nama)


def hapus_rekaman(sumber):
    p = _sumber_video(sumber)
    if not sumber.startswith("rekaman/"):
        raise Salah("Hanya rekaman yang bisa dihapus.")
    with _kunci:
        if any(j.get("sumber") == sumber and j["status"] in ("antre", "proses") for j in _jobs.values()):
            raise Salah("Rekaman ini sedang diproses.")
    os.remove(p)
    for f in os.listdir(os.path.dirname(p)):               # cache deteksi milik rekaman itu
        if f.startswith(os.path.basename(p) + ".") and f.endswith(".det.pkl"):
            os.remove(os.path.join(os.path.dirname(p), f))


# ====================================================================== 4. node (Raspberry Pi)
def token_sah(token):
    return bool(token) and hmac.compare_digest(str(token), str(setelan()["token_node"]))


def minta_rekam(node_id, durasi):
    """Dari halaman web: minta node merekam sekarang. Node mengambil permintaan ini saat menanyakan tugas."""
    _cek_node(node_id)
    try:
        durasi = int(float(durasi))
    except (TypeError, ValueError):
        raise Salah("Durasi bukan angka.")
    if not 5 <= durasi <= 1800:
        raise Salah("Durasi harus 5 sampai 1800 detik.")
    r = {"id": secrets.token_hex(4), "node": node_id, "durasi_detik": durasi, "status": "menunggu node",
         "dibuat": time.strftime("%Y-%m-%d %H:%M:%S"), "t": time.time()}
    with _kunci:
        _permintaan.append(r)
        del _permintaan[:-50]
    return r


def daftar_permintaan(node_id=None):
    with _kunci:
        for r in _permintaan:                       # node tidak pernah mengambil / tidak pernah mengirim
            if r["status"] in ("menunggu node", "merekam") and time.time() - r["t"] > r["durasi_detik"] + 600:
                r["status"] = "gagal (node tidak menjawab)"
        return [dict(r) for r in reversed(_permintaan) if node_id in (None, r["node"])]


def _slot_terisi(node_id, tanggal):
    """Jam jadwal hari ini yang rekamannya sudah diterima (agar tidak direkam dua kali)."""
    return _baca_json(os.path.join(REKAMAN, node_id, "slot_%s.json" % tanggal), [])


def node_tugas(node_id):
    """Dipanggil node tiap beberapa detik. Mengembalikan jadwal hari ini dan permintaan manual yang menunggu."""
    _cek_node(node_id)
    _terlihat[node_id] = time.time()
    manual = []
    with _kunci:
        for r in _permintaan:
            if r["node"] == node_id and r["status"] == "menunggu node":
                r["status"] = "merekam"
                manual.append({"id": r["id"], "durasi_detik": r["durasi_detik"]})
    tanggal = time.strftime("%Y%m%d")
    return {"waktu_server": time.strftime("%Y-%m-%d %H:%M:%S"), "tanggal": tanggal,
            "durasi_detik": int(setelan()["jadwal"]["durasi_detik"]), "jadwal": jadwal_harian(),
            "sudah": _slot_terisi(node_id, tanggal), "manual": manual}


def node_unggah(node_id, berkas, mode, slot="", id_permintaan="", nama_asli="rekaman.mp4"):
    """Node mengirim hasil rekaman. Otomatis -> langsung diproses. Manual -> disimpan saja."""
    _cek_node(node_id)
    _terlihat[node_id] = time.time()
    tanggal = time.strftime("%Y%m%d")
    if mode == "otomatis":
        if slot not in jadwal_harian():
            raise Salah("Jam jadwal tidak dikenal: %s" % slot)
        if slot in _slot_terisi(node_id, tanggal):
            raise Salah("Rekaman untuk jadwal %s sudah diterima." % slot)
    sumber = simpan_rekaman(node_id, berkas, mode, nama_asli)
    hasil = {"sumber": sumber}
    if mode == "otomatis":
        _tulis_json(os.path.join(REKAMAN, node_id, "slot_%s.json" % tanggal), _slot_terisi(node_id, tanggal) + [slot])
        try:
            hasil["job"] = buat_job(sumber=sumber, node_id=node_id)["id"]
        except Exception as e:                    # rekaman tetap tersimpan walau gagal masuk antrean
            hasil["galat"] = str(e)
    else:
        with _kunci:
            for r in _permintaan:
                if r["id"] == id_permintaan:
                    r["status"] = "selesai"
                    r["sumber"] = sumber
    return hasil


# ====================================================================== 5. pekerjaan (job)
def _folder(job_id):
    return os.path.join(DATA, job_id)


def _simpan(st):
    _tulis_json(os.path.join(_folder(st["id"]), "status.json"), st)


def _ubah(job_id, **kw):
    with _kunci:
        st = _jobs[job_id]
        st.update(kw)
        _simpan(st)


def muat_dari_disk():
    """Saat server mulai: baca job lama; job yang terputus ditandai gagal."""
    os.makedirs(DATA, exist_ok=True)
    setelan()
    with _kunci:
        for n in sorted(os.listdir(DATA)):
            st = _baca_json(os.path.join(DATA, n, "status.json"))
            if not ID_SAH.match(n) or not st:
                continue
            _jobs[n] = st
            if st.get("status") in ("antre", "proses"):
                st.update(status="gagal", tahap="Gagal", pesan="Server dimulai ulang saat video ini sedang diproses.")
                _simpan(st)


def _ringkas_status(st):
    return {k: st.get(k) for k in ("id", "nama_video", "sumber", "node", "model", "dibuat", "waktu_video", "status",
                                   "tahap", "progres", "total", "per_kelas", "pemicu")}


def daftar_job():
    with _kunci:
        return sorted((_ringkas_status(s) for s in _jobs.values()), key=lambda s: s["id"], reverse=True)


def ambil_job(job_id):
    with _kunci:
        st = _jobs.get(job_id)
        if st is None:
            return None
        st = dict(st)
    if st["status"] == "selesai":
        st["ringkasan"] = _baca_json(os.path.join(_folder(job_id), "ringkasan.json"))
    return st


def jalur_berkas(job_id, nama):
    if not ID_SAH.match(job_id) or nama not in ("hasil.mp4", "counting_log.csv", "keluaran.txt"):
        return None
    p = os.path.join(_folder(job_id), nama)
    return p if os.path.exists(p) else None


def hapus_job(job_id):
    with _kunci:
        st = _jobs.get(job_id)
        if st is None:
            return "tidak ada"
        if st["status"] in ("antre", "proses"):
            return "sedang berjalan"
        del _jobs[job_id]
    shutil.rmtree(_folder(job_id), ignore_errors=True)
    return "ok"


def _angka(nilai, bawaan, lo, hi):
    try:
        v = float(nilai)
    except (TypeError, ValueError):
        return bawaan
    return min(max(v, lo), hi)


def buat_job(sumber, node_id, model=None, conf=None, conf_low=None, pemicu=None):
    """sumber: 'contoh/<nama>' atau 'rekaman/<node>/<nama>'. Profil kamera diambil dari node_id."""
    _cek_node(node_id)
    video = _sumber_video(sumber)
    model = model or (daftar_model() or [None])[0]
    if model not in daftar_model():
        raise Salah("Bobot model tidak ditemukan: %s" % model)
    b = info()["bawaan"]
    s = {"conf": _angka(conf, b["conf"], 0.05, 0.95), "conf_low": _angka(conf_low, b["conf_low"], 0.0, 0.9)}
    if s["conf_low"] >= s["conf"]:
        raise Salah("Ambang rendah harus lebih kecil dari ambang deteksi (atau 0 untuk mematikan).")
    p = profil(node_id)
    if p["mode"] == "xml" and not p["ada_xml"]:
        raise Salah("Profil kamera %s memakai berkas kalibrasi yang tidak ada. Buka halaman Kalibrasi." % node_id)

    m = NAMA_REKAMAN.match(os.path.basename(video))
    if m:
        t, j = m.group(1), m.group(2)
        waktu_video = "%s-%s-%s %s:%s:%s" % (t[:4], t[4:6], t[6:], j[:2], j[2:4], j[4:])
        pemicu = pemicu or m.group(3)
    else:
        waktu_video = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(video)))
        pemicu = pemicu or "contoh"
    job_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
    os.makedirs(_folder(job_id))
    _tulis_json(os.path.join(_folder(job_id), "profil.json"), _profil_pipeline(p))
    st = {"id": job_id, "nama_video": os.path.basename(video), "sumber": sumber, "node": node_id, "model": model,
          "dibuat": time.strftime("%Y-%m-%d %H:%M:%S"), "waktu_video": waktu_video, "pemicu": pemicu,
          "status": "antre", "tahap": "Menunggu giliran", "progres": 0.0, "setelan": s,
          "garis": {"mendekat": p["LINE_Y_DEFAULT_M"], "menjauh": p["LINE_Y_AWAY_M"], "median": p["MEDIAN_X_M"]},
          "masukan": video, "cache": _jalur_cache(video, model), "pesan": ""}
    with _kunci:
        _jobs[job_id] = st
        _simpan(st)
    _mulai_pekerja()
    _antrean.put(job_id)
    return dict(st)


def _jalur_cache(video, model):
    """Cache deteksi bergantung pada video DAN model, jadi nama model ikut di nama berkas."""
    khusus = CACHE_KHUSUS.get((os.path.basename(video), model))
    if khusus and os.path.exists(os.path.join(os.path.dirname(video), khusus)):
        return os.path.join(os.path.dirname(video), khusus)
    return "%s.%s.det.pkl" % (video, os.path.splitext(model)[0])


def _mulai_pekerja():
    global _pekerja
    with _kunci:
        if _pekerja is None or not _pekerja.is_alive():
            _pekerja = threading.Thread(target=_putaran, daemon=True)
            _pekerja.start()


def _putaran():
    while True:
        job_id = _antrean.get()
        try:
            _kerjakan(job_id)
        except Exception as e:
            try:
                _ubah(job_id, status="gagal", tahap="Gagal", pesan="Galat internal: %s" % e)
            except Exception:
                pass


def _siapkan_video(job_id, jalur):
    """Pastikan video berukuran IMG_W x IMG_H; bila tidak, buat salinan yang diubah ukurannya."""
    import cv2
    cap = cv2.VideoCapture(jalur)
    if not cap.isOpened():
        raise RuntimeError("Video tidak bisa dibuka.")
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n, fps = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), cap.get(cv2.CAP_PROP_FPS)
    fps = fps if fps and fps > 1 else 25.0
    if (w, h) == (cfg.IMG_W, cfg.IMG_H):
        cap.release()
        return jalur, n, fps
    _ubah(job_id, tahap="Mengubah ukuran video ke %dx%d" % (cfg.IMG_W, cfg.IMG_H))
    baru = os.path.join(_folder(job_id), "masukan_%dp.mp4" % cfg.IMG_H)
    out = cv2.VideoWriter(baru, cv2.VideoWriter_fourcc(*"mp4v"), fps, (cfg.IMG_W, cfg.IMG_H))
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        out.write(cv2.resize(fr, (cfg.IMG_W, cfg.IMG_H), interpolation=cv2.INTER_AREA))
        i += 1
        if i % 25 == 0 and n:
            _ubah(job_id, progres=round(0.1 * i / n, 3))
    cap.release()
    out.release()
    return baru, i, fps


def _kerjakan(job_id):
    st = ambil_job(job_id)
    if st is None:
        return
    folder, s = _folder(job_id), st["setelan"]
    _ubah(job_id, status="proses", tahap="Menyiapkan video", mulai=time.time())
    if not os.path.exists(st["masukan"]):
        _ubah(job_id, status="gagal", tahap="Gagal", pesan="Berkas video sudah tidak ada.")
        return
    try:
        video, n_frame, fps = _siapkan_video(job_id, st["masukan"])
    except Exception as e:
        _ubah(job_id, status="gagal", tahap="Gagal", pesan=str(e))
        return
    pakai_cache = os.path.exists(st["cache"])
    _ubah(job_id, frame_total=n_frame, fps=fps,
          tahap="Melacak dan menghitung (deteksi dari cache)" if pakai_cache else "Mendeteksi kendaraan (tanpa GPU, lambat)")

    cmd = [PYTHON, "run.py", video, os.path.join(MODEL_DIR, st["model"]), "--no-show",
           "--out", os.path.join(folder, "hasil.mp4"), "--cache", st["cache"], "--conf", str(s["conf"])]
    if s["conf_low"] > 0:
        cmd += ["--conf-low", str(s["conf_low"])]
    cmd += os.environ.get("ANTARMUKA_ARG_TAMBAHAN", "").split()   # mis. --tanpa-gambar
    env = dict(os.environ, PROFIL_KAMERA=os.path.join(folder, "profil.json"))
    log = open(os.path.join(folder, "keluaran.txt"), "wb")
    p = subprocess.Popen(cmd, cwd=PIPELINE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    baris, terakhir = b"", 0.0
    while True:
        c = p.stdout.read(1)
        if not c:
            break
        if c in (b"\r", b"\n"):
            m = POLA_PROGRES.search(baris)
            if m and int(m.group(2)) > 0:
                if time.time() - terakhir > 0.5:
                    terakhir = time.time()
                    _ubah(job_id, progres=round(0.1 + 0.85 * int(m.group(1)) / int(m.group(2)), 3))
            elif baris.strip():
                log.write(baris + b"\n")
                log.flush()
            baris = b""
        else:
            baris += c
    kode = p.wait()
    log.close()
    if kode != 0:
        ekor = open(os.path.join(folder, "keluaran.txt"), errors="replace").read()[-600:]
        _ubah(job_id, status="gagal", tahap="Gagal", pesan="Pipeline berhenti dengan galat:\n" + ekor)
        return
    try:
        shutil.copy(os.path.join(PIPELINE, cfg.COUNT_LOG), os.path.join(folder, "counting_log.csv"))
        r = ringkas(os.path.join(folder, "counting_log.csv"), fps, n_frame, st["garis"]["median"])
        _tulis_json(os.path.join(folder, "ringkasan.json"), r)
    except Exception as e:
        _ubah(job_id, status="gagal", tahap="Gagal", pesan="Hasil tidak bisa dibaca: %s" % e)
        return
    st2 = ambil_job(job_id)
    _ubah(job_id, status="selesai", tahap="Selesai", progres=1.0, total=r["total"], per_kelas=r["per_kelas"],
          lama_detik=round(time.time() - st2.get("mulai", time.time()), 1),
          ada_video=os.path.exists(os.path.join(folder, "hasil.mp4")))


# ====================================================================== 6. ringkasan hasil
def ringkas(csv_path, fps, n_frame, median=None):
    """Ringkas counting_log.csv: per kelas, per arah, per rentang waktu, dan daftar kendaraan."""
    kelas = list(cfg.CLASSES)
    durasi = n_frame / fps if fps else 0.0
    langkah = next((x for x in (5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600) if durasi / x <= 12), 3600)
    n_bak = max(1, int(durasi // langkah) + (1 if durasi % langkah else 0))
    waktu = [dict({"mulai": i * langkah}, **{c: 0 for c in kelas}) for i in range(n_bak)]
    per_kelas = {c: 0 for c in kelas}
    per_arah = {"mendekat": 0, "menjauh": 0}
    kendaraan = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            k = r["kelas"]
            if k not in per_kelas:
                continue
            fr, x = int(r["frame"]), float(r["x_m"])
            t = fr / fps if fps else 0.0
            arah = "menjauh" if (median is not None and x >= median) else "mendekat"
            per_kelas[k] += 1
            per_arah[arah] += 1
            waktu[min(int(t // langkah), n_bak - 1)][k] += 1
            skor = r.get("suara_" + k, "")
            kendaraan.append({"frame": fr, "detik": round(t, 2), "id": int(r["id"]), "kelas": k, "arah": arah,
                              "panjang_m": float(r["panjang_m"]), "x_m": x,
                              "skor": float(skor) if skor not in ("", None) else None})
    return {"total": len(kendaraan), "per_kelas": per_kelas, "per_arah": per_arah, "ada_arah": median is not None,
            "durasi_detik": round(durasi, 1), "langkah_detik": langkah, "per_waktu": waktu, "kendaraan": kendaraan}
