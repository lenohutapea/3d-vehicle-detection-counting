"""
click_calibration.py - kalibrasi kamera dari klik pada gambar (tanpa berkas kalibrasi).

Masukan (koordinat piksel pada frame IMG_W x IMG_H, y dihitung dari ATAS):
  garis A : 2 titik di sepanjang satu marka / tepi lajur
  garis B : 2 titik di sepanjang marka / tepi lajur lain yang SEJAJAR dengan garis A
  lebar   : jarak nyata antara garis A dan garis B (meter), mis. lebar satu lajur 3,5 m
  panjang : 2 titik di sepanjang jalan (di satu garis) + jarak nyatanya (meter),
            mis. ujung-ujung satu marka putus-putus, atau marka + celahnya

Cara menghitung (model lubang jarum, titik pusat citra = tengah frame, kamera tidak miring ke samping):
  1. Titik hilang arah jalan (vp1) = perpotongan garis A dan garis B.
  2. Untuk sebuah focal f, titik hilang arah melintang (vp2) berada di garis horizon yang mendatar
     melalui vp1 dan tegak lurus arah jalan:  (u1-cx)(u2-cx) + (v1-cy)^2 + f^2 = 0.
  3. Dengan tinggi kamera 1 m, piksel diproyeksikan ke bidang jalan. Perbandingan panjang/lebar
     hasil proyeksi hanya bergantung pada f, jadi f dicari sampai perbandingannya sama dengan
     perbandingan ukuran nyata.
  4. Tinggi kamera = lebar nyata / lebar hasil proyeksi (yang dihitung dengan tinggi 1 m).
Hasilnya ditulis sebagai berkas kalibrasi berformat BrnoCompSpeed (f, h, vanishPoints), sehingga
dipakai pipeline dengan fungsi yang sama: geometry.build_camera_from_calib (rotasi dari dua titik hilang).
"""
import math

import numpy as np


class GagalKalibrasi(ValueError):
    pass


def _rotasi_dari_titik_hilang(vp1, vp2, f, cx, cy):
    """Sama dengan geometry.build_camera_from_calib (dengan ref_size = ukuran frame)."""
    k = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1.0]])

    def direction(p):
        d = np.linalg.inv(k) @ np.array([p[0], p[1], 1.0])
        return d / np.linalg.norm(d)

    d1, d2 = direction(vp1), direction(vp2)
    if d1[2] < 0:
        d1 = -d1
    if d2[0] < 0:
        d2 = -d2
    x_ax = d2 - (d2 @ d1) * d1
    x_ax /= np.linalg.norm(x_ax)
    z_ax = np.cross(x_ax, d1)
    if z_ax[1] > 0:
        z_ax = -z_ax
    flip = np.array([1.0, -1.0, 1.0])
    return np.stack([x_ax * flip, z_ax * flip, d1 * flip], axis=0), k


def _ke_jalan(pts, r_wc, k, h, img_h):
    """Sama dengan geometry.get_position_ground: piksel (y dari atas) -> (x, z) di bidang jalan."""
    kinv = np.linalg.inv(k)
    cam = np.array([0.0, h, 0.0])
    out = []
    for x, y in pts:
        pc = kinv @ np.array([x, img_h - y, 1.0])
        d = r_wc @ pc
        d /= np.linalg.norm(d)
        if d[1] >= -1e-9:                       # sinar tidak mengenai jalan (di atas horizon)
            return None
        lam = -cam[1] / d[1]
        p = cam + lam * d
        out.append((p[0], p[2]))
    return np.array(out)


def _potong(a1, a2, b1, b2):
    la = np.cross([*a1, 1.0], [*a2, 1.0])
    lb = np.cross([*b1, 1.0], [*b2, 1.0])
    p = np.cross(la, lb)
    if abs(p[2]) < 1e-9:
        return None
    return p[:2] / p[2]


def _vp2(vp1, f, cx, cy):
    du = vp1[0] - cx
    if abs(du) < 1e-3:
        du = 1e-3 if du >= 0 else -1e-3
    return np.array([cx - (f * f + (vp1[1] - cy) ** 2) / du, vp1[1]])


def _ukur(f, vp1, a, b, panjang_titik, cx, cy, img_h):
    """Lebar (jarak garis A-B) dan panjang di bidang jalan untuk focal f dan tinggi 1 m."""
    r, k = _rotasi_dari_titik_hilang(vp1, _vp2(vp1, f, cx, cy), f, cx, cy)
    ga, gb, gl = (_ke_jalan(p, r, k, 1.0, img_h) for p in (a, b, panjang_titik))
    if ga is None or gb is None or gl is None:
        return None
    arah = ga[1] - ga[0]
    arah /= np.linalg.norm(arah)
    normal = np.array([-arah[1], arah[0]])
    lebar = abs(np.mean([(q - ga[0]) @ normal for q in gb]))
    panjang = float(np.linalg.norm(gl[1] - gl[0]))
    return lebar, panjang


