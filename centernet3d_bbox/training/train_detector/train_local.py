#!/usr/bin/env python3
"""train_local.py - fine-tune CenterNet-3D-bbox dengan data kamera sendiri (hasil tools/label_detector.py),
boleh dicampur dengan data session0_right supaya kemampuan lama tidak hilang.

    python3 train_local.py --data ~/dataset_deteksi/balige --init centernet_dari_baru.pth \\
        --session0 ~/projects/data_session0_right --session0-n 600 --epochs 10 --batch-size 8 --out centernet_balige.pth

Folder --data (dari label_detector.py): converted/images, converted/labels (x,y,w,h,l), calib/kalibrasi.xml.
Folder --session0: converted/images, converted/labels, calib/session0_right_calibParams.xml.

Normalisasi focal (sama dengan config.KOREKSI_FOKUS di pipeline): detektor menebak ukuran sebagai rasio
ukuran/jarak pada focal data latih asal (F_LATIH_PX). Untuk kamera dengan focal f, target ukuran dikalikan
f / F_LATIH_PX, sehingga satu bobot berlaku untuk semua kamera dan pipeline cukup mengalikan F_LATIH_PX / f.
Model, loss, dan lintasan latih/uji diambil dari train_session0_right.py tanpa diubah.
"""
import argparse
import csv
import os
import random
import sys
import time
import xml.etree.ElementTree as ET

import numpy as np
import torch
import torch.optim as optim
import torchvision

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import target as tg  # noqa: E402
from train_session0_right import Data, centernet, run_pass  # noqa: E402

F_LATIH_PX = 2662.78      # focal session0_right pada 1280 px (sama dengan config.F_LATIH_PX)


def kamera_dari_xml(xml_path, img_w=1280, ref_w=1920, ref_h=1080):
    """Sama dengan kamera.load_camera / geometry.build_camera_from_calib, tetapi dari berkas XML mana pun."""
    cal = ET.parse(xml_path).getroot()
    f_ref = float(cal.findtext("f"))
    h_m = float(cal.findtext("h")) / 1000.0
    v = [float(t) for t in cal.findtext("vanishPoints").split()]
    kf = np.array([[f_ref, 0, ref_w / 2], [0, f_ref, ref_h / 2], [0, 0, 1.]])

    def arah(vp):
        d = np.linalg.inv(kf) @ np.array([vp[0], vp[1], 1.0])
        return d / np.linalg.norm(d)
    d1, d2 = arah(v[0:2]), arah(v[2:4])
    if d1[2] < 0: d1 = -d1
    if d2[0] < 0: d2 = -d2
    x = d2 - (d2 @ d1) * d1
    x /= np.linalg.norm(x)
    z = np.cross(x, d1)
    if z[1] > 0: z = -z
    flip = np.array([1, -1, 1])
    T = np.identity(4)
    T[:3, :3] = np.stack([x * flip, z * flip, d1 * flip], axis=0)
    T[:3, 3] = [0, h_m, 0]
    f = f_ref * img_w / ref_w
    K = np.array([[f, 0, img_w / 2], [0, f, img_w * ref_h / ref_w / 2], [0, 0, 1.]])
    return K, T, f, h_m


class DataSkala(Data):
    """Data dengan target ukuran dinormalisasi ke focal data latih asal."""
    def __init__(self, *args, skala=1.0, **kw):
        super().__init__(*args, **kw)
        self.skala = skala

    def __getitem__(self, idx):
        img, hm, off, regr = super().__getitem__(idx)
        return img, hm, off, (regr * self.skala).astype(np.float32)


def bagi_per_video(names, frac=0.2):
    """Validasi = video utuh (tiap video ke-5), supaya frame mirip tidak bocor ke validasi."""
    vids = sorted({n.rsplit("_f", 1)[0] for n in names})
    if len(vids) < 3:
        n_val = int(np.ceil(frac * len(names)))
        return names[:-n_val], names[-n_val:]
    val_v = set(vids[i] for i in range(len(vids)) if i % 5 == 4) or {vids[-1]}
    return [n for n in names if n.rsplit("_f", 1)[0] not in val_v], [n for n in names if n.rsplit("_f", 1)[0] in val_v]


