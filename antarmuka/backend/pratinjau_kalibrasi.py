"""
pratinjau_kalibrasi.py - menggambar kisi jalan, garis hitung, dan kotak mobil acuan di atas satu frame.

Dijalankan layanan.py DARI folder pipeline, dengan variabel lingkungan PROFIL_KAMERA berisi profil
yang sedang disunting, sehingga geometri yang dipakai persis sama dengan yang dipakai run.py.
    python pratinjau_kalibrasi.py frame.jpg hasil.jpg
Kalibrasi benar bila: garis kisi sejajar marka jalan, dan kotak acuan (4,5 x 1,8 x 1,5 m)
seukuran mobil yang berada di dekatnya.
"""
import os
import sys

sys.path.insert(0, os.getcwd())

import cv2                      # noqa: E402
import numpy as np              # noqa: E402

import config as cfg            # noqa: E402
from box3d import box_corners   # noqa: E402
from geometry import CAMERA_POS, TO_CAMERA_FROM_WORLD, world_to_image  # noqa: E402

frame = cv2.imread(sys.argv[1])
H, W = frame.shape[:2]


def piksel(x, z, y=0.0):
    """Titik dunia -> piksel, atau None bila di belakang kamera / terlalu jauh dari gambar."""
    p = np.array([x, y, z], dtype=float)
    if (TO_CAMERA_FROM_WORLD[:3, :3] @ p + TO_CAMERA_FROM_WORLD[:3, 3])[2] <= 0.5:
        return None
    u, v = world_to_image(p, H)
    return (u, v) if abs(u) < 20000 and abs(v) < 20000 else None


def garis(a, b, warna, tebal=1):
    if a is None or b is None:
        return
    ok, p, q = cv2.clipLine((0, 0, W, H), a, b)
    if ok:
        cv2.line(frame, p, q, warna, tebal, cv2.LINE_AA)


half, jauh = cfg.LANE_HALF_WIDTH_M, cfg.MAX_TRACK_DEPTH_M
median = getattr(cfg, "MEDIAN_X_M", 0.0)
away = getattr(cfg, "LINE_Y_AWAY_M", cfg.LINE_Y_DEFAULT_M)
langkah = 10 if jauh <= 150 else 20
z0 = 5.0

# kisi: garis melintang tiap `langkah` meter, garis memanjang tiap 5 m
for z in np.arange(langkah, jauh + 0.1, langkah):
    garis(piksel(-half, z), piksel(half, z), (255, 255, 255), 1)
    p = piksel(-half, z)
    if p and 0 <= p[1] < H:
        cv2.putText(frame, "%d m" % z, (max(4, min(W - 60, p[0] + 4)), p[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (255, 255, 255), 1, cv2.LINE_AA)
for x in np.arange(-half, half + 0.1, 5.0):
    garis(piksel(x, z0), piksel(x, jauh), (200, 200, 200), 1)
# batas jalur (jingga) dan median (sian)
for x in (-half, half):
    garis(piksel(x, z0), piksel(x, jauh), (0, 165, 255), 2)
garis(piksel(median, z0), piksel(median, jauh), (255, 255, 0), 2)
# garis hitung: mendekat (merah, kiri median), menjauh (ungu, kanan median)
garis(piksel(-half, cfg.LINE_Y_DEFAULT_M), piksel(median, cfg.LINE_Y_DEFAULT_M), (0, 0, 255), 3)
garis(piksel(median, away), piksel(half, away), (255, 0, 255), 3)
# kotak mobil acuan di beberapa jarak
tepi = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
for z in (jauh * 0.2, jauh * 0.4, jauh * 0.65):
    for x in ((-half + median) / 2, (median + half) / 2):
        pts = [piksel(c[0], c[2], c[1]) for c in box_corners(x, z, (1.8, 1.5, 4.5), 0.0)]
        for a, b in tepi:
            garis(pts[a], pts[b], (0, 255, 0), 2)

teks = "tinggi kamera %.2f m" % CAMERA_POS[1]
cv2.rectangle(frame, (8, 8), (16 + 9 * len(teks), 32), (0, 0, 0), -1)
cv2.putText(frame, teks, (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
cv2.imwrite(sys.argv[2], frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
