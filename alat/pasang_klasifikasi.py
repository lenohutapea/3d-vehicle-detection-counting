#!/usr/bin/env python3
"""pasang_klasifikasi.py - tambah klasifier gambar 4 kelas + warna kotak per kelas.

Jalankan DARI folder pipeline (uji_session0_pipeline), bukan repo utama:
    cd ~/projects/uji_session0_pipeline
    python3 ~/projects/alat/pasang_klasifikasi.py
Cadangan tiap berkas: <nama>.sebelum_klas. Menolak jalan dua kali.

Yang diubah:
  config.py            CLASSES 4 kelas (+bus), TEMPLATES/LIMITS bus, CLASS_COLORS, KLAS_*
  classifier.py        suara panjang (prior lunak) digabung dengan probabilitas gambar
  visualize.py         warna kotak/label/panel per kelas (bukan per ID)
  run.py               opsi --klas, --tanpa-gambar, --simpan-crop; panggil klasifier tiap frame
  klasifikasi_gambar.py  (BARU) ResNet-18 klas_ft2.pth; crop dari kotak 3D yang diproyeksikan
"""
import os, shutil, sys

MARK = "KLAS_MODEL"


def baca(p):
    return open(p, encoding="utf-8").read()


def tulis(p, s):
    open(p, "w", encoding="utf-8").write(s)


def ganti(s, lama, baru, nama):
    if s.count(lama) != 1:
        sys.exit("GAGAL: bagian '%s' tidak ditemukan tepat satu kali di %s (versi berkas berbeda dari yang saya kenal)." % (lama[:50].strip(), nama))
    return s.replace(lama, baru)


for f in ("config.py", "classifier.py", "visualize.py", "run.py", "tracker.py"):
    if not os.path.exists(f):
        sys.exit("Jalankan dari folder pipeline; %s tidak ada di sini." % f)
if MARK in baca("config.py"):
    sys.exit("Sudah terpasang (KLAS_MODEL ada di config.py). Tidak melakukan apa-apa.")
for f in ("config.py", "classifier.py", "visualize.py", "run.py"):
    shutil.copy(f, f + ".sebelum_klas")

# ---------------------------------------------------------------- config.py
c = baca("config.py")
c = ganti(c, 'CLASSES = ("car", "van", "truck")   # urutan = prioritas saat suara seri',
          'CLASSES = ("car", "van", "truck", "bus")   # urutan = prioritas saat suara seri', "config.py")
c = ganti(c, '    "truck": {"w": 2.50, "h": 3.20, "l": 9.00},\n}',
          '    "truck": {"w": 2.50, "h": 3.20, "l": 9.00},\n    "bus": {"w": 2.55, "h": 3.20, "l": 11.00},\n}', "config.py")
c = ganti(c, '    "truck": {"w": (2.2, 2.6), "h": (2.5, 4.2), "l": (6.5, 13.0)},\n}',
          '    "truck": {"w": (2.2, 2.6), "h": (2.5, 4.2), "l": (6.5, 13.0)},\n    "bus": {"w": (2.3, 2.6), "h": (2.8, 4.2), "l": (9.0, 14.0)},\n}', "config.py")
c = c.rstrip("\n") + '''

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
'''
if "\nimport os" not in c and not c.lstrip().startswith("import os"):
    # sisipkan import os setelah docstring pembuka
    idx = c.index('"""', 3) + 3
    c = c[:idx] + "\nimport os\n" + c[idx:]
tulis("config.py", c)