def daftar_gambar(base):
    d = os.path.join(base, "converted", "images")
    return sorted(f for f in os.listdir(d) if f.lower().endswith(".jpg"))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", action="append", required=True, help="folder dataset kamera sendiri (boleh berulang)")
    p.add_argument("--session0", help="folder data_session0_right (opsional, dicampur)")
    p.add_argument("--session0-n", type=int, default=600, help="jumlah gambar session0 yang ikut dilatih")
    p.add_argument("--init", required=True, help="bobot awal .pth (detektor yang sekarang dipakai)")
    p.add_argument("--out", required=True)
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--lr", type=float, default=5e-5)
    p.add_argument("--step", type=int, default=5, help="lr x0.1 setiap --step epoch")
    p.add_argument("--y-min", type=float, default=150)
    p.add_argument("--ulang", type=int, default=2, help="pengulangan data kamera sendiri per epoch")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--logdir", default=".")
    a = p.parse_args(argv)
    random.seed(a.seed); np.random.seed(a.seed); torch.manual_seed(a.seed)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_txt = os.path.join(a.logdir, "latih_lokal_%s.txt" % stamp)
    log_csv = os.path.join(a.logdir, "latih_lokal_%s.csv" % stamp)
    logf = open(log_txt, "a")

    def log(msg):
        print(msg, flush=True)
        logf.write(msg + "\n"); logf.flush()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log("torch %s | torchvision %s | device %s" % (torch.__version__, torchvision.__version__, device))
    log("argumen: %s" % vars(a))
    latih, uji_lokal, uji_s0 = [], [], []
    for base in a.data:
        base = os.path.expanduser(base)
        K, T, f, h = kamera_dari_xml(os.path.join(base, "calib", "kalibrasi.xml"))
        s = f / F_LATIH_PX
        names = daftar_gambar(base)
        tr, va = bagi_per_video(names)
        img, lab = os.path.join(base, "converted", "images"), os.path.join(base, "converted", "labels")
        for _ in range(a.ulang):
            latih.append(DataSkala(tr, img, lab, K, T, a.y_min, True, True, skala=s))
        uji_lokal.append(DataSkala(va, img, lab, K, T, a.y_min, False, False, skala=s))
        log("data %s: f=%.1f px h=%.2f m skala ukuran=%.4f | latih %d (x%d) | validasi %d"
            % (base, f, h, s, len(tr), a.ulang, len(va)))
    if a.session0:
        base = os.path.expanduser(a.session0)
        K, T, f, h = kamera_dari_xml(os.path.join(base, "calib", "session0_right_calibParams.xml"))
        names = daftar_gambar(base)
        n_uji = int(np.ceil(0.2 * len(names)))
        tr_all, va = names[:len(names) - n_uji], names[len(names) - n_uji:]
        tr = sorted(random.sample(tr_all, min(a.session0_n, len(tr_all))))
        va = va[::max(1, len(va) // 200)]
        img, lab = os.path.join(base, "converted", "images"), os.path.join(base, "converted", "labels")
        latih.append(DataSkala(tr, img, lab, K, T, a.y_min, True, True, skala=f / F_LATIH_PX))
        uji_s0.append(DataSkala(va, img, lab, K, T, a.y_min, False, False, skala=f / F_LATIH_PX))
        log("session0: f=%.1f px skala=%.4f | latih %d | validasi %d" % (f, f / F_LATIH_PX, len(tr), len(va)))

    cd = torch.utils.data.ConcatDataset
    dl_tr = torch.utils.data.DataLoader(cd(latih), batch_size=a.batch_size, shuffle=True, num_workers=2)
    dl_lok = torch.utils.data.DataLoader(cd(uji_lokal), batch_size=a.batch_size, shuffle=False, num_workers=2)
    dl_s0 = torch.utils.data.DataLoader(cd(uji_s0), batch_size=a.batch_size, shuffle=False, num_workers=2) if uji_s0 else None

    model = centernet(pretrained=False).to(device)
    model.load_state_dict(torch.load(os.path.expanduser(a.init), map_location=device))
    log("bobot awal: %s" % a.init)
    opt = optim.Adam(model.parameters(), lr=a.lr)
    sch = torch.optim.lr_scheduler.StepLR(opt, step_size=a.step, gamma=0.1)

    def uji(tag):
        va, _ = run_pass(model, dl_lok, device, None, "uji lokal")
        s0 = run_pass(model, dl_s0, device, None, "uji session0")[0] if dl_s0 else None
        log("  %s lokal   : %s" % (tag, " ".join("%s=%.4f" % kv for kv in va.items())))
        if s0:
            log("  %s session0: %s" % (tag, " ".join("%s=%.4f" % kv for kv in s0.items())))
        return va, s0

    awal, _ = uji("sebelum")
    best = awal["loss"]
    torch.save(model.state_dict(), a.out)
    with open(log_csv, "w", newline="") as fc:
        csv.writer(fc).writerow(["epoch", "lr", "latih_loss", "lokal_loss", "lokal_pos", "lokal_whl",
                                 "s0_loss", "detik"])
    for ep in range(a.epochs):
        t0 = time.time()
        lr = opt.param_groups[0]["lr"]
        log("epoch %d/%d | lr %g" % (ep + 1, a.epochs, lr))
        tr, _ = run_pass(model, dl_tr, device, opt, "latih")
        sch.step()
        va, s0 = uji("epoch %d" % (ep + 1))
        with open(log_csv, "a", newline="") as fc:
            csv.writer(fc).writerow([ep + 1, lr, tr["loss"], va["loss"], va["pos"], va["whl"],
                                     s0["loss"] if s0 else "", round(time.time() - t0, 1)])
        if va["loss"] < best:
            best = va["loss"]
            torch.save(model.state_dict(), a.out)
            log("  val loss lokal membaik ke %.4f -> disimpan %s" % (best, a.out))
    log("selesai. val loss lokal: sebelum %.4f -> terbaik %.4f" % (awal["loss"], best))


if __name__ == "__main__":
    main()
