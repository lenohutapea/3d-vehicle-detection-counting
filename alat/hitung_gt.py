#!/usr/bin/env python3
"""hitung_gt.py - hitungan kebenaran dasar (ground truth) dari anotasi XML session0_right, lalu
bandingkan dengan counting_log.csv hasil pipeline.

Cara kerja:
  1. Untuk tiap frame --first..--last baca XML: tiap <object> punya type, vertex2d, veh_size (p x l x t, meter).
     Titik tanah kendaraan = rata-rata 4 titik alas (4 vertex2d pertama), diskalakan ke IMG_W x IMG_H lalu
     diproyeksikan ke jalan memakai geometry.py repo (kamera yang SAMA dengan pipeline).
  2. XML tidak punya ID antar-frame, jadi kendaraan dihubungkan sendiri antar-frame (Hungarian, jarak posisi).
  3. Kendaraan dihitung "melintas" bila posisi z-nya berpindah dari satu sisi garis --line ke sisi lain
     (aturan sama dengan counter.py). z mengecil = mendekat, z membesar = menjauh.
  4. Dengan --log: tiap baris counting_log.csv dicocokkan ke kendaraan GT (selisih frame <= --tol-frame,
     selisih x <= --tol-x). Dilaporkan TP, FP (terhitung pipeline tapi tidak ada di GT), FN (ada di GT tapi
     tidak terhitung), dan galat panjang terukur.
Jalankan DARI folder repo pipeline (agar config.py dan geometry.py yang sama terbaca):
  cd ~/projects/uji_session0_pipeline
  python3 ~/projects/alat/hitung_gt.py --first 2545 --last 3181 --line 50 --log counting_log.csv
Frame video = nomor gambar - --first (video uji dimulai dari --first).
"""
import argparse, csv, glob, os, re, sys
import xml.etree.ElementTree as ET

import numpy as np
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, os.getcwd())
import config as cfg                      # noqa: E402
from geometry import get_position_ground  # noqa: E402

NUM = re.compile(r"\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)")


def baca_frame(path):
    root = ET.parse(path).getroot()
    w = float(root.findtext("size/width", "1920"))
    s = cfg.IMG_W / w
    out = []
    for o in root.findall("object"):
        pts = [(float(a), float(b)) for a, b in NUM.findall(o.findtext("vertex2d", ""))]
        if len(pts) < 4:
            continue
        gx = float(np.mean([p[0] for p in pts[:4]])) * s
        gy = float(np.mean([p[1] for p in pts[:4]])) * s
        g = get_position_ground(gx, gy)
        size = [float(v) for v in o.findtext("veh_size", "0 0 0").split()]
        out.append({"type": o.findtext("type", "?"), "x": float(g[0]), "z": float(g[2]),
                    "l": size[0], "w": size[1], "h": size[2]})
    return out


def hubungkan(frames, first):
    tracks = []
    for fi, dets in enumerate(frames):
        f = first + fi
        aktif = [t for t in tracks if f - t["last_f"] <= 3]
        cost = np.full((len(aktif), len(dets)), 1e6)
        for a, t in enumerate(aktif):
            gap = f - t["last_f"]
            px = t["pts"][-1][1] + t["vx"] * gap
            pz = t["pts"][-1][2] + t["vz"] * gap
            for j, d in enumerate(dets):
                dist = float(np.hypot(d["x"] - px, d["z"] - pz))
                if dist <= 2.5 + 0.8 * gap:
                    cost[a, j] = dist
        used = set()
        if aktif and dets:
            for a, j in zip(*linear_sum_assignment(cost)):
                if cost[a, j] < 1e6:
                    t, d = aktif[a], dets[j]
                    gap = f - t["last_f"]
                    t["vx"] = (d["x"] - t["pts"][-1][1]) / gap
                    t["vz"] = (d["z"] - t["pts"][-1][2]) / gap
                    t["pts"].append((f, d["x"], d["z"]))
                    t["last_f"] = f
                    t["ls"].append(d["l"])
                    used.add(j)
        for j, d in enumerate(dets):
            if j not in used:
                tracks.append({"pts": [(f, d["x"], d["z"])], "last_f": f, "vx": 0.0, "vz": 0.0,
                               "type": d["type"], "ls": [d["l"]]})
    return tracks


