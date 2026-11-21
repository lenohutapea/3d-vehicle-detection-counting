#!/usr/bin/env python3
"""lembar_truk.py - lembar kontak potongan 'Truck' session0_right, bernomor dan berurut frame,
untuk dipisah manual menjadi truk atau van. Keluaran: hasil_klasifikasi/lembar_truk_<n>.png (36 gambar/halaman)
dan daftar_truk.csv (nomor,berkas,frame)."""
import csv, os, re
import cv2, numpy as np

H = os.path.expanduser("~/dataset_publik")
D = H + "/uji_session0_right/truk"
OUT = H + "/hasil_klasifikasi"
os.makedirs(OUT, exist_ok=True)

def frame(f):
    m = re.search(r"_(\d{6})_", f)
    return int(m.group(1)) if m else -1

nama = sorted((f for f in os.listdir(D) if f.lower().endswith(".jpg")), key=lambda f: (frame(f), f))
with open(OUT + "/daftar_truk.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["nomor", "berkas", "frame"])
    for i, f in enumerate(nama):
        w.writerow([i, "truk/" + f, frame(f)])

S, KOL, BARIS = 160, 6, 6
for hal in range((len(nama) + KOL * BARIS - 1) // (KOL * BARIS)):
    sheet = np.full((BARIS * (S + 20), KOL * S, 3), 255, np.uint8)
    for j in range(KOL * BARIS):
        i = hal * KOL * BARIS + j
        if i >= len(nama):
            break
        im = cv2.imread(D + "/" + nama[i])
        if im is None:
            continue
        s = S / max(im.shape[:2])
        im = cv2.resize(im, (max(1, int(im.shape[1] * s)), max(1, int(im.shape[0] * s))))
        r, c = divmod(j, KOL)
        y0, x0 = r * (S + 20) + 20, c * S
        sheet[y0:y0 + im.shape[0], x0:x0 + im.shape[1]] = im
        cv2.putText(sheet, "#%d  f%d" % (i, frame(nama[i])), (x0 + 2, y0 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 180), 1)
    p = "%s/lembar_truk_%d.png" % (OUT, hal + 1)
    cv2.imwrite(p, sheet); print("tersimpan:", p)
print("total %d potongan; daftar: %s/daftar_truk.csv" % (len(nama), OUT))