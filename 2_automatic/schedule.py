"""
schedule.py - UTAMA 2: jadwal rekaman otomatis.

Jadwal disimpan di schedule.json (folder ini):
    {"video_per_hari": 6, "durasi_detik": 60, "jam_mulai": "06:00", "jam_selesai": "18:00"}
Jam rekaman dibagi rata di antara jam_mulai dan jam_selesai. Jam yang sudah direkam hari ini
dicatat di data/recordings/automatic/<node>/slot_<YYYYMMDD>.json agar tidak direkam dua kali.
Isi ini berasal dari layanan.py lama (jadwal_harian, _menit, _slot_terisi).
"""
import os

from settings import _baca_json, _tulis_json, folder_rekaman, setelan


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


def _jalur_slot(node_id, tanggal):
    return os.path.join(folder_rekaman("otomatis", node_id), "slot_%s.json" % tanggal)


def slot_terisi(node_id, tanggal):
    """Jam jadwal hari ini yang rekamannya sudah diterima (agar tidak direkam dua kali)."""
    return _baca_json(_jalur_slot(node_id, tanggal), [])


def tandai_slot(node_id, tanggal, slot):
    _tulis_json(_jalur_slot(node_id, tanggal), slot_terisi(node_id, tanggal) + [slot])