# ------------------------------------------------------------- classifier.py
tulis("classifier.py", '''"""
Klasifikasi kendaraan: car / van / truck / bus.

Dua sumber bukti per track:
  1. PANJANG terukur (proyeksi ke bidang jalan): prior lunak per kelas dari config.LIMITS["l"].
     Dipanggil tiap deteksi lewat update(w, h, l).
  2. GAMBAR: probabilitas klasifier ResNet-18 (klasifikasi_gambar.py) lewat add_image(probs).
Skor tiap sumber dirata-ratakan sepanjang hidup track, lalu dikalikan:
  skor[c] = (rata_gambar[c] + EPS) * (rata_panjang[c] + EPS), dinormalkan.
Tanpa pengamatan gambar, kelas ditentukan dari panjang saja (perilaku lama).
Kelas akhir = skor terbesar; seri dimenangkan kelas lebih awal di config.CLASSES.

Dasar: cara menggabungkan ini [heuristik proyek], belum ada rujukan.
Catatan: panjang tidak bisa membedakan truck dan bus (rentangnya tumpang tindih);
yang membedakan hanya gambar.
"""

from collections import deque
import math

import numpy as np

import config as cfg

EPS = 0.02


def classify_by_length(length):
    """Kelas dari panjang saja (ambang tegas); dipakai sebagai cadangan/uji."""
    if length < cfg.CAR_MAX_LEN_M:
        return "car"
    if length < cfg.VAN_MAX_LEN_M:
        return "van"
    return "truck"


def length_prior(length):
    """Prior lunak per kelas dari panjang: 1 di dalam rentang LIMITS[c]["l"], meluruh di luarnya."""
    raw = {}
    for c in cfg.CLASSES:
        lo, hi = cfg.LIMITS[c]["l"]
        d = max(lo - length, length - hi, 0.0)
        raw[c] = max(cfg.LEN_FLOOR, math.exp(-((d / cfg.LEN_SIGMA_M) ** 2)))
    s = sum(raw.values())
    return {c: v / s for c, v in raw.items()}


class VehicleClassifier:
    def __init__(self):
        self.votes = {c: 0.0 for c in cfg.CLASSES}   # skor gabungan terakhir (ditulis counter ke log)
        self.cls = cfg.CLASSES[0]
        self.dim_buf = deque(maxlen=cfg.DIM_BUF_SIZE)  # (w, h, l) terukur
        self._len_sum = {c: 0.0 for c in cfg.CLASSES}
        self._img_sum = {c: 0.0 for c in cfg.CLASSES}
        self.n_len = 0
        self.n_img = 0

    def update(self, w, h, l):
        """Dipanggil setiap kali track mendapat deteksi."""
        for c, p in length_prior(l).items():
            self._len_sum[c] += p
        self.n_len += 1
        self.dim_buf.append((w, h, l))
        self._pilih()

    def add_image(self, probs):
        """probs: {kelas: probabilitas} dari klasifier gambar untuk satu crop."""
        for c in cfg.CLASSES:
            self._img_sum[c] += float(probs.get(c, 0.0))
        self.n_img += 1
        self._pilih()

    def _pilih(self):
        if self.n_len == 0:
            return
        len_m = {c: self._len_sum[c] / self.n_len for c in cfg.CLASSES}
        if self.n_img == 0:
            fused = len_m
        else:
            fused = {c: (self._img_sum[c] / self.n_img + EPS) * (len_m[c] + EPS) for c in cfg.CLASSES}
            s = sum(fused.values())
            fused = {c: v / s for c, v in fused.items()}
        self.votes = fused
        self.cls = max(cfg.CLASSES, key=lambda c: fused[c])  # seri: yang lebih awal menang

    def median_dims(self):
        """Median (w, h, l) terukur."""
        return np.median(np.array(self.dim_buf), axis=0)
''')

