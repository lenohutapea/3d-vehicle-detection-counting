#!/usr/bin/env python3
"""diagnosa_domain.py - cari penyebab van_pickup membanjiri hasil session0_right.
Mencetak ukuran potongan (session0_right vs MIO-TCD val) dan membuat diagnosa.png:
baris 1 = 'Car' diprediksi van_pickup, baris 2 = 'Car' diprediksi mobil_pribadi,
baris 3 = 'Truck' diprediksi van_pickup, baris 4 = contoh MIO-TCD van_pickup (val)."""
import csv, os, random
import cv2, numpy as np

H = os.path.expanduser("~/dataset_publik")
PRED = H + "/hasil_klasifikasi/prediksi_session0_klas5.csv"
SES = H + "/uji_session0_right"
MIO = H + "/dataset_klasifikasi/val"
random.seed(1)

def ukuran(paths):
    w, h = [], []
    for p in paths:
        im = cv2.imread(p)
        if im is not None:
            h.append(im.shape[0]); w.append(im.shape[1])
    return np.array(w), np.array(h)

def ringkas(nama, paths):
    w, h = ukuran(paths)
    if len(w) == 0:
        print("%-34s (kosong)" % nama); return
    print("%-34s n=%-5d lebar median %4d | tinggi median %4d | sisi terpanjang median %4d | rasio w/h median %.2f"
          % (nama, len(w), np.median(w), np.median(h), np.median(np.maximum(w, h)), np.median(w / h)))

baris = list(csv.DictReader(open(PRED)))
def pilih(xml, pred): return [SES + "/" + r["berkas"] for r in baris if r["kelas_xml"] == xml and r["prediksi"] == pred]
a = pilih("mobil_pribadi", "van_pickup"); b = pilih("mobil_pribadi", "mobil_pribadi"); c = pilih("truk", "van_pickup")
mio_vp = [MIO + "/van_pickup/" + f for f in os.listdir(MIO + "/van_pickup")]
mio_mp = [MIO + "/mobil_pribadi/" + f for f in os.listdir(MIO + "/mobil_pribadi")]
print("UKURAN POTONGAN (piksel, sebelum diubah ke 128x128)")
ringkas("session0 Car -> van_pickup", a)
ringkas("session0 Car -> mobil_pribadi", b)
ringkas("session0 Truck -> van_pickup", c)
ringkas("MIO-TCD val mobil_pribadi", random.sample(mio_mp, min(300, len(mio_mp))))
ringkas("MIO-TCD val van_pickup", random.sample(mio_vp, min(300, len(mio_vp))))

S, N = 128, 10
def baris_gambar(paths, judul):
    p = random.sample(paths, min(N, len(paths)))
    row = np.full((S + 18, S * N, 3), 255, np.uint8)
    for i, f in enumerate(p):
        im = cv2.imread(f)
        if im is None: continue
        s = S / max(im.shape[:2])
        im = cv2.resize(im, (max(1, int(im.shape[1] * s)), max(1, int(im.shape[0] * s))))
        row[18:18 + im.shape[0], i * S:i * S + im.shape[1]] = im
    cv2.putText(row, judul, (2, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 160), 1)
    return row
sheet = np.vstack([baris_gambar(a, "session0 Car -> van_pickup"), baris_gambar(b, "session0 Car -> mobil_pribadi"),
                   baris_gambar(c, "session0 Truck -> van_pickup"), baris_gambar(mio_vp, "MIO-TCD van_pickup (contoh asli)"),
                   baris_gambar(mio_mp, "MIO-TCD mobil_pribadi (contoh asli)")])
out = H + "/hasil_klasifikasi/diagnosa.png"
cv2.imwrite(out, sheet); print("\ntersimpan:", out)