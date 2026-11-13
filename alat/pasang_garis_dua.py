#!/usr/bin/env python3
"""pasang_garis_dua.py - garis counting terpisah untuk jalur yang MENJAUH (sisi kanan median).

Masalah: kendaraan jalur kanan masuk dari tepi kanan gambar dan baru terlihat pada jarak
> 50 m, jadi sudah melewati garis 50 m sebelum punya kotak. Solusi: kendaraan dengan
x >= MEDIAN_X_M memakai garis sendiri yang lebih jauh (LINE_Y_AWAY_M).

Jalankan dari folder pipeline SETELAH pasang_klasifikasi.py:
    cd ~/projects/uji_session0_pipeline && python3 ~/projects/alat/pasang_garis_dua.py
Cadangan: <nama>.sebelum_garis2. Menolak jalan dua kali.
"""
import os, shutil, sys


def baca(p):
    return open(p, encoding="utf-8").read()


def ganti(s, lama, baru, nama):
    if s.count(lama) != 1:
        sys.exit("GAGAL: bagian '%s' tidak ditemukan tepat satu kali di %s." % (lama[:50].strip(), nama))
    return s.replace(lama, baru)


for f in ("config.py", "counter.py", "visualize.py", "run.py"):
    if not os.path.exists(f):
        sys.exit("Jalankan dari folder pipeline; %s tidak ada di sini." % f)
if "LINE_Y_AWAY_M" in baca("config.py"):
    sys.exit("Sudah terpasang (LINE_Y_AWAY_M ada di config.py). Tidak melakukan apa-apa.")
if "KLAS_MODEL" not in baca("config.py"):
    sys.exit("Jalankan pasang_klasifikasi.py dulu.")

c, k, v, r = baca("config.py"), baca("counter.py"), baca("visualize.py"), baca("run.py")

c = c.rstrip("\n") + '''

# ----------------------------------------------------------------------
# Garis counting kedua untuk jalur yang MENJAUH [heuristik, diukur dari video uji]
# Kendaraan dengan x >= MEDIAN_X_M (kanan median) memakai LINE_Y_AWAY_M, sisanya LINE_Y_DEFAULT_M.
# Garis menjauh harus lebih jauh dari tempat jalur terluar mulai terlihat di tepi gambar.
# ----------------------------------------------------------------------
MEDIAN_X_M = 7.0           # batas dua arah (x dunia, meter)
LINE_Y_AWAY_M = 85.0       # garis untuk kendaraan yang menjauh (meter dari kamera)
'''

k = ganti(k, "    def __init__(self, line_y=cfg.LINE_Y_DEFAULT_M):\n        self.line_y = line_y\n",
          "    def __init__(self, line_y=cfg.LINE_Y_DEFAULT_M, line_y_away=None):\n        self.line_y = line_y\n"
          "        self.line_y_away = line_y if line_y_away is None else line_y_away\n", "counter.py")
k = ganti(k, "    def total(self):",
          "    def line_for(self, x):\n        \"\"\"Garis yang berlaku untuk posisi lateral x (kanan median = garis menjauh).\"\"\"\n"
          "        return self.line_y_away if x >= cfg.MEDIAN_X_M else self.line_y\n\n    def total(self):", "counter.py")
k = ganti(k, "            y = t.y()\n", "            y = t.y()\n            line = self.line_for(t.x())\n", "counter.py")
k = ganti(k, "                and (prev - self.line_y) * (y - self.line_y) <= 0\n",
          "                and (prev - line) * (y - line) <= 0\n", "counter.py")
k = ganti(k, '                if v["y_min"] > self.line_y:\n',
          '                line = self.line_for(v["x_first"])\n                if v["y_min"] > line:\n', "counter.py")
k = ganti(k, '                elif v["y_max"] < self.line_y:\n', '                elif v["y_max"] < line:\n', "counter.py")

i0, i1 = v.index("def draw_counting_line("), v.index("def draw_counts(")
v = v[:i0] + '''def draw_counting_line(frame, line_y, line_y_away=None):
    """Garis virtual di bidang jalan: kiri median pada line_y, kanan median pada line_y_away."""
    h = frame.shape[0]
    half = cfg.LANE_HALF_WIDTH_M
    if line_y_away is None or line_y_away == line_y:
        segs = [(-half, half, line_y, (0, 0, 255))]
    else:
        segs = [(-half, cfg.MEDIAN_X_M, line_y, (0, 0, 255)),
                (cfg.MEDIAN_X_M, half, line_y_away, (255, 0, 255))]
    for xa, xb, z, col in segs:
        p0 = world_to_image(np.array([xa, 0.0, z]), h)
        p1 = world_to_image(np.array([xb, 0.0, z]), h)
        cv2.line(frame, p0, p1, col, 3)
    return frame


''' + v[i1:]

r = ganti(r, '    p.add_argument("--cache", default=None,',
          '    p.add_argument("--line-y-away", type=float, default=cfg.LINE_Y_AWAY_M,\n'
          '                   help="Garis counting jalur yang MENJAUH, x >= MEDIAN_X_M (meter dari kamera)")\n'
          '    p.add_argument("--cache", default=None,', "run.py")
r = ganti(r, "    counter = LineCounter(args.line_y)\n", "    counter = LineCounter(args.line_y, args.line_y_away)\n", "run.py")
r = ganti(r, "            frame = draw_counting_line(frame, args.line_y)\n",
          "            frame = draw_counting_line(frame, args.line_y, args.line_y_away)\n", "run.py")
r = ganti(r, 'line_y={args.line_y}")', 'line_y={args.line_y} line_y_away={args.line_y_away}")', "run.py")

for f, s in (("config.py", c), ("counter.py", k), ("visualize.py", v), ("run.py", r)):
    shutil.copy(f, f + ".sebelum_garis2")
    open(f, "w", encoding="utf-8").write(s)
print("SELESAI. Garis mendekat = --line-y (kiri median), garis menjauh = --line-y-away (kanan median, bawaan 85 m).")