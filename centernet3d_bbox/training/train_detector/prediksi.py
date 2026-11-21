#!/usr/bin/env python3
"""prediksi.py - jalankan model pada gambar uji (atau latih) dan simpan hasil dekodenya ke file pickle.
Urutan dekode mengikuti notebook (baris 646-679): gambar BGR tanpa penukaran kanal -> model -> sigmoid
-> select -> pred2box -> ukuran x kedalaman. Ambang bawaan 0,1 (notebook baris 641).
Bobot dimuat dengan map_location='cpu' (bobot penulis disimpan dari GPU).
Pemakaian: python3 prediksi.py --weights ~/projects/uji_kecil.pth --max 6 --tag uji
"""
import argparse
import os
import pickle
import sys
import time

import cv2
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kamera  # noqa: E402
import target as tg  # noqa: E402
import dekode  # noqa: E402
from train_session0_right import centernet, split_ids  # noqa: E402


def baca_gambar(path):
    """Sama dengan jalur data uji (target.load_item, train=False): BGR, resize 1280x720, Normalize, (3,H,W)."""
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(path)
    img = cv2.resize(img, (tg.INPUT_W, tg.INPUT_H))
    return tg.Normalize()(img).transpose([2, 0, 1])


def main(argv=None):
    p = argparse.ArgumentParser()
    conv = os.path.expanduser("~/projects/data_session0_right/converted")
    p.add_argument("--images", default=os.path.join(conv, "images"))
    p.add_argument("--weights", required=True)
    p.add_argument("--split", choices=["val", "train"], default="val")
    p.add_argument("--max", type=int, default=None)
    p.add_argument("--thresh", type=float, default=0.1)
    p.add_argument("--tag", default="pred")
    p.add_argument("--outdir", default=os.path.expanduser("~/projects/hasil/prediksi_detektor"))
    a = p.parse_args(argv)

    cam = kamera.load_camera()
    K, T = cam["K"], cam["T"]
    names = sorted(f for f in os.listdir(a.images) if f.lower().endswith(".jpg"))
    tr, va = split_ids(names)
    ids = va if a.split == "val" else tr
    if a.max:
        ids = ids[:a.max]

    model = centernet(pretrained=False)
    model.load_state_dict(torch.load(a.weights, map_location="cpu"))
    model.eval()

    os.makedirs(a.outdir, exist_ok=True)
    out_path = os.path.join(a.outdir, "%s_%s.pkl" % (a.tag, a.split))
    dets, t0 = {}, time.time()
    for k, nm in enumerate(ids):
        x = torch.from_numpy(np.ascontiguousarray(baca_gambar(os.path.join(a.images, nm)))).float().unsqueeze(0)
        with torch.no_grad():
            hm, offset, whl = model(x)
        hm = hm.cpu().numpy().squeeze(0).squeeze(0)
        offset = offset.cpu().numpy().squeeze(0)
        whl = whl.cpu().numpy().squeeze(0)
        dets[nm] = dekode.decode(hm, offset, whl, K, T, 720, thresh=a.thresh, apply_sigmoid=True)
        if k < 3 or (k + 1) % 50 == 0 or k + 1 == len(ids):
            print("%s | deteksi: %d | %d/%d | %.2f s/gambar" % (nm, len(dets[nm]), k + 1, len(ids), (time.time() - t0) / (k + 1)))
    with open(out_path, "wb") as f:
        pickle.dump(dict(args=vars(a), names=ids, dets=dets), f)
    print("tersimpan:", out_path, "| gambar:", len(ids), "| total deteksi:", sum(len(v) for v in dets.values()))


if __name__ == "__main__":
    main()