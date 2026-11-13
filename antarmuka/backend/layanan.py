"""
layanan.py - logika antarmuka: mengelola pekerjaan (job) yang menjalankan pipeline run.py
dan meringkas hasilnya. Tidak bergantung pada FastAPI, sehingga bisa diuji sendiri.

Satu job = satu video diproses. Job dijalankan SATU per satu (antrean), karena run.py
menulis counting_log.csv di folder pipeline dan mesin ini tanpa GPU.

Folder tiap job: ~/projects/hasil/antarmuka/<id>/
    status.json        keadaan job (antre/proses/selesai/gagal, progres, setelan)
    hasil.mp4          video dengan kotak 3D
    counting_log.csv   satu baris per kendaraan yang dihitung
    ringkasan.json     hitungan per kelas, per arah, per rentang waktu
    keluaran.txt       keluaran terminal run.py (untuk mencari penyebab bila gagal)
"""

import csv
import importlib.util
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time

PROYEK = os.path.expanduser(os.environ.get("ANTARMUKA_PROYEK", "~/projects"))
PIPELINE = os.environ.get("ANTARMUKA_PIPELINE", os.path.join(PROYEK, "uji_session0_pipeline"))
DATA = os.path.join(PROYEK, "hasil", "antarmuka")
VIDEO_DIR = os.path.join(PROYEK, "video_uji")
MODEL = os.environ.get("ANTARMUKA_MODEL", os.path.join(PROYEK, "bobot", "detektor", "centernet_dari_baru.pth"))
PYTHON = sys.executable
EKSTENSI = (".mp4", ".avi", ".mov", ".mkv")
MAKS_UNGGAH = 500 * 1024 * 1024          # byte
CACHE_KHUSUS = {"uji_val_720p.mp4": "det_session0.pkl"}   # cache deteksi yang sudah ada
ID_SAH = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
POLA_PROGRES = re.compile(rb"(\d+)/(\d+) \[")              # baris progres tqdm

_kunci = threading.Lock()
_jobs = {}                 # id -> status (dict)
_antrean = queue.Queue()
_pekerja = None


