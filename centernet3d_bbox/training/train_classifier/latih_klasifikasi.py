#!/usr/bin/env python3
"""latih_klasifikasi.py - latih klasifikasi 4 kelas (mobil_pribadi, truk, bus, van_pickup) dari gambar.

Model : ResNet-18 bobot ImageNet (torchvision), lapisan fc diganti 4 keluaran. Tanpa YOLO.
Data  : ~/dataset_publik/dataset_klasifikasi/{train,val,test}/<kelas>/*.jpg   (MIO-TCD, siapkan_mio_tcd.py)
Uji   : ~/dataset_publik/uji_session0_right/{mobil_pribadi,truk}/*.jpg         (potong_session0.py)
Masukan: potongan kendaraan, diskalakan ke 128x128 tanpa mengubah rasio (sisa diberi warna rata-rata
         ImageNet), urutan kanal RGB, normalisasi ImageNet. (Berbeda dari detektor CenterNet yang BGR.)
Augmentasi (latih saja, semuanya pilihan kita): flip horizontal, geser tepi 0-8%, penurunan resolusi
         acak (skala 0,4-1,0 lalu diperbesar lagi, agar model tidak bersandar pada ketajaman gambar,
         karena potongan bus di MIO-TCD lebih besar dan tajam), kecerahan/kontras acak.
Keluaran: bobot terbaik (akurasi validasi tertinggi) + log txt/csv + prediksi_session0.csv.
Catatan : 'Car' di XML session0_right mencakup SUV, minivan, bahkan van/pickup; prediksi van_pickup
          pada potongan itu belum tentu salah, jadi dilaporkan terpisah dan perlu diperiksa manual.
Pemakaian: python3 latih_klasifikasi.py --epochs 1 --max-per-class 20 --tag uji     (uji kecil)
           python3 latih_klasifikasi.py --epochs 5 --tag klas5
           python3 latih_klasifikasi.py --eval-saja ~/projects/bobot/klasifikasi/klas5.pth
"""
import argparse
import csv
import os
import random
import re
import sys
import time

import cv2
import numpy as np

KELAS = ("mobil_pribadi", "truk", "bus", "van_pickup")
UKURAN = 128
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
PAD_BGR = (104, 116, 124)  # rata-rata ImageNet x 255 (urutan BGR) -> 0 setelah normalisasi


def listar(root, split, kelas=KELAS, maks=None, seed=0):
    """Daftar (jalur, indeks_kelas) dari root/split/<kelas>/*.jpg."""
    out = []
    for i, k in enumerate(KELAS):
        if k not in kelas:
            continue
        d = os.path.join(root, split, k) if split else os.path.join(root, k)
        if not os.path.isdir(d):
            continue
        nama = sorted(f for f in os.listdir(d) if f.lower().endswith(".jpg"))
        if maks and len(nama) > maks:
            nama = random.Random(seed).sample(nama, maks)
        out += [(os.path.join(d, n), i) for n in nama]
    return out


def nomor_frame(path):
    """Nomor frame dari nama berkas, mis. session0_right_000057_o2.jpg -> 57 (tidak ada -> -1)."""
    m = re.search(r"_(\d{6})_", os.path.basename(path))
    return int(m.group(1)) if m else -1


def letterbox(img, ukuran=UKURAN):
    h, w = img.shape[:2]
    s = ukuran / max(h, w)
    nh, nw = max(1, int(round(h * s))), max(1, int(round(w * s)))
    kecil = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    out = np.empty((ukuran, ukuran, 3), np.uint8)
    out[:] = PAD_BGR
    y0, x0 = (ukuran - nh) // 2, (ukuran - nw) // 2
    out[y0:y0 + nh, x0:x0 + nw] = kecil
    return out


def augment(img):
    h, w = img.shape[:2]
    if random.random() < 0.5:
        img = img[:, ::-1]
    # geser tepi 0-8%
    ty, by = int(h * random.uniform(0, 0.08)), int(h * random.uniform(0, 0.08))
    lx, rx = int(w * random.uniform(0, 0.08)), int(w * random.uniform(0, 0.08))
    if h - ty - by > 8 and w - lx - rx > 8:
        img = img[ty:h - by, lx:w - rx]
    # penurunan resolusi acak
    if random.random() < 0.5:
        s = random.uniform(0.4, 1.0)
        hh, ww = img.shape[:2]
        kecil = cv2.resize(np.ascontiguousarray(img), (max(2, int(ww * s)), max(2, int(hh * s))),
                           interpolation=cv2.INTER_AREA)
        img = cv2.resize(kecil, (ww, hh), interpolation=cv2.INTER_LINEAR)
    # kecerahan dan kontras
    a, b = random.uniform(0.7, 1.3), random.uniform(-25, 25)
    img = np.clip(np.ascontiguousarray(img).astype(np.float32) * a + b, 0, 255).astype(np.uint8)
    return img


def ke_array(img_bgr):
    rgb = img_bgr[:, :, ::-1].astype(np.float32) / 255.0
    return np.ascontiguousarray(((rgb - MEAN) / STD).transpose(2, 0, 1), dtype=np.float32)


