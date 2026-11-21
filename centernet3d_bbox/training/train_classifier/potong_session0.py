#!/usr/bin/env python3
"""potong_session0.py - potong gambar kendaraan dari frame session0_right memakai <bbox2d> di XML.

Hasil: folder uji dengan format sama seperti dataset publik (folder per kelas) + objects.csv:
  <keluar>/mobil_pribadi/session0_right_000342_o0.jpg   (jenis XML: Car)
  <keluar>/truk/...                                      (jenis XML: Truck)
  Bus (hanya 1 objek) dan jenis lain dilewati: terlalu sedikit untuk diuji.
Catatan: label 'Car' di XML mencakup mobil pribadi, SUV, minivan, bahkan van/pickup (tidak dipisah),
jadi kelas mobil_pribadi di sini adalah 'Car' apa adanya. Satu kendaraan muncul di banyak frame
berurutan, jadi tiap-N-frame dipakai untuk mengurangi duplikat (jumlah potongan != jumlah kendaraan).
Aturan (pilihan kita): margin 5% di sekeliling kotak; potongan dengan sisi < --min-sisi piksel dilewati.
Pemakaian: python3 potong_session0.py [--tiap 10] [--tiap-truk 3]
"""
import argparse
import csv
import os
import xml.etree.ElementTree as ET

import cv2

PETA = {"Car": "mobil_pribadi", "Truck": "truk"}


def main():
    p = argparse.ArgumentParser()
    base = os.path.expanduser("~/projects/data_session0_right")
    p.add_argument("--base", default=base)
    p.add_argument("--keluar", default=os.path.expanduser("~/dataset_publik/uji_session0_right"))
    p.add_argument("--tiap", type=int, default=10, help="ambil Car tiap N frame")
    p.add_argument("--tiap-truk", type=int, default=3, help="ambil Truck tiap N frame")
    p.add_argument("--min-sisi", type=int, default=30)
    p.add_argument("--margin", type=float, default=0.05)
    a = p.parse_args()

    xmls = sorted(f for f in os.listdir(os.path.join(a.base, "annotations")) if f.endswith(".xml"))
    for k in PETA.values():
        os.makedirs(os.path.join(a.keluar, k), exist_ok=True)
    rows, skip_kecil, skip_jenis = [], 0, {}
    for idx, fx in enumerate(xmls):
        stem = fx[:-4]
        root = ET.parse(os.path.join(a.base, "annotations", fx)).getroot()
        objs = root.findall("object")
        perlu = [o for o in objs if (o.findtext("type") or "").strip() in PETA]
        for o in objs:
            j = (o.findtext("type") or "").strip()
            if j not in PETA:
                skip_jenis[j] = skip_jenis.get(j, 0) + 1
        ambil = [o for o in perlu if idx % (a.tiap_truk if o.findtext("type").strip() == "Truck" else a.tiap) == 0]
        if not ambil:
            continue
        img = cv2.imread(os.path.join(a.base, "images", stem + ".jpg"))
        if img is None:
            raise SystemExit("gambar tidak terbaca: " + stem)
        H, W = img.shape[:2]
        for oi, o in enumerate(objs):
            if o not in ambil:
                continue
            x, y, w, h = [float(v) for v in o.findtext("bbox2d").split()]
            mx, my = w * a.margin, h * a.margin
            x0, y0 = max(0, int(x - mx)), max(0, int(y - my))
            x1, y1 = min(W, int(x + w + mx)), min(H, int(y + h + my))
            if min(x1 - x0, y1 - y0) < a.min_sisi:
                skip_kecil += 1
                continue
            jenis = o.findtext("type").strip()
            kelas = PETA[jenis]
            nama = "%s_o%d.jpg" % (stem, oi)
            cv2.imwrite(os.path.join(a.keluar, kelas, nama), img[y0:y1, x0:x1])
            l, wd, hh = (float(v) for v in o.findtext("veh_size").split())  # urutan XML: panjang lebar tinggi
            rows.append([os.path.join(kelas, nama), kelas, jenis, stem, oi, x0, y0, x1 - x0, y1 - y0,
                         (o.findtext("perspective") or "").strip(), l, wd, hh])
    with open(os.path.join(a.keluar, "objects.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["berkas", "kelas", "jenis_xml", "frame", "obj", "x", "y", "lebar_px", "tinggi_px",
                    "perspektif", "panjang_m", "lebar_m", "tinggi_m"])
        w.writerows(rows)
    n = {k: sum(1 for r in rows if r[1] == k) for k in PETA.values()}
    print("frame XML: %d | potongan: %s | dilewati terlalu kecil: %d | jenis lain dilewati: %s"
          % (len(xmls), n, skip_kecil, skip_jenis or "-"))
    print("tersimpan:", a.keluar)


if __name__ == "__main__":
    main()