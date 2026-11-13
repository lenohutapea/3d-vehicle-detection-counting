"""target.py - pembuatan masukan dan target latihan (tanpa PyTorch).
Salinan setia dari centernet-3d-bbox.ipynb (repo antoinekeller/3d_bbox_highway, commit 3fa494cd):
  draw_msra_gaussian (baris 84-108), draw_offset (111-114), make_hm_offset_regr (117-152),
  Normalize (238-248), pembacaan item CarlaDataset.__getitem__ (261-279).
Perubahan atas acuan (semua dicatat):
  1. K dan to_world_from_camera menjadi argumen (acuan: variabel global kamera Carla).
  2. y_min menjadi argumen (acuan: angka 150 tertulis langsung di baris 130).
  3. 'except:' telanjang diganti 'except IndexError:' (perilaku sama untuk kasus yang dimaksud).
  4. aug_fix (default False = persis acuan): jitter warna yang ditahan di 0-255, karena acuan
     membungkus modulo 256 (uji: piksel 3 dengan offset -20 menjadi 239).
  5. Normalize: impor torchvision yang tidak terpakai dibuang.
"""
import os
import sys
import numpy as np
import pandas as pd
import cv2

REPO = os.path.expanduser("~/projects/acuan/3d_bbox_highway")
sys.path.insert(0, REPO)
from utils import get_position_ground  # noqa: E402  (repo acuan, hanya dibaca)

INPUT_W, INPUT_H, MODEL_SCALE = 1280, 720, 32


def draw_msra_gaussian(heatmap, center, sigma=2):
    tmp_size = sigma * 6
    mu_x = int(center[0])
    mu_y = int(center[1])
    w, h = heatmap.shape[0], heatmap.shape[1]
    ul = [int(mu_x - tmp_size), int(mu_y - tmp_size)]
    br = [int(mu_x + tmp_size + 1), int(mu_y + tmp_size + 1)]
    if ul[0] >= h or ul[1] >= w or br[0] < 0 or br[1] < 0:
        return heatmap
    size = br[0] - ul[0]
    x = np.arange(0, size, 1, np.float32)
    y = x[:, np.newaxis]
    x0 = y0 = size // 2
    g = np.exp(- ((x - x0) ** 2 + (y - y0) ** 2) / (2 * sigma ** 2))
    g_x = max(0, -ul[0]), min(br[0], h) - ul[0]
    g_y = max(0, -ul[1]), min(br[1], w) - ul[1]
    img_x = max(0, ul[0]), min(br[0], h)
    img_y = max(0, ul[1]), min(br[1], w)
    heatmap[img_y[0]:img_y[1], img_x[0]:img_x[1]] = np.maximum(
        heatmap[img_y[0]:img_y[1], img_x[0]:img_x[1]],
        g[g_y[0]:g_y[1], g_x[0]:g_x[1]])
    return heatmap


def draw_offset(offset, x, y):
    offset[0, int(y), int(x)] = x - int(x)
    offset[1, int(y), int(x)] = y - int(y)
    return offset


def make_hm_offset_regr(target, K, to_world_from_camera, y_min=150):
    hm = np.zeros([INPUT_H // MODEL_SCALE + 1, INPUT_W // MODEL_SCALE])
    offset = np.zeros([2, INPUT_H // MODEL_SCALE + 1, INPUT_W // MODEL_SCALE])
    regr = np.zeros([3, INPUT_H // MODEL_SCALE + 1, INPUT_W // MODEL_SCALE])

    if len(target) == 0:
        return hm, offset, regr

    for i, c in target.iterrows():
        hm = draw_msra_gaussian(hm, [int(c["x"] / MODEL_SCALE), int(c["y"] / MODEL_SCALE)],
                                sigma=1)
        if not (0 <= c["x"] < INPUT_W and y_min <= c["y"] < INPUT_H):
            continue

        assert 0 <= c["x"] < INPUT_W
        assert 0 <= c["y"] < INPUT_H
        offset = draw_offset(offset, c["x"] / MODEL_SCALE, c["y"] / MODEL_SCALE)

        position_on_ground = get_position_ground(
            c["x"], c["y"], K, to_world_from_camera, 720
        )
        depth = np.linalg.norm(position_on_ground - to_world_from_camera[:3, 3])

        for i in range(-1, 2):
            for j in range(-1, 2):
                try:
                    regr[0, int(c["y"] / MODEL_SCALE) + i, int(c["x"] / MODEL_SCALE) + j] = c["w"] / depth
                    regr[1, int(c["y"] / MODEL_SCALE) + i, int(c["x"] / MODEL_SCALE) + j] = c["h"] / depth
                    regr[2, int(c["y"] / MODEL_SCALE) + i, int(c["x"] / MODEL_SCALE) + j] = c["l"] / depth
                except IndexError:
                    pass

    return hm, offset, regr


class Normalize(object):
    def __init__(self):
        self.mean = [0.485, 0.456, 0.406]
        self.std = [0.229, 0.224, 0.225]

    def __call__(self, image):
        image = image.astype(np.float32) / 255
        image -= self.mean
        image /= self.std
        return image


def load_item(img_path, label_path, K, to_world_from_camera, y_min=150, train=False, aug_fix=False):
    """Mengembalikan img (3,720,1280) float32, hm (23,40), offset (2,23,40), regr (3,23,40) (float64 seperti acuan)."""
    img = cv2.imread(img_path)
    if img is None:
        raise FileNotFoundError(img_path)
    img = cv2.resize(img, (INPUT_W, INPUT_H))

    if train:
        if np.random.rand() > 0.5:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if aug_fix:
            jitter = np.random.randint(-20, 20, size=3)
            img = np.clip(img.astype(np.int16) + jitter, 0, 255).astype(np.uint8)
        else:
            rgb_offset = np.random.randint(-20, 20, size=3).astype('uint8')
            img += rgb_offset

    img = Normalize()(img)
    img = img.transpose([2, 0, 1])

    labels = pd.read_csv(label_path)
    hm, offset, regr = make_hm_offset_regr(labels, K, to_world_from_camera, y_min)
    return img, hm, offset, regr


if __name__ == "__main__":
    # Pemeriksaan pada data asli: python3 target.py
    import kamera
    cam = kamera.load_camera()
    K, T = cam["K"], cam["T"]
    base = os.path.expanduser("~/projects/data_session0_right/converted")
    names = sorted(os.listdir(os.path.join(base, "images")))
    for nm in [names[0], names[len(names) // 2], names[-1]]:
        lp = os.path.join(base, "labels", nm[:-4] + ".txt")
        img, hm, off, regr = load_item(os.path.join(base, "images", nm), lp, K, T, 150, train=False)
        lab = pd.read_csv(lp)
        uniq = len({(int(x / 32), int(y / 32)) for x, y in zip(lab["x"], lab["y"])})
        n_near = int((lab["y"] >= 150).sum())
        filled = int((regr[0] != 0).sum())
        nz = regr[0][regr[0] != 0]
        print("%s | img %s %s | hm %s | objek %d (y>=150: %d) | sel pusat hm>=1: %d (sel unik: %d) | sel ukuran terisi: %d (maks %d)"
              % (nm, img.shape, img.dtype, hm.shape, len(lab), n_near, int((hm >= 1).sum()), uniq, filled, 9 * n_near))
        if filled:
            print("    w/depth: min %.4f maks %.4f | offset maks %.3f" % (nz.min(), nz.max(), off.max()))