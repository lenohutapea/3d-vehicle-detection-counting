"""
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
