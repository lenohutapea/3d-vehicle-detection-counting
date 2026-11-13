#!/usr/bin/env python3
"""pasang_jalur.py - sesuaikan jalur, median, arah, dan garis hitung untuk kamera session0_right.
Dasar: kalibrasi.png (grid jarak) dan keterangan pengguna: jalur kiri (3 lajur) = MENDEKAT,
jalur kanan = MENJAUH. Repo asal berasumsi sebaliknya (kiri median = menjauh), jadi ditambah
config.AWAY_SIDE ("left"/"right" = sisi median tempat kendaraan menjauh).
Perubahan (setiap potongan harus ditemukan tepat 1 kali, kalau tidak berhenti tanpa mengubah apa pun):
  config.py    : LANE_X_MIN, LANE_X_MAX, MEDIAN_X, MAX_TRACK_DEPTH_M, LINE_Y_DEFAULT_M,
                 LINE_Y_AWAY_DEFAULT_M diganti; AWAY_SIDE ditambah
  counter.py   : sisi 'menjauh' dibaca dari AWAY_SIDE (2 tempat)
  visualize.py : garis hitung digambar di sisi 'mendekat'
  tests/       : conftest.py baru (mengunci tata letak jalur untuk tes sintetis, yang dibuat untuk CARLA)
                 dan satu tes baru test_two_way_kanan_menjauh di test_pipeline.py
Cadangan: <berkas>.sebelum_jalur. Pemakaian: python3 pasang_jalur.py [folder_repo]
"""
import os, re, shutil, sys
repo = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/projects/3d-car-classification-counting")

def baca(n):
    return open(os.path.join(repo, n), encoding="utf-8").read()

def ganti1(s, a, b, nama):
    if s.count(a) != 1:
        raise SystemExit("%s: potongan tidak ditemukan tepat 1 kali (%d), dihentikan:\n%s" % (nama, s.count(a), a))
    return s.replace(a, b)

NILAI = [("LANE_X_MIN", "-5.5"), ("LANE_X_MAX", "14.0"), ("MEDIAN_X", "7.0"),
         ("MAX_TRACK_DEPTH_M", "105.0"), ("LINE_Y_DEFAULT_M", "50.0"), ("LINE_Y_AWAY_DEFAULT_M", "50.0")]

cfg_s = baca("config.py")
if "AWAY_SIDE" in cfg_s:
    raise SystemExit("config.py sudah punya AWAY_SIDE; tidak diubah")
for nama, baru in NILAI:
    m = re.findall(r"(?m)^%s = ([-0-9.]+)(.*)$" % nama, cfg_s)
    if len(m) != 1:
        raise SystemExit("config.py: baris '%s = ...' tidak ditemukan tepat 1 kali (%d)" % (nama, len(m)))
    lama = m[0][0]
    cfg_s = re.sub(r"(?m)^%s = [-0-9.]+.*$" % nama,
                   "%s = %s   # session0_right, perkiraan dari kalibrasi.png [heuristik] (bawaan CARLA: %s)" % (nama, baru, lama), cfg_s)
TAMBAH = (
    "\n# Sisi median tempat kendaraan MENJAUH dari kamera: 'left' (x < MEDIAN_X) atau 'right' (x >= MEDIAN_X)."
    "\n# session0_right: jalur kiri (3 lajur) MENDEKAT, jalur kanan MENJAUH. Bawaan proyek asal: 'left'."
    "\nAWAY_SIDE = 'right'"
)
cfg_s = re.sub(r"(?m)^(MEDIAN_X = .*)$", lambda m: m.group(1) + TAMBAH, cfg_s, count=1)

