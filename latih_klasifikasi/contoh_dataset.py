#!/usr/bin/env python3
"""contoh_dataset.py - lembar contoh gambar per kelas dan statistik ukuran (cv2 + numpy).
Hanya membaca dataset. Keluaran: contoh_dataset.png (satu baris per kelas, 12 gambar acak dari train).
Pemakaian: python3 contoh_dataset.py [--root ~/dataset_publik/dataset_klasifikasi] [--per 12]
"""
import argparse
import os
import random

import cv2
import numpy as np

KELAS = ("mobil_pribadi", "truk", "bus", "van_pickup")
SEL = 140  # sisi tiap kotak contoh (piksel)


def kotak(img):
    """Skala ke dalam kotak SELxSEL tanpa mengubah rasio, latar abu-abu."""
    h, w = img.shape[:2]
    s = SEL / max(h, w)
    kecil = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))))
    out = np.full((SEL, SEL, 3), 128, np.uint8)
    y0, x0 = (SEL - kecil.shape[0]) // 2, (SEL - kecil.shape[1]) // 2
    out[y0:y0 + kecil.shape[0], x0:x0 + kecil.shape[1]] = kecil
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=os.path.expanduser("~/dataset_publik/dataset_klasifikasi"))
    p.add_argument("--per", type=int, default=12)
    p.add_argument("--out", default=os.path.expanduser("~/dataset_publik/hasil_klasifikasi/contoh_dataset.png"))
    a = p.parse_args()
    rng = random.Random(7)
    baris = []
    print("%-14s %7s | %-19s | %-19s" % ("kelas", "n_cek", "lebar p5/med/p95", "tinggi p5/med/p95"))
    for k in KELAS:
        d = os.path.join(a.root, "train", k)
        nama = sorted(os.listdir(d))
        cek = rng.sample(nama, min(400, len(nama)))
        ws, hs = [], []
        for n in cek:
            im = cv2.imread(os.path.join(d, n))
            if im is not None:
                hs.append(im.shape[0]); ws.append(im.shape[1])
        pw, ph = np.percentile(ws, [5, 50, 95]), np.percentile(hs, [5, 50, 95])
        print("%-14s %7d | %5.0f/%5.0f/%5.0f   | %5.0f/%5.0f/%5.0f" % (k, len(ws), *pw, *ph))
        sel = []
        for n in cek[:a.per]:
            sel.append(kotak(cv2.imread(os.path.join(d, n))))
        while len(sel) < a.per:
            sel.append(np.full((SEL, SEL, 3), 128, np.uint8))
        row = np.hstack(sel)
        cv2.putText(row, k, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        baris.append(row)
    cv2.imwrite(a.out, np.vstack(baris))
    print("tersimpan:", a.out)


if __name__ == "__main__":
    main()