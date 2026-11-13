"""
Program utama: deteksi -> tracking -> klasifikasi -> counting pada video jalan.

Contoh:
  python run.py VIDEO.mp4 MODEL.pth
  python run.py VIDEO.mp4 MODEL.pth --no-show --no-save --line-y 15
  python run.py VIDEO.mp4 MODEL.pth --cache det_low.pkl --conf 0.5 --conf-low 0.3 --no-show --no-save
"""

import os
from argparse import ArgumentParser

import cv2
from tqdm import tqdm

import config as cfg
import detection_cache
from counter import LineCounter
from detection_filter import to_world_detections
from kalman_filter import TIME_INTERVAL_FALLBACK
from klasifikasi_gambar import buat_klasifier_gambar
from tracker import Tracker
from visualize import draw_counting_line, draw_counts, draw_debug, draw_frame_id, draw_tracks


def parse_args():
    p = ArgumentParser(description="Deteksi, tracking, klasifikasi, dan counting kendaraan")
    p.add_argument("video")
    p.add_argument("model", help="Bobot CenterNet (.pth)")
    p.add_argument("--conf", type=float, default=cfg.DEFAULT_CONF, help="Ambang skor deteksi")
    p.add_argument(
        "--conf-low", type=float, default=None,
        help="Aktifkan asosiasi dua tahap (ByteTrack, Zhang dkk. 2022): deteksi skor antara "
        "ini dan --conf hanya menyambung track yang ada. Harus > 0 dan < --conf",
    )
    p.add_argument("--line-y", type=float, default=cfg.LINE_Y_DEFAULT_M,
                   help="Posisi garis counting (meter dari kamera)")
    p.add_argument("--line-y-away", type=float, default=cfg.LINE_Y_AWAY_M,
                   help="Garis counting jalur yang MENJAUH, x >= MEDIAN_X_M (meter dari kamera)")
    p.add_argument("--cache", default=None,
                   help="File cache deteksi mentah: ada = dimuat, belum ada = dibuat")
    p.add_argument("--cache-conf", type=float, default=cfg.CACHE_CONF_DEFAULT,
                   help="Ambang skor terendah saat membuat cache")
    p.add_argument("--no-show", action="store_true", help="Tanpa jendela (SSH / VS Code remote)")
    p.add_argument("--no-save", action="store_true", help="Jangan simpan hasil (video/PNG)")
    p.add_argument("--out", default=None,
                   help="Berkas video hasil (.mp4). Bawaan: ~/projects/hasil/video/<nama_video>_hasil.mp4")
    p.add_argument("--png", action="store_true", help="Simpan juga PNG tiap frame ke folder output di config")
    p.add_argument("--klas", default=cfg.KLAS_MODEL, help="Bobot klasifier gambar 4 kelas (.pth)")
    p.add_argument("--tanpa-gambar", action="store_true", help="Klasifikasi dari panjang saja (tanpa klasifier gambar)")
    p.add_argument("--simpan-crop", default=None, help="Folder: simpan crop yang dikirim ke klasifier (untuk dicek mata)")
    p.add_argument("--play", action="store_true", help="Langsung jalan tanpa menunggu tombol")
    p.add_argument("-f", type=int, default=float("inf"),
                   help="Putar otomatis sampai frame ke-N, setelah itu berhenti tiap frame")
    p.add_argument("--debug", action="store_true",
                   help="Tandai deteksi mentah: hijau = lolos, kuning = skor rendah, merah = ditolak")
    return p.parse_args()


