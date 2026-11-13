#!/usr/bin/env python3
"""rapikan_folder.py - merapikan ~/projects dan ~/dataset_publik.

Bawaan: HANYA menampilkan rencana (tidak memindah apa pun).
    python3 rapikan_folder.py              # lihat rencana
    python3 rapikan_folder.py --jalankan   # pindahkan sungguhan
    python3 rapikan_folder.py --batalkan   # kembalikan seperti semula

Tidak ada berkas yang dihapus kecuali __pycache__ (dibuat ulang otomatis oleh Python).
Yang TIDAK disentuh: 3d-car-classification-counting (repo utama), venv_3dbbox,
data_session0_right (dirujuk banyak skrip), video_uji, dataset_klasifikasi, mio_tcd.
Path di dalam skrip yang menunjuk berkas yang dipindah ikut diperbarui (cadangan disimpan).
"""
import glob, json, os, re, shutil, sys

HOME = os.path.expanduser("~")
P, D = "projects", "dataset_publik"
CATATAN = os.path.join(HOME, P, ".rapikan_catatan.json")
CADANGAN = os.path.join(HOME, P, ".rapikan_cadangan")

# (asal, tujuan) relatif terhadap HOME; pola glob boleh di asal (tujuan = folder)
RENCANA = [
    # bobot
    (P + "/centernet*.pth", P + "/bobot/detektor/"),
    (D + "/hasil_klasifikasi/klas*.pth", P + "/bobot/klasifikasi/"),
    # kode latihan/evaluasi detektor (saling impor, harus satu folder)
    *[(P + "/" + n, P + "/latih_detektor/") for n in (
        "train_session0_right.py", "kamera.py", "target.py", "dekode.py", "evaluasi.py", "prediksi.py",
        "analisis_galat.py", "cek_target.py", "ukur_waktu.py", "notebook_kode.py", "progres.sh")],
    # alat sekali pakai
    (P + "/pasang_*.py", P + "/alat/"),
    (P + "/hitung_gt.py", P + "/alat/"),
    (P + "/cek_kalibrasi.py", P + "/alat/"),
    # hasil
    (P + "/logs", P + "/hasil/log_latih_detektor"),
    (P + "/prediksi", P + "/hasil/prediksi_detektor"),
    (P + "/kalibrasi.png", P + "/hasil/gambar/"),
    (P + "/uji_session0_pipeline/lembar_*.png", P + "/hasil/gambar/"),
    # acuan
    (P + "/3d_bbox_highway", P + "/acuan/3d_bbox_highway"),
    # dataset_publik
    (D + "/*.py", D + "/kode/"),
    (D + "/progres_klas.sh", D + "/kode/"),
    (D + "/*_stdout.txt", D + "/hasil_klasifikasi/log/"),
    (D + "/contoh_dataset.png", D + "/hasil_klasifikasi/"),
    (D + "/hasil_klasifikasi/uji*", D + "/hasil_klasifikasi/uji_coba/"),
]
SALIN = [  # disalin (bukan dipindah) karena pipeline menulis ulang berkas ini tiap jalan
    (P + "/uji_session0_pipeline/counting_log.csv", P + "/hasil/counting/"),
    (P + "/uji_session0_pipeline/gt_hitung.csv", P + "/hasil/counting/"),
]
HAPUS = [P + "/__pycache__"]

