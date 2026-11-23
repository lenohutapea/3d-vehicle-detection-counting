#!/usr/bin/env python3
"""
compare_manual_count.py - bandingkan hitungan manual (kebenaran dasar) dengan hitungan sistem satu hasil proses.

    cd ~/3d-vehicle-detection-counting
    python3 centernet3d_bbox/tools/compare_manual_count.py --manual ~/hitung_manual_142911.csv \\
        --job data/results/manual/20261123-092522-ab95 [--job <hasil lain, mis. model baru> ...]

Berkas manual (CSV, baris pertama judul):  detik,arah,kelas
  detik : saat kendaraan melewati garis hitung (angka detik video, boleh desimal, atau mm:ss)
  arah  : mendekat / menjauh
  kelas : mobil_pribadi / van_pickup / truk / bus   (boleh juga: mobil, car, van, pikap, angkot, truck)
Hanya kendaraan roda empat ke atas (sama dengan sistem).

Pencocokan: dalam arah yang sama, satu kendaraan manual dipasangkan dengan paling banyak satu hitungan sistem
bila selisih waktunya <= --toleransi detik (pemasangan optimal, Hungarian). Lalu:
  TP = terpasang, FN = manual tanpa pasangan (terlewat), FP = hitungan sistem tanpa pasangan (lebih).
  presisi = TP/(TP+FP), recall = TP/(TP+FN), F1; akurasi kelas = kelas sama di antara TP;
  galat jumlah per kelas & arah = |sistem - manual| / manual.
Hasil juga disimpan ke <job>/evaluasi_manual.csv (pasangan per kendaraan).
"""
import argparse
import csv
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KELAS = ("mobil_pribadi", "van_pickup", "truk", "bus")
ALIAS = {"mobil": "mobil_pribadi", "car": "mobil_pribadi", "mobil_pribadi": "mobil_pribadi", "sedan": "mobil_pribadi",
         "van": "van_pickup", "van_pickup": "van_pickup", "pikap": "van_pickup", "pickup": "van_pickup",
         "angkot": "van_pickup", "minibus": "van_pickup", "truk": "truk", "truck": "truk", "bus": "bus"}
ARAH = {"mendekat": "mendekat", "dekat": "mendekat", "m": "mendekat", "menjauh": "menjauh", "jauh": "menjauh",
        "j": "menjauh"}


def detik(t):
    t = str(t).strip().replace(",", ".")
    if ":" in t:
        m, s = t.split(":", 1)
        return int(m) * 60 + float(s)
    return float(t)


def baca_manual(p):
    out = []
    for i, r in enumerate(csv.DictReader(open(os.path.expanduser(p), encoding="utf-8-sig")), start=2):
        r = {k.strip().lower(): (v or "").strip().lower() for k, v in r.items() if k}
        if not r.get("detik"):
            continue
        if r.get("arah") not in ARAH or r.get("kelas") not in ALIAS:
            sys.exit("Baris %d berkas manual tidak dikenal: %s" % (i, r))
        out.append((detik(r["detik"]), ARAH[r["arah"]], ALIAS[r["kelas"]]))
    return out


def baca_sistem(job):
    st = json.load(open(os.path.join(job, "status.json"), encoding="utf-8"))
    prof = json.load(open(os.path.join(job, "profil.json"), encoding="utf-8"))
    fps = float(st.get("fps") or 25.0)
    median, lajur = float(prof.get("MEDIAN_X_M", 0)), prof.get("LAJUR", "kanan")
    peta = {"car": "mobil_pribadi", "van": "van_pickup", "truck": "truk", "bus": "bus"}
    out = []
    for r in csv.DictReader(open(os.path.join(job, "counting_log.csv"), encoding="utf-8")):
        x = float(r["x_m"])
        menjauh = x >= median if lajur == "kanan" else x < median
        out.append((int(r["frame"]) / fps, "menjauh" if menjauh else "mendekat", peta.get(r["kelas"], r["kelas"])))
    return out, st, fps


def pasangkan(gt, sis, tol):
    from scipy.optimize import linear_sum_assignment
    pas = []
    for arah in ("mendekat", "menjauh"):
        g = [i for i, v in enumerate(gt) if v[1] == arah]
        s = [j for j, v in enumerate(sis) if v[1] == arah]
        if not g or not s:
            continue
        c = np.array([[abs(gt[i][0] - sis[j][0]) for j in s] for i in g])
        biaya = np.where(c <= tol, c, 1e6)
        ri, ci = linear_sum_assignment(biaya)
        pas += [(g[a], s[b]) for a, b in zip(ri, ci) if biaya[a, b] < 1e6]
    return pas


