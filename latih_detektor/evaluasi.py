#!/usr/bin/env python3
"""evaluasi.py - hitung metrik dari file pickle hasil prediksi.py (numpy + pandas saja, tanpa PyTorch).

Masukan : ~/projects/hasil/prediksi_detektor/<tag>_val.pkl  (dict: args, names, dets)
          label asli di converted/labels/image_NNNN.txt (kolom x,y,w,h,l; piksel 720p, meter)
Kotak 2D ground-truth dibuat dengan cara yang sama dengan uji bolak-balik di dekode.py
(get_position_ground -> 8 sudut Box -> min/maks), jadi pembanding dan prediksi memakai rumus yang sama.

Aturan (semuanya pilihan kita, bukan bawaan notebook; notebook tidak punya evaluasi angka):
 1. Objek ground-truth "dekat" = y >= y_min (default 150), yaitu objek yang punya target ukuran saat latihan.
 2. Deteksi dibagi menurut posisi pusatnya, mengikuti aturan latihan: py < y_min = "zona jauh"
    (tidak punya target ukuran, tidak dihitung sebagai FP, dilaporkan terpisah); py >= y_min = zona
    dekat. Di zona dekat, deteksi dengan w, h, atau l <= 0 adalah kotak tidak valid dan dihitung FP
    (kepala ukuran tidak punya aktivasi akhir, jadi keluarannya bisa negatif; ini terbukti dari pkl uji).
 3. Pencocokan: deteksi diurutkan dari skor tertinggi; tiap deteksi dipasangkan dengan ground-truth
    yang belum terpakai dan IoU 2D tertingginya, dianggap TP bila IoU >= ambang (default 0,5).
 4. Objek jauh (y < y_min) tidak punya target ukuran, jadi hanya dilaporkan "pusat terdeteksi":
    ada deteksi (ukuran apa pun) di sel 32x32 yang sama dengan pusat label.
 5. AP = luas di bawah kurva presisi-recall dengan interpolasi semua titik (gaya PASCAL VOC,
    dari ingatan, belum dicek ke makalahnya) pada deteksi berukuran.
Pemakaian: python3 evaluasi.py --pred ~/projects/hasil/prediksi_detektor/uji_val.pkl
"""
import argparse
import csv
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dekode  # noqa: E402
from dekode import iou_2d, bbox_2d, box_corners_2d  # noqa: E402

SCALE = 32  # dekode.MODEL_SCALE


def muat_gt(path, K, T, y_min):
    """Mengembalikan (dekat, jauh): daftar dict objek label. 'dekat' punya depth dan bbox2d."""
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return [], []
    dekat, jauh = [], []
    for _, c in df.iterrows():
        g = dict(x=float(c["x"]), y=float(c["y"]), w=float(c["w"]), h=float(c["h"]), l=float(c["l"]))
        if g["y"] >= y_min:
            pos = dekode.get_position_ground(g["x"], g["y"], K, T, 720)
            g["depth"] = float(np.linalg.norm(pos - T[:3, 3]))
            g["bbox2d"] = bbox_2d(box_corners_2d(pos[0], pos[2], g["w"], g["h"], g["l"], T, K, 720))
            dekat.append(g)
        else:
            jauh.append(g)
    return dekat, jauh


def berukuran(d):
    return d["w"] > 0 and d["h"] > 0 and d["l"] > 0


def cocokkan_frame(dets, gts, thr):
    """dets: deteksi berukuran. Mengembalikan daftar (skor, tp, indeks_deteksi, indeks_gt, iou)."""
    urut = sorted(range(len(dets)), key=lambda i: -dets[i]["score"])
    terpakai, hasil = set(), []
    for i in urut:
        terbaik, bj = 0.0, None
        for j, g in enumerate(gts):
            if j in terpakai:
                continue
            v = iou_2d(dets[i]["bbox2d"], g["bbox2d"])
            if v > terbaik:
                terbaik, bj = v, j
        if bj is not None and terbaik >= thr:
            terpakai.add(bj)
            hasil.append((dets[i]["score"], True, i, bj, terbaik))
        else:
            hasil.append((dets[i]["score"], False, i, None, terbaik))
    return hasil


