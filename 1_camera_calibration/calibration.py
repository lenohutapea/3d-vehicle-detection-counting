"""
calibration.py - UTAMA 1: kalibrasi kamera per node.

Dua cara kalibrasi:
  1. mode "xml"   : impor berkas kalibrasi (format calibParams BrnoCompSpeed: <f>, <h>, <vanishPoints>)
  2. mode "nilai" : isi manual sudut kamera, tinggi, focal length, lebar lajur, dan garis hitung
Profil disimpan di camera_profiles/<node>.json; berkas XML unggahan di xml/<node>.xml.
Profil ini dipakai oleh alur Otomatis (2_automatic) dan Manual (3_manual) saat memproses video.
Isi ini berasal dari layanan.py lama (bagian 2. profil kamera).
"""
import os
import subprocess
import tempfile
import time

from settings import (PIPELINE, PYTHON, XML_DIR, Salah, _baca_json, _cek_node, _jalur_profil, _sumber_video,
                      _tulis_json, cfg)

KUNCI_PROFIL = ("PITCH_DEG", "CAM_HEIGHT_M", "FOCAL_PX", "LANE_HALF_WIDTH_M", "MAX_TRACK_DEPTH_M",
                "LINE_Y_DEFAULT_M", "LINE_Y_AWAY_M", "MEDIAN_X_M")
BATAS_PROFIL = {"PITCH_DEG": (0.0, 89.0), "CAM_HEIGHT_M": (1.0, 60.0), "FOCAL_PX": (100.0, 20000.0),
                "LANE_HALF_WIDTH_M": (2.0, 60.0), "MAX_TRACK_DEPTH_M": (10.0, 400.0),
                "LINE_Y_DEFAULT_M": (3.0, 300.0), "LINE_Y_AWAY_M": (3.0, 300.0), "MEDIAN_X_M": (-60.0, 60.0)}
PRATINJAU = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration_preview.py")


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
        jalur = os.path.join(XML_DIR, node_id + ".xml")
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


def profil_pipeline(p):
    """Bentuk yang dibaca config.py pipeline lewat variabel lingkungan PROFIL_KAMERA."""
    out = {k: p[k] for k in KUNCI_PROFIL if k in p}
    out["CALIB_XML"] = p.get("CALIB_XML") if p.get("mode") == "xml" else None
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