README = """# Peta folder ~/projects

| Folder | Isi |
|---|---|
| 3d-car-classification-counting/ | REPO UTAMA pipeline (untuk kamera sendiri) |
| uji_session0_pipeline/ | salinan repo untuk latihan dengan data session0_right: kalibrasi, klasifier gambar 4 kelas, dua garis counting |
| bobot/detektor/ | bobot CenterNet (.pth); yang dipakai: centernet_dari_baru.pth |
| bobot/klasifikasi/ | bobot klasifier gambar 4 kelas; yang dipakai: klas_ft2.pth |
| latih_detektor/ | kode latihan dan evaluasi detektor (train_session0_right.py, evaluasi.py, ...) |
| alat/ | skrip bantu: hitung_gt.py (evaluasi counting), pasang_*.py (patch), cek_kalibrasi.py |
| data_session0_right/ | data acuan latihan: images, annotations, calib |
| video_uji/ | video uji dan cache deteksi |
| hasil/ | log latihan, prediksi, gambar, hasil counting |
| acuan/3d_bbox_highway/ | proyek asal (antoinekeller) sebagai rujukan |
| venv_3dbbox/ | lingkungan Python |

Data dan kode klasifikasi (MIO-TCD) ada di ~/dataset_publik: dataset_klasifikasi/, uji_session0_right/, kode/, hasil_klasifikasi/.

Jalankan pipeline latihan:
  cd ~/projects/uji_session0_pipeline
  python3 run.py ~/projects/video_uji/uji_val_720p.mp4 ~/projects/bobot/detektor/centernet_dari_baru.pth --cache ~/projects/video_uji/det_session0.pkl --conf 0.4 --conf-low 0.2 --no-show --no-save
  python3 ~/projects/alat/hitung_gt.py --first 2545 --last 3181 --line 50 --log counting_log.csv
"""


def susun():
    """Daftar (asal_abs, tujuan_abs) yang nyata ada."""
    out, seen = [], set()
    for asal, tujuan in RENCANA:
        for src in sorted(glob.glob(os.path.join(HOME, asal))):
            if src in seen:
                continue
            dst = os.path.join(HOME, tujuan)
            if tujuan.endswith("/"):
                if os.path.abspath(src) == os.path.abspath(dst.rstrip("/")):
                    continue
                dst = os.path.join(dst, os.path.basename(src))
            seen.add(src)
            out.append((src, dst))
    return out


def berkas_teks(moves):
    """Skrip yang path di dalamnya perlu diperiksa (lokasi SETELAH dipindah bila ikut pindah)."""
    peta = dict(moves)
    cand = []
    for pola in (P + "/*.py", P + "/*.sh", P + "/uji_session0_pipeline/*.py", P + "/uji_session0_pipeline/tools/*.py",
                 D + "/*.py", D + "/*.sh"):
        cand += glob.glob(os.path.join(HOME, pola))
    return sorted(set(cand)), peta


