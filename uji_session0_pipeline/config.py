"""
Konfigurasi terpusat. Semua angka yang memengaruhi hasil ada di sini.

Kolom "Dasar" di komentar menyatakan asal nilai:
  [rujukan]    ada dasar literatur (disebut di komentar)
  [kode asal]  diwarisi dari proyek asal antoinekeller/3d_bbox_highway
  [heuristik]  dipilih/diuji manual pada video uji; BELUM ada rujukan
               literatur. Nilainya perlu dievaluasi, jangan dianggap baku.
"""

import os

# ----------------------------------------------------------------------
# Citra dan kalibrasi kamera
# Model kamera lubang jarum (pinhole): Hartley & Zisserman, "Multiple View
# Geometry in Computer Vision", 2nd ed., Cambridge Univ. Press, 2004, bab 6.
# Nilai awal berasal dari simulator CARLA [kode asal]; untuk video nyata
# setel ulang dengan: python -m tools.calibrate_tuner VIDEO.mp4
# ----------------------------------------------------------------------
IMG_W = 1280
IMG_H = 720
PITCH_DEG = 9.80       # kamera menunduk (derajat)
CAM_HEIGHT_M = 8.30    # tinggi kamera dari jalan (meter)
FOCAL_PX = 770.00      # focal length (piksel)
# Kalibrasi kamera nyata dari berkas BrnoCompSpeed (calibParams.xml). Bila diisi, PITCH_DEG,
# CAM_HEIGHT_M, dan FOCAL_PX di atas TIDAK dipakai oleh geometry.py. None = pakai model pitch di atas.
CALIB_XML = os.path.expanduser("~/projects/data_session0_right/calib/session0_right_calibParams.xml")
CALIB_REF_SIZE = (1920, 1080)   # ukuran citra asli yang dipakai berkas kalibrasi (lebar, tinggi)

# ----------------------------------------------------------------------
# Detektor CenterNet
# Zhou, Wang, Krahenbuhl, "Objects as Points", arXiv:1904.07850, 2019.
# Stride 32 karena backbone ResNet-18 dipotong di layer4 [kode asal].
# ----------------------------------------------------------------------
MODEL_SCALE = 32
DEFAULT_CONF = 0.5         # ambang skor deteksi [kode asal]
CACHE_CONF_DEFAULT = 0.2   # ambang terendah saat membuat cache [heuristik]

# ----------------------------------------------------------------------
# Filter deteksi (setelah diproyeksikan ke bidang jalan)
# [kode asal] untuk struktur filter; angka ambang [heuristik]
# ----------------------------------------------------------------------
LANE_HALF_WIDTH_M = 20.0   # session0_right [heuristik] (sebelumnya 11.0)
MIN_WIDTH_M = 0.6          # sebelumnya 1.0; dilonggarkan karena lebar dari model CARLA sering meleset
MAX_WIDTH_M = 2.5          # lebar dipotong sampai batas ini
HEIGHT_RANGE_M = (1.0, 5.0)
MIN_LENGTH_M = 3.0

# ----------------------------------------------------------------------
# Kalman Filter (constant velocity pada sumbu jalan)
# R. E. Kalman, "A New Approach to Linear Filtering and Prediction
# Problems", J. Basic Engineering 82(1), 1960.
# Model constant velocity dan bentuk Joseph: Bar-Shalom, Li, Kirubarajan,
# "Estimation with Applications to Tracking and Navigation", Wiley, 2001.
# Besaran Q dan R di bawah ini [heuristik].
# ----------------------------------------------------------------------
MAX_ACCEL = 2.0            # m/s^2, percepatan wajar mobil di jalan tol
LATERAL_STD = 1.0          # m/s, gerak lateral kecil
DIM_STD_PER_STEP = 0.01    # m per frame; dimensi dibuat hampir konstan
# simpangan baku awal state: x, y, vy, w, h, l
KF_INIT_STD = (1.0, 3.0, 20.0, 2.0, 2.0, 3.0)
# Noise pengukuran membesar dengan jarak (depth, meter): std = a + b * depth^p
KF_STD_X = (0.15, 0.010, 1)
KF_STD_Y = (0.20, 0.0005, 2)
KF_STD_DIM = (0.30, 0.015, 1)

# ----------------------------------------------------------------------
# Tracking
# Asosiasi Hungarian: H. W. Kuhn, Naval Research Logistics Quarterly 2(1-2),
# 1955; implementasi SciPy mengikuti D. F. Crouse, IEEE Trans. Aerospace and
# Electronic Systems 52(4), 2016.
# Kombinasi Kalman + Hungarian + min_hits/max_age: A. Bewley dkk., "Simple
# Online and Realtime Tracking" (SORT), ICIP 2016, arXiv:1602.00763.
# Asosiasi dua tahap (--conf-low): Y. Zhang dkk., "ByteTrack", ECCV 2022,
# arXiv:2110.06864.
# Nilai angka di bawah [heuristik].
# ----------------------------------------------------------------------
MAX_LOST_FRAMES = 30        # track dihapus setelah sekian frame tanpa deteksi (max_age)
MIN_HITS_TO_DISPLAY = 3     # track baru dipakai/ditampilkan setelah sekian deteksi (min_hits)
MAX_LOST_TO_DISPLAY = 5     # track hilang > sekian frame tidak ditampilkan
MAX_TRACK_DEPTH_M = 105.0   # session0_right [heuristik] (sebelumnya 40.0)
CONFLICT_DIST_M = 3.0       # dua track lebih dekat dari ini dianggap duplikat
# Gerbang asosiasi adaptif: batas = base + slope * kedalaman (meter).
# Objek jauh lebih noisy, objek yang baru hilang diberi toleransi lebih besar.
GATE_TRACKED = {"dist": (2.0, 0.05), "lateral": (1.0, 0.01)}
GATE_LOST = {"dist": (4.0, 0.05), "lateral": (2.0, 0.01)}

