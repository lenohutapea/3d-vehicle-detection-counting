"""
calibration.py - UTAMA 1: kalibrasi kamera per node.

Tiga cara kalibrasi:
  1. klik pada gambar (utama) : dua garis marka sejajar + satu lebar + satu panjang nyata
                                -> click_calibration.py membuat berkas kalibrasi (disimpan sebagai mode "xml")
  2. mode "nilai"             : isi manual sudut kamera, tinggi, dan focal length
  3. mode "xml" (lanjutan)    : impor berkas kalibrasi BrnoCompSpeed (<f>, <h>, <vanishPoints>)
Urutan profil yang dipakai (yang paling bawah menimpa yang di atasnya):
  1. nilai bawaan pipeline (centernet3d_bbox/pipeline/config.py)
  2. profil BAWAAN node: camera_profiles/<node>.json        (masuk Git, TIDAK pernah ditulis server)
  3. hasil kalibrasi di web: data/calibration/<node>/active.json
Setiap kali Simpan, kalibrasi dicatat sebagai versi baru data/calibration/<node>/<YYYYMMDD_HHMMSS>.json
(berkas XML unggahan ikut: <YYYYMMDD_HHMMSS>.xml). Versi lama tidak ditimpa dan bisa dipakai lagi.
Profil ini dipakai oleh alur Otomatis (2_automatic) dan Manual (3_manual) saat memproses video.
Isi ini berasal dari layanan.py lama (bagian 2. profil kamera).
"""
import json
import os
import subprocess
import tempfile
import time

from settings import (KAL_DATA, KALIBRASI, PIPELINE, PYTHON, VERSI_SAH, Salah, _baca_json, _cek_node, _jalur_profil,
                      _sumber_video, _tulis_json, cfg, daftar_versi, kembali_bawaan, pakai_versi, simpan_versi)

KUNCI_PROFIL = ("PITCH_DEG", "CAM_HEIGHT_M", "FOCAL_PX", "LANE_HALF_WIDTH_M", "MAX_TRACK_DEPTH_M",
                "LINE_Y_DEFAULT_M", "LINE_Y_AWAY_M", "MEDIAN_X_M")
BATAS_PROFIL = {"PITCH_DEG": (0.0, 89.0), "CAM_HEIGHT_M": (1.0, 60.0), "FOCAL_PX": (100.0, 20000.0),
                "LANE_HALF_WIDTH_M": (2.0, 60.0), "MAX_TRACK_DEPTH_M": (10.0, 400.0),
                "LINE_Y_DEFAULT_M": (3.0, 300.0), "LINE_Y_AWAY_M": (3.0, 300.0), "MEDIAN_X_M": (-60.0, 60.0)}
PRATINJAU = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration_preview.py")
KUNCI_KLIK = ("A", "B", "P")


def _profil_bawaan():
    p = {k: float(getattr(cfg, k)) for k in KUNCI_PROFIL if hasattr(cfg, k)}
    p.setdefault("LINE_Y_AWAY_M", p.get("LINE_Y_DEFAULT_M", 50.0))
    p.setdefault("MEDIAN_X_M", 0.0)
    xml = getattr(cfg, "CALIB_XML", None)
    p["mode"] = "xml" if xml else "nilai"
    p["CALIB_XML"] = xml
    p["LAJUR"] = "kiri"            # Indonesia; profil bawaan session0_right (data Ceko) berisi "kanan"
    p["tersimpan"] = None
    return p


def _folder(node_id):
    return os.path.join(KAL_DATA, node_id)


def _xml_mutlak(x):
    """CALIB_XML di profil bawaan boleh relatif terhadap folder 1_camera_calibration (mis. xml/a.xml)."""
    return os.path.join(KALIBRASI, x) if x and not os.path.isabs(x) else x


def _susun(node_id, lapisan):
    """nilai config.py <- profil bawaan node <- lapisan (satu versi kalibrasi dari data/, atau None)."""
    p = _profil_bawaan()
    p["sumber_profil"], p["versi"] = "config", None
    bawaan = _baca_json(_jalur_profil(node_id))
    if bawaan:
        p.update(bawaan)
        p["sumber_profil"] = "bawaan"
    else:                                   # node tanpa profil bawaan: jangan pakai berkas kalibrasi kamera lain
        p["mode"], p["CALIB_XML"] = "nilai", None
    if lapisan:
        p.update(lapisan)
        p["sumber_profil"] = "riwayat"
    p["versi"] = lapisan.get("versi") if lapisan else None
    p["metode"] = "klik" if p.get("klik") else p.get("mode", "nilai")
    p["CALIB_XML"] = _xml_mutlak(p.get("CALIB_XML"))
    p["ada_xml"] = bool(p.get("CALIB_XML") and os.path.exists(p["CALIB_XML"]))
    return p


def profil(node_id):
    """Profil yang SEDANG DIPAKAI node ini (dipakai rekaman otomatis dan sebagai bawaan halaman Proses)."""
    _cek_node(node_id)
    return _susun(node_id, _baca_json(os.path.join(_folder(node_id), "active.json")))


