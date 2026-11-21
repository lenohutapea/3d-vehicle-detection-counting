"""
settings.py - pengaturan bersama antarmuka web: lokasi folder, setelan server, daftar node,
dan fungsi kecil yang dipakai semua bagian (baca/tulis JSON, pemeriksaan masukan).

Lokasi folder dihitung dari letak berkas ini, jadi proyek bisa dipindah ke mana saja:
    <ROOT>/web/backend/settings.py  ->  ROOT = tiga tingkat di atasnya
Isi ini berasal dari layanan.py lama (bagian 1. setelan server + fungsi bantu).
"""
import importlib.util
import json
import os
import queue
import re
import secrets
import shutil
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PIPELINE = os.environ.get("ANTARMUKA_PIPELINE", os.path.join(ROOT, "centernet3d_bbox", "pipeline"))
KALIBRASI = os.path.join(ROOT, "1_camera_calibration")
PROFIL_DIR = os.path.join(KALIBRASI, "camera_profiles")     # <node>.json
XML_DIR = os.path.join(KALIBRASI, "xml")                    # berkas kalibrasi bawaan (mis. session0_right)
JADWAL_FILE = os.path.join(ROOT, "2_automatic", "schedule.json")    # jadwal BAWAAN (tidak pernah diubah server)
DATA = os.environ.get("ANTARMUKA_DATA", os.path.join(ROOT, "data"))
KAL_DATA = os.path.join(DATA, "calibration")                # calibration/<node>/active.json + riwayat
JADWAL_DATA = os.path.join(DATA, "schedule")                # schedule/active.json + riwayat
SETELAN_FILE = os.path.join(DATA, "settings.json")
REKAMAN = os.path.join(DATA, "recordings")                  # recordings/<automatic|manual>/<node>/...
HASIL = os.path.join(DATA, "results")                       # results/<automatic|manual>/<job>/...
VIDEO_DIR = os.path.join(DATA, "test_videos")               # video contoh
MODEL_DIR = os.path.join(DATA, "weights", "detector")
MODEL_BAWAAN = "centernet_dari_baru.pth"
FOLDER_MODE = {"otomatis": "automatic", "manual": "manual"}  # mode di nama berkas -> nama folder
PYTHON = sys.executable
EKSTENSI = (".mp4", ".avi", ".mov", ".mkv")
NODE_SAH = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
NAMA_REKAMAN = re.compile(r"^(\d{8})_(\d{6})_(otomatis|manual)\.mp4$")
VERSI_SAH = re.compile(r"^\d{8}_\d{6}(_\d+)?$")

# keadaan bersama (dipakai beberapa modul; objeknya diubah isinya, tidak pernah diganti)
_kunci = threading.RLock()
_jobs = {}                 # id -> status
_antrean = queue.Queue()
_terlihat = {}             # node -> waktu terakhir node menghubungi server
_permintaan = []           # permintaan rekam manual: {id, node, durasi_detik, status, dibuat}


class Salah(ValueError):
    """Masukan tidak sah; pesannya ditampilkan ke pengguna."""


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


def _angka(nilai, bawaan, lo, hi):
    try:
        v = float(nilai)
    except (TypeError, ValueError):
        return bawaan
    return min(max(v, lo), hi)


JADWAL_BAWAAN = {"video_per_hari": 6, "durasi_detik": 60, "jam_mulai": "06:00", "jam_selesai": "18:00"}


def setelan():
    """Setelan tetap server (data/settings.json) + jadwal yang berlaku.
    Jadwal: data/schedule/active.json (diubah dari web) bila ada, selain itu jadwal bawaan
    2_automatic/schedule.json. Berkas bawaan tidak pernah ditulis oleh server."""
    s = _baca_json(SETELAN_FILE)
    if s is None:
        s = {
            "_keterangan": "Setelan tetap. Sunting berkas ini lalu mulai ulang server. Halaman web hanya menampilkan.",
            "izinkan_jaringan": False,
            "token_node": secrets.token_hex(16),
            "node": [{"id": "session0_right", "nama": "Latihan session0_right"},
                     {"id": "kamera1", "nama": "Kamera 1 (Raspberry Pi)"}],
        }
        _tulis_json(SETELAN_FILE, s)
    s = dict(s)
    aktif = _baca_json(os.path.join(JADWAL_DATA, "active.json"))
    if aktif:
        s["jadwal"], s["jadwal_sumber"] = aktif, "riwayat"
    else:
        s["jadwal"] = _baca_json(JADWAL_FILE) or s.get("jadwal") or dict(JADWAL_BAWAAN)
        s["jadwal_sumber"] = "bawaan"
    return s


