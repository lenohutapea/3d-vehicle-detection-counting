"""cek_target.py - memeriksa dari file label: objek di tepi sel, tabrakan sel, dan sebaran y.
Meniru indeks sel make_hm_offset_regr (notebook baris 127 dan 143-148): sel = (int(y/32), int(x/32)).
Hanya membaca; tidak mengubah apa pun. Pemakaian: python3 cek_target.py [folder_labels]
"""
import os, sys, glob
import pandas as pd

M = 32
Y_MIN = 150
NROW, NCOL = 720 // M + 1, 1280 // M      # 23 x 40, sama dengan notebook baris 118
folder = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/projects/data_session0_right/converted/labels")

files = sorted(glob.glob(os.path.join(folder, "*.txt")))
n_obj = n_y_lt_ymin = n_y_lt_M = n_x_lt_M = 0
dup_all = dup_far = dup_near = 0           # objek yang selnya sudah ditempati objek lain di frame yang sama
frames_dup = 0
wrap_hit = 0                                # objek x<32 yang isian 3x3-nya membungkus ke sel PUSAT objek lain
for fp in files:
    df = pd.read_csv(fp)
    cells = {}
    objs = []
    for _, c in df.iterrows():
        cx, cy = int(c["x"] / M), int(c["y"] / M)
        objs.append((cx, cy, c["y"]))
    n_obj += len(objs)
    seen, dup_here = set(), 0
    for cx, cy, y in objs:
        if y < Y_MIN: n_y_lt_ymin += 1
        if y < M: n_y_lt_M += 1
        if cx == 0: n_x_lt_M += 1
        if (cx, cy) in seen:
            dup_here += 1
            dup_all += 1
            if y < Y_MIN: dup_far += 1
            else: dup_near += 1
        seen.add((cx, cy))
    if dup_here: frames_dup += 1
    centers = set((cx, cy) for cx, cy, _ in objs)
    for cx, cy, y in objs:
        if y >= Y_MIN and cx == 0:
            for i in (-1, 0, 1):
                if (NCOL - 1 + 0, cy + i) in centers:   # kolom -1 membungkus ke kolom terakhir
                    wrap_hit += 1
                    break

print("folder:", folder)
print("file label: %d | objek: %d" % (len(files), n_obj))
print("objek y < %d (jauh, tanpa target ukuran): %d (%.1f%%)" % (Y_MIN, n_y_lt_ymin, 100.0 * n_y_lt_ymin / max(n_obj, 1)))
print("objek y < %d (sel baris 0, bisa membungkus bila Y_MIN=0): %d" % (M, n_y_lt_M))
print("objek x < %d (sel kolom 0, isian j=-1 membungkus ke kolom terakhir): %d" % (M, n_x_lt_M))
print("objek yang selnya sudah ditempati objek lain di frame yang sama: %d (di frame: %d)" % (dup_all, frames_dup))
print("   dari itu y < %d: %d | y >= %d: %d" % (Y_MIN, dup_far, Y_MIN, dup_near))
print("objek x<32 (y>=%d) yang isian membungkusnya jatuh di sel pusat objek lain: %d" % (Y_MIN, wrap_hit))