# ----------------------------------------------------------------------
# Klasifikasi kendaraan (dari ukuran terukur, dengan voting)
# SELURUH bagian ini [heuristik]: ambang panjang dan batas ukuran dipilih
# manual. Detektor tidak membedakan jenis kendaraan (head heatmap 1 kanal).
# ----------------------------------------------------------------------
CLASSES = ("car", "van", "truck", "bus")   # urutan = prioritas saat suara seri
CAR_MAX_LEN_M = 5.2
VAN_MAX_LEN_M = 7.0
TEMPLATES = {
    "car": {"w": 1.85, "h": 1.50, "l": 4.50},
    "van": {"w": 2.00, "h": 2.00, "l": 5.60},
    "truck": {"w": 2.50, "h": 3.20, "l": 9.00},
    "bus": {"w": 2.55, "h": 3.20, "l": 11.00},
}
LIMITS = {
    "car": {"w": (1.6, 2.1), "h": (1.2, 1.9), "l": (3.5, 5.3)},
    "van": {"w": (1.8, 2.3), "h": (1.7, 2.6), "l": (4.8, 7.0)},
    "truck": {"w": (2.2, 2.6), "h": (2.5, 4.2), "l": (6.5, 13.0)},
    "bus": {"w": (2.3, 2.6), "h": (2.8, 4.2), "l": (9.0, 14.0)},
}
DIM_BUF_SIZE = 30          # jumlah pengamatan dimensi yang disimpan (median)

# ----------------------------------------------------------------------
# Kotak 3D untuk tampilan [heuristik]
# ----------------------------------------------------------------------
MEASURED_WEIGHT = 0.5      # 0 = template saja, 1 = ukuran terukur saja
DIM_WARMUP = 10            # bobot ukuran terukur naik sampai sekian pengamatan
YAW_WINDOW = 10            # jumlah posisi terakhir untuk menaksir arah
YAW_MIN_DISPLACEMENT_M = 1.0
YAW_ALPHA = 0.2            # EMA pada sudut ganda
YAW_MAX_DEG = 35.0

# ----------------------------------------------------------------------
# Counting dengan garis virtual [heuristik]
# ----------------------------------------------------------------------
LINE_Y_DEFAULT_M = 50.0   # session0_right [heuristik] (sebelumnya 15.0)
COUNT_LOG = "counting_log.csv"
OUTPUT_DIR = "output_frames"

# ----------------------------------------------------------------------
# Klasifier gambar 4 kelas (ResNet-18, dilatih pada MIO-TCD + potongan session0_right)
# [heuristik] cara menggabungkan dengan panjang; bobot dari dosen/penelitian sendiri.
# ----------------------------------------------------------------------
KLAS_MODEL = os.path.expanduser("~/projects/bobot/klasifikasi/klas_ft2.pth")
KLAS_UKURAN = 128          # sisi letterbox masukan (sama dengan saat latihan)
KLAS_EVERY = 2             # klasifikasi gambar tiap sekian frame per track (hemat waktu)
KLAS_MIN_SIDE_PX = 24      # crop dengan sisi terpanjang lebih kecil dari ini dilewati
KLAS_MIN_VISIBLE = 0.7     # bagian kotak yang harus ada di dalam gambar (kotak terpotong dilewati)
KLAS_MARGIN = 0.05         # tambahan sisi crop (pecahan dari ukuran kotak)
LEN_SIGMA_M = 0.7          # kelunakan prior panjang di luar rentang LIMITS["l"]
LEN_FLOOR = 0.03           # prior panjang minimum agar satu pengamatan tidak mematikan kelas
# Warna kotak/label per kelas (BGR)
CLASS_COLORS = {
    "car": (0, 200, 0),       # hijau
    "van": (0, 215, 255),     # kuning
    "truck": (0, 0, 255),     # merah
    "bus": (255, 128, 0),     # biru
}

# ----------------------------------------------------------------------
# Garis counting kedua untuk jalur yang MENJAUH [heuristik, diukur dari video uji]
# Kendaraan dengan x >= MEDIAN_X_M (kanan median) memakai LINE_Y_AWAY_M, sisanya LINE_Y_DEFAULT_M.
# Garis menjauh harus lebih jauh dari tempat jalur terluar mulai terlihat di tepi gambar.
# ----------------------------------------------------------------------
MEDIAN_X_M = 7.0           # batas dua arah (x dunia, meter)
LINE_Y_AWAY_M = 85.0       # garis untuk kendaraan yang menjauh (meter dari kamera)

# ----------------------------------------------------------------------
# Profil kamera dari antarmuka web. Bila variabel lingkungan PROFIL_KAMERA berisi jalur berkas
# JSON, nilai kalibrasi dan garis hitung di atas ditimpa oleh isi berkas itu (per kamera/node).
# Tanpa variabel itu, config ini berlaku apa adanya.
# ----------------------------------------------------------------------
import os as _os
_profil_kamera = _os.environ.get("PROFIL_KAMERA")
if _profil_kamera and _os.path.exists(_profil_kamera):
    import json as _json
    with open(_profil_kamera, encoding="utf-8") as _f:
        for _k, _v in _json.load(_f).items():
            if _k in ("CALIB_XML", "PITCH_DEG", "CAM_HEIGHT_M", "FOCAL_PX", "LANE_HALF_WIDTH_M",
                      "MAX_TRACK_DEPTH_M", "LINE_Y_DEFAULT_M", "LINE_Y_AWAY_M", "MEDIAN_X_M"):
                globals()[_k] = _v
