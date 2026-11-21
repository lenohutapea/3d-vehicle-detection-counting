#!/usr/bin/env python3
"""analisis_galat.py - uraikan FN dan FP dari pkl hasil prediksi.py menurut jarak dan penyebab (numpy + pandas saja).

Memakai fungsi pencocokan yang sama dengan evaluasi.py (muat_gt, cocokkan_frame), jadi TP/FP/FN di sini
harus sama dengan tabel evaluasi.py pada ambang skor yang sama (bawaan 0,1).

Kelompok jarak = jarak kamera ke titik tanah objek (meter), dibagi N kelompok dengan jumlah objek sama
(bawaan 5), batasnya dicetak. FP dikelompokkan dengan jarak deteksinya sendiri; FP di luar rentang jarak
objek label masuk kelompok paling dekat atau paling jauh.

Penyebab (semuanya aturan kita sendiri, bukan bawaan notebook):
 FN (objek zona dekat yang tidak tercocokkan):
   tanpa_deteksi : tidak ada deteksi dalam radius 2 sel (jarak yang sama dengan select) dari pusat label.
                   Dari pkl tidak bisa dibedakan antara skor heatmap di bawah ambang dan ditekan select,
                   karena pkl hanya menyimpan hasil sesudah select.
   lokalisasi    : ada deteksi dalam radius 2 sel, tetapi IoU 2D terbaiknya < ambang IoU.
   berimpit      : ada deteksi ber-IoU >= ambang, tetapi deteksi itu sudah dipakai objek label lain
                   (dua kendaraan yang kotaknya saling menutupi).
 FP (deteksi zona dekat yang tidak tercocokkan):
   duplikat      : IoU >= ambang dengan objek yang sudah dicocokkan deteksi lain.
   lokalisasi    : IoU terbaik dengan objek label antara 0,1 dan ambang.
   latar         : IoU terbaik dengan semua objek label < 0,1.
   tak_valid     : w, h, atau l <= 0.
 Objek jauh (y < y_min): dilaporkan apakah pusatnya terdeteksi (deteksi apa pun di sel 32x32 yang sama,
 sama dengan evaluasi.py) dan seberapa besar ukuran deteksinya; target latihannya adalah ukuran nol.
Pemakaian: python3 analisis_galat.py --pred ~/projects/hasil/prediksi_detektor/latih3ep_val.pkl
"""
import argparse
import csv
import os
import pickle
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dekode import iou_2d  # noqa: E402
from evaluasi import muat_gt, berukuran, cocokkan_frame, med, SCALE  # noqa: E402


def sel_of(y, x):
    return (int(y / SCALE), int(x / SCALE))


def radius_sel(d, g, radius=2):
    cy, cx = sel_of(g["y"], g["x"])
    dy, dx = sel_of(d["py"], d["px"])
    return ((cy - dy) ** 2 + (cx - dx) ** 2) ** 0.5 <= radius


def kumpulkan(pkl, labels, K, T, y_min, iou_thr, skor_min):
    gt_rec, fp_rec, far_rec = [], [], []
    far_det_tanpa_label = 0
    for nm in pkl["names"]:
        dekat, jauh = muat_gt(os.path.join(labels, nm[:-4] + ".txt"), K, T, y_min)
        dets = [d for d in pkl["dets"][nm] if d["score"] >= skor_min]
        zona_jauh = [d for d in dets if d["py"] < y_min]
        dekat_det = [d for d in dets if d["py"] >= y_min]
        ukur = [d for d in dekat_det if berukuran(d)]
        tak_valid = [d for d in dekat_det if not berukuran(d)]
        hasil = cocokkan_frame(ukur, dekat, iou_thr)
        gt_cocok = {j: (i, iou) for (_, tp, i, j, iou) in hasil if tp}
        det_cocok = {i for (_, tp, i, j, iou) in hasil if tp}
        for j, g in enumerate(dekat):
            r = dict(frame=nm, x=g["x"], y=g["y"], depth=g["depth"], skor="")
            if j in gt_cocok:
                i, iou = gt_cocok[j]
                d = ukur[i]
                r.update(status="TP", sebab="", iou=iou, skor=d["score"],
                         rw=abs(d["w"] - g["w"]) / g["w"], rh=abs(d["h"] - g["h"]) / g["h"],
                         rl=abs(d["l"] - g["l"]) / g["l"], ed=abs(d["depth"] - g["depth"]))
            else:
                best = max((iou_2d(d["bbox2d"], g["bbox2d"]) for d in ukur), default=0.0)
                if best >= iou_thr:
                    sebab = "berimpit"
                elif any(radius_sel(d, g) for d in dekat_det):
                    sebab = "lokalisasi"
                else:
                    sebab = "tanpa_deteksi"
                r.update(status="FN", sebab=sebab)
            gt_rec.append(r)
        for i, d in enumerate(ukur):
            if i in det_cocok:
                continue
            best = max((iou_2d(d["bbox2d"], g["bbox2d"]) for g in dekat), default=0.0)
            sebab = "duplikat" if best >= iou_thr else ("lokalisasi" if best >= 0.1 else "latar")
            fp_rec.append(dict(frame=nm, x=d["px"], y=d["py"], depth=d["depth"], skor=d["score"], sebab=sebab))
        for d in tak_valid:
            fp_rec.append(dict(frame=nm, x=d["px"], y=d["py"], depth=d["depth"], skor=d["score"], sebab="tak_valid"))
        sel_jauh = {sel_of(g["y"], g["x"]) for g in jauh}
        for g in jauh:
            c = [d for d in dets if sel_of(d["py"], d["px"]) == sel_of(g["y"], g["x"])]
            if c:
                d = max(c, key=lambda q: q["score"])
                far_rec.append(dict(terdeteksi=True, w=d["w"], h=d["h"], l=d["l"], skor=d["score"]))
            else:
                far_rec.append(dict(terdeteksi=False))
        far_det_tanpa_label += sum(1 for d in zona_jauh if sel_of(d["py"], d["px"]) not in sel_jauh)
    return gt_rec, fp_rec, far_rec, far_det_tanpa_label


