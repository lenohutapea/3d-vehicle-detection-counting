#!/usr/bin/env python3
"""pasang_jalur_lama.py - setel config.py (versi lokal: satu garis, jalur simetris, arah tidak dibedakan)
untuk kamera session0_right. HANYA mengubah tiga angka di config.py; tidak mengubah kode lain:
  LANE_HALF_WIDTH_M 11.0 -> 14.0   (jalur kanan terlihat sampai x ~ 12-14 m; batas simetris)
  MAX_TRACK_DEPTH_M 40.0 -> 105.0  (kendaraan terlihat di jarak ~27-98 m dari kamera)
  LINE_Y_DEFAULT_M  15.0 -> 50.0   (garis hitung di dalam area gambar)
Dasar: grid jarak kalibrasi.png. Semua [heuristik], disetel lewat uji video.
Tiap baris harus ditemukan tepat 1 kali dengan nilai lama yang diharapkan, kalau tidak berhenti tanpa mengubah apa pun.
Cadangan: config.py.sebelum_jalur. Pemakaian: python3 pasang_jalur_lama.py [folder_repo]"""
import os, re, shutil, sys
repo = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/projects/uji_session0_pipeline")
p = os.path.join(repo, "config.py")
s = open(p, encoding="utf-8").read()
UBAH = (("LANE_HALF_WIDTH_M", "11.0", "14.0"), ("MAX_TRACK_DEPTH_M", "40.0", "105.0"), ("LINE_Y_DEFAULT_M", "15.0", "50.0"))
for nama, lama, baru in UBAH:
    pola = r"(?m)^%s = ([-0-9.]+)(.*)$" % nama
    m = re.findall(pola, s)
    if len(m) != 1:
        raise SystemExit("config.py: baris '%s = ...' ditemukan %d kali (harus 1), dihentikan" % (nama, len(m)))
    if float(m[0][0]) != float(lama):
        raise SystemExit("config.py: %s bernilai %s, bukan %s seperti yang diduga. Sudah ditambal? Dihentikan." % (nama, m[0][0], lama))
    s = re.sub(pola, lambda mm: "%s = %s   # session0_right [heuristik] (sebelumnya %s)" % (nama, baru, lama), s)
shutil.copy2(p, p + ".sebelum_jalur")
open(p, "w", encoding="utf-8").write(s)
print("selesai. cadangan: config.py.sebelum_jalur")
for nama, _, _ in UBAH:
    print(" ", [l for l in s.splitlines() if l.startswith(nama + " =")][0])