def main():
    args = parse_args()
    if args.conf_low is not None and not (0 < args.conf_low < args.conf):
        raise SystemExit("--conf-low harus > 0 dan lebih kecil dari --conf")
    min_conf = args.conf_low if args.conf_low is not None else args.conf
    conf_split = args.conf if args.conf_low is not None else None

    # --- sumber deteksi: cache (jika ada) atau detektor ---
    cached_frames, detector, new_frames, detect_conf = None, None, None, min_conf
    if args.cache and os.path.exists(args.cache):
        cached_frames = detection_cache.load(args.cache, min_conf)
        print(f"Memakai cache deteksi: {args.cache} ({len(cached_frames)} frame)")
    else:
        from detector import Detector  # impor torch hanya bila detektor dipakai

        detect_conf = min(args.cache_conf, min_conf) if args.cache else min_conf
        detector = Detector(args.model, detect_conf)
        new_frames = [] if args.cache else None

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise SystemExit("Gagal membuka video")
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    dt = 1.0 / fps if fps and fps > 1 else TIME_INTERVAL_FALLBACK
    print(f"Video FPS: {fps:.1f} -> dt = {dt:.4f} s")
    print(f"Opsi: conf={args.conf} conf_low={args.conf_low} line_y={args.line_y} line_y_away={args.line_y_away}")

    writer, out_path, tmp_path = None, None, None
    if not args.no_save:
        stem = os.path.splitext(os.path.basename(args.video))[0]
        out_path = os.path.abspath(os.path.expanduser(
            args.out or os.path.join("~/projects/hasil/video", stem + "_hasil.mp4")))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        tmp_path = out_path + ".tmp.mp4"
        writer = cv2.VideoWriter(tmp_path, cv2.VideoWriter_fourcc(*"mp4v"),
                                 fps if fps and fps > 1 else 25.0, (cfg.IMG_W, cfg.IMG_H))
        if not writer.isOpened():
            raise SystemExit(f"Gagal membuat berkas video: {tmp_path}")
        if args.png:
            os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)

    tracker = Tracker(dt)
    counter = LineCounter(args.line_y, args.line_y_away)
    klas = None if args.tanpa_gambar else buat_klasifier_gambar(args.klas, args.simpan_crop)
    print("Klasifikasi:", "panjang saja" if klas is None else "gambar + panjang (" + os.path.basename(args.klas) + ")")
    rejected_total = {}
    play = args.play
    need_draw = (not args.no_show) or (not args.no_save)
    finished = True

    for idx in tqdm(range(n_frames)):
        ok, frame = cap.read()
        if not ok:
            finished = False
            break
        if frame.shape[:2] != (cfg.IMG_H, cfg.IMG_W):
            raise SystemExit(
                f"Ukuran video {frame.shape[1]}x{frame.shape[0]}, harus {cfg.IMG_W}x{cfg.IMG_H} "
                "(kalibrasi dan detektor mengasumsikan ukuran ini)."
            )

        # 1. deteksi
        if cached_frames is not None:
            raw = cached_frames[idx] if idx < len(cached_frames) else []
        else:
            raw = detector.detect(frame)
            if new_frames is not None:
                new_frames.append(raw)
        boxes = [b for b in raw if b["score"] >= min_conf]

        # 2. proyeksi ke jalan dan filter
        dets, marks, rejected = to_world_detections(boxes, conf_split)
        for reason, n in rejected.items():
            rejected_total[reason] = rejected_total.get(reason, 0) + n

        # 3. tracking, lalu klasifikasi (di dalam Track) dan counting
        tracker.update(dets, conf_high=conf_split)
        tracker.assign_display_ids()
        if klas is not None:
            klas.perbarui(frame, tracker.tracks, idx)  # frame masih bersih (belum digambar)
        counter.update(tracker.tracks, idx)

        if need_draw:
            frame = draw_tracks(frame, tracker)
            frame = draw_counting_line(frame, args.line_y, args.line_y_away)
            if args.debug:
                frame = draw_debug(frame, marks)
            frame = draw_counts(frame, counter.counts)
            draw_frame_id(frame, idx)

        if not args.no_show:
            cv2.imshow("Detection", frame)
            k = cv2.waitKey(10 if (idx < args.f or play) else 0)
            if k == 27:  # ESC
                finished = False
                break
            if k == 32:  # SPASI
                play = not play

        if writer is not None:
            writer.write(frame)
            if args.png:
                cv2.imwrite(f"{cfg.OUTPUT_DIR}/image_{idx:04d}.png", frame)

    cap.release()
    if writer is not None:
        writer.release()
        # Ubah ke H.264 bila ffmpeg ada, supaya bisa diputar di VS Code / peramban / pemutar bawaan.
        import shutil
        import subprocess
        ok = False
        if shutil.which("ffmpeg"):
            ok = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp_path, "-c:v", "libx264",
                                 "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", out_path]).returncode == 0
        if ok:
            os.remove(tmp_path)
        else:
            os.replace(tmp_path, out_path)
            print("Catatan: ffmpeg tidak dipakai; video berformat mp4v (bila tidak bisa diputar: sudo apt install ffmpeg).")
        print(f"\nVideo hasil disimpan: {out_path}")
    if not args.no_show:
        cv2.destroyAllWindows()

    if new_frames is not None and finished and len(new_frames) == n_frames:
        detection_cache.save(args.cache, new_frames, detect_conf)
        print(f"\nCache deteksi disimpan: {args.cache}")

    counter.save_log(cfg.COUNT_LOG)
    counter.print_report(cfg.COUNT_LOG)
    if rejected_total:
        print("\nDeteksi mentah yang dibuang filter (per alasan):")
        for reason, n in sorted(rejected_total.items(), key=lambda kv: -kv[1]):
            print(f"  {reason:12}: {n}")


if __name__ == "__main__":
    main()