def analisis(pkl, labels, K, T, y_min=150, iou_thr=0.5, skor_min=0.1, n_bin=5, nol_m=1.0):
    gt_rec, fp_rec, far_rec, far_tanpa = kumpulkan(pkl, labels, K, T, y_min, iou_thr, skor_min)
    dep = np.array([r["depth"] for r in gt_rec]) if gt_rec else np.array([0.0])
    edges = np.quantile(dep, np.linspace(0, 1, n_bin + 1))
    inner = edges[1:-1]

    def bin_of(d):
        return int(np.searchsorted(inner, d, side="right"))

    tabel = []
    for b in range(n_bin):
        G = [r for r in gt_rec if bin_of(r["depth"]) == b]
        tp = [r for r in G if r["status"] == "TP"]
        fn = [r for r in G if r["status"] == "FN"]
        F = [r for r in fp_rec if bin_of(r["depth"]) == b]
        tabel.append(dict(
            kelompok=b + 1, dari_m=float(edges[b]), sampai_m=float(edges[b + 1]),
            n_gt=len(G), TP=len(tp), FN=len(fn), recall=len(tp) / max(len(G), 1),
            fn_tanpa_deteksi=sum(1 for r in fn if r["sebab"] == "tanpa_deteksi"),
            fn_lokalisasi=sum(1 for r in fn if r["sebab"] == "lokalisasi"),
            fn_berimpit=sum(1 for r in fn if r["sebab"] == "berimpit"),
            FP=len(F),
            fp_duplikat=sum(1 for r in F if r["sebab"] == "duplikat"),
            fp_lokalisasi=sum(1 for r in F if r["sebab"] == "lokalisasi"),
            fp_latar=sum(1 for r in F if r["sebab"] == "latar"),
            fp_tak_valid=sum(1 for r in F if r["sebab"] == "tak_valid"),
            med_iou_tp=med([r["iou"] for r in tp]),
            med_rel_w=med([r["rw"] for r in tp]), med_rel_h=med([r["rh"] for r in tp]),
            med_rel_l=med([r["rl"] for r in tp]), med_galat_depth_m=med([r["ed"] for r in tp])))
    det = [r for r in far_rec if r["terdeteksi"]]
    mutlak = [max(abs(r["w"]), abs(r["h"]), abs(r["l"])) for r in det]
    jauh = dict(n=len(far_rec), terdeteksi=len(det), tanpa_label=far_tanpa,
                med_abs_w=med([abs(r["w"]) for r in det]), med_abs_h=med([abs(r["h"]) for r in det]),
                med_abs_l=med([abs(r["l"]) for r in det]),
                dekat_nol=sum(1 for v in mutlak if v < nol_m), nol_m=nol_m)
    kasus = [dict(jenis="FN", **{k: r[k] for k in ("sebab", "frame", "x", "y", "depth", "skor")})
             for r in gt_rec if r["status"] == "FN"]
    kasus += [dict(jenis="FP", **{k: r[k] for k in ("sebab", "frame", "x", "y", "depth", "skor")}) for r in fp_rec]
    return dict(n_frame=len(pkl["names"]), n_gt=len(gt_rec), edges=edges, tabel=tabel, jauh=jauh, kasus=kasus,
                n_tp=sum(1 for r in gt_rec if r["status"] == "TP"), n_fp=len(fp_rec))


