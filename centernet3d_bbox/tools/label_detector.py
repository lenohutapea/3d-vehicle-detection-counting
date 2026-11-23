#!/usr/bin/env python3
"""
label_detector.py - label 3D semi-otomatis untuk melatih ulang detektor (CenterNet) dengan video kamera sendiri.

Cara kerja:
  1. Kamera diam, jadi kendaraan = piksel yang bergerak (pengurangan latar, OpenCV MOG2; bayangan dibuang).
  2. Setiap gumpalan bergerak yang alasnya di jalan menjadi kotak 2D usulan.
  3. Kotak 2D diubah menjadi kotak 3D (posisi di jalan + lebar, tinggi, panjang dalam meter) memakai kalibrasi:
     kotak 3D searah jalan dicari yang proyeksinya paling pas dengan kotak 2D (Nelder-Mead).
  4. Anda memeriksa setiap frame contoh dan menyimpan yang benar.

Pemakaian (di VM, folder utama proyek):
    ~/projects/venv_3dbbox/bin/python centernet3d_bbox/tools/label_detector.py --node kamera_2_jalan_balige \\
        --dari 20261125_0700 --sampai 20261125_1800 --setiap 3 --keluar ~/dataset_deteksi/balige
  Kalibrasi = versi yang sedang dipakai kamera (data/calibration/<node>/active.json), atau --profil <berkas.json>.
  Video = rekaman kamera itu di data/recordings/*/<node>/ (disaring --dari/--sampai), atau --video a.mp4 b.mp4.

Tombol di jendela:
  Spasi / Enter  simpan frame ini (kotak hijau saja; frame tanpa kotak juga boleh disimpan)
  klik kotak     hapus / pulihkan kotak (merah = dihapus)
  tarik mouse    tambah kotak untuk kendaraan yang terlewat (tarik dari pojok ke pojok kendaraan)
  0 atau x       lewati frame (tidak disimpan)
  r              kembalikan usulan awal frame ini
  u              batalkan frame terakhir yang disimpan
  q / Esc        berhenti (jalankan lagi perintah yang sama untuk melanjutkan)
Aturan: beri kotak hanya kendaraan RODA EMPAT ke atas yang terlihat cukup utuh. Motor, orang, bayangan: hapus.

Keluaran (format sama dengan data latih session0_right):
  <keluar>/converted/images/<video>_f000123.jpg   (1280x720)
  <keluar>/converted/labels/<video>_f000123.txt   CSV x,y,w,h,l (x,y = piksel 720p titik tengah alas; w,h,l meter)
  <keluar>/calib/kalibrasi.xml, <keluar>/profil.json, <keluar>/catatan.csv
Satu folder keluaran = satu kalibrasi. Kalibrasi berbeda -> folder keluaran berbeda.

Tanpa layar (memeriksa usulan saja):  ... --pratinjau 20   -> 20 gambar contoh di <keluar>/pratinjau/
"""
import argparse
import csv
import glob
import hashlib
import json
import math
import os
import shutil
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PIPELINE = os.path.join(ROOT, "centernet3d_bbox", "pipeline")
PRIOR = np.array([1.8, 1.6, 4.5])          # lebar, tinggi, panjang mobil biasa (m)
PRIOR_SD = np.array([0.4, 0.5, 2.0])
BATAS = [(-30, 30), (1.0, 120.0), (0.5, 2.8), (1.0, 4.5), (1.5, 14.0)]   # cx, cz, w, h, l


# ---------------------------------------------------------------- kalibrasi
def siapkan_profil(a):
    if a.profil:
        prof = os.path.abspath(os.path.expanduser(a.profil))
    elif a.node:
        prof = os.path.join(ROOT, "data", "calibration", a.node, "active.json")
    else:
        sys.exit("Isi --node atau --profil.")
    if not os.path.exists(prof):
        sys.exit("Kalibrasi tidak ditemukan: %s (simpan kalibrasi kamera ini di halaman Kalibrasi dulu)" % prof)
    isi = json.load(open(prof, encoding="utf-8"))
    if not isi.get("CALIB_XML") or not os.path.exists(isi["CALIB_XML"]):
        sys.exit("Profil tidak punya berkas kalibrasi XML (CALIB_XML). Kalibrasi dengan cara klik dulu.")
    os.environ["PROFIL_KAMERA"] = prof
    sys.path.insert(0, PIPELINE)
    return prof, isi


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


