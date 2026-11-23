#!/usr/bin/env python3
"""
crop_from_video.py - ambil potongan kendaraan dari hasil proses (video kamera sendiri) untuk melatih klasifier.

    cd ~/3d-vehicle-detection-counting
    ~/projects/venv_3dbbox/bin/python centernet3d_bbox/tools/crop_from_video.py data/results/manual/<JOB> [<JOB> ...]
atau pilih otomatis semua hasil satu kamera (hasil terbaru per video, status selesai):
    ~/projects/venv_3dbbox/bin/python centernet3d_bbox/tools/crop_from_video.py --node kamera_2_jalan_balige \
        --dari 20261122_1409 --sampai 20261122_1438

Untuk tiap JOB (folder di data/results/...): video, kalibrasi (profil.json), dan cache deteksinya dipakai lagi,
jadi cepat dan potongannya sama persis dengan yang dilihat klasifier saat sistem berjalan.
Dari tiap kendaraan (ID track) diambil paling banyak --per-id potongan terbesar yang saling berjauhan waktunya.
Kendaraan dibagi utuh ke train/val (80/20 menurut ID), supaya satu kendaraan tidak muncul di keduanya.

Keluaran: ~/dataset_lokal/potongan/{train,val}/belum_dipilah/<job>_id<ID>_f<frame>.jpg
Lalu pilah ke kelas dengan:  python3 centernet3d_bbox/tools/sort_crops.py ~/dataset_lokal/potongan
"""
import argparse
import glob
import hashlib
import json
import os
import re
import runpy
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PIPELINE = os.path.join(ROOT, "centernet3d_bbox", "pipeline")


def jalankan_pipeline(job, folder_crop):
    st = json.load(open(os.path.join(job, "status.json"), encoding="utf-8"))
    kecil = glob.glob(os.path.join(job, "masukan_*p.mp4"))      # salinan 1280x720 yang dibuat saat proses
    video, cache = (kecil[0] if kecil else st["masukan"]), st["cache"]
    model = os.path.join(ROOT, "data", "weights", "detector", st["model"])
    s = st.get("setelan", {})
    if not os.path.exists(video):
        raise SystemExit("Video tidak ada: " + video)
    if not os.path.exists(cache):
        raise SystemExit("Cache deteksi tidak ada (proses dulu di web): " + cache)
    os.environ["PROFIL_KAMERA"] = os.path.join(job, "profil.json")
    sys.path.insert(0, PIPELINE)
    os.chdir(folder_crop)                          # counting_log.csv dsb. jatuh di folder sementara
    import image_classifier as ic
    asli = ic.KlasifierGambar.perbarui

    def perbarui_tanpa_batas(self, *a, **k):      # bawaan hanya menyimpan 400 potongan
        self._n_simpan = 0
        return asli(self, *a, **k)
    ic.KlasifierGambar.perbarui = perbarui_tanpa_batas
    sys.argv = ["run.py", video, model, "--no-show", "--no-save", "--play", "--cache", cache,
                "--conf", str(s.get("conf", 0.4)), "--simpan-crop", folder_crop]
    if s.get("conf_low", 0) and s["conf_low"] < s.get("conf", 0.4):
        sys.argv += ["--conf-low", str(s["conf_low"])]
    runpy.run_path(os.path.join(PIPELINE, "run.py"), run_name="__main__")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("job", nargs="*", help="folder hasil proses, mis. data/results/manual/20261123-092522-ab95")
    p.add_argument("--node", help="ambil semua hasil proses kamera ini (terbaru per video)")
    p.add_argument("--dari", default="", help="nama video mulai, mis. 20261122_1409 (dibandingkan sebagai teks)")
    p.add_argument("--sampai", default="~", help="nama video sampai, mis. 20261122_1438")
    p.add_argument("--keluar", default=os.path.expanduser("~/dataset_lokal/potongan"))
    p.add_argument("--per-id", type=int, default=4, help="potongan maksimum per kendaraan")
    p.add_argument("--sisi-min", type=int, default=48, help="sisi terpanjang minimum (piksel)")
    p.add_argument("--val", type=float, default=0.2, help="bagian kendaraan untuk validasi")
    a = p.parse_args()
    import cv2

    if a.node:
        akhir = {}
        for f in sorted(glob.glob(os.path.join(ROOT, "data", "results", "*", "*", "status.json"))):
            st = json.load(open(f, encoding="utf-8"))
            v = os.path.basename(st.get("masukan", ""))
            if st.get("node") == a.node and st.get("status") == "selesai" and a.dari <= v[:len(a.dari)] and \
                    v[:len(a.sampai)] <= a.sampai:
                lama = akhir.get(v)
                if lama is None or st.get("dibuat", "") >= lama[0]:
                    akhir[v] = (st.get("dibuat", ""), os.path.dirname(f))
        a.job += [d for _, d in akhir.values()]
        for v in sorted(akhir):
            print("dipakai: %s  (%s)" % (v, os.path.basename(akhir[v][1])))
    if not a.job:
        sys.exit("Tidak ada hasil proses yang cocok (sudah selesai diproses?).")
    print("%d hasil proses\n" % len(a.job))

    for job in a.job:
        job = os.path.abspath(job)
        nama_job = os.path.basename(job.rstrip("/"))
        sementara = tempfile.mkdtemp(prefix="potong_")
        pid = os.fork()                           # tiap job di proses terpisah (config dimuat per kamera)
        if pid == 0:
            try:
                sys.stdout = sys.stderr = open(os.devnull, "w")
                jalankan_pipeline(job, sementara)
            finally:
                os._exit(0)
        os.waitpid(pid, 0)
        per_id = {}
        for f in glob.glob(os.path.join(sementara, "f*_id*.jpg")):
            m = re.match(r"f(\d+)_id(\d+)\.jpg$", os.path.basename(f))
            if not m:
                continue
            im = cv2.imread(f)
            if im is None or max(im.shape[:2]) < a.sisi_min:
                continue
            per_id.setdefault(int(m.group(2)), []).append((int(m.group(1)), max(im.shape[:2]), f))
        n_simpan = {"train": 0, "val": 0}
        for i, daftar in per_id.items():
            daftar.sort()
            # pilih yang terbesar, tapi berjarak minimal 1/per_id panjang track
            jarak = max(1, (daftar[-1][0] - daftar[0][0]) // max(1, a.per_id))
            pilih = []
            for fr, sisi, f in sorted(daftar, key=lambda t: -t[1]):
                if all(abs(fr - q[0]) >= jarak for q in pilih):
                    pilih.append((fr, sisi, f))
                if len(pilih) >= a.per_id:
                    break
            h = int(hashlib.md5(("%s_%d" % (nama_job, i)).encode()).hexdigest(), 16) % 100
            split = "val" if h < a.val * 100 else "train"
            tujuan = os.path.join(a.keluar, split, "belum_dipilah")
            os.makedirs(tujuan, exist_ok=True)
            for fr, _, f in pilih:
                shutil.copy2(f, os.path.join(tujuan, "%s_id%d_f%06d.jpg" % (nama_job, i, fr)))
                n_simpan[split] += 1
        shutil.rmtree(sementara, ignore_errors=True)
        print("%s: %d kendaraan -> %d potongan latih, %d validasi" % (nama_job, len(per_id), n_simpan["train"], n_simpan["val"]))
    print("\nSelanjutnya pilah ke kelas:\n  python3 centernet3d_bbox/tools/sort_crops.py " + a.keluar)


if __name__ == "__main__":
    main()