def _muat_config():
    spec = importlib.util.spec_from_file_location("config_pipeline", os.path.join(PIPELINE, "config.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cfg = _muat_config()


def _hex(bgr):
    b, g, r = bgr
    return "#%02x%02x%02x" % (r, g, b)


def daftar_video():
    out = []
    if os.path.isdir(VIDEO_DIR):
        for n in sorted(os.listdir(VIDEO_DIR)):
            if n.lower().endswith(EKSTENSI):
                out.append({"nama": n, "ada_cache": os.path.exists(_jalur_cache(os.path.join(VIDEO_DIR, n)))})
    return out


def info():
    run_py = open(os.path.join(PIPELINE, "run.py"), encoding="utf-8").read()
    masalah = []
    if '"--out"' not in run_py:
        masalah.append("run.py belum bisa menyimpan video (jalankan alat/pasang_video.py di folder pipeline).")
    if not os.path.exists(MODEL):
        masalah.append("Bobot detektor tidak ada: " + MODEL)
    if not shutil.which("ffmpeg"):
        masalah.append("ffmpeg belum terpasang; video hasil mungkin tidak bisa diputar di peramban (sudo apt install ffmpeg).")
    warna = getattr(cfg, "CLASS_COLORS", {})
    return {
        "kelas": [{"nama": c, "warna": _hex(warna.get(c, (200, 200, 200)))} for c in cfg.CLASSES],
        "bawaan": {"conf": 0.4, "conf_low": 0.2, "line_y": cfg.LINE_Y_DEFAULT_M,
                   "line_y_away": getattr(cfg, "LINE_Y_AWAY_M", cfg.LINE_Y_DEFAULT_M)},
        "median_x": getattr(cfg, "MEDIAN_X_M", None),
        "video": daftar_video(),
        "model": os.path.basename(MODEL),
        "masalah": masalah,
    }


# ------------------------------------------------------------------ penyimpanan status
def _folder(job_id):
    return os.path.join(DATA, job_id)


def _simpan(st):
    tmp = os.path.join(_folder(st["id"]), "status.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(_folder(st["id"]), "status.json"))


def _ubah(job_id, **kw):
    with _kunci:
        st = _jobs[job_id]
        st.update(kw)
        _simpan(st)


def muat_dari_disk():
    """Dipanggil saat server mulai: baca job lama; job yang terputus ditandai gagal."""
    os.makedirs(DATA, exist_ok=True)
    with _kunci:
        for n in sorted(os.listdir(DATA)):
            p = os.path.join(DATA, n, "status.json")
            if not ID_SAH.match(n) or not os.path.exists(p):
                continue
            st = json.load(open(p, encoding="utf-8"))
            if st.get("status") in ("antre", "proses"):
                st.update(status="gagal", pesan="Server dimulai ulang saat video ini sedang diproses.")
                _jobs[n] = st
                _simpan(st)
            _jobs[n] = st


def daftar_job():
    with _kunci:
        return sorted((dict(s) for s in _jobs.values()), key=lambda s: s["id"], reverse=True)


def ambil_job(job_id):
    with _kunci:
        st = _jobs.get(job_id)
        if st is None:
            return None
        st = dict(st)
    p = os.path.join(_folder(job_id), "ringkasan.json")
    if st["status"] == "selesai" and os.path.exists(p):
        st["ringkasan"] = json.load(open(p, encoding="utf-8"))
    return st


def jalur_berkas(job_id, nama):
    """Jalur berkas hasil milik job (hanya nama yang diizinkan), atau None."""
    if not ID_SAH.match(job_id) or nama not in ("hasil.mp4", "counting_log.csv", "keluaran.txt"):
        return None
    p = os.path.join(_folder(job_id), nama)
    return p if os.path.exists(p) else None


def hapus_job(job_id):
    with _kunci:
        st = _jobs.get(job_id)
        if st is None:
            return "tidak ada"
        if st["status"] in ("antre", "proses"):
            return "sedang berjalan"
        del _jobs[job_id]
    shutil.rmtree(_folder(job_id), ignore_errors=True)
    return "ok"


# ------------------------------------------------------------------ membuat job
def _angka(nilai, bawaan, lo, hi):
    try:
        v = float(nilai)
    except (TypeError, ValueError):
        return bawaan
    return min(max(v, lo), hi)


def buat_job(nama_video=None, unggahan=None, nama_unggahan=None, setelan=None):
    """
    nama_video : nama berkas di folder video_uji, ATAU
    unggahan   : objek berkas (punya .read(n)) + nama_unggahan.
    Mengembalikan status job. ValueError bila masukan tidak sah.
    """
    setelan = setelan or {}
    b = info()["bawaan"]
    s = {
        "conf": _angka(setelan.get("conf"), b["conf"], 0.05, 0.95),
        "conf_low": _angka(setelan.get("conf_low"), b["conf_low"], 0.0, 0.9),
        "line_y": _angka(setelan.get("line_y"), b["line_y"], 5.0, 200.0),
        "line_y_away": _angka(setelan.get("line_y_away"), b["line_y_away"], 5.0, 200.0),
    }
    if s["conf_low"] >= s["conf"]:
        raise ValueError("Ambang rendah harus lebih kecil dari ambang deteksi (atau 0 untuk mematikan).")

    job_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
    os.makedirs(_folder(job_id))
    try:
        if unggahan is not None:
            eks = os.path.splitext(nama_unggahan or "")[1].lower()
            if eks not in EKSTENSI:
                raise ValueError("Jenis berkas tidak didukung. Pakai: " + ", ".join(EKSTENSI))
            jalur = os.path.join(_folder(job_id), "masukan" + eks)
            total = 0
            with open(jalur, "wb") as f:
                while True:
                    potong = unggahan.read(1024 * 1024)
                    if not potong:
                        break
                    total += len(potong)
                    if total > MAKS_UNGGAH:
                        raise ValueError("Berkas terlalu besar (maksimum %d MB)." % (MAKS_UNGGAH // 1024 // 1024))
                    f.write(potong)
            if total == 0:
                raise ValueError("Berkas kosong.")
            nama, cache = os.path.basename(nama_unggahan), os.path.join(_folder(job_id), "deteksi.pkl")
        else:
            if nama_video not in [v["nama"] for v in daftar_video()]:
                raise ValueError("Video tidak ditemukan di folder video_uji.")
            jalur = os.path.join(VIDEO_DIR, nama_video)
            nama, cache = nama_video, _jalur_cache(jalur)
    except Exception:
        shutil.rmtree(_folder(job_id), ignore_errors=True)
        raise

    st = {"id": job_id, "nama_video": nama, "dibuat": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "antre",
          "tahap": "Menunggu giliran", "progres": 0.0, "setelan": s, "masukan": jalur, "cache": cache, "pesan": ""}
    with _kunci:
        _jobs[job_id] = st
        _simpan(st)
    _mulai_pekerja()
    _antrean.put(job_id)
    return dict(st)


def _jalur_cache(jalur_video):
    khusus = CACHE_KHUSUS.get(os.path.basename(jalur_video))
    if khusus and os.path.exists(os.path.join(os.path.dirname(jalur_video), khusus)):
        return os.path.join(os.path.dirname(jalur_video), khusus)
    return jalur_video + ".det.pkl"


# ------------------------------------------------------------------ menjalankan pipeline
def _mulai_pekerja():
    global _pekerja
    with _kunci:
        if _pekerja is None or not _pekerja.is_alive():
            _pekerja = threading.Thread(target=_putaran, daemon=True)
            _pekerja.start()


def _putaran():
    while True:
        job_id = _antrean.get()
        try:
            _kerjakan(job_id)
        except Exception as e:                      # jangan sampai pekerja mati
            try:
                _ubah(job_id, status="gagal", tahap="Gagal", pesan="Galat internal: %s" % e)
            except Exception:
                pass


def _siapkan_video(job_id, jalur):
    """Pastikan video berukuran IMG_W x IMG_H; bila tidak, buat salinan yang diubah ukurannya."""
    import cv2
    cap = cv2.VideoCapture(jalur)
    if not cap.isOpened():
        raise RuntimeError("Video tidak bisa dibuka.")
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n, fps = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), cap.get(cv2.CAP_PROP_FPS)
    fps = fps if fps and fps > 1 else 25.0
    if (w, h) == (cfg.IMG_W, cfg.IMG_H):
        cap.release()
        return jalur, n, fps
    _ubah(job_id, tahap="Mengubah ukuran video ke %dx%d" % (cfg.IMG_W, cfg.IMG_H))
    baru = os.path.join(_folder(job_id), "masukan_%dp.mp4" % cfg.IMG_H)
    out = cv2.VideoWriter(baru, cv2.VideoWriter_fourcc(*"mp4v"), fps, (cfg.IMG_W, cfg.IMG_H))
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        out.write(cv2.resize(fr, (cfg.IMG_W, cfg.IMG_H), interpolation=cv2.INTER_AREA))
        i += 1
        if i % 25 == 0 and n:
            _ubah(job_id, progres=round(0.1 * i / n, 3))
    cap.release()
    out.release()
    return baru, i, fps


def _kerjakan(job_id):
    st = ambil_job(job_id)
    if st is None:
        return
    folder, s = _folder(job_id), st["setelan"]
    _ubah(job_id, status="proses", tahap="Menyiapkan video", mulai=time.time())
    try:
        video, n_frame, fps = _siapkan_video(job_id, st["masukan"])
    except Exception as e:
        _ubah(job_id, status="gagal", tahap="Gagal", pesan=str(e))
        return
    pakai_cache = os.path.exists(st["cache"])
    _ubah(job_id, frame_total=n_frame, fps=fps,
          tahap="Melacak dan menghitung (deteksi dari cache)" if pakai_cache else "Mendeteksi kendaraan (tanpa GPU, lambat)")

    cmd = [PYTHON, "run.py", video, MODEL, "--no-show", "--out", os.path.join(folder, "hasil.mp4"),
           "--cache", st["cache"], "--conf", str(s["conf"]),
           "--line-y", str(s["line_y"]), "--line-y-away", str(s["line_y_away"])]
    if s["conf_low"] > 0:
        cmd += ["--conf-low", str(s["conf_low"])]
    cmd += os.environ.get("ANTARMUKA_ARG_TAMBAHAN", "").split()   # mis. --tanpa-gambar
    log = open(os.path.join(folder, "keluaran.txt"), "wb")
    p = subprocess.Popen(cmd, cwd=PIPELINE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    baris, terakhir = b"", 0.0
    while True:
        c = p.stdout.read(1)
        if not c:
            break
        if c in (b"\r", b"\n"):
            m = POLA_PROGRES.search(baris)
            if m and int(m.group(2)) > 0:
                if time.time() - terakhir > 0.5:
                    terakhir = time.time()
                    _ubah(job_id, progres=round(0.1 + 0.85 * int(m.group(1)) / int(m.group(2)), 3))
            elif baris.strip():
                log.write(baris + b"\n")
                log.flush()
            baris = b""
        else:
            baris += c
    kode = p.wait()
    log.close()
    if kode != 0:
        ekor = open(os.path.join(folder, "keluaran.txt"), errors="replace").read()[-600:]
        _ubah(job_id, status="gagal", tahap="Gagal", pesan="Pipeline berhenti dengan galat:\n" + ekor)
        return
    try:
        shutil.copy(os.path.join(PIPELINE, cfg.COUNT_LOG), os.path.join(folder, "counting_log.csv"))
        r = ringkas(os.path.join(folder, "counting_log.csv"), fps, n_frame)
        json.dump(r, open(os.path.join(folder, "ringkasan.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception as e:
        _ubah(job_id, status="gagal", tahap="Gagal", pesan="Hasil tidak bisa dibaca: %s" % e)
        return
    st2 = ambil_job(job_id)
    _ubah(job_id, status="selesai", tahap="Selesai", progres=1.0, total=r["total"],
          lama_detik=round(time.time() - st2.get("mulai", time.time()), 1),
          ada_video=os.path.exists(os.path.join(folder, "hasil.mp4")))


# ------------------------------------------------------------------ ringkasan hasil
def ringkas(csv_path, fps, n_frame):
    """Ringkas counting_log.csv: per kelas, per arah, per rentang waktu, dan daftar kendaraan."""
    kelas = list(cfg.CLASSES)
    median = getattr(cfg, "MEDIAN_X_M", None)
    durasi = n_frame / fps if fps else 0.0
    langkah = next((x for x in (5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600) if durasi / x <= 12), 3600)
    n_bak = max(1, int(durasi // langkah) + (1 if durasi % langkah else 0))
    waktu = [{"mulai": i * langkah, **{c: 0 for c in kelas}} for i in range(n_bak)]
    per_kelas = {c: 0 for c in kelas}
    per_arah = {"mendekat": 0, "menjauh": 0}
    kendaraan = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            k = r["kelas"]
            if k not in per_kelas:
                continue
            fr, x = int(r["frame"]), float(r["x_m"])
            t = fr / fps if fps else 0.0
            arah = "menjauh" if (median is not None and x >= median) else "mendekat"
            per_kelas[k] += 1
            per_arah[arah] += 1
            waktu[min(int(t // langkah), n_bak - 1)][k] += 1
            skor = r.get("suara_" + k, "")
            kendaraan.append({"frame": fr, "detik": round(t, 2), "id": int(r["id"]), "kelas": k, "arah": arah,
                              "panjang_m": float(r["panjang_m"]), "x_m": x,
                              "skor": float(skor) if skor not in ("", None) else None})
    return {"total": len(kendaraan), "per_kelas": per_kelas, "per_arah": per_arah, "ada_arah": median is not None,
            "durasi_detik": round(durasi, 1), "langkah_detik": langkah, "per_waktu": waktu, "kendaraan": kendaraan}
