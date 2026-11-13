#!/usr/bin/env python3
"""pasang_video.py - run.py menyimpan hasil sebagai SATU video mp4 (bukan PNG per frame).

Jalankan dari folder pipeline:
    cd ~/projects/uji_session0_pipeline && python3 ~/projects/alat/pasang_video.py
Sesudahnya:
    python3 run.py VIDEO MODEL ... --no-show            -> ~/projects/hasil/video/<nama_video>_hasil.mp4
    ... --out jalur/berkas.mp4                          -> nama sendiri
    ... --png                                           -> simpan juga PNG tiap frame (perilaku lama)
    ... --no-save                                       -> tidak menyimpan apa pun
Cadangan: run.py.sebelum_video. Menolak jalan dua kali.
"""
import os, shutil, sys

if not os.path.exists("run.py"):
    sys.exit("Jalankan dari folder pipeline; run.py tidak ada di sini.")
r = open("run.py", encoding="utf-8").read()
if "--png" in r:
    sys.exit("Sudah terpasang. Tidak melakukan apa-apa.")


def ganti(s, lama, baru):
    if s.count(lama) != 1:
        sys.exit("GAGAL: bagian '%s' tidak ditemukan tepat satu kali di run.py." % lama[:50].strip())
    return s.replace(lama, baru)


r = ganti(r, '    p.add_argument("--no-save", action="store_true", help="Jangan simpan PNG tiap frame")\n',
          '    p.add_argument("--no-save", action="store_true", help="Jangan simpan hasil (video/PNG)")\n'
          '    p.add_argument("--out", default=None,\n'
          '                   help="Berkas video hasil (.mp4). Bawaan: ~/projects/hasil/video/<nama_video>_hasil.mp4")\n'
          '    p.add_argument("--png", action="store_true", help="Simpan juga PNG tiap frame ke folder output di config")\n')
r = ganti(r, "    if not args.no_save:\n        os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)\n",
          '''    writer, out_path, tmp_path = None, None, None
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
''')
r = ganti(r, '        if not args.no_save:\n            cv2.imwrite(f"{cfg.OUTPUT_DIR}/image_{idx:04d}.png", frame)\n',
          '        if writer is not None:\n            writer.write(frame)\n            if args.png:\n'
          '                cv2.imwrite(f"{cfg.OUTPUT_DIR}/image_{idx:04d}.png", frame)\n')
r = ganti(r, "    cap.release()\n",
          '''    cap.release()
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
        print(f"\\nVideo hasil disimpan: {out_path}")
''')
shutil.copy("run.py", "run.py.sebelum_video")
open("run.py", "w", encoding="utf-8").write(r)
print("SELESAI. Hasil sekarang disimpan sebagai satu video mp4 (bawaan: ~/projects/hasil/video/).")