def profil_versi(node_id, versi=None):
    """Profil untuk satu pemrosesan: versi kosong = yang sedang dipakai, "bawaan" = tanpa kalibrasi dari web,
    selain itu = versi tertentu dari riwayat (tanpa mengubah versi yang sedang dipakai)."""
    _cek_node(node_id)
    if not versi:
        return profil(node_id)
    if versi == "bawaan":
        return _susun(node_id, None)
    p = os.path.join(_folder(node_id), versi + ".json")
    if not VERSI_SAH.match(versi) or not os.path.exists(p):
        raise Salah("Versi kalibrasi tidak ditemukan: %s" % versi)
    return _susun(node_id, _baca_json(p))


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
    """data: nilai formulir; xml: isi berkas kalibrasi (bytes) bila diunggah.
    Disimpan sebagai versi baru di data/calibration/<node>/; profil bawaan tidak diubah."""
    _cek_node(node_id)
    p = _rapikan_profil(node_id, data, profil(node_id))
    if xml:
        _cek_xml(xml)
        jalur = os.path.join(_folder(node_id), time.strftime("%Y%m%d_%H%M%S") + ".xml")
        os.makedirs(os.path.dirname(jalur), exist_ok=True)
        with open(jalur, "wb") as f:
            f.write(xml)
        p["CALIB_XML"] = jalur
    if p["mode"] == "xml" and not (p.get("CALIB_XML") and os.path.exists(p["CALIB_XML"])):
        raise Salah("Mode berkas kalibrasi dipilih, tetapi berkasnya belum diunggah.")
    klik = _rapikan_klik(data.get("klik")) if data.get("klik") else None
    if klik and p["mode"] == "xml":
        p["klik"] = klik
    else:
        p.pop("klik", None)
    p["tersimpan"] = time.strftime("%Y-%m-%d %H:%M:%S")
    for k in ("ada_xml", "sumber_profil", "versi", "metode"):
        p.pop(k, None)
    simpan_versi(_folder(node_id), p)
    return profil(node_id)


def riwayat(node_id):
    """Daftar versi kalibrasi node ini, terbaru di depan."""
    _cek_node(node_id)
    out = []
    for v in daftar_versi(_folder(node_id)):
        i = v["isi"]
        out.append({"versi": v["versi"], "aktif": v["aktif"], "tersimpan": i.get("tersimpan"), "mode": i.get("mode"),
                    "metode": "klik" if i.get("klik") else i.get("mode"),
                    **{k: i.get(k) for k in KUNCI_PROFIL}})
    return out


def pakai(node_id, versi):
    _cek_node(node_id)
    pakai_versi(_folder(node_id), versi)
    return profil(node_id)


def ke_bawaan(node_id):
    _cek_node(node_id)
    kembali_bawaan(_folder(node_id))
    return profil(node_id)


def _rapikan_klik(isi):
    """Data kalibrasi klik dari formulir (JSON) -> dict yang diperiksa: A, B, P (2 titik), lebar, panjang."""
    try:
        d = json.loads(isi) if isinstance(isi, str) else dict(isi)
        out = {k: [[float(t[0]), float(t[1])] for t in d[k]] for k in KUNCI_KLIK}
        if any(len(out[k]) != 2 for k in KUNCI_KLIK):
            raise ValueError
        out["lebar"], out["panjang"] = float(d["lebar"]), float(d["panjang"])
    except (TypeError, ValueError, KeyError, IndexError):
        raise Salah("Data kalibrasi klik tidak lengkap.")
    if isinstance(d.get("hasil"), dict):
        out["hasil"] = {k: d["hasil"][k] for k in ("f", "h", "sudut_tunduk") if k in d["hasil"]}
    return out


def kalibrasi_klik(node_id, data):
    """Hitung kalibrasi dari klik. Belum disimpan: halaman web memakai hasilnya untuk pratinjau,
    lalu menyimpannya lewat simpan_profil bila pengguna menekan Simpan."""
    import click_calibration as K
    _cek_node(node_id)
    d = _rapikan_klik(data)
    try:
        r = K.hitung(d["A"], d["B"], d["P"], d["lebar"], d["panjang"], cfg.IMG_W, cfg.IMG_H)
    except K.GagalKalibrasi as e:
        raise Salah(str(e))
    xml = K.ke_xml(r, cfg.IMG_W, cfg.IMG_H, getattr(cfg, "CALIB_REF_SIZE", (1920, 1080)))
    return {"xml": xml.decode(), "hasil": r,
            "nilai": {"PITCH_DEG": round(r["sudut_tunduk"], 2), "CAM_HEIGHT_M": round(r["h"], 2),
                      "FOCAL_PX": round(r["f"], 1)}}


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


def profil_pipeline(p):
    """Bentuk yang dibaca config.py pipeline lewat variabel lingkungan PROFIL_KAMERA."""
    out = {k: p[k] for k in KUNCI_PROFIL if k in p}
    out["CALIB_XML"] = p.get("CALIB_XML") if p.get("mode") == "xml" else None
    out["LAJUR"] = p.get("LAJUR", "kiri")
    return out


def pratinjau(node_id, data, sumber, posisi=0.5, xml=None):
    """Gambar JPG: frame video dengan kisi jalan, garis hitung, dan kotak mobil acuan untuk profil yang
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
        _tulis_json(os.path.join(d, "profil.json"), profil_pipeline(p))
        r = subprocess.run([PYTHON, PRATINJAU, os.path.join(d, "frame.jpg"), os.path.join(d, "hasil.jpg")],
                           cwd=PIPELINE, env=dict(os.environ, PROFIL_KAMERA=os.path.join(d, "profil.json")),
                           capture_output=True, timeout=60)
        if r.returncode != 0:
            raise Salah("Pratinjau gagal: " + r.stderr.decode(errors="replace")[-300:])
        return open(os.path.join(d, "hasil.jpg"), "rb").read()