def persilangan(t, line):
    p = t["pts"]
    for (f0, _, z0), (f1, _, z1) in zip(p, p[1:]):
        if z0 != z1 and (z0 - line) * (z1 - line) <= 0:
            frac = (line - z0) / (z1 - z0)
            return f0 + frac * (f1 - f0), ("mendekat" if z1 < z0 else "menjauh")
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ann", default=os.path.expanduser("~/projects/data_session0_right/annotations"))
    ap.add_argument("--first", type=int, default=2545)
    ap.add_argument("--last", type=int, default=3181)
    ap.add_argument("--line", type=float, default=cfg.LINE_Y_DEFAULT_M)
    ap.add_argument("--line-away", type=float, default=getattr(cfg, "LINE_Y_AWAY_M", None),
                    help="garis untuk x >= --median-x (jalur menjauh); bawaan dari config bila ada")
    ap.add_argument("--median-x", type=float, default=getattr(cfg, "MEDIAN_X_M", 7.0))
    ap.add_argument("--log", default=None)
    ap.add_argument("--tol-frame", type=int, default=25)
    ap.add_argument("--tol-x", type=float, default=4.0)
    ap.add_argument("--min-frames", type=int, default=3, help="abaikan lintasan GT yang lebih pendek dari ini")
    ap.add_argument("--out", default="gt_hitung.csv")
    a = ap.parse_args()

    frames = []
    for n in range(a.first, a.last + 1):
        p = os.path.join(a.ann, "session0_right_%06d.xml" % n)
        frames.append(baca_frame(p) if os.path.exists(p) else [])
    tracks = [t for t in hubungkan(frames, a.first) if len(t["pts"]) >= a.min_frames]
    for k, t in enumerate(tracks):
        t["id"] = k + 1
        t["x_med"] = float(np.median([p[1] for p in t["pts"]]))
        t["l_med"] = float(np.median(t["ls"]))
        t["line"] = a.line_away if (a.line_away is not None and t["x_med"] >= a.median_x) else a.line
        t["cross_f"], t["arah"] = persilangan(t, t["line"])
        t["cross_vid"] = None if t["cross_f"] is None else t["cross_f"] - a.first

    cross = [t for t in tracks if t["cross_f"] is not None]
    print("Frame %d-%d (%d frame), garis z = %.1f m%s" % (a.first, a.last, len(frames), a.line,
          "" if a.line_away is None else "; x >= %.1f memakai garis z = %.1f m" % (a.median_x, a.line_away)))
    print("Lintasan GT: %d (>= %d frame); melintasi garis: %d" % (len(tracks), a.min_frames, len(cross)))
    for arah in ("mendekat", "menjauh"):
        ts = [t for t in cross if t["arah"] == arah]
        tipe = {}
        for t in ts:
            tipe[t["type"]] = tipe.get(t["type"], 0) + 1
        print("  %-9s: %d  %s" % (arah, len(ts), tipe))
    print("\nLintasan yang MELINTASI garis (frame video = nomor gambar - %d):" % a.first)
    print("  id  tipe    p(m)  x_med  frame_gambar   z awal->akhir   frame_melintas  arah")
    for t in sorted(cross, key=lambda t: t["cross_vid"]):
        print("  %2d  %-6s %5.2f  %5.1f  %5d-%-5d  %6.1f->%-6.1f  %8.1f      %s" % (
            t["id"], t["type"], t["l_med"], t["x_med"], t["pts"][0][0], t["pts"][-1][0],
            t["pts"][0][2], t["pts"][-1][2], t["cross_vid"], t["arah"]))
    nc = [t for t in tracks if t["cross_f"] is None]
    print("\nLintasan yang TIDAK melintasi garis: %d" % len(nc))
    print("  id  tipe    x_med  frame_gambar   z awal->akhir   keterangan")
    for t in nc:
        z0, z1 = t["pts"][0][2], t["pts"][-1][2]
        if abs(z1 - z0) < 2.0:
            ket = "diam (kendaraan parkir)"
        elif min(z0, z1) > t["line"]:
            ket = "seluruhnya lebih jauh dari garis"
        else:
            ket = "seluruhnya lebih dekat dari garis"
        print("  %2d  %-6s %5.1f  %5d-%-5d  %6.1f->%-6.1f   %s" % (
            t["id"], t["type"], t["x_med"], t["pts"][0][0], t["pts"][-1][0], z0, z1, ket))

    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "tipe", "panjang_m", "x_med", "frame_awal", "frame_akhir", "z_awal", "z_akhir", "melintas_frame_video", "arah"])
        for t in tracks:
            w.writerow([t["id"], t["type"], round(t["l_med"], 2), round(t["x_med"], 2), t["pts"][0][0], t["pts"][-1][0],
                        round(t["pts"][0][2], 1), round(t["pts"][-1][2], 1),
                        "" if t["cross_vid"] is None else round(t["cross_vid"], 1), t["arah"] or ""])
    print("\nDaftar lengkap GT disimpan:", a.out)

    if a.log:
        ev = list(csv.DictReader(open(a.log)))
        pasang, dipakai = [], set()
        for e in sorted(ev, key=lambda e: int(e["frame"])):
            ef, ex = int(e["frame"]), float(e["x_m"])
            best = None
            for t in cross:
                if t["id"] in dipakai:
                    continue
                df, dx = abs(ef - t["cross_vid"]), abs(ex - t["x_med"])
                if df <= a.tol_frame and dx <= a.tol_x and (best is None or df < best[0]):
                    best = (df, t)
            if best:
                dipakai.add(best[1]["id"]); pasang.append((e, best[1]))
            else:
                pasang.append((e, None))
        tp = sum(1 for _, t in pasang if t); fp = len(pasang) - tp
        fn = [t for t in cross if t["id"] not in dipakai]
        print("\nPERBANDINGAN dengan %s (toleransi %d frame, %.1f m)" % (a.log, a.tol_frame, a.tol_x))
        print("  pipeline menghitung: %d | GT melintasi: %d" % (len(ev), len(cross)))
        print("  TP (cocok): %d | FP (terhitung, tidak ada di GT): %d | FN (ada di GT, tidak terhitung): %d" % (tp, fp, len(fn)))
        print("  presisi = %s | recall = %s" % (
            "%.2f" % (tp / len(ev)) if ev else "-", "%.2f" % (tp / len(cross)) if cross else "-"))
        print("\n  Terhitung pipeline        -> kendaraan GT                 panjang pipeline vs GT")
        for e, t in pasang:
            if t:
                print("   f%-4s id%-3s %-5s x=%5.1f -> GT#%-2d %-6s x=%5.1f  %s   %.2f vs %.2f m" % (
                    e["frame"], e["id"], e["kelas"], float(e["x_m"]), t["id"], t["type"], t["x_med"], t["arah"],
                    float(e["panjang_m"]), t["l_med"]))
            else:
                print("   f%-4s id%-3s %-5s x=%5.1f -> (tidak ada di GT)  <- FP" % (e["frame"], e["id"], e["kelas"], float(e["x_m"])))
        if fn:
            print("\n  Tidak terhitung pipeline (FN):")
            for t in fn:
                print("   GT#%-2d %-6s x=%5.1f frame_gambar %d-%d z %.1f->%.1f %s (melintas di frame video %.0f)" % (
                    t["id"], t["type"], t["x_med"], t["pts"][0][0], t["pts"][-1][0], t["pts"][0][2], t["pts"][-1][2], t["arah"], t["cross_vid"]))


if __name__ == "__main__":
    main()