def ap_semua_titik(skor, tp, n_gt):
    if n_gt == 0 or len(skor) == 0:
        return 0.0
    o = np.argsort(-np.asarray(skor), kind="stable")
    tp = np.asarray(tp, dtype=float)[o]
    fp = 1.0 - tp
    ctp, cfp = np.cumsum(tp), np.cumsum(fp)
    rec = ctp / n_gt
    prec = ctp / np.maximum(ctp + cfp, 1e-12)
    rec = np.concatenate(([0.0], rec, [1.0]))
    prec = np.concatenate(([0.0], prec, [0.0]))
    for k in range(len(prec) - 2, -1, -1):
        prec[k] = max(prec[k], prec[k + 1])
    idx = np.where(rec[1:] != rec[:-1])[0]
    return float(np.sum((rec[idx + 1] - rec[idx]) * prec[idx + 1]))


def med(x):
    return float(np.median(x)) if len(x) else float("nan")


def evaluasi(pkl, labels, K, T, y_min=150, iou_thr=0.5, ambang_skor=(0.1, 0.3, 0.5, 0.7, 0.9)):
    dets_all, names = pkl["dets"], pkl["names"]
    n_gt = 0
    rek = []          # per deteksi berukuran: skor, tp, galat
    nol_skor = []     # skor deteksi di zona jauh (py < y_min)
    tv_skor = []      # skor deteksi zona dekat dengan kotak tidak valid (w, h, atau l <= 0)
    jauh_skor = []    # skor terbaik per objek jauh (0 bila tidak ada deteksi di selnya)
    for nm in names:
        dekat, jauh = muat_gt(os.path.join(labels, nm[:-4] + ".txt"), K, T, y_min)
        n_gt += len(dekat)
        dets = dets_all[nm]
        zona_jauh = [d for d in dets if d["py"] < y_min]
        dekat_det = [d for d in dets if d["py"] >= y_min]
        ukur = [d for d in dekat_det if berukuran(d)]
        tak_valid = [d for d in dekat_det if not berukuran(d)]
        nol_skor += [d["score"] for d in zona_jauh]
        tv_skor += [d["score"] for d in tak_valid]
        rek += [dict(skor=d["score"], tp=False, iou=0.0) for d in tak_valid]
        for (s, tp, i, j, iou) in cocokkan_frame(ukur, dekat, iou_thr):
            r = dict(skor=s, tp=tp, iou=iou)
            if tp:
                g, d = dekat[j], ukur[i]
                r.update(ew=abs(d["w"] - g["w"]), eh=abs(d["h"] - g["h"]), el=abs(d["l"] - g["l"]),
                         rw=abs(d["w"] - g["w"]) / g["w"], rh=abs(d["h"] - g["h"]) / g["h"],
                         rl=abs(d["l"] - g["l"]) / g["l"], ed=abs(d["depth"] - g["depth"]),
                         rd=abs(d["depth"] - g["depth"]) / g["depth"])
            rek.append(r)
        for g in jauh:
            sel = (int(g["y"] / SCALE), int(g["x"] / SCALE))
            ss = [d["score"] for d in dets if (int(d["py"] / SCALE), int(d["px"] / SCALE)) == sel]
            jauh_skor.append(max(ss) if ss else 0.0)
    ap = ap_semua_titik([r["skor"] for r in rek], [r["tp"] for r in rek], n_gt)
    tabel = []
    for t in ambang_skor:
        pilih = [r for r in rek if r["skor"] >= t]
        tp = [r for r in pilih if r["tp"]]
        fp = len(pilih) - len(tp)
        fn = n_gt - len(tp)
        baris = dict(skor_min=t, TP=len(tp), FP=fp, FN=fn,
                     presisi=len(tp) / max(len(tp) + fp, 1), recall=len(tp) / max(n_gt, 1),
                     deteksi_zona_jauh=sum(1 for s in nol_skor if s >= t),
                     kotak_tak_valid=sum(1 for s in tv_skor if s >= t),
                     jauh_pusat_terdeteksi=sum(1 for s in jauh_skor if s >= t),
                     med_iou_tp=med([r["iou"] for r in tp]),
                     med_galat_w_m=med([r["ew"] for r in tp]), med_galat_h_m=med([r["eh"] for r in tp]),
                     med_galat_l_m=med([r["el"] for r in tp]), med_galat_depth_m=med([r["ed"] for r in tp]),
                     med_rel_w=med([r["rw"] for r in tp]), med_rel_h=med([r["rh"] for r in tp]),
                     med_rel_l=med([r["rl"] for r in tp]), med_rel_depth=med([r["rd"] for r in tp]))
        tabel.append(baris)
    return dict(n_frame=len(names), n_gt_dekat=n_gt, n_gt_jauh=len(jauh_skor),
                n_det_dekat=len(rek), n_det_zona_jauh=len(nol_skor), n_det_tak_valid=len(tv_skor),
                ap=ap, tabel=tabel)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--pred", required=True)
    p.add_argument("--labels", default=os.path.expanduser("~/projects/data_session0_right/converted/labels"))
    p.add_argument("--y-min", type=float, default=150)
    p.add_argument("--iou", type=float, default=0.5)
    p.add_argument("--csv", default=None)
    a = p.parse_args(argv)

    import kamera
    cam = kamera.load_camera()
    with open(a.pred, "rb") as f:
        pkl = pickle.load(f)
    h = evaluasi(pkl, a.labels, cam["K"], cam["T"], a.y_min, a.iou)

    print("berkas: %s | frame: %d" % (a.pred, h["n_frame"]))
    print("objek dekat (y>=%g): %d | objek jauh: %d" % (a.y_min, h["n_gt_dekat"], h["n_gt_jauh"]))
    print("deteksi zona dekat: %d (di antaranya kotak tidak valid: %d) | deteksi zona jauh (py<%g): %d"
          % (h["n_det_dekat"], h["n_det_tak_valid"], a.y_min, h["n_det_zona_jauh"]))
    print("AP (IoU 2D >= %.2f, deteksi zona dekat): %.4f" % (a.iou, h["ap"]))
    print("%8s %6s %6s %6s %8s %8s | %6s %6s %6s | %7s" %
          ("skor>=", "TP", "FP", "FN", "presisi", "recall", "tkvld", "zjauh", "jauhOK", "medIoU"))
    for b in h["tabel"]:
        print("%8.2f %6d %6d %6d %8.3f %8.3f | %6d %6d %6d | %7.3f" %
              (b["skor_min"], b["TP"], b["FP"], b["FN"], b["presisi"], b["recall"],
               b["kotak_tak_valid"], b["deteksi_zona_jauh"], b["jauh_pusat_terdeteksi"], b["med_iou_tp"]))
    print("galat ukuran pada TP, median (m): lihat CSV; ringkas untuk skor>=%.2f:" % h["tabel"][0]["skor_min"])
    b = h["tabel"][0]
    print("  w %.2f m (%.0f%%) | h %.2f m (%.0f%%) | l %.2f m (%.0f%%) | kedalaman %.2f m (%.1f%%)" %
          (b["med_galat_w_m"], 100 * b["med_rel_w"], b["med_galat_h_m"], 100 * b["med_rel_h"],
           b["med_galat_l_m"], 100 * b["med_rel_l"], b["med_galat_depth_m"], 100 * b["med_rel_depth"]))
    out = a.csv or os.path.splitext(a.pred)[0] + "_evaluasi.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(h["tabel"][0].keys()))
        w.writeheader()
        w.writerows(h["tabel"])
    print("tersimpan:", out)


if __name__ == "__main__":
    main()