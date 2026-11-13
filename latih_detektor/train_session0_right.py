#!/usr/bin/env python3
"""train_session0_right.py - latih CenterNet-3D-bbox pada session0_right (CPU).
Salinan kode latih centernet-3d-bbox.ipynb (repo antoinekeller/3d_bbox_highway, commit 3fa494cd):
  model (baris 330-381), focal_loss/_regr_loss/global_loss (390-475), train/validasi (476-578),
  optimizer, StepLR, jumlah epoch, dan aturan simpan model terbaik (579-597).
Perubahan atas acuan (semua dicatat):
  1. Kamera K,T dari kamera.py (acuan: kamera Carla); target dari target.py.
  2. Folder data dari converted/images dan converted/labels; pembagian urutan 80/20 tanpa sklearn
     (aturan sama dengan train_test_split(test_size=0.2, shuffle=False): n_uji = ceil(0.2*n)).
  3. Target (hm, offset, regr) dijadikan float32 (acuan: float64 yang dicampur dengan float32 di loss).
  4. Log juga memuat loss ukuran (whl) latih dan validasi, waktu epoch, dan waktu per iterasi.
  5. plt/summary/assert cuda dibuang. Bobot disimpan ke --out (bukan ke centernet-3d-bbox.pth).
  6. Opsi: --y-min (acuan 150), --shuffle (acuan: tanpa acak), --aug-fix (acuan: jitter membungkus),
     --no-pretrained (hanya untuk uji tanpa internet), --max-train/--max-val/--epochs.
  7. Opsi --init: muat bobot awal dari .pth (bobot penulis atau hasil latihan sendiri).
  8. sigmoid pada global_loss dibatasi ke [1e-6, 1-1e-6] (acuan: tanpa batas; gradien NaN bila sigmoid jenuh 0/1).
  9. Langkah optimizer dilewati bila gradien tak berhingga; jumlahnya dicetak (acuan: hanya memeriksa loss).
"""
import argparse
import csv
import os
import random
import sys
import time

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torchvision
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kamera  # noqa: E402
import target as tg  # noqa: E402


def split_ids(names, test_frac=0.2):
    """Urutan 80/20 seperti train_test_split(test_size=0.2, shuffle=False)."""
    n_test = int(np.ceil(test_frac * len(names)))
    return names[:len(names) - n_test], names[len(names) - n_test:]


class Data(torch.utils.data.Dataset):
    def __init__(self, names, images_dir, labels_dir, K, T, y_min, train, aug_fix):
        self.names, self.images_dir, self.labels_dir = names, images_dir, labels_dir
        self.K, self.T, self.y_min, self.train, self.aug_fix = K, T, y_min, train, aug_fix

    def __len__(self):
        return len(self.names)

    def __getitem__(self, idx):
        nm = self.names[idx]
        img, hm, offset, regr = tg.load_item(
            os.path.join(self.images_dir, nm),
            os.path.join(self.labels_dir, nm[:-4] + ".txt"),
            self.K, self.T, self.y_min, self.train, self.aug_fix)
        return img, hm.astype(np.float32), offset.astype(np.float32), regr.astype(np.float32)


