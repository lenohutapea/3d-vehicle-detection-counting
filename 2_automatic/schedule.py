"""
schedule.py - UTAMA 2: jadwal rekaman otomatis.

Jadwal BAWAAN ada di schedule.json (folder ini, masuk Git, tidak pernah ditulis server):
    {"video_per_hari": 6, "durasi_detik": 60, "jam_mulai": "06:00", "jam_selesai": "18:00"}
Jadwal yang diubah dari halaman web disimpan sebagai versi baru di data/schedule/<YYYYMMDD_HHMMSS>.json
dan dipakai lewat data/schedule/active.json. Perubahan langsung berlaku (node menanyakan tugas tiap 5 detik).
Jam rekaman dibagi rata di antara jam_mulai dan jam_selesai. Jam yang sudah direkam hari ini
dicatat di data/recordings/automatic/<node>/slot_<YYYYMMDD>.json agar tidak direkam dua kali.
Isi ini berasal dari layanan.py lama (jadwal_harian, _menit, _slot_terisi).
"""
import os
import re
import time

from settings import (JADWAL_DATA, Salah, _baca_json, _tulis_json, daftar_versi, folder_rekaman, kembali_bawaan,
                      pakai_versi, setelan, simpan_versi)

POLA_JAM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


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


# ---------------------------------------------------------------- jadwal dari halaman web
def info_jadwal():
    s = setelan()
    return {"aktif": s["jadwal"], "sumber": s["jadwal_sumber"], "versi": s["jadwal"].get("versi"),
            "jam": jadwal_harian(), "riwayat": [dict(v["isi"], versi=v["versi"], aktif=v["aktif"])
                                               for v in daftar_versi(JADWAL_DATA)]}


def simpan_jadwal(data):
    try:
        n = int(float(data.get("video_per_hari", "")))
        durasi = int(float(data.get("durasi_detik", "")))
    except (TypeError, ValueError):
        raise Salah("Jumlah video dan durasi harus angka.")
    mulai, selesai = (data.get("jam_mulai") or "").strip()[:5], (data.get("jam_selesai") or "").strip()[:5]
    if not 0 <= n <= 48:
        raise Salah("Video per hari harus 0 sampai 48.")
    if not 5 <= durasi <= 1800:
        raise Salah("Durasi harus 5 sampai 1800 detik.")
    if not (POLA_JAM.match(mulai) and POLA_JAM.match(selesai)):
        raise Salah("Jam harus berformat JJ:MM, misalnya 06:00.")
    if n > 0 and _menit(selesai) <= _menit(mulai):
        raise Salah("Jam selesai harus lebih besar dari jam mulai.")
    simpan_versi(JADWAL_DATA, {"video_per_hari": n, "durasi_detik": durasi, "jam_mulai": mulai,
                               "jam_selesai": selesai, "tersimpan": time.strftime("%Y-%m-%d %H:%M:%S")})
    return info_jadwal()


def pakai_jadwal(versi):
    pakai_versi(JADWAL_DATA, versi)
    return info_jadwal()


def jadwal_bawaan():
    kembali_bawaan(JADWAL_DATA)
    return info_jadwal()
