"""
manual_record.py - UTAMA 3: tombol Rekam di halaman Pengambilan Video.

Halaman web membuat permintaan; node kamera mengambilnya saat menanyakan tugas (paling lama 5 detik),
merekam selama durasi yang diminta, lalu mengirim videonya. Rekaman manual TIDAK langsung diproses.
Isi ini berasal dari layanan.py lama (minta_rekam, daftar_permintaan).
"""
import secrets
import time

from settings import Salah, _cek_node, _kunci, _permintaan


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