# ---------------------------------------------------------------- versi (riwayat) JSON di data/
def simpan_versi(folder, obj):
    """Simpan obj sebagai versi baru <YYYYMMDD_HHMMSS>.json dan jadikan active.json.
    Versi lama tidak pernah ditimpa, sehingga bisa dipakai lagi."""
    os.makedirs(folder, exist_ok=True)
    dasar = time.strftime("%Y%m%d_%H%M%S")
    nama, i = dasar, 2
    while os.path.exists(os.path.join(folder, nama + ".json")):
        nama, i = "%s_%d" % (dasar, i), i + 1
    obj = dict(obj, versi=nama)
    _tulis_json(os.path.join(folder, nama + ".json"), obj)
    _tulis_json(os.path.join(folder, "active.json"), obj)
    return obj


def daftar_versi(folder):
    aktif = (_baca_json(os.path.join(folder, "active.json")) or {}).get("versi")
    out = []
    if os.path.isdir(folder):
        for f in sorted(os.listdir(folder), reverse=True):
            nama = f[:-5]
            if f.endswith(".json") and VERSI_SAH.match(nama):
                out.append({"versi": nama, "aktif": nama == aktif, "isi": _baca_json(os.path.join(folder, f), {})})
    return out


def pakai_versi(folder, versi):
    p = os.path.join(folder, (versi or "") + ".json")
    if not VERSI_SAH.match(versi or "") or not os.path.exists(p):
        raise Salah("Versi tidak ditemukan: %s" % versi)
    _tulis_json(os.path.join(folder, "active.json"), _baca_json(p))


def kembali_bawaan(folder):
    """Berhenti memakai versi dari riwayat (riwayatnya tetap disimpan)."""
    p = os.path.join(folder, "active.json")
    if os.path.exists(p):
        os.remove(p)


def _jalur_profil(node_id):
    """Profil BAWAAN node (1_camera_calibration/camera_profiles, tidak pernah ditulis server)."""
    return os.path.join(PROFIL_DIR, node_id + ".json")


def _jalur_profil_aktif(node_id):
    """Profil hasil kalibrasi di web (data/calibration/<node>/active.json)."""
    return os.path.join(KAL_DATA, node_id, "active.json")


def _cek_node(node_id):
    if not node_id or not NODE_SAH.match(node_id) or node_id not in [n["id"] for n in setelan()["node"]]:
        raise Salah("Node tidak dikenal: %s (daftarkan di halaman Kamera)." % node_id)
    return node_id


def daftar_node():
    """Semua kamera (yang nonaktif juga, ditandai aktif=False)."""
    out = []
    for n in setelan()["node"]:
        t = _terlihat.get(n["id"])
        out.append({"id": n["id"], "nama": n.get("nama", n["id"]),
                    "terhubung": bool(t and time.time() - t < 20),
                    "terakhir": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else None,
                    "ada_profil": os.path.exists(_jalur_profil(n["id"])) or os.path.exists(_jalur_profil_aktif(n["id"])),
                    "aktif": n.get("aktif", True), "jenis": n.get("jenis")})
    return out


def daftar_model():
    if not os.path.isdir(MODEL_DIR):
        return []
    m = sorted(n for n in os.listdir(MODEL_DIR) if n.endswith(".pth"))
    return sorted(m, key=lambda n: n != MODEL_BAWAAN)       # bawaan di depan


def daftar_contoh():
    if not os.path.isdir(VIDEO_DIR):
        return []
    return sorted(n for n in os.listdir(VIDEO_DIR) if n.lower().endswith(EKSTENSI))


def folder_rekaman(mode, node_id):
    """data/recordings/<automatic|manual>/<node>"""
    return os.path.join(REKAMAN, FOLDER_MODE[mode], node_id)


def _sumber_video(sumber):
    """sumber = 'contoh/<nama>' atau 'rekaman/<node>/<nama>' -> jalur berkas."""
    bagian = (sumber or "").split("/")
    if len(bagian) == 2 and bagian[0] == "contoh" and bagian[1] in daftar_contoh():
        return os.path.join(VIDEO_DIR, bagian[1])
    if len(bagian) == 3 and bagian[0] == "rekaman" and NODE_SAH.match(bagian[1]):
        m = NAMA_REKAMAN.match(bagian[2])
        if m:
            p = os.path.join(folder_rekaman(m.group(3), bagian[1]), bagian[2])
            if os.path.exists(p):
                return p
    raise Salah("Video tidak ditemukan.")


def info():
    import schedule                                  # 2_automatic/schedule.py
    run_py = open(os.path.join(PIPELINE, "run.py"), encoding="utf-8").read()
    cfg_py = open(os.path.join(PIPELINE, "config.py"), encoding="utf-8").read()
    masalah = []
    if '"--out"' not in run_py:
        masalah.append("run.py belum bisa menyimpan video.")
    if "PROFIL_KAMERA" not in cfg_py:
        masalah.append("config.py pipeline belum membaca profil kamera.")
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
        "jadwal": dict(s["jadwal"], jam=schedule.jadwal_harian()),
        "jadwal_sumber": s["jadwal_sumber"],
        "berkas_setelan": SETELAN_FILE,
        "masalah": masalah,
    }
