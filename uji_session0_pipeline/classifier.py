"""
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