def seragamkan(img, sisi):
    """Ubah sisi terpanjang menjadi tepat `sisi` piksel (naik atau turun) agar semua potongan
    punya resolusi efektif sama; ketajaman tidak lagi bisa dipakai sebagai petunjuk kelas."""
    h, w = img.shape[:2]
    s = sisi / max(h, w)
    return cv2.resize(np.ascontiguousarray(img), (max(1, int(round(w * s))), max(1, int(round(h * s)))),
                      interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)


def muat(path, latih, sisi=0):
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(path)
    if latih:
        img = augment(img)
    if sisi:
        img = seragamkan(img, sisi)
    return ke_array(letterbox(img))


def matriks(y_true, y_pred, n=len(KELAS)):
    m = np.zeros((n, n), int)
    for t, p in zip(y_true, y_pred):
        m[t, p] += 1
    return m


def cetak_matriks(m, judul, baris_idx=None):
    baris_idx = list(range(len(KELAS))) if baris_idx is None else baris_idx
    print("\n%s (baris = kelas benar, kolom = prediksi)" % judul)
    print("%-14s" % "" + "".join("%14s" % k for k in KELAS) + "%10s" % "recall")
    for i in baris_idx:
        tot = m[i].sum()
        print("%-14s" % KELAS[i] + "".join("%14d" % v for v in m[i]) + "%10.3f" % (m[i, i] / tot if tot else float("nan")))
    if len(baris_idx) == len(KELAS):
        print("%-14s" % "presisi" + "".join("%14.3f" % (m[j, j] / m[:, j].sum() if m[:, j].sum() else float("nan")) for j in range(len(KELAS))))
        print("akurasi total: %.4f" % (np.trace(m) / max(m.sum(), 1)))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=os.path.expanduser("~/dataset_publik/dataset_klasifikasi"))
    p.add_argument("--uji-session", default=os.path.expanduser("~/dataset_publik/uji_session0_right"))
    p.add_argument("--outdir", default=os.path.expanduser("~/dataset_publik/hasil_klasifikasi"))
    p.add_argument("--tag", default="klas")
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--max-per-class", type=int, default=None, help="uji kecil: batasi gambar per kelas")
    p.add_argument("--no-pretrained", action="store_true")
    p.add_argument("--eval-saja", default=None, help="jalur .pth: hanya evaluasi, tanpa latihan")
    p.add_argument("--res-tetap", type=int, default=0,
                   help="seragamkan sisi terpanjang potongan ke N piksel (mis. 48) sebelum letterbox; 0 = mati")
    p.add_argument("--init", default=None, help="mulai dari bobot klasifikasi ini (fine-tune)")
    p.add_argument("--tambah-session", action="store_true",
                   help="tambahkan potongan mobil_pribadi session0_right (frame < --frame-bagi) ke data latih; "
                        "uji session0_right otomatis hanya frame >= --frame-bagi")
    p.add_argument("--ulang-session", type=int, default=3, help="pengulangan potongan mobil session0 di data latih")
    p.add_argument("--ulang-van", type=int, default=1, help="pengulangan potongan van_pickup session0 di data latih")
    p.add_argument("--frame-bagi", type=int, default=2545, help="frame < ini = latih, >= ini = uji (sama dengan detektor)")
    p.add_argument("--uji-val-saja", action="store_true", help="uji session0_right hanya frame >= --frame-bagi")
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args(argv)

    import torch
    import torch.nn as nn
    import torchvision

    random.seed(a.seed); np.random.seed(a.seed); torch.manual_seed(a.seed)
    os.makedirs(a.outdir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_txt = os.path.join(a.outdir, "%s_%s.txt" % (a.tag, stamp))
    log_csv = os.path.join(a.outdir, "%s_%s.csv" % (a.tag, stamp))
    logf = open(log_txt, "a")

    def log(msg):
        print(msg)
        logf.write(msg + "\n")
        logf.flush()

    class Data(torch.utils.data.Dataset):
        def __init__(self, items, latih):
            self.items, self.latih = items, latih

        def __len__(self):
            return len(self.items)

        def __getitem__(self, i):
            path, y = self.items[i]
            return torch.from_numpy(muat(path, self.latih, a.res_tetap)), y

    def loader(items, latih):
        return torch.utils.data.DataLoader(Data(items, latih), batch_size=a.batch, shuffle=latih,
                                           num_workers=a.workers, drop_last=False)

    def buat_model(pretrained):  # noqa
        m = torchvision.models.resnet18(weights="ResNet18_Weights.IMAGENET1K_V1" if pretrained else None)
        m.fc = nn.Linear(m.fc.in_features, len(KELAS))
        return m

    def lintasan(model, dl, optimizer=None):
        training = optimizer is not None
        model.train() if training else model.eval()
        crit = nn.CrossEntropyLoss()
        tot, n, benar = 0.0, 0, 0
        yt, yp, probs = [], [], []
        ctx = torch.enable_grad() if training else torch.no_grad()
        with ctx:
            for x, y in dl:
                out = model(x)
                loss = crit(out, y)
                if training:
                    optimizer.zero_grad()
                    loss.backward()
                    optimizer.step()
                tot += float(loss.detach()) * len(y)
                n += len(y)
                pred = out.argmax(1)
                benar += int((pred == y).sum())
                yt += y.tolist(); yp += pred.tolist()
                probs += torch.softmax(out.detach(), 1).tolist()
        return tot / max(n, 1), benar / max(n, 1), yt, yp, probs

    def evaluasi_akhir(model, tag):
        te = listar(a.root, "test", maks=a.max_per_class)
        _, acc, yt, yp, _ = lintasan(model, loader(te, False))
        cetak_matriks(matriks(yt, yp), "UJI MIO-TCD (%d gambar, akurasi %.4f)" % (len(te), acc))
        se = listar(a.uji_session, None, kelas=("mobil_pribadi", "truk", "van_pickup"), maks=None)
        if a.tambah_session or a.uji_val_saja:
            se = [(pt, y) for pt, y in se if nomor_frame(pt) >= a.frame_bagi]
            log("uji session0_right dibatasi frame >= %d (tidak dipakai melatih)" % a.frame_bagi)
        if se:
            _, acc2, yt2, yp2, pr2 = lintasan(model, loader(se, False))
            m2 = matriks(yt2, yp2)
            cetak_matriks(m2, "UJI session0_right (%d potongan; label: Car->mobil_pribadi, van manual->van_pickup)" % len(se),
                          sorted(set(y for _, y in se)))
            log("catatan: prediksi van_pickup/bus pada 'Car' belum tentu salah (label XML tidak memisahkan van/pickup).")
            out_csv = os.path.join(a.outdir, "prediksi_session0_%s.csv" % tag)
            with open(out_csv, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["berkas", "kelas_xml", "prediksi"] + ["p_" + k for k in KELAS])
                for (path, y), pb, yy in zip(se, pr2, yp2):
                    w.writerow([os.path.relpath(path, a.uji_session), KELAS[y], KELAS[yy]] + ["%.4f" % v for v in pb])
            log("tersimpan: " + out_csv)
        else:
            log("folder uji session0_right tidak ditemukan: " + a.uji_session)

    if a.eval_saja:
        model = buat_model(False)
        model.load_state_dict(torch.load(a.eval_saja, map_location="cpu"))
        evaluasi_akhir(model, a.tag)
        return

    tr = listar(a.root, "train", maks=a.max_per_class)
    if a.tambah_session:
        sc = [(pt, y) for pt, y in listar(a.uji_session, None, kelas=("mobil_pribadi",))
              if 0 <= nomor_frame(pt) < a.frame_bagi]
        sv = [(pt, y) for pt, y in listar(a.uji_session, None, kelas=("van_pickup",))
              if 0 <= nomor_frame(pt) < a.frame_bagi]
        log("tambah session0_right (frame < %d): %d mobil_pribadi x%d, %d van_pickup x%d"
            % (a.frame_bagi, len(sc), a.ulang_session, len(sv), a.ulang_van))
        tr = tr + sc * a.ulang_session + sv * a.ulang_van
    va = listar(a.root, "val", maks=a.max_per_class)
    log("torch %s | torchvision %s | argumen: %s" % (torch.__version__, torchvision.__version__, vars(a)))
    log("latih %d | validasi %d gambar" % (len(tr), len(va)))
    model = buat_model(not a.no_pretrained and not a.init)
    if a.init:
        model.load_state_dict(torch.load(a.init, map_location="cpu"))
        log("bobot awal dimuat dari %s" % a.init)
    opt = torch.optim.Adam(model.parameters(), lr=a.lr)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(a.epochs, 1))
    with open(log_csv, "w", newline="") as f:
        csv.writer(f).writerow(["epoch", "lr", "train_loss", "train_acc", "val_loss", "val_acc", "detik"])
    out = os.path.join(a.outdir, a.tag + ".pth")
    terbaik = -1.0
    dl_tr, dl_va = loader(tr, True), loader(va, False)
    for ep in range(a.epochs):
        t0 = time.time()
        lr = opt.param_groups[0]["lr"]
        l1, a1, _, _, _ = lintasan(model, dl_tr, opt)
        sch.step()
        l2, a2, _, _, _ = lintasan(model, dl_va)
        dt = time.time() - t0
        log("epoch %d/%d | lr %.2e | latih loss %.4f acc %.4f | val loss %.4f acc %.4f | %.0f s"
            % (ep + 1, a.epochs, lr, l1, a1, l2, a2, dt))
        with open(log_csv, "a", newline="") as f:
            csv.writer(f).writerow([ep + 1, lr, l1, a1, l2, a2, round(dt, 1)])
        if a2 > terbaik:
            terbaik = a2
            torch.save(model.state_dict(), out)
            log("  akurasi validasi membaik ke %.4f -> disimpan %s" % (a2, out))
    log("selesai. akurasi validasi terbaik %.4f" % terbaik)
    model.load_state_dict(torch.load(out, map_location="cpu"))
    evaluasi_akhir(model, a.tag)


if __name__ == "__main__":
    main()