def hitung(a, b, panjang_titik, lebar_m, panjang_m, img_w, img_h):
    """Kembalikan dict: f, h (m), vp1, vp2 (piksel frame), sudut tunduk, dan galat ukur."""
    a, b, panjang_titik = (np.asarray(p, dtype=float).reshape(2, 2) for p in (a, b, panjang_titik))
    if not (0.5 <= lebar_m <= 100 and 0.5 <= panjang_m <= 500):
        raise GagalKalibrasi("Lebar harus 0,5–100 m dan panjang 0,5–500 m.")
    for nama, p in (("A", a), ("B", b), ("panjang", panjang_titik)):
        if np.linalg.norm(p[1] - p[0]) < 10:
            raise GagalKalibrasi("Dua titik garis %s terlalu berdekatan; klik lebih berjauhan." % nama)
    cx, cy = img_w / 2.0, img_h / 2.0
    vp1 = _potong(a[0], a[1], b[0], b[1])
    if vp1 is None or not np.all(np.isfinite(vp1)):
        raise GagalKalibrasi("Garis A dan B tampak sejajar di gambar. Pilih dua marka yang tampak "
                             "menyempit ke satu titik di kejauhan.")
    if vp1[1] > img_h * 0.6:
        raise GagalKalibrasi("Titik temu garis A dan B berada di bawah gambar. Pastikan kedua garis "
                             "mengikuti arah jalan (menjauh dari kamera).")
    target = math.log(panjang_m / lebar_m)

    def galat(f):
        u = _ukur(f, vp1, a, b, panjang_titik, cx, cy, img_h)
        if u is None or u[0] <= 1e-9 or u[1] <= 1e-9:
            return None
        return math.log(u[1] / u[0]) - target

    kandidat = np.geomspace(0.2 * img_w, 15 * img_w, 600)
    nilai = [galat(f) for f in kandidat]
    terbaik = None
    for i in range(len(kandidat) - 1):                        # cari perubahan tanda, lalu bagi dua
        g0, g1 = nilai[i], nilai[i + 1]
        if g0 is None or g1 is None or g0 * g1 > 0:
            continue
        lo, hi = kandidat[i], kandidat[i + 1]
        for _ in range(60):
            mid = math.sqrt(lo * hi)
            gm = galat(mid)
            if gm is None:
                break
            if (gm > 0) == (galat(lo) > 0):
                lo = mid
            else:
                hi = mid
        f = math.sqrt(lo * hi)
        if terbaik is None or abs(galat(f)) < abs(galat(terbaik)):
            terbaik = f
    if terbaik is None:
        sah = [(abs(g), f) for g, f in zip(nilai, kandidat) if g is not None]
        if not sah or min(sah)[0] > 0.02:
            raise GagalKalibrasi("Tidak ditemukan focal yang cocok dengan ukuran yang diberikan. Periksa "
                                 "lagi titik-titiknya dan angka lebar/panjangnya.")
        terbaik = min(sah)[1]
    f = float(terbaik)
    lebar1, panjang1 = _ukur(f, vp1, a, b, panjang_titik, cx, cy, img_h)
    h = lebar_m / lebar1
    vp2 = _vp2(vp1, f, cx, cy)
    return {"f": f, "h": float(h), "vp1": [float(vp1[0]), float(vp1[1])], "vp2": [float(vp2[0]), float(vp2[1])],
            "sudut_tunduk": math.degrees(math.atan2(cy - vp1[1], f)),
            "cek_panjang_m": panjang1 * h, "cek_lebar_m": lebar1 * h}


def ke_xml(hasil, img_w, img_h, ref_size=(1920, 1080)):
    """Berkas kalibrasi berformat BrnoCompSpeed (koordinat pada ref_size, h dalam mm)."""
    s = ref_size[0] / float(img_w)
    v1, v2 = hasil["vp1"], hasil["vp2"]
    return ('<?xml version="1.0"?>\n<opencv_storage>\n<!-- dibuat dari kalibrasi klik -->\n'
            "<f>%.6f</f>\n<h>%.3f</h>\n<vanishPoints>\n  %.4f %.4f %.4f %.4f</vanishPoints>\n</opencv_storage>\n"
            % (hasil["f"] * s, hasil["h"] * 1000.0, v1[0] * s, v1[1] * s, v2[0] * s, v2[1] * s)).encode()
