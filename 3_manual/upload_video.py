"""
upload_video.py - UTAMA 3: menyimpan, menampilkan, dan menghapus rekaman.

Rekaman disimpan di data/recordings/<automatic|manual>/<node>/<YYYYMMDD>_<HHMMSS>_<mode>.mp4
(dipakai juga oleh node untuk rekaman otomatis). Unggahan dari komputer selalu bermode manual.
Isi ini berasal dari layanan.py lama (bagian 3. rekaman).
"""
import os
import shutil
import subprocess
import time

from settings import (EKSTENSI, FOLDER_MODE, NAMA_REKAMAN, NODE_SAH, Salah, _cek_node, _jobs, _kunci,
                      _sumber_video, folder_rekaman, setelan)

MAKS_UNGGAH = 500 * 1024 * 1024


def daftar_rekaman(node_id=None):
    dipakai = {}
    with _kunci:
        for j in _jobs.values():
            if j.get("sumber", "").startswith("rekaman/"):
                dipakai.setdefault(j["sumber"], []).append({"id": j["id"], "status": j["status"]})
    out = []
    for n in ([node_id] if node_id else [x["id"] for x in setelan()["node"]]):
        if not NODE_SAH.match(n):
            continue
        for mode in FOLDER_MODE:
            d = folder_rekaman(mode, n)
            if not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                m = NAMA_REKAMAN.match(f)
                if not m or m.group(3) != mode:
                    continue
                tgl, jam, _ = m.groups()
                sumber = "rekaman/%s/%s" % (n, f)
                out.append({"sumber": sumber, "node": n, "nama": f, "mode": mode,
                            "waktu": "%s-%s-%s %s:%s:%s" % (tgl[:4], tgl[4:6], tgl[6:], jam[:2], jam[2:4], jam[4:]),
                            "ukuran_mb": round(os.path.getsize(os.path.join(d, f)) / 1048576, 1),
                            "job": dipakai.get(sumber, [])})
    return sorted(out, key=lambda r: r["waktu"], reverse=True)


def simpan_rekaman(node_id, berkas, mode, nama_asli="rekaman.mp4"):
    """Simpan rekaman (dari node atau unggahan manual di peramban). Mengembalikan 'rekaman/<node>/<nama>'."""
    _cek_node(node_id)
    if mode not in FOLDER_MODE:
        raise Salah("Mode rekaman tidak dikenal.")
    if os.path.splitext(nama_asli or "")[1].lower() not in EKSTENSI:
        raise Salah("Jenis berkas tidak didukung. Pakai: " + ", ".join(EKSTENSI))
    d = folder_rekaman(mode, node_id)
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