# ---------------------------------------------------------------- 3D <-> 2D
class Kamera:
    def __init__(self):
        import config as cfg
        import geometry as g
        self.cfg, self.g = cfg, g
        self.W, self.H = cfg.IMG_W, cfg.IMG_H
        self.K = g.K
        self.R = g.TO_WORLD_FROM_CAMERA[:3, :3]
        self.C = g.CAMERA_POS.copy()
        self.Rcw = g.TO_CAMERA_FROM_WORLD[:3, :3]
        self.tcw = g.TO_CAMERA_FROM_WORLD[:3, 3]

    def proyeksi(self, pts):
        """(N,3) dunia -> (N,2) piksel OpenCV (v dari atas), dan kedalaman kamera."""
        pc = pts @ self.Rcw.T + self.tcw
        z = pc[:, 2]
        uv = (pc @ self.K.T)
        u = uv[:, 0] / np.abs(z)
        v = self.H - uv[:, 1] / np.abs(z)
        return np.stack([u, v], 1), z

    def ke_tanah(self, u, v):
        """Piksel (array) -> (gx, gz, sah)."""
        u, v = np.asarray(u, float), np.asarray(v, float)
        ray = np.stack([u, self.H - v, np.ones_like(u)], -1) @ np.linalg.inv(self.K).T
        d = ray @ self.R.T
        sah = d[..., 1] < -1e-6
        lam = np.where(sah, -self.C[1] / np.where(sah, d[..., 1], -1), 0)
        return self.C[0] + lam * d[..., 0], self.C[2] + lam * d[..., 2], sah

    def sudut(self, p):
        cx, cz, w, h, l = p
        xs = np.array([w / 2, -w / 2])
        zs = np.array([l / 2, -l / 2])
        return np.array([[cx + x, y, cz + z] for y in (0.0, h) for z in zs for x in xs])

    def kotak2d(self, p):
        uv, z = self.proyeksi(self.sudut(p))
        if (z <= 0.5).any():
            return None
        return np.array([uv[:, 0].min(), uv[:, 1].min(), uv[:, 0].max(), uv[:, 1].max()])

    def titik_label(self, p):
        uv, z = self.proyeksi(np.array([[p[0], 0.0, p[1]]]))
        return float(uv[0, 0]), float(uv[0, 1])


