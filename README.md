# Peta folder ~/projects

| Folder | Isi |
|---|---|
| 3d-car-classification-counting/ | REPO UTAMA pipeline (untuk kamera sendiri) |
| uji_session0_pipeline/ | salinan repo untuk latihan dengan data session0_right: kalibrasi, klasifier gambar 4 kelas, dua garis counting |
| bobot/detektor/ | bobot CenterNet (.pth); yang dipakai: centernet_dari_baru.pth |
| bobot/klasifikasi/ | bobot klasifier gambar 4 kelas; yang dipakai: klas_ft2.pth |
| latih_detektor/ | kode latihan dan evaluasi detektor (train_session0_right.py, evaluasi.py, ...) |
| alat/ | skrip bantu: hitung_gt.py (evaluasi counting), pasang_*.py (patch), cek_kalibrasi.py |
| data_session0_right/ | data acuan latihan: images, annotations, calib |
| video_uji/ | video uji dan cache deteksi |
| hasil/ | log latihan, prediksi, gambar, hasil counting |
| acuan/3d_bbox_highway/ | proyek asal (antoinekeller) sebagai rujukan |
| venv_3dbbox/ | lingkungan Python |

Data dan kode klasifikasi (MIO-TCD) ada di ~/dataset_publik: dataset_klasifikasi/, uji_session0_right/, kode/, hasil_klasifikasi/.

Jalankan pipeline latihan:
  cd ~/projects/uji_session0_pipeline
  python3 run.py ~/projects/video_uji/uji_val_720p.mp4 ~/projects/bobot/detektor/centernet_dari_baru.pth --cache ~/projects/video_uji/det_session0.pkl --conf 0.4 --conf-low 0.2 --no-show --no-save
  python3 ~/projects/alat/hitung_gt.py --first 2545 --last 3181 --line 50 --log counting_log.csv

| latih_klasifikasi/ | kode latihan klasifier gambar 4 kelas (data di ~/dataset_publik) |

Tidak ikut di repo ini: data (session0_right, MIO-TCD), bobot .pth, video, dan venv.

| latih_klasifikasi/ | kode latihan klasifier gambar 4 kelas (data di ~/dataset_publik) |

Tidak ikut di repo ini: data (session0_right, MIO-TCD), bobot .pth, video, dan venv.