class centernet(nn.Module):
    def __init__(self, pretrained=True):
        super(centernet, self).__init__()
        basemodel = torchvision.models.resnet18(
            weights='ResNet18_Weights.IMAGENET1K_V1' if pretrained else None)
        self.base_model = nn.Sequential(*list(basemodel.children())[:-2])
        num_ch = 512
        head_conv = 64
        self.outc = nn.Sequential(
            nn.Conv2d(num_ch, head_conv, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(head_conv, 1, kernel_size=1, stride=1))
        self.outo = nn.Sequential(
            nn.Conv2d(num_ch, head_conv, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(head_conv, 2, kernel_size=1, stride=1))
        self.outr = nn.Sequential(
            nn.Conv2d(num_ch, head_conv, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(head_conv, 3, kernel_size=1, stride=1))

    def forward(self, x):
        x = self.base_model(x)
        assert not torch.isnan(x).any()
        outc = self.outc(x)
        assert not torch.isnan(outc).any()
        outo = self.outo(x)
        assert not torch.isnan(outo).any()
        outr = self.outr(x)
        return outc, outo, outr


def focal_loss(pred_mask, gt, gamma=0.2):
    gt = gt.unsqueeze(1).float()
    pos_inds = gt.ge(1.0).float()
    neg_inds = gt.lt(1.0).float()
    neg_weights = torch.pow(1 - gt, 4)
    pos_loss = - torch.pow(1 - pred_mask, gamma) * torch.log(pred_mask + 1e-12) * pos_inds
    neg_loss = - torch.pow(pred_mask, gamma) * torch.log(1 - pred_mask + 1e-12) * neg_inds * neg_weights
    loss = 0
    num_pos = pos_inds.float().sum()
    pos_loss = pos_loss.sum()
    neg_loss = neg_loss.sum()
    if num_pos == 0:
        loss = neg_loss
    else:
        pos_loss /= num_pos
        neg_loss /= num_pos
        loss = pos_loss + neg_loss
    assert not torch.isnan(pos_loss)
    assert not torch.isnan(neg_loss)
    return loss, pos_loss, neg_loss


def _regr_loss(off_pred, off_gt, whl_pred, whl_gt, hm_gt):
    mask = hm_gt.unsqueeze(1).float().ge(1.0).float()
    num = mask.float().sum()
    mask_2 = mask.expand_as(off_gt).float()
    mask_3 = mask.expand_as(whl_gt).float()
    assert off_pred.size() == mask_2.size()
    off_pred = off_pred * mask_2
    off_gt = off_gt * mask_2
    whl_pred = whl_pred * mask_3
    whl_gt = whl_gt * mask_3
    assert whl_pred.size() == mask_3.size()
    assert mask_3.float().sum() == 3 * num
    off_loss = nn.functional.l1_loss(off_pred, off_gt, reduction='sum') / (num + 1e-4)
    whl_loss = 20.0 * nn.functional.l1_loss(whl_pred, whl_gt, reduction='sum') / (num + 1e-4)
    return off_loss, whl_loss


def global_loss(hm_pred, hm_gt, off_pred, off_gt, whl_pred, whl_gt):
    pred_mask = torch.sigmoid(hm_pred[:, 0]).clamp(1e-6, 1 - 1e-6)
    pred_mask = pred_mask.unsqueeze(1).float()
    foc_loss, pos_loss, neg_loss = focal_loss(pred_mask, hm_gt)
    off_loss, whl_loss = _regr_loss(off_pred, off_gt, whl_pred, whl_gt, hm_gt)
    assert not torch.isnan(off_loss)
    return foc_loss, pos_loss, neg_loss, off_loss, whl_loss


def run_pass(model, loader, device, optimizer=None, desc=""):
    """Satu lintasan data. optimizer ada -> latih; tidak ada -> validasi. Mengembalikan (rata2 loss dict, detik/iterasi)."""
    training = optimizer is not None
    names = ["loss", "pos", "neg", "off", "whl"]
    tot = dict.fromkeys(names, 0.0)
    model.train() if training else model.eval()
    t0, n_iter, n_skip = time.time(), 0, 0
    ctx = torch.enable_grad() if training else torch.no_grad()
    with ctx:
        t = tqdm(loader, desc=desc)
        for idx, (img, hm, offset, regr) in enumerate(t):
            img = img.to(device)
            hm_gt, offset_gt, whl_gt = hm.to(device), offset.to(device), regr.to(device)
            if training:
                optimizer.zero_grad()
            preds_hm, preds_offset, preds_whl = model(img)
            foc_loss, pos_loss, neg_loss, off_loss, whl_loss = global_loss(
                preds_hm, hm_gt, preds_offset, offset_gt, preds_whl, whl_gt)
            loss = foc_loss + off_loss + whl_loss
            if torch.isnan(loss):
                print("NAN loss")
                continue
            tot["loss"] += float(loss)
            tot["pos"] += float(pos_loss)
            tot["neg"] += float(neg_loss)
            tot["off"] += float(off_loss)
            tot["whl"] += float(whl_loss)
            if training:
                loss.backward()
                if not all(bool(torch.isfinite(q.grad).all()) for q in model.parameters() if q.grad is not None):
                    n_skip += 1
                    optimizer.zero_grad()
                    continue
                optimizer.step()
            n_iter += 1
            t.set_description(f'{desc} (l={tot["loss"]/(idx+1):.2f}) (pos={tot["pos"]/(idx+1):.3f}) '
                              f'(neg={tot["neg"]/(idx+1):.3f}) (off={tot["off"]/(idx+1):.3f}) (whl={tot["whl"]/(idx+1):.3f})')
    if n_skip:
        print('PERINGATAN: %d langkah dilewati karena gradien tak berhingga (%s)' % (n_skip, desc))
    n = len(loader)  # acuan membagi dengan len(loader), juga bila ada iterasi NaN yang dilewati
    return {k: v / n for k, v in tot.items()}, (time.time() - t0) / max(n_iter, 1)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Latih CenterNet-3D-bbox pada session0_right (CPU).")
    conv = os.path.expanduser("~/projects/data_session0_right/converted")
    p.add_argument("--images", default=os.path.join(conv, "images"))
    p.add_argument("--labels", default=os.path.join(conv, "labels"))
    p.add_argument("--out", default=os.path.expanduser("~/projects/bobot/detektor/centernet_session0_right.pth"))
    p.add_argument("--force", action="store_true", help="izinkan menimpa --out yang sudah ada")
    p.add_argument("--logdir", default=os.path.expanduser("~/projects/hasil/log_latih_detektor"))
    p.add_argument("--tag", default="latih", help="nama pendek untuk file log")
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=2)
    p.add_argument("--lr", type=float, default=5e-5)
    p.add_argument("--y-min", type=float, default=150)
    p.add_argument("--max-train", type=int, default=None)
    p.add_argument("--max-val", type=int, default=None)
    p.add_argument("--shuffle", action="store_true", help="acak urutan data latih (acuan: tidak)")
    p.add_argument("--aug-fix", action="store_true", help="jitter warna tanpa pembungkusan (acuan: membungkus)")
    p.add_argument("--no-pretrained", action="store_true", help="tanpa bobot ImageNet; hanya untuk uji tanpa internet")
    p.add_argument("--init", default=None, help="bobot awal (.pth): bobot penulis atau hasil latihan sendiri")
    p.add_argument("--seed", type=int, default=None)
    return p.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    if os.path.exists(a.out) and not a.force:
        sys.exit("GALAT: %s sudah ada. Pakai --out nama lain atau --force." % a.out)
    os.makedirs(a.logdir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_txt = os.path.join(a.logdir, "%s_%s.txt" % (a.tag, stamp))
    log_csv = os.path.join(a.logdir, "%s_%s.csv" % (a.tag, stamp))
    logf = open(log_txt, "a")

    def log(msg):
        print(msg)
        logf.write(msg + "\n")
        logf.flush()

    if a.seed is not None:
        random.seed(a.seed); np.random.seed(a.seed); torch.manual_seed(a.seed)

    cam = kamera.load_camera()
    K, T = cam["K"], cam["T"]
    names = sorted(f for f in os.listdir(a.images) if f.lower().endswith(".jpg"))
    train_ids, val_ids = split_ids(names)
    n_train_full, n_val_full = len(train_ids), len(val_ids)
    if a.max_train: train_ids = train_ids[:a.max_train]
    if a.max_val: val_ids = val_ids[:a.max_val]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    log("torch %s | torchvision %s | numpy %s | device %s" % (torch.__version__, torchvision.__version__, np.__version__, device))
    log("argumen: %s" % vars(a))
    log("gambar: %d | pembagian penuh latih/uji: %d/%d | dipakai: %d/%d" % (len(names), n_train_full, n_val_full, len(train_ids), len(val_ids)))
    log("latih %s .. %s | uji %s .. %s" % (train_ids[0], train_ids[-1], val_ids[0], val_ids[-1]))
    log("kamera: f(720p)=%.2f h=%.3f m | y_min=%s | shuffle=%s | aug_fix=%s" % (cam["f"], cam["h_m"], a.y_min, a.shuffle, a.aug_fix))
    log("log: %s | %s" % (log_txt, log_csv))

    train_ds = Data(train_ids, a.images, a.labels, K, T, a.y_min, True, a.aug_fix)
    val_ds = Data(val_ids, a.images, a.labels, K, T, a.y_min, False, False)
    train_loader = torch.utils.data.DataLoader(train_ds, batch_size=a.batch_size, shuffle=a.shuffle)
    val_loader = torch.utils.data.DataLoader(val_ds, batch_size=a.batch_size, shuffle=False)

    model = centernet(pretrained=not (a.no_pretrained or a.init)).to(device)
    if a.init:
        model.load_state_dict(torch.load(a.init, map_location=device))
        log("bobot awal dimuat dari %s" % a.init)
    optimizer = optim.Adam(model.parameters(), lr=a.lr)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=5, gamma=0.1)

    cols = ["epoch", "lr", "train_loss", "train_pos", "train_neg", "train_off", "train_whl",
            "val_loss", "val_pos", "val_neg", "val_off", "val_whl", "detik_epoch", "detik_per_iter_latih"]
    with open(log_csv, "w", newline="") as fcsv:
        csv.writer(fcsv).writerow(cols)

    best = float("inf")
    for epoch in range(a.epochs):
        te = time.time()
        lr = optimizer.param_groups[0]["lr"]
        log("epoch %d/%d | lr %g" % (epoch + 1, a.epochs, lr))
        tr, sec_iter = run_pass(model, train_loader, device, optimizer, "latih")
        scheduler.step()
        va, _ = run_pass(model, val_loader, device, None, "uji")
        dt = time.time() - te
        log("  latih: " + " ".join("%s=%.4f" % kv for kv in tr.items()))
        log("  uji  : " + " ".join("%s=%.4f" % kv for kv in va.items()))
        log("  waktu epoch %.1f s | %.2f s/iterasi latih" % (dt, sec_iter))
        with open(log_csv, "a", newline="") as fcsv:
            csv.writer(fcsv).writerow([epoch + 1, lr, tr["loss"], tr["pos"], tr["neg"], tr["off"], tr["whl"],
                                       va["loss"], va["pos"], va["neg"], va["off"], va["whl"], round(dt, 1), round(sec_iter, 3)])
        if va["loss"] < best:
            best = va["loss"]
            torch.save(model.state_dict(), a.out)
            log("  val loss membaik ke %.4f -> disimpan %s" % (best, a.out))
    log("selesai. val loss terbaik %.4f" % best)


if __name__ == "__main__":
    main()