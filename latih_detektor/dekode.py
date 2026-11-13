"""dekode.py - dekode keluaran jaringan menjadi kotak 3D dan kotak 2D (numpy saja, tanpa PyTorch).
Salinan dari centernet-3d-bbox.ipynb (commit 3fa494cd): select (baris 154-174), pred2box (175-204),
bagian hitung showbox (206-233), urutan dekode pengujian (664-679: sigmoid -> select -> pred2box),
dan 8 sudut Box.project di utils.py (baris 155-205) tanpa menggambar.
Perubahan atas acuan: sigmoid ditulis dengan numpy (0.5*(1+tanh(x/2)), identik secara matematis,
tanpa galat limpahan); select bekerja pada salinan agar heatmap masukan tidak berubah;
iou_2d dan kotak 2D ditambahkan (acuan hanya menggambar).
Pemakaian uji: python3 dekode.py [jumlah_frame]   (uji bolak-balik pada label asli)
"""
import os
import sys
import numpy as np

REPO = os.path.expanduser("~/projects/acuan/3d_bbox_highway")
sys.path.insert(0, REPO)
from utils import get_position_ground, project  # noqa: E402

MODEL_SCALE = 32


def sigmoid(x):
    return 0.5 * (1.0 + np.tanh(0.5 * np.asarray(x, dtype=np.float64)))


def select(hm, threshold):
    pred = hm > threshold
    pred_centers = np.argwhere(pred)
    for i, ci in enumerate(pred_centers):
        for j in range(i + 1, len(pred_centers)):
            cj = pred_centers[j]
            if np.linalg.norm(ci - cj) <= 2:
                score_i = hm[ci[0], ci[1]]
                score_j = hm[cj[0], cj[1]]
                if score_i > score_j:
                    hm[cj[0], cj[1]] = 0
                else:
                    hm[ci[0], ci[1]] = 0
    return hm


def pred2box(hm, offset, regr, thresh=0.99):
    pred = hm > thresh
    pred_center = np.where(hm > thresh)
    pred_r = regr[:, pred].T
    boxes = []
    scores = hm[pred]
    pred_center = np.asarray(pred_center).T
    for (center, b) in zip(pred_center, pred_r):
        offset_xy = offset[:, center[0], center[1]]
        arr = np.array([(center[1] + offset_xy[0]) * MODEL_SCALE, (center[0] + offset_xy[1]) * MODEL_SCALE,
                        b[0], b[1], b[2]])
        boxes.append(arr)
    return np.asarray(boxes), scores


def box_corners_2d(x, z, w, h, l, to_world_from_camera, K, img_height):
    """8 sudut Box(x, z, w, h, l) di piksel gambar (y dari atas), tanpa dibulatkan."""
    to_camera_from_world = np.linalg.inv(to_world_from_camera)
    pts = []
    for dx in (-w / 2, w / 2):
        for dy in (0.0, h):
            for dz in (-l / 2, l / 2):
                p = project(np.array([x + dx, dy, z + dz]), to_camera_from_world, K)
                p[1] = img_height - p[1]
                pts.append(p)
    return np.array(pts)


def bbox_2d(corners):
    return (float(corners[:, 0].min()), float(corners[:, 1].min()),
            float(corners[:, 0].max()), float(corners[:, 1].max()))


