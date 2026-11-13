"""
cek_kalibrasi.py - lihat apakah kalibrasi kamera cocok, dan pilih jalur/garis hitung dari gambar.

Menggambar grid jarak (garis z tiap 10 m, garis x tiap 4 m, sebagai garis di permukaan jalan) di atas
satu frame, lalu mencetak jarak (z) dari kamera untuk beberapa baris piksel. Frame dikecilkan ke
IMG_W x IMG_H di config bila ukurannya berbeda.

  python -m tools.cek_kalibrasi FRAME.jpg [--out kalibrasi.png]
"""
import argparse

import cv2
import numpy as np

import config as cfg
from geometry import CAMERA_POS, get_position_ground, world_to_image


def main():
    p = argparse.ArgumentParser()
    p.add_argument("frame")
    p.add_argument("--out", default="kalibrasi.png")
    p.add_argument("--z-max", type=float, default=160.0)
    a = p.parse_args()
    img = cv2.imread(a.frame)
    if img is None:
        raise SystemExit("gagal membaca " + a.frame)
    if img.shape[:2] != (cfg.IMG_H, cfg.IMG_W):
        img = cv2.resize(img, (cfg.IMG_W, cfg.IMG_H), interpolation=cv2.INTER_AREA)
    H, W = img.shape[:2]

    print("jarak z (m) dari kamera pada kolom tengah dan baris piksel tertentu (x=0 di bawah kamera):")
    for y in (700, 600, 500, 400, 300, 250, 200, 150):
        g = get_position_ground(W / 2, y)
        print("  baris y=%3d -> z = %7.1f m  (x di kolom tengah = %6.1f m)" % (y, g[2], g[0]))
    print("tinggi kamera = %.2f m" % CAMERA_POS[1])

    def inside(pt):
        return -2000 < pt[0] < W + 2000 and -2000 < pt[1] < H + 2000

    overlay = img.copy()
    for z in np.arange(10, a.z_max + 1, 10):
        p0 = world_to_image(np.array([-15.0, 0.0, z]), H)
        p1 = world_to_image(np.array([15.0, 0.0, z]), H)
        if not (inside(p0) and inside(p1)):
            continue
        major = int(z) % 50 == 0
        cv2.line(overlay, p0, p1, (0, 255, 255) if major else (0, 200, 0), 2 if major else 1)
        xm, ym = max(5, min(W - 60, p0[0] + 4)), max(14, min(H - 4, p0[1] - 4))
        if 0 <= p0[1] < H:
            cv2.putText(overlay, "z=%d" % z, (xm, ym), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    for x in range(-16, 17, 4):
        pa = world_to_image(np.array([float(x), 0.0, 5.0]), H)
        pb = world_to_image(np.array([float(x), 0.0, a.z_max]), H)
        cv2.line(overlay, pa, pb, (255, 128, 0) if x else (0, 0, 255), 1 if x else 2)
        if 0 <= pb[1] < H and 0 <= pb[0] < W:
            cv2.putText(overlay, "x=%d" % x, (pb[0] + 3, pb[1] + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 160, 0), 1)
    out = cv2.addWeighted(overlay, 0.85, img, 0.15, 0)
    cv2.imwrite(a.out, out)
    print("tersimpan:", a.out)


if __name__ == "__main__":
    main()