def cetak(h, skor_min, iou_thr):
    n_fn = h["n_gt"] - h["n_tp"]
    print("frame: %d | objek dekat: %d | skor >= %.2f | IoU >= %.2f" % (h["n_frame"], h["n_gt"], skor_min, iou_thr))
    print("TP %d | FN %d | FP %d (harus sama dengan baris skor %.2f di evaluasi.py)" % (h["n_tp"], n_fn, h["n_fp"], skor_min))
    print("jarak objek dekat (m): min %.1f | maks %.1f" % (h["edges"][0], h["edges"][-1]))
    kk = ("tanpa_deteksi", "lokalisasi", "berimpit")
    fk = ("duplikat", "lokalisasi", "latar", "tak_valid")
    print("\nPenyebab FN: " + " | ".join("%s %d (%.0f%%)" % (s, sum(b["fn_" + s] for b in h["tabel"]),
          100.0 * sum(b["fn_" + s] for b in h["tabel"]) / max(n_fn, 1)) for s in kk))
    print("Penyebab FP: " + " | ".join("%s %d (%.0f%%)" % (s, sum(b["fp_" + s] for b in h["tabel"]),
          100.0 * sum(b["fp_" + s] for b in h["tabel"]) / max(h["n_fp"], 1)) for s in fk))
    print("\n%2s %13s %5s %5s %5s %7s | %8s %8s %8s | %5s %5s %5s %5s %5s | %6s" %
          ("kl", "jarak (m)", "GT", "TP", "FN", "recall", "tnpdtk", "lokal", "berimp", "FP", "dupl", "lokal", "latar", "tkvld", "medIoU"))
    for b in h["tabel"]:
        print("%2d %5.1f-%-7.1f %5d %5d %5d %7.3f | %8d %8d %8d | %5d %5d %5d %5d %5d | %6.3f" %
              (b["kelompok"], b["dari_m"], b["sampai_m"], b["n_gt"], b["TP"], b["FN"], b["recall"],
               b["fn_tanpa_deteksi"], b["fn_lokalisasi"], b["fn_berimpit"],
               b["FP"], b["fp_duplikat"], b["fp_lokalisasi"], b["fp_latar"], b["fp_tak_valid"], b["med_iou_tp"]))
    print("\nGalat ukuran median pada TP per kelompok jarak (relatif; kedalaman dalam m):")
    for b in h["tabel"]:
        print("  kl %d: w %.0f%% | h %.0f%% | l %.0f%% | kedalaman %.2f m" %
              (b["kelompok"], 100 * b["med_rel_w"], 100 * b["med_rel_h"], 100 * b["med_rel_l"], b["med_galat_depth_m"]))
    j = h["jauh"]
    print("\nObjek jauh (y < y_min): %d | pusat terdeteksi: %d (%.0f%%) | deteksi zona jauh tanpa label di selnya: %d" %
          (j["n"], j["terdeteksi"], 100.0 * j["terdeteksi"] / max(j["n"], 1), j["tanpa_label"]))
    print("  ukuran deteksi pada objek jauh yang terdeteksi, median |w| %.2f m | |h| %.2f m | |l| %.2f m" %
          (j["med_abs_w"], j["med_abs_h"], j["med_abs_l"]))
    print("  ukuran mendekati nol (semua |w|,|h|,|l| < %.1f m): %d dari %d" % (j["nol_m"], j["dekat_nol"], j["terdeteksi"]))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--pred", required=True)
    p.add_argument("--labels", default=os.path.expanduser("~/projects/data_session0_right/converted/labels"))
    p.add_argument("--y-min", type=float, default=150)
    p.add_argument("--iou", type=float, default=0.5)
    p.add_argument("--skor-min", type=float, default=0.1)
    p.add_argument("--bin", type=int, default=5)
    p.add_argument("--nol-m", type=float, default=1.0)
    p.add_argument("--csv", default=None, help="awalan berkas keluaran; bawaan = nama pkl")
    a = p.parse_args(argv)

    import kamera
    cam = kamera.load_camera()
    with open(a.pred, "rb") as f:
        pkl = pickle.load(f)
    h = analisis(pkl, a.labels, cam["K"], cam["T"], a.y_min, a.iou, a.skor_min, a.bin, a.nol_m)
    cetak(h, a.skor_min, a.iou)
    awal = a.csv or os.path.splitext(a.pred)[0]
    with open(awal + "_jarak.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(h["tabel"][0].keys()))
        w.writeheader()
        w.writerows(h["tabel"])
    with open(awal + "_kasus.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["jenis", "sebab", "frame", "x", "y", "depth", "skor"])
        w.writeheader()
        w.writerows(h["kasus"])
    print("\ntersimpan:", awal + "_jarak.csv", "|", awal + "_kasus.csv", "(%d baris FN dan FP)" % len(h["kasus"]))


if __name__ == "__main__":
    main()