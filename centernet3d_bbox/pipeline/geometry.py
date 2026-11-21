"""
Geometri kamera: proyeksi 3D -> 2D dan proyeksi balik piksel ke bidang jalan.

Konvensi dunia: x = kanan, y = atas (0 = permukaan jalan), z = maju.
Pada Track, "y" milik Kalman Filter adalah z dunia.

Dasar: model kamera lubang jarum dan perpotongan sinar dengan bidang
y = 0 (Hartley & Zisserman, Multiple View Geometry, 2004, bab 6).
"""

import xml.etree.ElementTree as ET

import numpy as np

import config as cfg


def pitch_matrix(angle):
    """Rotasi sudut `angle` (radian) di sumbu X."""
    m = np.zeros((3, 3))
    m[0, 0] = 1
    m[1, 1] = np.cos(angle)
    m[1, 2] = np.sin(angle)
    m[2, 1] = -np.sin(angle)
    m[2, 2] = np.cos(angle)
    return m


def build_camera(pitch_deg, height_m, focal_px, img_w, img_h):
    """Kembalikan (K, to_world_from_camera). Titik pusat citra = tengah frame."""
    to_world = np.identity(4)
    to_world[:3, :3] = pitch_matrix(-pitch_deg * np.pi / 180)
    to_world[:3, 3] = np.array([0.0, height_m, 0.0])
    K = np.array(
        [[focal_px, 0.0, img_w / 2], [0.0, focal_px, img_h / 2], [0.0, 0.0, 1.0]]
    )
    return K, to_world


def build_camera_from_calib(xml_path, img_w, img_h, ref_size=(1920, 1080)):
    """Kamera dari berkas kalibrasi BrnoCompSpeed (calibParams.xml): fokus f (px pada ref_size),
    tinggi kamera h (mm), dan dua titik hilang (arah jalan dan arah melintang jalan).
    Rotasi kamera dihitung dari kedua titik hilang (pitch, yaw, dan roll sekaligus), sama dengan
    kamera.py yang dipakai membuat label 3D data latih. Kembalikan (K, to_world_from_camera).
    Konvensi dunia sama dengan build_camera: x = kanan, y = atas, z = maju; kamera di (0, h, 0)."""
    cal = ET.parse(xml_path).getroot()
    f_ref = float(cal.findtext("f"))
    h_m = float(cal.findtext("h")) / 1000.0
    vp = [float(t) for t in cal.findtext("vanishPoints").split()]
    ref_w, ref_h = ref_size
    k_ref = np.array([[f_ref, 0, ref_w / 2], [0, f_ref, ref_h / 2], [0, 0, 1.0]])

    def direction(p):
        d = np.linalg.inv(k_ref) @ np.array([p[0], p[1], 1.0])
        return d / np.linalg.norm(d)

    d1, d2 = direction(vp[0:2]), direction(vp[2:4])
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
    r_wc = np.stack([x_ax * flip, z_ax * flip, d1 * flip], axis=0)
    to_world = np.identity(4)
    to_world[:3, :3] = r_wc
    to_world[:3, 3] = [0.0, h_m, 0.0]
    f = f_ref * img_w / ref_w
    k = np.array([[f, 0.0, img_w / 2], [0.0, f, img_h / 2], [0.0, 0.0, 1.0]])
    return k, to_world


if getattr(cfg, "CALIB_XML", None):
    K, TO_WORLD_FROM_CAMERA = build_camera_from_calib(
        cfg.CALIB_XML, cfg.IMG_W, cfg.IMG_H, getattr(cfg, "CALIB_REF_SIZE", (1920, 1080))
    )
else:
    K, TO_WORLD_FROM_CAMERA = build_camera(
        cfg.PITCH_DEG, cfg.CAM_HEIGHT_M, cfg.FOCAL_PX, cfg.IMG_W, cfg.IMG_H
    )
TO_CAMERA_FROM_WORLD = np.linalg.inv(TO_WORLD_FROM_CAMERA)
CAMERA_POS = TO_WORLD_FROM_CAMERA[:3, 3].copy()


def project(point_in_world, to_camera_from_world=TO_CAMERA_FROM_WORLD, k=K):
    """Titik dunia (3,) -> piksel (u, v) dengan v dihitung dari BAWAH citra."""
    p = np.asarray(point_in_world, dtype=float).reshape(3, 1)
    pc = to_camera_from_world[:3, :3].dot(p) + to_camera_from_world[:3, 3].reshape(3, 1)
    pc /= abs(pc[2])
    return k.dot(pc).flatten()[:2]


def world_to_image(point_in_world, img_h=cfg.IMG_H):
    """Titik dunia -> (u, v) piksel OpenCV (v dari ATAS citra), bertipe int."""
    pix = project(point_in_world)
    return int(pix[0]), int(img_h - pix[1])


def get_position_ground(x, y, img_h=cfg.IMG_H):
    """Piksel (x, y) OpenCV -> posisi dunia pada bidang jalan (y dunia = 0)."""
    pc = np.linalg.inv(K).dot(np.array([x, img_h - y, 1.0]).reshape(3, 1))
    pw = TO_WORLD_FROM_CAMERA[:3, :3].dot(pc) + CAMERA_POS.reshape(3, 1)
    direction = pw - CAMERA_POS.reshape(3, 1)
    direction /= np.linalg.norm(direction)
    lam = -CAMERA_POS[1] / direction[1]
    return (CAMERA_POS.reshape(3, 1) + lam * direction).flatten()
