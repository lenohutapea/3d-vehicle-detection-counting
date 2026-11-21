"""kamera.py - K dan T kamera session0_right (resolusi 1280x720).
Salinan logika cek_bagian1.py baris 13-36 (terbukti: IoU kotak 2D median 0,906).
Dipakai bersama oleh pelatihan dan deteksi/tracking.
"""
import os
import xml.etree.ElementTree as ET
import numpy as np

BASE_DEFAULT = os.path.expanduser("~/projects/data_session0_right")
S = 2.0 / 3.0  # skala 1920x1080 -> 1280x720


def load_camera(base=None):
    """Mengembalikan dict: K (3x3), T (4x4, to_world_from_camera), f, f_full, h_m, R_wc."""
    base = base or BASE_DEFAULT
    cal = ET.parse(os.path.join(base, "calib", "session0_right_calibParams.xml")).getroot()
    f_full = float(cal.findtext("f"))
    h_m = float(cal.findtext("h")) / 1000.0
    v = [float(t) for t in cal.findtext("vanishPoints").split()]
    Kf = np.array([[f_full, 0, 960.], [0, f_full, 540.], [0, 0, 1.]])

    def direction(vp):
        d = np.linalg.inv(Kf) @ np.array([vp[0], vp[1], 1.0])
        return d / np.linalg.norm(d)

    d1, d2 = direction(v[0:2]), direction(v[2:4])
    if d1[2] < 0: d1 = -d1
    if d2[0] < 0: d2 = -d2
    X = d2 - (d2 @ d1) * d1
    X /= np.linalg.norm(X)
    Z = np.cross(X, d1)
    if Z[1] > 0: Z = -Z
    flip = np.array([1, -1, 1])
    R_wc = np.stack([X * flip, Z * flip, d1 * flip], axis=0)
    T = np.identity(4)
    T[:3, :3] = R_wc
    T[:3, 3] = [0, h_m, 0]
    f = f_full * S
    K = np.array([[f, 0, 640.], [0, f, 360.], [0, 0, 1.]])
    return {"K": K, "T": T, "f": f, "f_full": f_full, "h_m": h_m, "R_wc": R_wc}


if __name__ == "__main__":
    c = load_camera()
    print("f(720p)=%.2f  h=%.3f m  det(R)=%.6f" % (c["f"], c["h_m"], np.linalg.det(c["R_wc"])))