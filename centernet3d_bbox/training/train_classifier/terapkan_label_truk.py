#!/usr/bin/env python3
"""terapkan_label_truk.py - terapkan label manual pada potongan 'Truck' session0_right.
Hasil pemeriksaan lembar kontak: #0-#66 = van putih (1-2 kendaraan), #67-#70 = potongan buruk (papan jalan).
Aksi (aman, tidak menghapus apa pun):
  - salin #0-#66 ke uji_session0_right/van_pickup/
  - pindahkan folder 'truk' asli menjadi 'truk_xml_asli' (agar tidak dibaca sebagai kelas truk)
  - catat #67-#70 di uji_session0_right/potongan_dibuang.txt
Jalankan sekali saja."""
import csv, os, shutil
H = os.path.expanduser("~/dataset_publik")
U = H + "/uji_session0_right"
daftar = list(csv.DictReader(open(H + "/hasil_klasifikasi/daftar_truk.csv")))
assert len(daftar) == 71, "daftar_truk.csv harus 71 baris, ada %d" % len(daftar)
assert os.path.isdir(U + "/truk"), "folder truk sudah dipindah? jangan jalankan dua kali"
van, buang = daftar[0:67], daftar[67:71]
os.makedirs(U + "/van_pickup", exist_ok=True)
for r in van:
    shutil.copy2(U + "/" + r["berkas"], U + "/van_pickup/" + os.path.basename(r["berkas"]))
with open(U + "/potongan_dibuang.txt", "w") as f:
    for r in buang:
        f.write("%s (frame %s): potongan bukan kendaraan yang layak\n" % (r["berkas"], r["frame"]))
os.rename(U + "/truk", U + "/truk_xml_asli")
print("van_pickup: %d potongan; dibuang: %d; folder truk -> truk_xml_asli" % (len(van), len(buang)))