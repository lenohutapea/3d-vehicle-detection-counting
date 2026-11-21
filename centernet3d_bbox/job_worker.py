"""
job_worker.py - antrean pemrosesan video (dipakai alur Otomatis dan Manual).

Satu video diproses pipeline/run.py dalam satu waktu (antrean). Setiap job punya folder:
    data/results/<automatic|manual>/<job_id>/
        status.json, profil.json, result.mp4, counting_log.csv, summary.json, keluaran.txt
"automatic" = dipicu jadwal (2_automatic/auto_process.py), "manual" = dipilih di halaman Proses.
Isi ini berasal dari layanan.py lama (bagian 5. pekerjaan dan 6. ringkasan hasil).
"""
import csv
import os
import re
import secrets
import shutil
import subprocess
import threading
import time

import calibration
from settings import (HASIL, MODEL_DIR, NAMA_REKAMAN, PIPELINE, PYTHON, Salah, _angka, _antrean, _baca_json,
                      _cek_node, _jobs, _kunci, _sumber_video, _tulis_json, cfg, daftar_model, info, setelan)

ID_SAH = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
POLA_PROGRES = re.compile(rb"(\d+)/(\d+) \[")
CACHE_KHUSUS = {("uji_val_720p.mp4", "centernet_dari_baru.pth"): "det_session0.pkl"}   # cache deteksi yang sudah ada
JALUR = {"otomatis": "automatic", "manual": "manual"}
BERKAS = {"result.mp4": "result.mp4", "hasil.mp4": "result.mp4",          # hasil.mp4 = nama lama
          "counting_log.csv": "counting_log.csv", "keluaran.txt": "keluaran.txt"}
_pekerja = None


def _folder(job_id, jalur=None):
    if jalur is None:
        with _kunci:
            st = _jobs.get(job_id)
        jalur = st.get("jalur", "manual") if st else None
    if jalur is None:                       # belum dimuat: cari di kedua folder
        for j in JALUR.values():
            if os.path.isdir(os.path.join(HASIL, j, job_id)):
                return os.path.join(HASIL, j, job_id)
        jalur = "manual"
    return os.path.join(HASIL, JALUR.get(jalur, jalur), job_id)


def _simpan(st):
    _tulis_json(os.path.join(_folder(st["id"], st.get("jalur", "manual")), "status.json"), st)


def _ubah(job_id, **kw):
    with _kunci:
        st = _jobs[job_id]
        st.update(kw)
        _simpan(st)


def muat_dari_disk():
    """Saat server mulai: baca job lama; job yang terputus ditandai gagal."""
    setelan()
    with _kunci:
        for jalur, folder in JALUR.items():
            d = os.path.join(HASIL, folder)
            os.makedirs(d, exist_ok=True)
            for n in sorted(os.listdir(d)):
                st = _baca_json(os.path.join(d, n, "status.json"))
                if not ID_SAH.match(n) or not st:
                    continue
                st["jalur"] = jalur
                _jobs[n] = st
                if st.get("status") in ("antre", "proses"):
                    st.update(status="gagal", tahap="Gagal", pesan="Server dimulai ulang saat video ini sedang diproses.")
                    _simpan(st)


def _ringkas_status(st):
    return {k: st.get(k) for k in ("id", "nama_video", "sumber", "node", "model", "dibuat", "waktu_video", "status",
                                   "tahap", "progres", "total", "per_kelas", "pemicu", "jalur", "kalibrasi")}


def daftar_job():
    with _kunci:
        return sorted((_ringkas_status(s) for s in _jobs.values()), key=lambda s: s["id"], reverse=True)


def ambil_job(job_id):
    with _kunci:
        st = _jobs.get(job_id)
        if st is None:
            return None
        st = dict(st)
    if st["status"] == "selesai":
        st["ringkasan"] = _baca_json(os.path.join(_folder(job_id), "summary.json"))
    return st


def jalur_berkas(job_id, nama):
    if not ID_SAH.match(job_id) or nama not in BERKAS:
        return None
    p = os.path.join(_folder(job_id), BERKAS[nama])
    return p if os.path.exists(p) else None


def hapus_job(job_id):
    with _kunci:
        st = _jobs.get(job_id)
        if st is None:
            return "tidak ada"
        if st["status"] in ("antre", "proses"):
            return "sedang berjalan"
        folder = _folder(job_id)
        del _jobs[job_id]
    shutil.rmtree(folder, ignore_errors=True)
    return "ok"