def evaluasi(gt, job, tol):
    sis, st, fps = baca_sistem(job)
    pas = pasangkan(gt, sis, tol)
    tp = len(pas)
    fn, fp = len(gt) - tp, len(sis) - tp
    pre = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * pre * rec / (pre + rec) if pre + rec else float("nan")
    kelas_ok = sum(gt[i][2] == sis[j][2] for i, j in pas)
    print("\n=== %s | model %s | kalibrasi %s ===" % (os.path.basename(job.rstrip("/")), st.get("model"),
                                                    (st.get("kalibrasi") or {}).get("versi", "-")))
    print("manual %d | sistem %d | TP %d | FN (terlewat) %d | FP (lebih) %d" % (len(gt), len(sis), tp, fn, fp))
    print("presisi %.3f | recall %.3f | F1 %.3f | akurasi kelas (di antara TP) %s"
          % (pre, rec, f1, "%.3f" % (kelas_ok / tp) if tp else "-"))
    print("\n%-10s %-14s %7s %7s %8s" % ("arah", "kelas", "manual", "sistem", "galat"))
    for arah in ("mendekat", "menjauh", "semua"):
        for k in KELAS + ("TOTAL",):
            def n(daftar):
                return sum(1 for v in daftar if (arah == "semua" or v[1] == arah) and (k == "TOTAL" or v[2] == k))
            a, b = n(gt), n(sis)
            if a or b:
                print("%-10s %-14s %7d %7d %8s" % (arah, k, a, b, "%.1f%%" % (100 * abs(b - a) / a) if a else "-"))
    m = np.zeros((len(KELAS), len(KELAS)), int)
    for i, j in pas:
        if gt[i][2] in KELAS and sis[j][2] in KELAS:
            m[KELAS.index(gt[i][2]), KELAS.index(sis[j][2])] += 1
    print("\nmatriks kelas (baris = manual, kolom = sistem), hanya pasangan TP")
    print("%-14s" % "" + "".join("%14s" % k for k in KELAS))
    for i, k in enumerate(KELAS):
        print("%-14s" % k + "".join("%14d" % v for v in m[i]))
    keluar = os.path.join(job, "evaluasi_manual.csv")
    dipakai_g, dipakai_s = {i for i, _ in pas}, {j for _, j in pas}
    with open(keluar, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["status", "detik_manual", "detik_sistem", "arah", "kelas_manual", "kelas_sistem"])
        for i, j in sorted(pas, key=lambda t: gt[t[0]][0]):
            w.writerow(["TP", "%.2f" % gt[i][0], "%.2f" % sis[j][0], gt[i][1], gt[i][2], sis[j][2]])
        for i, v in enumerate(gt):
            if i not in dipakai_g:
                w.writerow(["FN", "%.2f" % v[0], "", v[1], v[2], ""])
        for j, v in enumerate(sis):
            if j not in dipakai_s:
                w.writerow(["FP", "", "%.2f" % v[0], v[1], "", v[2]])
    print("pasangan per kendaraan: %s" % keluar)
    return {"job": os.path.basename(job.rstrip("/")), "model": st.get("model"), "manual": len(gt), "sistem": len(sis),
            "tp": tp, "fn": fn, "fp": fp, "presisi": pre, "recall": rec, "f1": f1,
            "akurasi_kelas": kelas_ok / tp if tp else float("nan")}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manual", required=True)
    p.add_argument("--job", action="append", required=True, help="folder hasil proses (boleh berulang)")
    p.add_argument("--toleransi", type=float, default=2.0, help="selisih waktu maksimum (detik)")
    a = p.parse_args()
    gt = baca_manual(a.manual)
    hasil = [evaluasi(gt, os.path.abspath(os.path.expanduser(j)), a.toleransi) for j in a.job]
    if len(hasil) > 1:
        print("\n=== ringkasan ===")
        print("%-24s %-26s %5s %5s %5s %7s %7s %7s %8s" % ("job", "model", "TP", "FN", "FP", "presisi", "recall", "F1", "kelas"))
        for h in hasil:
            print("%-24s %-26s %5d %5d %5d %7.3f %7.3f %7.3f %8.3f" % (h["job"], h["model"], h["tp"], h["fn"], h["fp"],
                                                                      h["presisi"], h["recall"], h["f1"], h["akurasi_kelas"]))


if __name__ == "__main__":
    main()
