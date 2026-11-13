#!/usr/bin/env python3
"""pasang_kalibrasi.py - pasang kalibrasi kamera session0_right (dari calibParams.xml) ke repo.
Perubahan (semua dicek tepat 1 kali ditemukan; kalau tidak, berhenti tanpa mengubah apa pun):
  geometry.py : + build_camera_from_calib() dan pemilihan kamera lewat cfg.CALIB_XML
  config.py   : + CALIB_XML dan CALIB_REF_SIZE setelah FOCAL_PX
Cadangan asli disalin ke <berkas>.sebelum_kalibrasi. Pemakaian: python3 pasang_kalibrasi.py [folder_repo]
"""
import os, shutil, sys
repo = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/projects/3d-car-classification-counting")
BLOK = 'def build_camera_from_calib(xml_path, img_w, img_h, ref_size=(1920, 1080)):\n    """Kamera dari berkas kalibrasi BrnoCompSpeed (calibParams.xml): fokus f (px pada ref_size),\n    tinggi kamera h (mm), dan dua titik hilang (arah jalan dan arah melintang jalan).\n    Rotasi kamera dihitung dari kedua titik hilang (pitch, yaw, dan roll sekaligus), sama dengan\n    kamera.py yang dipakai membuat label 3D data latih. Kembalikan (K, to_world_from_camera).\n    Konvensi dunia sama dengan build_camera: x = kanan, y = atas, z = maju; kamera di (0, h, 0)."""\n    cal = ET.parse(xml_path).getroot()\n    f_ref = float(cal.findtext("f"))\n    h_m = float(cal.findtext("h")) / 1000.0\n    vp = [float(t) for t in cal.findtext("vanishPoints").split()]\n    ref_w, ref_h = ref_size\n    k_ref = np.array([[f_ref, 0, ref_w / 2], [0, f_ref, ref_h / 2], [0, 0, 1.0]])\n\n    def direction(p):\n        d = np.linalg.inv(k_ref) @ np.array([p[0], p[1], 1.0])\n        return d / np.linalg.norm(d)\n\n    d1, d2 = direction(vp[0:2]), direction(vp[2:4])\n    if d1[2] < 0:\n        d1 = -d1\n    if d2[0] < 0:\n        d2 = -d2\n    x_ax = d2 - (d2 @ d1) * d1\n    x_ax /= np.linalg.norm(x_ax)\n    z_ax = np.cross(x_ax, d1)\n    if z_ax[1] > 0:\n        z_ax = -z_ax\n    flip = np.array([1.0, -1.0, 1.0])\n    r_wc = np.stack([x_ax * flip, z_ax * flip, d1 * flip], axis=0)\n    to_world = np.identity(4)\n    to_world[:3, :3] = r_wc\n    to_world[:3, 3] = [0.0, h_m, 0.0]\n    f = f_ref * img_w / ref_w\n    k = np.array([[f, 0.0, img_w / 2], [0.0, f, img_h / 2], [0.0, 0.0, 1.0]])\n    return k, to_world\n\n\nif getattr(cfg, "CALIB_XML", None):\n    K, TO_WORLD_FROM_CAMERA = build_camera_from_calib(\n        cfg.CALIB_XML, cfg.IMG_W, cfg.IMG_H, getattr(cfg, "CALIB_REF_SIZE", (1920, 1080))\n    )\nelse:\n    K, TO_WORLD_FROM_CAMERA = build_camera(\n        cfg.PITCH_DEG, cfg.CAM_HEIGHT_M, cfg.FOCAL_PX, cfg.IMG_W, cfg.IMG_H\n    )\n'
def edit(nama, pasangan):
    p = os.path.join(repo, nama)
    s = open(p, encoding="utf-8").read()
    if "CALIB_XML" in s:
        raise SystemExit(nama + ": sudah ditambal (CALIB_XML ada); tidak diubah")
    for a, b in pasangan:
        if s.count(a) != 1:
            raise SystemExit("%s: potongan tidak ditemukan tepat 1 kali, dihentikan:\n%s" % (nama, a))
        s = s.replace(a, b)
    return p, s
pg, sg = edit("geometry.py", [
    ("import numpy as np\n\nimport config as cfg\n", "import xml.etree.ElementTree as ET\n\nimport numpy as np\n\nimport config as cfg\n"),
    ("K, TO_WORLD_FROM_CAMERA = build_camera(\n    cfg.PITCH_DEG, cfg.CAM_HEIGHT_M, cfg.FOCAL_PX, cfg.IMG_W, cfg.IMG_H\n)\n", BLOK),
])
pc, sc = edit("config.py", [
    ("FOCAL_PX = 770.00      # focal length (piksel)\n",
     "FOCAL_PX = 770.00      # focal length (piksel)\n"
     "# Kalibrasi kamera nyata dari berkas BrnoCompSpeed (calibParams.xml). Bila diisi, PITCH_DEG,\n"
     "# CAM_HEIGHT_M, dan FOCAL_PX di atas TIDAK dipakai oleh geometry.py. None = pakai model pitch di atas.\n"
     "CALIB_XML = os.path.expanduser(\"~/projects/data_session0_right/calib/session0_right_calibParams.xml\")\n"
     "CALIB_REF_SIZE = (1920, 1080)   # ukuran citra asli yang dipakai berkas kalibrasi (lebar, tinggi)\n"),
])
if "import os" not in sc.split("IMG_W")[0]:
    sc = sc.replace('"""\n\n# ---', '"""\n\nimport os\n\n# ---', 1)
    if "import os" not in sc:
        raise SystemExit("config.py: gagal menambah import os")
for p, s in ((pg, sg), (pc, sc)):
    shutil.copy2(p, p + ".sebelum_kalibrasi")
    open(p, "w", encoding="utf-8").write(s)
print("selesai. cadangan: geometry.py.sebelum_kalibrasi dan config.py.sebelum_kalibrasi")