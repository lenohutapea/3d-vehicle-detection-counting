#!/usr/bin/env python3
"""siapkan_mio_tcd.py - siapkan dataset klasifikasi 4 kelas dari MIO-TCD (hanya pustaka standar Python).

Dua tahap:
  1) python3 siapkan_mio_tcd.py daftar
       membaca gt_train.csv, mengambil subsampel acak (seed tetap) per jenis MIO-TCD, membagi
       80/10/10 (latih/validasi/uji, acak per gambar, seimbang per jenis), lalu menulis
         <akar>/terpilih.csv       (id, jenis_mio, kelas, split)
         <akar>/daftar_ekstrak.txt (jalur di dalam arsip, untuk tar -T)
  2) python3 siapkan_mio_tcd.py ekstrak
       mengalirkan arsip MIO-TCD dari internet (3,1 GB, TIDAK disimpan) dan hanya mengambil gambar
       yang ada di daftar. Boleh dijalankan ulang: yang sudah ada dilewati dan arsip dibaca lagi.
  3) python3 siapkan_mio_tcd.py susun
       memindahkan gambar hasil ekstraksi ke <keluar>/<split>/<kelas>/ dan menulis objects.csv

Pemetaan 4 kelas (pilihan kita; sesuaikan bila dosen meminta lain):
  car -> mobil_pribadi | single_unit_truck, articulated_truck -> truk | bus -> bus
  pickup_truck, work_van -> van_pickup
Catatan: MIO-TCD tidak punya ukuran kendaraan dan satu kendaraan bisa muncul di beberapa gambar;
pembagian di sini per gambar, jadi angka ujinya bisa sedikit optimistis.
"""
import argparse
import csv
import os
import random
import shutil
import sys

KELAS = {"car": "mobil_pribadi", "single_unit_truck": "truk", "articulated_truck": "truk",
         "bus": "bus", "pickup_truck": "van_pickup", "work_van": "van_pickup"}
JUMLAH = {"car": 10000, "bus": 10000, "single_unit_truck": 5000, "articulated_truck": 5000,
          "pickup_truck": 5000, "work_van": 5000}
SPLIT = (("train", 0.8), ("val", 0.1), ("test", 0.1))
SEED = 42


def daftar(akar):
    per = {j: [] for j in JUMLAH}
    with open(os.path.join(akar, "gt_train.csv"), newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[-1].strip() in per:
                per[row[-1].strip()].append(row[0].strip())
    rng = random.Random(SEED)
    baris = []
    for j in JUMLAH:
        ids = sorted(per[j])
        if len(ids) < JUMLAH[j]:
            print("PERINGATAN: %s hanya %d gambar (diminta %d)" % (j, len(ids), JUMLAH[j]))
        pilih = rng.sample(ids, min(JUMLAH[j], len(ids)))
        n = len(pilih)
        n_tr, n_va = int(n * SPLIT[0][1]), int(n * SPLIT[1][1])
        for k, i in enumerate(pilih):
            sp = "train" if k < n_tr else ("val" if k < n_tr + n_va else "test")
            baris.append((i, j, KELAS[j], sp))
    with open(os.path.join(akar, "terpilih.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "jenis_mio", "kelas", "split"])
        w.writerows(baris)
    with open(os.path.join(akar, "daftar_ekstrak.txt"), "w") as f:
        f.write("".join("train/%s/%s.jpg\n" % (j, i) for i, j, _, _ in baris))
    ring = {}
    for _, _, k, sp in baris:
        ring[(k, sp)] = ring.get((k, sp), 0) + 1
    print("total terpilih: %d" % len(baris))
    for k in ("mobil_pribadi", "truk", "bus", "van_pickup"):
        print("  %-14s " % k + " ".join("%s=%d" % (sp, ring.get((k, sp), 0)) for sp, _ in SPLIT))
    print("tersimpan: terpilih.csv dan daftar_ekstrak.txt di", akar)


def ekstrak(akar, url):
    import tarfile
    import time
    import urllib.request
    with open(os.path.join(akar, "daftar_ekstrak.txt")) as f:
        semua = [l.strip() for l in f if l.strip()]
    perlu = {p for p in semua if not os.path.exists(os.path.join(akar, p))}
    print("diminta: %d | sudah ada: %d | akan diambil: %d" % (len(semua), len(semua) - len(perlu), len(perlu)))
    if not perlu:
        return
    t0, lihat, ambil = time.time(), 0, 0
    with urllib.request.urlopen(url) as resp, tarfile.open(fileobj=resp, mode="r|") as tf:
        for m in tf:
            lihat += 1
            if m.name in perlu:
                try:
                    tf.extract(m, akar, filter="data")
                except TypeError:  # Python lama tanpa parameter filter
                    tf.extract(m, akar)
                perlu.discard(m.name)
                ambil += 1
                if not perlu:
                    break
            if lihat % 50000 == 0:
                print("  dibaca %d entri | terambil %d | %.0f detik" % (lihat, ambil, time.time() - t0))
    print("selesai: terambil %d | belum ketemu %d | %.0f detik" % (ambil, len(perlu), time.time() - t0))
    if perlu:
        print("PERINGATAN: sebagian tidak ketemu di arsip; jalankan ulang tahap ekstrak bila unduhan terputus.")


def susun(akar, keluar):
    hilang, dipindah, rows = 0, 0, []
    with open(os.path.join(akar, "terpilih.csv"), newline="") as f:
        for r in csv.DictReader(f):
            src = os.path.join(akar, "train", r["jenis_mio"], r["id"] + ".jpg")
            nama = "%s__%s.jpg" % (r["jenis_mio"], r["id"])
            dst_dir = os.path.join(keluar, r["split"], r["kelas"])
            if not os.path.exists(src):
                hilang += 1
                continue
            os.makedirs(dst_dir, exist_ok=True)
            shutil.move(src, os.path.join(dst_dir, nama))
            rows.append([os.path.join(r["split"], r["kelas"], nama), r["kelas"], r["jenis_mio"], r["split"]])
            dipindah += 1
    with open(os.path.join(keluar, "objects.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["berkas", "kelas", "jenis_mio", "split"])
        w.writerows(rows)
    print("dipindah: %d | tidak ditemukan: %d | tersimpan: %s" % (dipindah, hilang, keluar))
    if hilang:
        print("PERINGATAN: ada berkas yang belum terekstrak; jalankan ulang ekstraksi (tar -T).")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("tahap", choices=["daftar", "ekstrak", "susun"])
    p.add_argument("--url", default="https://tcd.miovision.com/static/dataset/MIO-TCD-Classification.tar")
    p.add_argument("--akar", default=os.path.expanduser("~/dataset_publik/mio_tcd"))
    p.add_argument("--keluar", default=os.path.expanduser("~/dataset_publik/dataset_klasifikasi"))
    a = p.parse_args()
    if a.tahap == "daftar":
        daftar(a.akar)
    elif a.tahap == "ekstrak":
        ekstrak(a.akar, a.url)
    else:
        susun(a.akar, a.keluar)


if __name__ == "__main__":
    sys.exit(main())