def buat_job(sumber, node_id, model=None, conf=None, conf_low=None, pemicu=None, kalibrasi=None):
    """sumber: 'contoh/<nama>' atau 'rekaman/<node>/<nama>'. Profil kamera diambil dari node_id.
    kalibrasi: None = versi yang sedang dipakai node, "bawaan", atau nama versi dari riwayat.
    pemicu="otomatis" -> data/results/automatic, selain itu -> data/results/manual."""
    _cek_node(node_id)
    video = _sumber_video(sumber)
    model = model or (daftar_model() or [None])[0]
    if model not in daftar_model():
        raise Salah("Bobot model tidak ditemukan: %s" % model)
    b = info()["bawaan"]
    s = {"conf": _angka(conf, b["conf"], 0.05, 0.95), "conf_low": _angka(conf_low, b["conf_low"], 0.0, 0.9)}
    if s["conf_low"] >= s["conf"]:
        raise Salah("Ambang rendah harus lebih kecil dari ambang deteksi (atau 0 untuk mematikan).")
    p = calibration.profil_versi(node_id, kalibrasi)
    if p["mode"] == "xml" and not p["ada_xml"]:
        raise Salah("Profil kamera %s memakai berkas kalibrasi yang tidak ada. Buka halaman Kalibrasi." % node_id)

    jalur = "otomatis" if pemicu == "otomatis" else "manual"
    m = NAMA_REKAMAN.match(os.path.basename(video))
    if m:
        t, j = m.group(1), m.group(2)
        waktu_video = "%s-%s-%s %s:%s:%s" % (t[:4], t[4:6], t[6:], j[:2], j[2:4], j[4:])
        pemicu = pemicu or m.group(3)
    else:
        waktu_video = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(video)))
        pemicu = pemicu or "contoh"
    job_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
    folder = _folder(job_id, jalur)
    os.makedirs(folder)
    _tulis_json(os.path.join(folder, "profil.json"), calibration.profil_pipeline(p))
    st = {"id": job_id, "nama_video": os.path.basename(video), "sumber": sumber, "node": node_id, "model": model,
          "dibuat": time.strftime("%Y-%m-%d %H:%M:%S"), "waktu_video": waktu_video, "pemicu": pemicu, "jalur": jalur,
          "status": "antre", "tahap": "Menunggu giliran", "progres": 0.0, "setelan": s,
          "kalibrasi": {"sumber": p["sumber_profil"], "versi": p["versi"]},
          "garis": {"mendekat": p["LINE_Y_DEFAULT_M"], "menjauh": p["LINE_Y_AWAY_M"], "median": p["MEDIAN_X_M"],
                    "lajur": p.get("LAJUR", "kiri")},
          "masukan": video, "cache": _jalur_cache(video, model), "pesan": ""}
    with _kunci:
        _jobs[job_id] = st
        _simpan(st)
    _mulai_pekerja()
    _antrean.put(job_id)
    return dict(st)


def _jalur_cache(video, model):
    """Cache deteksi bergantung pada video DAN model, jadi nama model ikut di nama berkas."""
    khusus = CACHE_KHUSUS.get((os.path.basename(video), model))
    if khusus and os.path.exists(os.path.join(os.path.dirname(video), khusus)):
        return os.path.join(os.path.dirname(video), khusus)
    return "%s.%s.det.pkl" % (video, os.path.splitext(model)[0])


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
        except Exception as e:
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
    if not os.path.exists(st["masukan"]):
        _ubah(job_id, status="gagal", tahap="Gagal", pesan="Berkas video sudah tidak ada.")
        return
    try:
        video, n_frame, fps = _siapkan_video(job_id, st["masukan"])
    except Exception as e:
        _ubah(job_id, status="gagal", tahap="Gagal", pesan=str(e))
        return
    pakai_cache = os.path.exists(st["cache"])
    _ubah(job_id, frame_total=n_frame, fps=fps,
          tahap="Melacak dan menghitung (deteksi dari cache)" if pakai_cache else "Mendeteksi kendaraan (tanpa GPU, lambat)")

    cmd = [PYTHON, "run.py", video, os.path.join(MODEL_DIR, st["model"]), "--no-show",
           "--out", os.path.join(folder, "result.mp4"), "--cache", st["cache"], "--conf", str(s["conf"])]
    if s["conf_low"] > 0:
        cmd += ["--conf-low", str(s["conf_low"])]
    cmd += os.environ.get("ANTARMUKA_ARG_TAMBAHAN", "").split()   # mis. --tanpa-gambar
    env = dict(os.environ, PROFIL_KAMERA=os.path.join(folder, "profil.json"))
    log = open(os.path.join(folder, "keluaran.txt"), "wb")
    p = subprocess.Popen(cmd, cwd=PIPELINE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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
        r = ringkas(os.path.join(folder, "counting_log.csv"), fps, n_frame, st["garis"]["median"],
                    st["garis"].get("lajur", "kanan"))
        _tulis_json(os.path.join(folder, "summary.json"), r)
    except Exception as e:
        _ubah(job_id, status="gagal", tahap="Gagal", pesan="Hasil tidak bisa dibaca: %s" % e)
        return
    st2 = ambil_job(job_id)
    _ubah(job_id, status="selesai", tahap="Selesai", progres=1.0, total=r["total"], per_kelas=r["per_kelas"],
          lama_detik=round(time.time() - st2.get("mulai", time.time()), 1),
          ada_video=os.path.exists(os.path.join(folder, "result.mp4")))


def ringkas(csv_path, fps, n_frame, median=None, lajur="kiri"):
    """Ringkas counting_log.csv: per kelas, per arah, per rentang waktu, dan daftar kendaraan.
    lajur "kiri" (Indonesia): kiri median = menjauh; "kanan": kanan median = menjauh."""
    kelas = list(cfg.CLASSES)
    durasi = n_frame / fps if fps else 0.0
    langkah = next((x for x in (5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600) if durasi / x <= 12), 3600)
    n_bak = max(1, int(durasi // langkah) + (1 if durasi % langkah else 0))
    waktu = [dict({"mulai": i * langkah}, **{c: 0 for c in kelas}) for i in range(n_bak)]
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
            kanan = median is not None and x >= median
            arah = "menjauh" if (kanan if lajur == "kanan" else (median is not None and not kanan)) else "mendekat"
            per_kelas[k] += 1
            per_arah[arah] += 1
            waktu[min(int(t // langkah), n_bak - 1)][k] += 1
            skor = r.get("suara_" + k, "")
            kendaraan.append({"frame": fr, "detik": round(t, 2), "id": int(r["id"]), "kelas": k, "arah": arah,
                              "panjang_m": float(r["panjang_m"]), "x_m": x,
                              "skor": float(skor) if skor not in ("", None) else None})
    return {"total": len(kendaraan), "per_kelas": per_kelas, "per_arah": per_arah, "ada_arah": median is not None,
            "durasi_detik": round(durasi, 1), "langkah_detik": langkah, "per_waktu": waktu, "kendaraan": kendaraan}
