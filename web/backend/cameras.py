"""
cameras.py - kelola kamera (node) dari halaman web: tambah, ubah, nonaktifkan, hapus, dan token per kamera.

Daftar kamera tetap disimpan di data/settings.json bagian "node" (data, tidak masuk Git):
    {"id": "kamera2", "nama": "Kamera 2 · Simpang Laguboti", "jenis": "ip", "catatan": "...",
     "aktif": true, "token": "<rahasia>", "dibuat": "2026-11-21 17:10:00"}
  * id      : tetap, dipakai sebagai nama folder data dan di perintah perangkat (--node)
  * jenis   : "pi" (Raspberry Pi Camera), "ip" (IP camera RTSP), "data" (data latihan, tanpa perangkat)
  * token   : rahasia khusus kamera ini. Kamera lama tanpa "token" tetap memakai token_node bersama.
Perubahan langsung berlaku; server tidak perlu dimulai ulang.
"""
import os
import re
import secrets
import time

from settings import (ROOT, SETELAN_FILE, Salah, _baca_json, _kunci, _terlihat, _tulis_json, folder_rekaman, setelan)

ID_BARU = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
JENIS = {"pi": "Raspberry Pi Camera", "ip": "IP camera (RTSP)", "data": "Data latihan (tanpa perangkat)"}
PROGRAM = os.path.join(ROOT, "centernet3d_bbox", "node", "node_camera.py")


def _baca():
    s = _baca_json(SETELAN_FILE)
    if s is None:
        setelan()                       # membuat berkas bawaan
        s = _baca_json(SETELAN_FILE)
    return s


def _cari(s, node_id):
    for n in s.get("node", []):
        if n["id"] == node_id:
            return n
    raise Salah("Kamera tidak dikenal: %s" % node_id)


def _jenis(n):
    return n.get("jenis") or ("data" if n["id"].startswith("session") else "pi")


def ringkas(n):
    import calibration                  # 1_camera_calibration (dimuat lewat sys.path di app.py)
    t = _terlihat.get(n["id"])
    try:
        p = calibration.profil(n["id"])
        kal = {"sumber": p.get("sumber_profil"), "versi": p.get("versi"), "metode": p.get("metode"),
               "tersimpan": p.get("tersimpan")}
    except Exception:
        kal = {"sumber": None}
    return {"id": n["id"], "nama": n.get("nama", n["id"]), "jenis": _jenis(n), "jenis_nama": JENIS[_jenis(n)],
            "catatan": n.get("catatan", ""), "aktif": n.get("aktif", True),
            "token_sendiri": bool(n.get("token")), "dibuat": n.get("dibuat"),
            "terhubung": bool(t and time.time() - t < 20), "detik_lalu": int(time.time() - t) if t else None,
            "terakhir": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else None, "kalibrasi": kal}


def daftar():
    return [ringkas(n) for n in _baca().get("node", [])]


def _rapikan_teks(nilai, maks, nama):
    v = (nilai or "").strip()
    if len(v) > maks:
        raise Salah("%s terlalu panjang (maksimum %d karakter)." % (nama, maks))
    return v


def tambah(data):
    node_id = (data.get("id") or "").strip()
    nama = _rapikan_teks(data.get("nama"), 80, "Nama")
    jenis = data.get("jenis") or "pi"
    if not nama:
        raise Salah("Nama kamera wajib diisi.")
    if not ID_BARU.match(node_id):
        raise Salah("ID hanya boleh huruf kecil, angka, _ dan -, diawali huruf atau angka (maksimum 40).")
    if jenis not in ("pi", "ip"):
        raise Salah("Jenis kamera tidak dikenal.")
    with _kunci:
        s = _baca()
        if any(n["id"] == node_id for n in s.get("node", [])):
            raise Salah("ID %s sudah dipakai kamera lain." % node_id)
        n = {"id": node_id, "nama": nama, "jenis": jenis, "catatan": _rapikan_teks(data.get("catatan"), 300, "Catatan"),
             "aktif": True, "token": secrets.token_urlsafe(24), "dibuat": time.strftime("%Y-%m-%d %H:%M:%S")}
        s.setdefault("node", []).append(n)
        _tulis_json(SETELAN_FILE, s)
    return dict(ringkas(n), token=n["token"])


def ubah(node_id, data):
    with _kunci:
        s = _baca()
        n = _cari(s, node_id)
        if "nama" in data:
            nama = _rapikan_teks(data.get("nama"), 80, "Nama")
            if not nama:
                raise Salah("Nama kamera wajib diisi.")
            n["nama"] = nama
        if "catatan" in data:
            n["catatan"] = _rapikan_teks(data.get("catatan"), 300, "Catatan")
        if "jenis" in data:
            if data["jenis"] not in JENIS:
                raise Salah("Jenis kamera tidak dikenal.")
            n["jenis"] = data["jenis"]
        if "aktif" in data:
            n["aktif"] = str(data["aktif"]).lower() in ("1", "true", "ya", "on")
        _tulis_json(SETELAN_FILE, s)
    return ringkas(n)


def hapus(node_id):
    """Keluarkan dari daftar. Rekaman, hasil, dan riwayat kalibrasi di data/ TIDAK dihapus."""
    with _kunci:
        s = _baca()
        n = _cari(s, node_id)
        s["node"] = [x for x in s["node"] if x is not n]
        _tulis_json(SETELAN_FILE, s)
    return {"ok": True, "id": node_id}


def token(node_id):
    s = _baca()
    n = _cari(s, node_id)
    if n.get("token"):
        return {"token": n["token"], "bersama": False}
    return {"token": s.get("token_node", ""), "bersama": True}


def token_baru(node_id):
    with _kunci:
        s = _baca()
        n = _cari(s, node_id)
        n["token"] = secrets.token_urlsafe(24)
        _tulis_json(SETELAN_FILE, s)
    return {"token": n["token"], "bersama": False}


def token_sah(token, node_id):
    """Token perangkat: token khusus kamera bila ada, selain itu token_node bersama (kamera lama)."""
    import hmac
    if not token:
        return False
    s = _baca()
    n = next((x for x in s.get("node", []) if x["id"] == node_id), None)
    if n is None or not n.get("aktif", True):
        return False
    benar = n.get("token") or s.get("token_node", "")
    return bool(benar) and hmac.compare_digest(str(token), str(benar))
