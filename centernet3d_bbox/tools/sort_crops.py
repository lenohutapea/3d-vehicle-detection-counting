#!/usr/bin/env python3
"""
Pilah potongan kendaraan ke 4 kelas dengan tombol keyboard.

    python centernet3d_bbox/tools/sort_crops.py ~/dataset_publik/atcs_medan/potongan

Tombol:
  1 = mobil_pribadi   2 = truk   3 = bus   4 = van_pickup
  0 = buang (motor / bukan kendaraan / terpotong / buram)
  u = batalkan pilihan terakhir     q / Esc = berhenti (bisa dilanjut nanti)

Berkas DIPINDAH dari <akar>/<split>/belum_dipilah/ ke <akar>/<split>/<kelas>/.
Setiap pilihan dicatat di <akar>/catatan_pilah.csv.
Kalau dihentikan, jalankan lagi perintah yang sama untuk melanjutkan.
"""
import argparse
import csv
import shutil
import sys
from pathlib import Path

KELAS = {"1": "mobil_pribadi", "2": "truk", "3": "bus", "4": "van_pickup", "0": "_buang"}
SUMBER = "belum_dipilah"
TAMPIL = 384  # sisi terpanjang gambar di layar


def kumpulkan(akar: Path):
    return sorted(akar.glob(f"*/{SUMBER}/*.jpg"))


def hitung(akar: Path):
    out = {}
    for k in KELAS.values():
        out[k] = len(list(akar.glob(f"*/{k}/*.jpg")))
    return out


class Pemilah:
    def __init__(self, akar: Path):
        self.akar = akar
        self.antrian = kumpulkan(akar)
        self.riwayat = []  # (asal, tujuan)
        self.catatan = akar / "catatan_pilah.csv"
        if not self.catatan.exists():
            self.catatan.write_text("berkas,split,kelas\n")

    def sekarang(self):
        return self.antrian[0] if self.antrian else None

    def pilih(self, tombol):
        f = self.sekarang()
        if f is None or tombol not in KELAS:
            return
        split = f.parent.parent.name
        tujuan_dir = self.akar / split / KELAS[tombol]
        tujuan_dir.mkdir(parents=True, exist_ok=True)
        tujuan = tujuan_dir / f.name
        shutil.move(str(f), str(tujuan))
        self.riwayat.append((f, tujuan))
        self.antrian.pop(0)
        with self.catatan.open("a", newline="") as fh:
            csv.writer(fh).writerow([f.name, split, KELAS[tombol]])

    def batal(self):
        if not self.riwayat:
            return
        asal, tujuan = self.riwayat.pop()
        shutil.move(str(tujuan), str(asal))
        self.antrian.insert(0, asal)
        with self.catatan.open("a", newline="") as fh:
            csv.writer(fh).writerow([asal.name, asal.parent.parent.name, "BATAL"])

    def judul(self):
        sisa = len(self.antrian)
        h = hitung(self.akar)
        ring = "  ".join(f"{k}={v}" for k, v in h.items())
        return f"sisa {sisa} | {ring}"


def jalankan_cv2(p: Pemilah):
    import cv2
    import numpy as np
    nama = "Pilah: 1 mobil 2 truk 3 bus 4 van/pickup 0 buang u batal q keluar"
    cv2.namedWindow(nama, cv2.WINDOW_AUTOSIZE)
    while True:
        f = p.sekarang()
        if f is None:
            break
        im = cv2.imread(str(f))
        if im is None:
            p.pilih("0")
            continue
        h, w = im.shape[:2]
        s = TAMPIL / max(h, w)
        im = cv2.resize(im, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_CUBIC)
        kanvas = np.full((TAMPIL + 60, max(TAMPIL, 520), 3), 30, np.uint8)
        kanvas[:im.shape[0], :im.shape[1]] = im
        cv2.putText(kanvas, p.judul()[:80], (8, TAMPIL + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)
        cv2.putText(kanvas, "1 mobil  2 truk  3 bus  4 van/pickup  0 buang  u batal  q keluar",
                    (8, TAMPIL + 48), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (120, 220, 255), 1)
        cv2.imshow(nama, kanvas)
        k = cv2.waitKey(0) & 0xFF
        c = chr(k) if k < 128 else ""
        if c in ("q",) or k == 27:
            break
        if c == "u":
            p.batal()
        elif c in KELAS:
            p.pilih(c)
    cv2.destroyAllWindows()


def jalankan_tk(p: Pemilah):
    import tkinter as tk
    from PIL import Image, ImageTk
    root = tk.Tk()
    root.title("Pilah potongan")
    lbl = tk.Label(root, bg="#1e1e1e")
    lbl.pack()
    info = tk.Label(root, font=("Sans", 10), justify="left")
    info.pack(fill="x")
    tk.Label(root, text="1 mobil  2 truk  3 bus  4 van/pickup  0 buang  u batal  q keluar",
             font=("Sans", 10, "bold")).pack(fill="x")
    ref = {}

    def tampil():
        f = p.sekarang()
        if f is None:
            root.destroy()
            return
        im = Image.open(f).convert("RGB")
        s = TAMPIL / max(im.size)
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.BICUBIC)
        ref["foto"] = ImageTk.PhotoImage(im)
        lbl.config(image=ref["foto"], width=TAMPIL, height=TAMPIL)
        info.config(text=p.judul())

    def tekan(e):
        c = e.char
        if c == "q" or e.keysym == "Escape":
            root.destroy()
            return
        if c == "u":
            p.batal()
        elif c in KELAS:
            p.pilih(c)
        tampil()

    root.bind("<Key>", tekan)
    tampil()
    root.mainloop()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("akar", type=Path)
    ap.add_argument("--tk", action="store_true", help="paksa pakai tkinter")
    a = ap.parse_args()
    akar = a.akar.expanduser()
    p = Pemilah(akar)
    print(f"{len(p.antrian)} potongan belum dipilah di {akar}")
    if not p.antrian:
        print(p.judul())
        return
    if not a.tk:
        try:
            jalankan_cv2(p)
            print("Selesai / berhenti.", p.judul())
            return
        except Exception as e:  # opencv-headless tidak punya jendela
            print(f"Jendela OpenCV tidak tersedia ({e.__class__.__name__}); mencoba tkinter...")
    try:
        jalankan_tk(p)
    except Exception as e:
        sys.exit(f"tkinter juga gagal ({e}). Pasang: sudo apt install python3-tk")
    print("Selesai / berhenti.", p.judul())


if __name__ == "__main__":
    main()