# ------------------------------------------------------ klasifikasi_gambar.py
tulis("klasifikasi_gambar.py", '''"""
Klasifier gambar kendaraan (ResNet-18, 4 kelas) untuk pipeline.

Detektor CenterNet tidak punya kotak 2D, jadi crop diambil dari kotak 3D track yang
diproyeksikan ke gambar (persegi panjang pembatas 8 sudut + margin kecil).
Praproses SAMA dengan latihan (latih_klasifikasi.py): letterbox 128 px, isi abu-abu
rata-rata ImageNet, RGB, normalisasi ImageNet.
torch hanya diimpor bila klasifier dipakai (--tanpa-gambar tidak memerlukannya).
"""

import os

import cv2
import numpy as np

import config as cfg
from box3d import box_corners
from geometry import world_to_image

# urutan keluaran jaringan = KELAS pada latih_klasifikasi.py
NAMA_LATIH = ("mobil_pribadi", "truk", "bus", "van_pickup")
KE_KELAS = {"mobil_pribadi": "car", "truk": "truck", "bus": "bus", "van_pickup": "van"}
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
PAD_BGR = (104, 116, 124)


def letterbox(img, ukuran):
    h, w = img.shape[:2]
    s = ukuran / max(h, w)
    nh, nw = max(1, int(round(h * s))), max(1, int(round(w * s)))
    kecil = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    out = np.empty((ukuran, ukuran, 3), np.uint8)
    out[:] = PAD_BGR
    y0, x0 = (ukuran - nh) // 2, (ukuran - nw) // 2
    out[y0:y0 + nh, x0:x0 + nw] = kecil
    return out


def ke_array(img_bgr):
    rgb = img_bgr[:, :, ::-1].astype(np.float32) / 255.0
    return np.ascontiguousarray(((rgb - MEAN) / STD).transpose(2, 0, 1), dtype=np.float32)


def crop_dari_track(frame, track):
    """Crop BGR dari kotak 3D track, atau None bila terlalu kecil / terlalu terpotong."""
    H, W = frame.shape[:2]
    pts = np.array([world_to_image(c, H) for c in box_corners(track.x(), track.y(), track.dims(), track.yaw)],
                   dtype=np.float64)
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    bw, bh = x1 - x0, y1 - y0
    if bw < 2 or bh < 2:
        return None
    x0 -= cfg.KLAS_MARGIN * bw; x1 += cfg.KLAS_MARGIN * bw
    y0 -= cfg.KLAS_MARGIN * bh; y1 += cfg.KLAS_MARGIN * bh
    area = (x1 - x0) * (y1 - y0)
    cx0, cy0, cx1, cy1 = max(0, int(x0)), max(0, int(y0)), min(W, int(round(x1))), min(H, int(round(y1)))
    if cx1 - cx0 < 2 or cy1 - cy0 < 2:
        return None
    if (cx1 - cx0) * (cy1 - cy0) / area < cfg.KLAS_MIN_VISIBLE:
        return None
    if max(cx1 - cx0, cy1 - cy0) < cfg.KLAS_MIN_SIDE_PX:
        return None
    return frame[cy0:cy1, cx0:cx1]


class KlasifierGambar:
    def __init__(self, path, simpan_crop=None, predict_fn=None):
        self.simpan_crop = simpan_crop
        self._n_simpan = 0
        if simpan_crop:
            os.makedirs(simpan_crop, exist_ok=True)
        if predict_fn is not None:        # untuk uji tanpa torch
            self._predict = predict_fn
            return
        import torch, torchvision          # noqa: E401
        torch.set_num_threads(getattr(cfg, "TORCH_THREADS", 2))
        m = torchvision.models.resnet18(weights=None)
        m.fc = torch.nn.Linear(m.fc.in_features, len(NAMA_LATIH))
        m.load_state_dict(torch.load(path, map_location="cpu"))
        m.eval()
        self._torch, self._model = torch, m

        def _predict(batch):              # batch: (N,3,S,S) float32 -> (N,4) probabilitas
            with torch.no_grad():
                return torch.softmax(m(torch.from_numpy(batch)), dim=1).numpy()
        self._predict = _predict

    def perbarui(self, frame, tracks, frame_idx):
        """Klasifikasi gambar untuk track yang baru diperbarui; hasilnya masuk ke track.classifier."""
        pilih, crops = [], []
        for t in tracks:
            if t.display_id is None or t.unassociated_counter != 0:
                continue
            if (frame_idx + t.id) % cfg.KLAS_EVERY != 0:   # sebar beban antar track
                continue
            cr = crop_dari_track(frame, t)
            if cr is None:
                continue
            pilih.append(t)
            crops.append(ke_array(letterbox(cr, cfg.KLAS_UKURAN)))
            if self.simpan_crop and self._n_simpan < 400:
                cv2.imwrite(os.path.join(self.simpan_crop, "f%04d_id%d.jpg" % (frame_idx, t.display_id)), cr)
                self._n_simpan += 1
        if not pilih:
            return
        probs = self._predict(np.stack(crops))
        for t, p in zip(pilih, probs):
            t.classifier.add_image({KE_KELAS[n]: float(v) for n, v in zip(NAMA_LATIH, p)})


def buat_klasifier_gambar(path, simpan_crop=None):
    if not os.path.exists(path):
        raise SystemExit("Bobot klasifier gambar tidak ada: %s (pakai --klas JALUR atau --tanpa-gambar)" % path)
    return KlasifierGambar(path, simpan_crop)
''')