cnt = baca("counter.py")
cnt = ganti1(cnt, "            away = t.x() < cfg.MEDIAN_X\n", "            away = is_away(t.x())\n", "counter.py")
cnt = ganti1(cnt, "if v[\"x_first\"] < cfg.MEDIAN_X else self.line_y", "if is_away(v[\"x_first\"]) else self.line_y", "counter.py")
cnt = ganti1(cnt, "# arah = sisi median saat melintasi garis (x < MEDIAN_X = menjauh)\nDIRECTIONS = (\"mendekat\", \"menjauh\")\n",
             "# arah = sisi median saat melintasi garis (sisi mana yang menjauh: cfg.AWAY_SIDE)\nDIRECTIONS = (\"mendekat\", \"menjauh\")\n\n\n"
             "def is_away(x):\n    \"\"\"True bila posisi lateral x ada di sisi median tempat kendaraan menjauh dari kamera.\"\"\"\n"
             "    if getattr(cfg, \"AWAY_SIDE\", \"left\") == \"right\":\n        return x >= cfg.MEDIAN_X\n    return x < cfg.MEDIAN_X\n", "counter.py")

vis = baca("visualize.py")
vis = ganti1(vis, "        (line_y, cfg.MEDIAN_X, cfg.LANE_X_MAX, (0, 0, 255)),\n",
             "        (line_y, cfg.LANE_X_MIN, cfg.MEDIAN_X, (0, 0, 255))\n"
             "        if getattr(cfg, \"AWAY_SIDE\", \"left\") == \"right\"\n"
             "        else (line_y, cfg.MEDIAN_X, cfg.LANE_X_MAX, (0, 0, 255)),\n", "visualize.py")

CONFTEST = '''"""Kunci tata letak jalur untuk tes sintetis: aliran sintetis (tests/synthetic.py) dibuat untuk
tata letak CARLA, jadi tes logika tracker/counter tidak boleh ikut berubah saat config.py
disetel untuk kamera lain. Nilai kamera nyata diuji lewat tes lain atau tools/cek_kalibrasi.py."""
import pytest

import config as cfg


@pytest.fixture(autouse=True)
def tata_letak_uji(monkeypatch):
    for nama, nilai in (("LANE_X_MIN", -30.0), ("LANE_X_MAX", 11.0), ("MEDIAN_X", -8.0),
                        ("MAX_TRACK_DEPTH_M", 40.0), ("AWAY_SIDE", "left")):
        monkeypatch.setattr(cfg, nama, nilai, raising=False)
'''

TES_BARU = '''def test_two_way_kanan_menjauh():
    """AWAY_SIDE='right' (seperti session0_right): kiri median = mendekat, kanan median = menjauh."""
    import pytest

    mp = pytest.MonkeyPatch()
    mp.setattr(cfg, "AWAY_SIDE", "right")
    try:
        near, v_near = make_stream(seed=0, fp_rate=0.0)
        far, v_far = make_stream(seed=1, fp_rate=0.0)
        frames = []
        for a, b in zip(near, far):
            kiri = [{**d, "x": d["x"] - 18.0} for d in a]            # mendekat, di kiri median (-8)
            kanan = [{**d, "y": 39.0 - d["y"]} for d in b]           # menjauh (y naik), di kanan median
            frames.append(kiri + kanan)
        tracker, counter = Tracker(DT), LineCounter(15.0, 25.0)
        for idx, dets in enumerate(frames):
            tracker.update(dets, conf_high=0.5)
            tracker.assign_display_ids()
            counter.update(tracker.tracks, idx)
        assert sum(counter.dir_counts["mendekat"].values()) == len(v_near), counter.dir_counts
        assert sum(counter.dir_counts["menjauh"].values()) == len(v_far), counter.dir_counts
    finally:
        mp.undo()


'''

cf = os.path.join(repo, "tests", "conftest.py")
if os.path.exists(cf):
    raise SystemExit("tests/conftest.py sudah ada; gabungkan manual, tidak diubah")
tp = os.path.join(repo, "tests", "test_pipeline.py")
tsrc = open(tp, encoding="utf-8").read()
tsrc = ganti1(tsrc, "def test_config_thresholds_consistent():", TES_BARU + "def test_config_thresholds_consistent():", "tests/test_pipeline.py")

for n, s in (("config.py", cfg_s), ("counter.py", cnt), ("visualize.py", vis), ("tests/test_pipeline.py", tsrc)):
    p = os.path.join(repo, n)
    shutil.copy2(p, p + ".sebelum_jalur")
    open(p, "w", encoding="utf-8").write(s)
open(cf, "w", encoding="utf-8").write(CONFTEST)
print("selesai. cadangan: <berkas>.sebelum_jalur; tests/conftest.py dibuat")