def nelder_mead(f, x0, langkah, iters=250):
    n = len(x0)
    simp = [np.array(x0, float)] + [np.array(x0, float) + np.eye(n)[i] * langkah[i] for i in range(n)]
    nilai = [f(x) for x in simp]
    for _ in range(iters):
        idx = np.argsort(nilai)
        simp = [simp[i] for i in idx]
        nilai = [nilai[i] for i in idx]
        if abs(nilai[-1] - nilai[0]) < 1e-7:
            break
        c = np.mean(simp[:-1], 0)
        xr = c + (c - simp[-1]); fr = f(xr)
        if fr < nilai[0]:
            xe = c + 2 * (c - simp[-1]); fe = f(xe)
            simp[-1], nilai[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < nilai[-2]:
            simp[-1], nilai[-1] = xr, fr
        else:
            xc = c + 0.5 * (simp[-1] - c); fc = f(xc)
            if fc < nilai[-1]:
                simp[-1], nilai[-1] = xc, fc
            else:
                simp = [simp[0]] + [simp[0] + 0.5 * (s - simp[0]) for s in simp[1:]]
                nilai = [nilai[0]] + [f(s) for s in simp[1:]]
    i = int(np.argmin(nilai))
    return simp[i], nilai[i]


def cocokkan_3d(kam, r, bobot_prior=0.03):
    """Kotak 2D r = [u1,v1,u2,v2] (720p) -> (params cx,cz,w,h,l, galat). Sisi yang menempel tepi citra diabaikan."""
    u1, v1, u2, v2 = r
    pakai = np.array([u1 > 3, v1 > 3, u2 < kam.W - 4, v2 < kam.H - 4], float)
    s = max(u2 - u1, v2 - v1, 8.0)

    def biaya(p):
        for k, (lo, hi) in enumerate(BATAS):
            if not lo <= p[k] <= hi:
                return 1e6
        b = kam.kotak2d(p)
        if b is None:
            return 1e6
        e = ((b - r) / s) ** 2 * pakai
        return e.sum() + bobot_prior * (((p[2:] - PRIOR) / PRIOR_SD) ** 2).sum()

    gx, gz, sah = kam.ke_tanah((u1 + u2) / 2, v2)
    if not sah:
        return None, 1e6
    terbaik = (None, 1e6)
    for l0 in (4.5, 8.0):
        p0 = [float(gx), float(gz) + l0 / 2, 1.8, 1.6, l0]
        p, c = nelder_mead(biaya, p0, [1.0, 2.0, 0.3, 0.3, 1.5])
        if c < terbaik[1]:
            terbaik = (p, c)
    return terbaik


# ---------------------------------------------------------------- usulan dari gerak
class Usulan:
    def __init__(self, kam, skala=0.5):
        import cv2
        self.cv2, self.kam, self.s = cv2, kam, skala
        self.mog = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=24, detectShadows=True)
        w, h = int(kam.W * skala), int(kam.H * skala)
        uu, vv = np.meshgrid((np.arange(w) + 0.5) / skala, (np.arange(h) + 0.5) / skala)
        gx, gz, sah = kam.ke_tanah(uu, vv)
        cfg = kam.cfg
        self.jalan = sah & (np.abs(gx) <= cfg.LANE_HALF_WIDTH_M) & (gz > 1.0) & (gz < cfg.MAX_TRACK_DEPTH_M)
        # daerah lebih jauh dari "jarak terjauh" kalibrasi atau di atas cakrawala: digelapkan di gambar latih,
        # supaya kendaraan jauh yang tidak diberi label tidak diajarkan sebagai "bukan kendaraan".
        # Kendaraan sejauh itu memang dibuang oleh sistem (MAX_TRACK_DEPTH_M).
        uu2, vv2 = np.meshgrid(np.arange(kam.W) + 0.5, np.arange(kam.H) + 0.5)
        gx2, gz2, sah2 = kam.ke_tanah(uu2, vv2)
        self.jauh = (~sah2) | (gz2 > cfg.MAX_TRACK_DEPTH_M)

    def tutup_jauh(self, frame720):
        out = frame720.copy()
        out[self.jauh] = (104, 116, 124)        # warna rata-rata ImageNet (BGR): "netral" untuk jaringan
        return out

    def latih(self, frame720):
        small = self.cv2.resize(frame720, None, fx=self.s, fy=self.s, interpolation=self.cv2.INTER_AREA)
        self.fg = self.mog.apply(small)

    def kotak(self, luas_min=500):
        cv2 = self.cv2
        m = (self.fg == 255).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
        out = []
        for i in range(1, n):
            x, y, w, h, area = st[i]
            if area < luas_min * self.s * self.s:
                continue
            bx, by = min(x + w // 2, self.jalan.shape[1] - 1), min(y + h - 1, self.jalan.shape[0] - 1)
            if not self.jalan[by, bx]:
                continue
            out.append(np.array([x, y, x + w, y + h], float) / self.s)
        return out


# ---------------------------------------------------------------- data
def daftar_video(a):
    if a.video:
        return [os.path.abspath(os.path.expanduser(v)) for v in a.video]
    fs = sorted(glob.glob(os.path.join(ROOT, "data", "recordings", "*", a.node, "*.mp4")),
                key=os.path.basename)
    return [f for f in fs if a.dari <= os.path.basename(f)[:len(a.dari)]
            and os.path.basename(f)[:len(a.sampai)] <= a.sampai]


def siapkan_keluar(a, prof, isi):
    kel = os.path.abspath(os.path.expanduser(a.keluar))
    for d in ("converted/images", "converted/labels", "calib"):
        os.makedirs(os.path.join(kel, d), exist_ok=True)
    xml = os.path.join(kel, "calib", "kalibrasi.xml")
    if os.path.exists(xml) and md5(xml) != md5(isi["CALIB_XML"]):
        sys.exit("Folder %s sudah memakai kalibrasi lain. Pakai --keluar folder baru untuk kalibrasi ini." % kel)
    shutil.copy2(isi["CALIB_XML"], xml)
    shutil.copy2(prof, os.path.join(kel, "profil.json"))
    return kel


def baca_catatan(kel):
    p = os.path.join(kel, "catatan.csv")
    if not os.path.exists(p):
        return {}
    return {r["nama"]: r["keputusan"] for r in csv.DictReader(open(p, encoding="utf-8"))}


def tulis_catatan(kel, nama, keputusan, n):
    p = os.path.join(kel, "catatan.csv")
    baru = not os.path.exists(p)
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if baru:
            w.writerow(["nama", "keputusan", "kotak"])
        w.writerow([nama, keputusan, n])


def simpan(kel, nama, frame, kotak, kam):
    import cv2
    cv2.imwrite(os.path.join(kel, "converted", "images", nama + ".jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    with open(os.path.join(kel, "converted", "labels", nama + ".txt"), "w") as f:
        f.write("x,y,w,h,l\n")
        for k in kotak:
            x, y = kam.titik_label(k["p"])
            f.write("%.3f,%.3f,%.3f,%.3f,%.3f\n" % (x, y, k["p"][2], k["p"][3], k["p"][4]))


def buat_kotak(kam, r):
    p, c = cocokkan_3d(kam, r)
    if p is None:
        return None
    k = {"r": r, "p": p, "galat": c, "aktif": True, "catatan": ""}
    lebar_px, tinggi_px = r[2] - r[0], r[3] - r[1]
    if p[2] < 1.2 or lebar_px < 0.8 * tinggi_px:                          # sempit dan tegak: motor / orang
        k["aktif"], k["catatan"] = False, "motor?"
        return k
    if p[2] < 1.5 or p[3] < 1.25 or p[4] < 3.2:
        # ukuran tidak masuk akal untuk roda empat (gumpalan gerak terpotong / dilihat dari depan):
        # cocokkan ulang dengan ukuran mobil biasa sebagai patokan kuat
        p2, c2 = cocokkan_3d(kam, r, bobot_prior=1.0)
        if p2 is not None:
            k["p"], k["galat"], c = p2, c2, c2
            k["catatan"] = "ukuran ditaksir"
    if c > 0.08:
        k["catatan"] = "kurang pas"
    return k


# ---------------------------------------------------------------- gambar
def gambar(frame, kotak, kam, info, seret=None):
    import cv2
    im = frame.copy()
    tepi = [(0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6), (6, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
    for i, k in enumerate(kotak):
        warna = (0, 200, 0) if k["aktif"] else (0, 0, 230)
        if k["aktif"] and k["catatan"]:
            warna = (0, 200, 230)
        uv, _ = kam.proyeksi(kam.sudut(k["p"]))
        pts = [tuple(int(t) for t in q) for q in uv]
        for a_, b_ in tepi:
            cv2.line(im, pts[a_], pts[b_], warna, 2 if k["aktif"] else 1)
        r = k["r"].astype(int)
        cv2.rectangle(im, (r[0], r[1]), (r[2], r[3]), warna, 1)
        teks = "%d  %.1fx%.1fx%.1fm %s" % (i + 1, k["p"][2], k["p"][3], k["p"][4], k["catatan"])
        cv2.putText(im, teks, (r[0], max(14, r[1] - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, warna, 2)
    if seret is not None:
        cv2.rectangle(im, seret[0], seret[1], (255, 200, 0), 2)
    cv2.rectangle(im, (0, 0), (kam.W, 26), (0, 0, 0), -1)
    cv2.putText(im, info, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.putText(im, "Spasi=simpan  klik=hapus/pulihkan  tarik=tambah  0=lewati  r=ulang  u=batal  q=berhenti",
                (8, kam.H - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    return im


# ---------------------------------------------------------------- utama
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--node")
    p.add_argument("--profil", help="berkas kalibrasi .json (bawaan: data/calibration/<node>/active.json)")
    p.add_argument("--video", nargs="*")
    p.add_argument("--dari", default="")
    p.add_argument("--sampai", default="~")
    p.add_argument("--setiap", type=float, default=3.0, help="jarak antar frame contoh (detik)")
    p.add_argument("--keluar", required=True)
    p.add_argument("--pratinjau", type=int, default=0, help="tanpa layar: simpan N gambar usulan lalu berhenti")
    a = p.parse_args()

    prof, isi = siapkan_profil(a)
    import cv2
    kam = Kamera()
    kel = siapkan_keluar(a, prof, isi)
    vids = daftar_video(a)
    if not vids:
        sys.exit("Tidak ada video yang cocok.")
    print("%d video, kalibrasi %s" % (len(vids), isi["CALIB_XML"]))
    catatan = baca_catatan(kel)
    disimpan = [n for n, k in catatan.items() if k == "simpan"]
    print("sudah diperiksa: %d frame (%d disimpan)" % (len(catatan), len(disimpan)))

    if a.pratinjau:
        os.makedirs(os.path.join(kel, "pratinjau"), exist_ok=True)
    else:
        cv2.namedWindow("label", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("label", kam.W, kam.H)
    mouse = {"bawah": None, "kini": None, "klik": None, "seret": None}

    def on_mouse(ev, x, y, flags, _):
        if ev == cv2.EVENT_LBUTTONDOWN:
            mouse["bawah"], mouse["kini"] = (x, y), (x, y)
        elif ev == cv2.EVENT_MOUSEMOVE and mouse["bawah"] is not None:
            mouse["kini"] = (x, y)
        elif ev == cv2.EVENT_LBUTTONUP and mouse["bawah"] is not None:
            x0, y0 = mouse["bawah"]
            if abs(x - x0) + abs(y - y0) < 10:
                mouse["klik"] = (x, y)
            else:
                mouse["seret"] = (min(x0, x), min(y0, y), max(x0, x), max(y0, y))
            mouse["bawah"] = None
    if not a.pratinjau:
        cv2.setMouseCallback("label", on_mouse)

    n_prat = 0
    for vid in vids:
        dasar = os.path.splitext(os.path.basename(vid))[0]
        cap = cv2.VideoCapture(vid)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        langkah = max(1, int(round(a.setiap * fps)))
        usul = Usulan(kam)
        # pemanasan latar: 12 detik pertama, lalu mulai lagi dari awal
        for _ in range(int(12 * fps)):
            ok, fr = cap.read()
            if not ok:
                break
            usul.latih(cv2.resize(fr, (kam.W, kam.H)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        i = -1
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            i += 1
            fr = cv2.resize(fr, (kam.W, kam.H))
            usul.latih(fr)
            if i < fps or i % langkah:
                continue
            nama = "%s_f%06d" % (dasar, i)
            if nama in catatan:
                continue
            kotak = [k for k in (buat_kotak(kam, r) for r in usul.kotak()) if k is not None]
            fr = usul.tutup_jauh(fr)
            if a.pratinjau:
                cv2.imwrite(os.path.join(kel, "pratinjau", nama + ".jpg"),
                            gambar(fr, kotak, kam, "%s  %d kotak" % (nama, len(kotak))))
                n_prat += 1
                if n_prat >= a.pratinjau:
                    print("pratinjau: %d gambar di %s" % (n_prat, os.path.join(kel, "pratinjau")))
                    return
                continue
            awal = [dict(k, r=k["r"].copy(), p=k["p"].copy()) for k in kotak]
            while True:
                info = "%s  frame %d/%d  |  tersimpan %d frame" % (dasar, i, total, len(disimpan))
                seret = (mouse["bawah"], mouse["kini"]) if mouse["bawah"] is not None else None
                cv2.imshow("label", gambar(fr, kotak, kam, info, seret))
                kunci = cv2.waitKey(30) & 0xFF
                if mouse["klik"] is not None:
                    x, y = mouse["klik"]; mouse["klik"] = None
                    kena = [k for k in kotak if k["r"][0] <= x <= k["r"][2] and k["r"][1] <= y <= k["r"][3]]
                    if kena:
                        k = min(kena, key=lambda t: (t["r"][2] - t["r"][0]) * (t["r"][3] - t["r"][1]))
                        k["aktif"] = not k["aktif"]
                if mouse["seret"] is not None:
                    k = buat_kotak(kam, np.array(mouse["seret"], float)); mouse["seret"] = None
                    if k is not None:
                        k["aktif"], k["catatan"] = True, "manual"
                        kotak.append(k)
                if kunci in (32, 13, 10):
                    aktif = [k for k in kotak if k["aktif"]]
                    simpan(kel, nama, fr, aktif, kam)
                    tulis_catatan(kel, nama, "simpan", len(aktif))
                    catatan[nama] = "simpan"; disimpan.append(nama)
                    break
                if kunci in (ord("0"), ord("x")):
                    tulis_catatan(kel, nama, "lewati", 0)
                    catatan[nama] = "lewati"
                    break
                if kunci == ord("r"):
                    kotak = [dict(k, r=k["r"].copy(), p=k["p"].copy()) for k in awal]
                if kunci == ord("u") and disimpan:
                    akhir = disimpan.pop()
                    for sub, ext in (("images", ".jpg"), ("labels", ".txt")):
                        f = os.path.join(kel, "converted", sub, akhir + ext)
                        if os.path.exists(f):
                            os.remove(f)
                    tulis_catatan(kel, akhir, "dibatalkan", 0)
                    catatan[akhir] = "dibatalkan"
                    print("dibatalkan:", akhir)
                if kunci in (ord("q"), 27):
                    print("berhenti. tersimpan %d frame di %s" % (len(disimpan), kel))
                    return
        cap.release()
    if a.pratinjau:
        print("pratinjau: %d gambar di %s" % (n_prat, os.path.join(kel, "pratinjau")))
    else:
        print("selesai semua video. tersimpan %d frame di %s" % (len(disimpan), kel))


if __name__ == "__main__":
    main()