# -------------------------------------------------------------- visualize.py
v = baca("visualize.py")
v = ganti(v, "        color = COLORS[t.display_id % len(COLORS)]\n",
          "        color = cfg.CLASS_COLORS.get(t.cls, (200, 200, 200))  # warna per KELAS\n", "visualize.py")
i0 = v.index("def draw_counts(")
i1 = v.index("def draw_debug(")
v = v[:i0] + '''def draw_counts(frame, counts):
    """Panel hitungan per kelas di pojok kiri bawah; kotak warna = warna kelas pada kotak 3D."""
    lines = [f"Total: {sum(counts.values())}"] + [f"{c}: {counts[c]}" for c in cfg.CLASSES]
    h = frame.shape[0]
    box_h = 26 * len(lines) + 10
    cv2.rectangle(frame, (10, h - box_h - 10), (210, h - 10), (0, 0, 0), -1)
    for i, text in enumerate(lines):
        y = h - box_h + 18 + 26 * i
        if i > 0:
            col = cfg.CLASS_COLORS.get(cfg.CLASSES[i - 1], (200, 200, 200))
            cv2.rectangle(frame, (18, y - 14), (34, y + 2), col, -1)
            cv2.putText(frame, text, (42, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        else:
            cv2.putText(frame, text, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
    return frame


''' + v[i1:]
tulis("visualize.py", v)

# -------------------------------------------------------------------- run.py
r = baca("run.py")
r = ganti(r, "from kalman_filter import TIME_INTERVAL_FALLBACK\n",
          "from kalman_filter import TIME_INTERVAL_FALLBACK\nfrom klasifikasi_gambar import buat_klasifier_gambar\n", "run.py")
r = ganti(r, '    p.add_argument("--play", action="store_true"',
          '    p.add_argument("--klas", default=cfg.KLAS_MODEL, help="Bobot klasifier gambar 4 kelas (.pth)")\n'
          '    p.add_argument("--tanpa-gambar", action="store_true", help="Klasifikasi dari panjang saja (tanpa klasifier gambar)")\n'
          '    p.add_argument("--simpan-crop", default=None, help="Folder: simpan crop yang dikirim ke klasifier (untuk dicek mata)")\n'
          '    p.add_argument("--play", action="store_true"', "run.py")
r = ganti(r, "    counter = LineCounter(args.line_y)\n",
          "    counter = LineCounter(args.line_y)\n"
          "    klas = None if args.tanpa_gambar else buat_klasifier_gambar(args.klas, args.simpan_crop)\n"
          '    print("Klasifikasi:", "panjang saja" if klas is None else "gambar + panjang (" + os.path.basename(args.klas) + ")")\n', "run.py")
r = ganti(r, "        tracker.assign_display_ids()\n        counter.update(tracker.tracks, idx)\n",
          "        tracker.assign_display_ids()\n        if klas is not None:\n            klas.perbarui(frame, tracker.tracks, idx)  # frame masih bersih (belum digambar)\n"
          "        counter.update(tracker.tracks, idx)\n", "run.py")
tulis("run.py", r)

# counter: log suara berupa pecahan -> bulatkan
k = baca("counter.py")
if "[votes[c] for c in cfg.CLASSES]" in k:
    shutil.copy("counter.py", "counter.py.sebelum_klas")
    k = k.replace("[votes[c] for c in cfg.CLASSES]", "[round(float(votes[c]), 3) for c in cfg.CLASSES]")
    tulis("counter.py", k)

print("SELESAI. Cadangan: *.sebelum_klas")
print('Cek cepat tanpa torch:  python3 -c "import config, classifier, visualize; print(config.CLASSES)"')
print("Jalankan:  python3 run.py ~/projects/video_uji/uji_val_720p.mp4 ~/projects/bobot/detektor/centernet_dari_baru.pth \\")
print("             --cache ~/projects/video_uji/det_session0.pkl --conf 0.4 --conf-low 0.2 --no-show --no-save --line-y 50")