def iou_2d(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def decode(hm, offset, whl, K, to_world_from_camera, img_height=720, thresh=0.1, apply_sigmoid=True):
    """hm: logit (23,40) bila apply_sigmoid. offset (2,23,40), whl (3,23,40). Mengembalikan daftar dict."""
    hm = sigmoid(hm) if apply_sigmoid else np.array(hm, dtype=np.float64)
    hm = select(hm, thresh)
    boxes, scores = pred2box(hm, offset, whl, thresh=thresh)
    out = []
    for box, s in zip(boxes, scores):
        pos = get_position_ground(box[0], box[1], K, to_world_from_camera, img_height)
        depth = float(np.linalg.norm(pos - to_world_from_camera[:3, 3]))
        x, z = float(pos[0]), float(pos[2])
        w, h, l = float(box[2] * depth), float(box[3] * depth), float(box[4] * depth)
        corners = box_corners_2d(x, z, w, h, l, to_world_from_camera, K, img_height)
        out.append(dict(px=float(box[0]), py=float(box[1]), x=x, z=z, w=w, h=h, l=l,
                        depth=depth, score=float(s), bbox2d=bbox_2d(corners)))
    return out


def selftest(n_frames=300):
    """Uji bolak-balik: label -> target (target.py) -> dekode -> harus kembali ke label.
    Objek yang sel pusatnya tertimpa isian 3x3 objek lain yang digambar belakangan (atau sel pusat
    yang sama) dipisahkan, karena targetnya memang menjadi milik objek lain (perilaku acuan)."""
    import glob
    import pandas as pd
    import kamera
    import target as tg
    cam = kamera.load_camera()
    K, T = cam["K"], cam["T"]
    folder = os.path.expanduser("~/projects/data_session0_right/converted/labels")
    files = sorted(glob.glob(os.path.join(folder, "*.txt")))[:n_frames]
    n_near = n_ok = n_over = n_sel = n_hilang = 0
    n_far = zero_far = 0
    max_pos = max_rel = max_iou_gap = 0.0
    for fp in files:
        df = pd.read_csv(fp)
        hm, off, regr = tg.make_hm_offset_regr(df, K, T, 150)
        dets = decode(hm, off, regr, K, T, 720, thresh=0.99, apply_sigmoid=False)
        rows = [(int(c["y"] / 32), int(c["x"] / 32), c) for _, c in df.iterrows()]
        for i, (ry, rx, c) in enumerate(rows):
            if c["y"] < 150:
                n_far += 1
                d = [q for q in dets if int(q["py"] / 32) == ry and int(q["px"] / 32) == rx]
                if d and d[0]["w"] == 0 and d[0]["h"] == 0 and d[0]["l"] == 0:
                    zero_far += 1
                continue
            n_near += 1
            ditimpa = any(j > i and cj["y"] >= 150 and abs(ry2 - ry) <= 1 and abs(rx2 - rx) <= 1
                          for j, (ry2, rx2, cj) in enumerate(rows))
            if ditimpa:
                n_over += 1
                continue
            d = [q for q in dets if abs(q["px"] - c["x"]) < 1e-3 and abs(q["py"] - c["y"]) < 1e-3]
            if not d:
                if any(j != i and ((ry2 - ry) ** 2 + (rx2 - rx) ** 2) ** 0.5 <= 2
                       for j, (ry2, rx2, cj) in enumerate(rows)):
                    n_sel += 1
                else:
                    n_hilang += 1
                continue
            q = d[0]
            n_ok += 1
            max_pos = max(max_pos, abs(q["px"] - c["x"]), abs(q["py"] - c["y"]))
            for k in ("w", "h", "l"):
                max_rel = max(max_rel, abs(q[k] - c[k]) / c[k])
            pos = get_position_ground(c["x"], c["y"], K, T, 720)
            ref = bbox_2d(box_corners_2d(pos[0], pos[2], c["w"], c["h"], c["l"], T, K, 720))
            max_iou_gap = max(max_iou_gap, 1.0 - iou_2d(q["bbox2d"], ref))
    print("frame: %d | objek y>=150: %d" % (len(files), n_near))
    print("  tidak tertimpa: %d | kembali ke label: %d | ditekan select (pusat lain berjarak sel <= 2): %d | hilang tanpa sebab: %d"
          % (n_near - n_over, n_ok, n_sel, n_hilang))
    print("  tertimpa isian 3x3 objek lain yang digambar belakangan: %d (%.1f%%)" % (n_over, 100.0 * n_over / max(n_near, 1)))
    print("  galat posisi piksel maks: %.2e | galat relatif w,h,l maks: %.2e | 1-IoU maks: %.2e" % (max_pos, max_rel, max_iou_gap))
    print("objek y<150: %d | didekode dengan ukuran nol (w=h=l=0): %d" % (n_far, zero_far))


if __name__ == "__main__":
    selftest(int(sys.argv[1]) if len(sys.argv) > 1 else 300)