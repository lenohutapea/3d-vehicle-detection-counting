#!/usr/bin/env python3
"""
pack_detector_training.py - satu berkas zip berisi semua yang dibutuhkan notebook Colab untuk melatih detektor.

    cd ~/3d-vehicle-detection-counting
    python3 centernet3d_bbox/tools/pack_detector_training.py --data ~/dataset_deteksi/balige

Isi zip (~/paket_latih_detektor.zip):
  kode/            train_local.py, train_session0_right.py, target.py, kamera.py
  data/<nama>/     converted/images, converted/labels, calib/kalibrasi.xml   (dari label_detector.py)
  session0/        sebagian data_session0_right (agar kemampuan lama tidak hilang), bila ada
  bobot/           detektor yang sekarang dipakai (--init)
Unggah zip itu ke Google Drive: MyDrive/TA_detektor/, lalu jalankan notebooks/latih_detektor_colab.ipynb.
"""
import argparse
import os
import random
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KODE = os.path.join(ROOT, "centernet3d_bbox", "training", "train_detector")
# target.py mengimpor get_position_ground dari repo acuan (antoinekeller/3d_bbox_highway, utils.py).
# Di Colab repo itu tidak ada, jadi fungsi yang sama (salinan persis) ikut dikemas sebagai kode/utils.py.
UTILS = '''import numpy as np


def get_position_ground(x, y, K, to_world_from_camera, img_height):
    """Salinan utils.get_position_ground dari antoinekeller/3d_bbox_highway (commit 3fa494cd)."""
    point_in_camera = np.linalg.inv(K).dot(np.array([x, img_height - y, 1]).reshape(3, 1))
    point_in_camera = point_in_camera.reshape(3, 1)
    point_in_world = to_world_from_camera[:3, :3].dot(point_in_camera) + to_world_from_camera[:3, 3].reshape(3, 1)
    camera_pos_in_world = to_world_from_camera[:3, 3].reshape(3, 1)
    direction = point_in_world - camera_pos_in_world
    direction /= np.linalg.norm(direction)
    lambda_ = -camera_pos_in_world[1] / direction[1]
    return (camera_pos_in_world + lambda_ * direction).flatten()
'''


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", action="append", required=True)
    p.add_argument("--init", default=os.path.join(ROOT, "data", "weights", "detector", "centernet_dari_baru.pth"))
    p.add_argument("--session0", default=os.path.expanduser("~/projects/data_session0_right"))
    p.add_argument("--session0-latih", type=int, default=600)
    p.add_argument("--session0-uji", type=int, default=150)
    p.add_argument("--keluar", default=os.path.expanduser("~/paket_latih_detektor.zip"))
    a = p.parse_args()
    random.seed(42)
    n = 0
    with zipfile.ZipFile(a.keluar, "w", zipfile.ZIP_STORED) as z:
        for f in ("train_local.py", "train_session0_right.py", "target.py", "kamera.py"):
            z.write(os.path.join(KODE, f), "kode/" + f)
        z.writestr("kode/utils.py", UTILS)
        z.write(a.init, "bobot/" + os.path.basename(a.init))
        for d in a.data:
            d = os.path.abspath(os.path.expanduser(d))
            nama = os.path.basename(d.rstrip("/"))
            imgs = sorted(os.listdir(os.path.join(d, "converted", "images")))
            for f in imgs:
                lab = f[:-4] + ".txt"
                z.write(os.path.join(d, "converted", "images", f), "data/%s/converted/images/%s" % (nama, f))
                z.write(os.path.join(d, "converted", "labels", lab), "data/%s/converted/labels/%s" % (nama, lab))
            z.write(os.path.join(d, "calib", "kalibrasi.xml"), "data/%s/calib/kalibrasi.xml" % nama)
            print("data %s: %d gambar" % (nama, len(imgs)))
            n += len(imgs)
        s0 = os.path.expanduser(a.session0)
        if os.path.isdir(os.path.join(s0, "converted", "images")):
            imgs = sorted(os.listdir(os.path.join(s0, "converted", "images")))
            n_uji = (len(imgs) + 4) // 5
            latih, uji = imgs[:len(imgs) - n_uji], imgs[len(imgs) - n_uji:]
            pilih = sorted(random.sample(latih, min(a.session0_latih, len(latih)))) + \
                uji[::max(1, len(uji) // a.session0_uji)][:a.session0_uji]
            for f in pilih:
                z.write(os.path.join(s0, "converted", "images", f), "session0/converted/images/" + f)
                z.write(os.path.join(s0, "converted", "labels", f[:-4] + ".txt"), "session0/converted/labels/" + f[:-4] + ".txt")
            z.write(os.path.join(s0, "calib", "session0_right_calibParams.xml"), "session0/calib/session0_right_calibParams.xml")
            print("session0: %d gambar" % len(pilih))
        else:
            print("session0 tidak ditemukan di %s (dilewati)" % s0)
    print("paket: %s (%.0f MB, %d gambar kamera sendiri)" % (a.keluar, os.path.getsize(a.keluar) / 1e6, n))
    print("Unggah ke Google Drive: MyDrive/TA_detektor/paket_latih_detektor.zip")


if __name__ == "__main__":
    main()