def tulis_ulang(teks, moves):
    """Ganti rujukan 'projects/x' -> lokasi baru. Mengembalikan (teks_baru, daftar perubahan)."""
    ubah = []
    for src, dst in sorted(moves, key=lambda m: -len(m[0])):
        lama, baru = os.path.relpath(src, HOME), os.path.relpath(dst, HOME)
        pat = re.compile(re.escape(lama) + r"(?![A-Za-z0-9_.\-])")
        if pat.search(teks):
            teks = pat.sub(lambda m: baru, teks)
            ubah.append((lama, baru))
    return teks, ubah


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "--batalkan":
        if not os.path.exists(CATATAN):
            sys.exit("Tidak ada catatan; tidak ada yang dibatalkan.")
        cat = json.load(open(CATATAN))
        for src, dst in reversed(cat["pindah"]):
            if os.path.exists(dst):
                os.makedirs(os.path.dirname(src), exist_ok=True)
                shutil.move(dst, src)
        for asli, cad in cat["cadangan"]:
            shutil.copy(cad, asli)
        for f in cat["baru"]:
            if os.path.isfile(f):
                os.remove(f)
        for d in sorted(cat["folder_baru"], key=len, reverse=True):
            try:
                os.removedirs(d)
            except OSError:
                pass
        os.remove(CATATAN)
        print("Dikembalikan seperti semula.")
        return
    jalan = mode == "--jalankan"
    if jalan and os.path.exists(CATATAN):
        sys.exit("Sudah pernah dijalankan (ada .rapikan_catatan.json). Pakai --batalkan dulu bila ingin mengulang.")

    moves = susun()
    bentrok = [d for _, d in moves if os.path.exists(d)]
    if bentrok:
        sys.exit("BERHENTI: tujuan sudah ada:\n  " + "\n  ".join(bentrok))
    print("=== RENCANA PEMINDAHAN (%d) ===" % len(moves))
    for s, d in moves:
        print("  %-62s -> %s" % (os.path.relpath(s, HOME), os.path.relpath(d, HOME)))
    print("=== DISALIN ===")
    for a, t in SALIN:
        if os.path.exists(os.path.join(HOME, a)):
            print("  %-62s -> %s" % (a, t))
    print("=== DIHAPUS (dibuat ulang otomatis) ===")
    for h in HAPUS:
        if os.path.exists(os.path.join(HOME, h)):
            print("  " + h)

    files, peta = berkas_teks(moves)
    rewrites, sisa = [], []
    nama_pindah = {os.path.basename(s) for s, _ in moves}
    for f in files:
        try:
            t = open(f, encoding="utf-8").read()
        except (UnicodeDecodeError, IsADirectoryError):
            continue
        if os.path.basename(f) == "rapikan_folder.py":
            continue
        baru, ubah = tulis_ulang(t, moves)
        if ubah:
            rewrites.append((f, baru, ubah))
        for i, ln in enumerate(baru.split("\n"), 1):     # rujukan relatif yang tidak ikut terganti
            for n in nama_pindah:
                if re.search(r"(?<![A-Za-z0-9_/.\-])" + re.escape(n) + r"(?![A-Za-z0-9_])", ln) and ("/" + n) not in ln \
                        and not ln.lstrip().startswith(("#", "import ", "from ")) and n not in ("logs", "prediksi", "uji", "uji48"):
                    sisa.append("%s:%d: %s" % (os.path.relpath(f, HOME), i, ln.strip()[:110]))
    print("=== PATH DI DALAM SKRIP YANG DIPERBARUI ===")
    for f, _, ubah in rewrites:
        for a, b in ubah:
            print("  %s: %s -> %s" % (os.path.relpath(f, HOME), a, b))
    print("=== RUJUKAN RELATIF (TIDAK diubah; hanya untuk diperiksa) ===")
    for s in sorted(set(sisa))[:40]:
        print("  " + s)

    if not jalan:
        print("\nBelum ada yang dipindah. Jalankan dengan --jalankan bila rencana ini sudah benar.")
        return

    cat = {"pindah": [], "cadangan": [], "baru": [], "folder_baru": []}

    def buat(d):
        baru, x = [], d
        while x and not os.path.exists(x):
            baru.append(x)
            x = os.path.dirname(x)
        os.makedirs(d, exist_ok=True)
        cat["folder_baru"] += baru

    buat(CADANGAN)
    for i, (f, baru, _) in enumerate(rewrites):          # tulis ulang dulu (di lokasi lama), baru pindah
        cad = os.path.join(CADANGAN, "%03d_%s" % (i, os.path.basename(f)))
        shutil.copy(f, cad)
        cat["cadangan"].append((f, cad))
        open(f, "w", encoding="utf-8").write(baru)
    for s, d in moves:
        buat(os.path.dirname(d))
        shutil.move(s, d)
        cat["pindah"].append((s, d))
    for a, t in SALIN:
        s = os.path.join(HOME, a)
        if os.path.exists(s):
            buat(os.path.join(HOME, t).rstrip("/"))
            d = os.path.join(HOME, t, os.path.basename(s))
            shutil.copy(s, d)
            cat["baru"].append(d)
    for h in HAPUS:
        shutil.rmtree(os.path.join(HOME, h), ignore_errors=True)
    rd = os.path.join(HOME, P, "README.md")
    if not os.path.exists(rd):
        open(rd, "w", encoding="utf-8").write(README)
        cat["baru"].append(rd)
    # cadangan menunjuk lokasi lama; setelah pindah, catat lokasi baru agar --batalkan benar
    json.dump(cat, open(CATATAN, "w"), indent=1)
    print("\nSELESAI. Peta folder: ~/projects/README.md. Batalkan dengan: python3 %s --batalkan" % os.path.basename(sys.argv[0]))


if __name__ == "__main__":
    main()