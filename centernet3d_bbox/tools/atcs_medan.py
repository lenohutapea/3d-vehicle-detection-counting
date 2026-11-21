#!/usr/bin/env python3
"""
Alat untuk "Dataset ATCS Medan" (Roboflow, format YOLO).

Tahap 1 - lihat isi dataset (kelas, jumlah kotak, jumlah gambar):
    python centernet3d_bbox/tools/atcs_medan.py lihat ~/dataset_publik/atcs_medan/mentah

Tahap 2 - potong kotak per kendaraan, petakan ke 4 kelas kita:
    python centernet3d_bbox/tools/atcs_medan.py potong ~/dataset_publik/atcs_medan/mentah \
        ~/dataset_publik/atcs_medan/potongan \
        --peta "car=mobil_pribadi,truck=truk,bus=bus,pickup=van_pickup"

Kelas yang tidak disebut di --peta (mis. motorcycle) dilewati.
Hasil: <keluaran>/<split>/<kelas_kita>/atcs_<nama>_<i>.jpg
"""
import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2

EKST_GAMBAR = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def baca_nama_kelas(akar: Path):
    yml = next(iter(sorted(akar.glob("*.yaml"))), None)
    if yml is None:
        sys.exit(f"data.yaml tidak ditemukan di {akar}. Pastikan unduh format YOLO.")
    try:
        import yaml
        isi = yaml.safe_load(yml.read_text())
        nama = isi["names"]
        if isinstance(nama, dict):
            nama = [nama[k] for k in sorted(nama)]
        return [str(n) for n in nama]
    except ImportError:
        teks = yml.read_text()
        m = re.search(r"names:\s*\[(.*?)\]", teks, re.S)
        if m:
            return [s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()]
        sys.exit("Gagal membaca names di data.yaml (pyyaml tidak ada).")


def daftar_pasangan(akar: Path):
    """Hasilkan (split, path_gambar, path_label) untuk train/valid/test."""
    for lbl in sorted(akar.rglob("labels/*.txt")):
        split = lbl.parent.parent.name
        dir_img = lbl.parent.parent / "images"
        img = None
        for e in EKST_GAMBAR:
            p = dir_img / (lbl.stem + e)
            if p.exists():
                img = p
                break
        if img is not None:
            yield split, img, lbl


def baca_kotak(lbl: Path):
    """Baris YOLO: kelas cx cy w h  atau poligon: kelas x1 y1 x2 y2 ..."""
    for baris in lbl.read_text().splitlines():
        a = baris.split()
        if len(a) < 5:
            continue
        k = int(float(a[0]))
        v = [float(x) for x in a[1:]]
        if len(v) == 4:
            cx, cy, w, h = v
            yield k, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
        else:
            xs, ys = v[0::2], v[1::2]
            yield k, min(xs), min(ys), max(xs), max(ys)


def lihat(akar: Path):
    nama = baca_nama_kelas(akar)
    jml_kotak = Counter()
    jml_gambar = Counter()
    per_split = Counter()
    lebar = defaultdict(list)
    for split, img, lbl in daftar_pasangan(akar):
        per_split[split] += 1
        ada = set()
        im = None
        for k, x1, y1, x2, y2 in baca_kotak(lbl):
            jml_kotak[k] += 1
            ada.add(k)
            if len(lebar[k]) < 200:
                if im is None:
                    im = cv2.imread(str(img))
                if im is not None:
                    lebar[k].append((x2 - x1) * im.shape[1])
        for k in ada:
            jml_gambar[k] += 1
    print(f"Dataset : {akar}")
    print(f"Gambar  : " + ", ".join(f"{s}={n}" for s, n in sorted(per_split.items())))
    print(f"\n{'id':>3}  {'kelas':<22}{'kotak':>8}{'gambar':>8}{'lebar_px_median':>17}")
    for i, n in enumerate(nama):
        lb = sorted(lebar[i])
        med = f"{lb[len(lb)//2]:.0f}" if lb else "-"
        print(f"{i:>3}  {n:<22}{jml_kotak[i]:>8}{jml_gambar[i]:>8}{med:>17}")
    print("\nLangkah berikut: tentukan --peta, contoh:")
    print('  --peta "car=mobil_pribadi,truck=truk,bus=bus,pickup=van_pickup"')


def potong(akar: Path, keluar: Path, peta_str: str, min_px: int, pad: float):
    nama = baca_nama_kelas(akar)
    peta = {}
    for pasang in peta_str.split(","):
        if "=" not in pasang:
            continue
        a, b = (s.strip() for s in pasang.split("=", 1))
        if a not in nama:
            sys.exit(f"Kelas '{a}' tidak ada di dataset. Kelas yang ada: {nama}")
        peta[nama.index(a)] = b
    if not peta:
        sys.exit("--peta kosong.")
    hasil = Counter()
    lewat_kecil = 0
    for split, img, lbl in daftar_pasangan(akar):
        kotak = [b for b in baca_kotak(lbl) if b[0] in peta]
        if not kotak:
            continue
        im = cv2.imread(str(img))
        if im is None:
            continue
        H, W = im.shape[:2]
        for i, (k, x1, y1, x2, y2) in enumerate(kotak):
            x1, x2 = x1 * W, x2 * W
            y1, y2 = y1 * H, y2 * H
            if (x2 - x1) < min_px or (y2 - y1) < min_px:
                lewat_kecil += 1
                continue
            px, py = (x2 - x1) * pad, (y2 - y1) * pad
            a = max(0, int(x1 - px)); b = max(0, int(y1 - py))
            c = min(W, int(x2 + px)); d = min(H, int(y2 + py))
            kelas = peta[k]
            tujuan = keluar / split / kelas
            tujuan.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(tujuan / f"atcs_{img.stem}_{i}.jpg"), im[b:d, a:c])
            hasil[(split, kelas)] += 1
    print(f"Hasil potongan di {keluar}")
    for (s, k), n in sorted(hasil.items()):
        print(f"  {s:<6} {k:<16} {n:>6}")
    print(f"Total {sum(hasil.values())} potongan, {lewat_kecil} kotak dilewati (< {min_px}px).")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="perintah", required=True)
    l = sub.add_parser("lihat")
    l.add_argument("akar", type=Path)
    p = sub.add_parser("potong")
    p.add_argument("akar", type=Path)
    p.add_argument("keluar", type=Path)
    p.add_argument("--peta", required=True)
    p.add_argument("--min-px", type=int, default=24)
    p.add_argument("--pad", type=float, default=0.05)
    a = ap.parse_args()
    if a.perintah == "lihat":
        lihat(a.akar.expanduser())
    else:
        potong(a.akar.expanduser(), a.keluar.expanduser(), a.peta, a.min_px, a.pad)


if __name__ == "__main__":
    main()