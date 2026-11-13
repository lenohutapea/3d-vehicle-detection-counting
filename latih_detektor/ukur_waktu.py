"""ukur_waktu.py - mengukur waktu membaca/menyiapkan data per gambar (tanpa melatih).
Hanya membaca. Pemakaian: python3 ukur_waktu.py
"""
import os, sys, time
import numpy as np
import cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kamera
import target as tg


def main(images=None, labels=None, n=10):
    conv = os.path.expanduser("~/projects/data_session0_right/converted")
    images = images or os.path.join(conv, "images")
    labels = labels or os.path.join(conv, "labels")
    cam = kamera.load_camera()
    K, T = cam["K"], cam["T"]
    names = sorted(f for f in os.listdir(images) if f.endswith(".jpg"))[:n]
    t_read, t_all = [], []
    for nm in names:
        t0 = time.time()
        cv2.imread(os.path.join(images, nm))
        t_read.append(time.time() - t0)
        t0 = time.time()
        tg.load_item(os.path.join(images, nm), os.path.join(labels, nm[:-4] + ".txt"), K, T, 150, True, False)
        t_all.append(time.time() - t0)
    print("inti CPU terlihat: %s" % os.cpu_count())
    try:
        import torch
        print("thread torch: %d" % torch.get_num_threads())
    except Exception as e:
        print("torch tidak terbaca: %s" % type(e).__name__)
    print("gambar diukur: %d" % len(names))
    print("baca JPEG saja      : median %.0f ms" % (1000 * np.median(t_read)))
    print("load_item lengkap   : median %.0f ms (baca+resize+augmentasi+normalisasi+target)" % (1000 * np.median(t_all)))
    print("per iterasi (2 gambar) kira-kira %.2f s untuk data" % (2 * np.median(t_all)))


if __name__ == "__main__":
    main()