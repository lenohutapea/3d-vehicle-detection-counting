#!/usr/bin/env python3
"""
buat_notebook_lengkap.py - menyusun SATU notebook berisi seluruh kode proyek, dari kode asli di ~/projects.

    python3 ~/projects/alat/buat_notebook_lengkap.py            -> ~/projects/notebook_lengkap.ipynb
    python3 ~/projects/alat/buat_notebook_lengkap.py --out X.ipynb

Cara kerja:
  1. Mulai dari skrip utama tiap tahap (latihan detektor, latihan klasifier, pipeline, evaluasi).
  2. Ikuti impornya: modul yang ditemukan di folder skrip, atau di folder yang ditambahkan skrip itu ke
     sys.path (misalnya acuan/3d_bbox_highway untuk arsitektur model), ikut dimasukkan. Pustaka luar
     (numpy, torch, cv2, ...) tidak dimasukkan.
  3. Tiap berkas dipecah per fungsi/kelas menjadi beberapa sel `%%writefile` (sel pertama menulis berkas,
     sel berikutnya `%%writefile -a` menambahkan), dengan judul dan penjelasan di antaranya.
  4. Isi berkas yang ditulis notebook diperiksa sama persis dengan aslinya sebelum notebook disimpan.

Saat notebook dijalankan, semua kode ditulis ke folder `kode_notebook/` di samping notebook, lalu tahap-tahapnya
dijalankan dari sana. Hanya memakai pustaka bawaan Python.
"""
import argparse
import ast
import json
import os
import re
import sys

RUMAH = os.path.expanduser("~")
PROYEK = os.path.join(RUMAH, "projects")

# ---------------------------------------------------------------- kelompok kode
KELOMPOK = [
    {"id": "latih_detektor", "judul": "Latihan dan evaluasi detektor CenterNet",
     "folder": os.path.join(PROYEK, "latih_detektor"),
     "utama": ["train_session0_right.py", "prediksi.py", "evaluasi.py", "analisis_galat.py"]},
    {"id": "latih_klasifikasi", "judul": "Klasifier gambar 4 kelas",
     "folder": os.path.join(PROYEK, "latih_klasifikasi"),
     "utama": ["siapkan_mio_tcd.py", "potong_session0.py", "terapkan_label_truk.py", "latih_klasifikasi.py"]},
    {"id": "pipeline", "judul": "Pipeline: deteksi, pelacakan, klasifikasi, penghitungan",
     "folder": os.path.join(PROYEK, "uji_session0_pipeline"),
     "utama": ["run.py", os.path.join(PROYEK, "alat", "hitung_gt.py")]},
]

# penjelasan berkas yang dikenal (berkas lain memakai docstring-nya sendiri)
KET = {
    "kamera.py": "Parameter kamera `session0_right` (matriks intrinsik K dan posisi kamera) pada resolusi 1280 × 720. "
                 "Dipakai untuk mengubah label anotasi menjadi target latihan dan sebaliknya.",
    "target.py": "Mengubah anotasi tiap frame menjadi **target latihan** CenterNet: heatmap titik tanah kendaraan dan "
                 "nilai regresi rasio lebar, tinggi, panjang pada sel grid stride 32.",
    "dekode.py": "Kebalikan dari target: mengubah keluaran jaringan menjadi kotak 3D (dan kotak 2D untuk evaluasi). "
                 "Bila dijalankan langsung, melakukan uji bolak-balik label → target → dekode → label.",
    "utils.py": "Fungsi geometri dari proyek asal (antoinekeller/3d_bbox_highway): proyeksi titik dunia ke gambar dan "
                "titik gambar ke bidang jalan.",
    "train_session0_right.py": "Loop latihan detektor. Opsi `--init` memilih bobot awal (bobot lama atau baru), dan bobot "
                               "epoch terbaik disimpan ke `--out`. Berisi juga tambalan gradien NaN.",
    "prediksi.py": "Menjalankan detektor pada frame uji dan menyimpan prediksinya ke berkas `.pkl` untuk dievaluasi.",
    "evaluasi.py": "Menghitung metrik deteksi (AP, presisi, recall) dari berkas prediksi `.pkl` terhadap anotasi.",
    "analisis_galat.py": "Menguraikan FN dan FP dari berkas prediksi menurut jarak dan penyebabnya.",
    "siapkan_mio_tcd.py": "Menyusun dataset klasifikasi 4 kelas dari MIO-TCD (memetakan kelas MIO-TCD ke mobil pribadi, "
                          "truk, bus, van/pickup) dan membaginya menjadi train, val, test.",
    "potong_session0.py": "Memotong gambar kendaraan dari frame `session0_right` memakai kotak 2D di anotasi XML, "
                          "untuk menguji dan menyesuaikan klasifier dengan sudut pandang kamera ini.",
    "terapkan_label_truk.py": "Menerapkan label hasil pemeriksaan manual: potongan berlabel \"Truck\" yang ternyata van "
                              "dipindah ke kelas van, sisanya dibuang.",
    "latih_klasifikasi.py": "Latihan klasifier ResNet-18. Opsi `--init` dan `--tambah-session` dipakai untuk menyesuaikan "
                            "model dengan potongan gambar dari kamera ini.",
    "run.py": "Program utama pipeline: membaca video, lalu tiap frame menjalankan deteksi → proyeksi dan filter → "
              "pelacakan → klasifikasi gambar → penghitungan, dan menyimpan video hasil serta `counting_log.csv`.",
    "config.py": "Semua setelan pipeline: ukuran gambar, kalibrasi kamera, ambang filter, kelas dan templat ukurannya, "
                 "garis hitung, warna per kelas, dan path bobot klasifier. Blok di akhir berkas membaca profil kamera "
                 "dari antarmuka web bila ada.",
    "geometry.py": "Model kamera: membangun K dan transformasi kamera, proyeksi dunia → gambar, dan gambar → bidang jalan. "
                   "Bila `CALIB_XML` diisi, kamera dibangun dari berkas kalibrasi.",
    "detector.py": "Pembungkus detektor CenterNet: memuat bobot, menjalankan jaringan pada satu frame, dan mendekode "
                   "keluarannya menjadi daftar deteksi.",
    "detection_cache.py": "Menyimpan dan memuat deteksi mentah per frame, supaya video yang sama tidak perlu dideteksi ulang.",
    "detection_filter.py": "Memproyeksikan deteksi ke bidang jalan (meter) dan membuang yang di luar jalur atau berukuran "
                           "tidak wajar.",
    "kalman_filter.py": "Kalman Filter kecepatan konstan untuk posisi dan ukuran tiap kendaraan.",
    "tracker.py": "Pelacak: asosiasi deteksi ke track dengan algoritma Hungarian (dua tahap ala ByteTrack bila "
                  "`--conf-low` diberikan), membuat dan menghapus track.",
    "box3d.py": "Kotak 3D untuk tampilan: campuran templat kelas dan ukuran terukur, serta arah dari lintasan.",
    "classifier.py": "Klasifikasi per track: rata-rata probabilitas gambar dikalikan rata-rata kecocokan panjang. "
                     "Tanpa gambar, kelas dari panjang saja.",
    "klasifikasi_gambar.py": "Memuat klasifier ResNet-18, memotong gambar kendaraan dari kotak 3D yang diproyeksikan, "
                             "dan mengirim probabilitas 4 kelas ke track.",
    "counter.py": "Penghitung garis: kendaraan dihitung sekali saat melintasi garisnya (50 m untuk yang mendekat, "
                  "85 m untuk yang menjauh), lalu dicatat ke `counting_log.csv`.",
    "visualize.py": "Menggambar kotak 3D, label, dua garis hitung, dan panel hitungan, dengan warna per kelas.",
    "hitung_gt.py": "Evaluasi hitungan: menghitung kendaraan yang sebenarnya melintasi garis dari anotasi XML, lalu "
                    "mencocokkannya dengan `counting_log.csv` (TP, FP, FN).",
}


# ---------------------------------------------------------------- mencari berkas yang diimpor
def _folder_dari_string(pohon, folder_berkas):
    """Folder yang disebut sebagai string di berkas (mis. jalur yang ditambahkan ke sys.path)."""
    out = []
    for n in ast.walk(pohon):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and ("/" in n.value) and len(n.value) < 300:
            p = os.path.expanduser(n.value)
            if not os.path.isabs(p):
                p = os.path.join(folder_berkas, p)
            if os.path.isdir(p) and p not in out:
                out.append(os.path.normpath(p))
    return out


def _nama_impor(pohon):
    nama = []
    for n in ast.walk(pohon):
        if isinstance(n, ast.Import):
            nama += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            nama.append(n.module)
            nama += [n.module + "." + a.name for a in n.names]      # from paket import modul
    return nama


def _cari(nama, folder_cari):
    """nama modul bertitik -> jalur berkas .py di salah satu folder, atau None."""
    bagian = nama.split(".")
    for d in folder_cari:
        p = os.path.join(d, *bagian) + ".py"
        if os.path.isfile(p):
            return p
        p = os.path.join(d, *bagian, "__init__.py")
        if os.path.isfile(p):
            return p
    return None


def kumpulkan(utama, folder):
    """Daftar berkas (urutan: yang diimpor lebih dulu), dan modul yang tidak ditemukan (pustaka luar)."""
    urut, dilihat, luar = [], set(), set()

    def kunjungi(jalur):
        jalur = os.path.normpath(jalur)
        if jalur in dilihat:
            return
        dilihat.add(jalur)
        pohon = ast.parse(open(jalur, encoding="utf-8").read(), jalur)
        cari = [os.path.dirname(jalur), folder] + _folder_dari_string(pohon, os.path.dirname(jalur))
        for nm in _nama_impor(pohon):
            p = _cari(nm, cari)
            if p:
                # paket: sertakan juga __init__.py induknya
                if nm.count(".") and p.endswith(".py") and not p.endswith("__init__.py"):
                    induk = os.path.join(os.path.dirname(p), "__init__.py")
                    if os.path.isfile(induk):
                        kunjungi(induk)
                kunjungi(p)
            elif "." not in nm and nm not in getattr(sys, "stdlib_module_names", ()):
                luar.add(nm)
        urut.append(jalur)

    for u in utama:
        p = u if os.path.isabs(u) else os.path.join(folder, u)
        if os.path.isfile(p):
            kunjungi(p)
        else:
            print("  (dilewati, tidak ada: %s)" % p.replace(RUMAH, "~"))
    return urut, sorted(luar)


def nama_tujuan(jalur, folder):
    """Jalur relatif di kode_notebook/<kelompok>/. Berkas di luar folder kelompok diletakkan rata di akarnya."""
    jalur = os.path.normpath(jalur)
    if jalur.startswith(os.path.normpath(folder) + os.sep):
        return os.path.relpath(jalur, folder)
    akar = os.path.dirname(jalur)
    if os.path.basename(jalur) == "__init__.py" or os.path.isfile(os.path.join(akar, "__init__.py")):
        # bagian dari paket: pertahankan nama paket
        paket = []
        while os.path.isfile(os.path.join(akar, "__init__.py")):
            paket.insert(0, os.path.basename(akar))
            akar = os.path.dirname(akar)
        return os.path.join(*paket, os.path.basename(jalur))
    return os.path.basename(jalur)


# ---------------------------------------------------------------- memecah berkas menjadi sel
def potong(teks):
    """Pecah isi berkas di batas fungsi/kelas tingkat atas. Mengembalikan [(judul_atau_None, potongan_teks)]."""
    baris = teks.splitlines(True)
    if len(baris) < 60:
        return [(None, teks)]
    try:
        pohon = ast.parse(teks)
    except SyntaxError:
        return [(None, teks)]
    titik = []          # (baris_mulai_0, node)
    for n in pohon.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            mulai = min([n.lineno] + [d.lineno for d in n.decorator_list]) - 1
            while mulai > 0 and baris[mulai - 1].lstrip().startswith("#"):     # komentar tepat di atasnya ikut
                mulai -= 1
            titik.append((mulai, n))
        elif isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and "__main__" in ast.dump(n.test):
            titik.append((n.lineno - 1, n))
    if not titik:
        return [(None, teks)]

    def judul(n):
        if isinstance(n, ast.If):
            return "Bagian utama (`if __name__ == \"__main__\"`)"
        jenis = "kelas" if isinstance(n, ast.ClassDef) else "fungsi"
        doc = (ast.get_docstring(n) or "").strip().split("\n")[0]
        return "%s `%s`%s" % (jenis, n.name, (" — " + doc) if doc else "")

    potongan, awal = [], 0
    if titik[0][0] > 0:
        potongan.append(("Impor dan konstanta", "".join(baris[:titik[0][0]])))
        awal = titik[0][0]
    kelompok_judul, kelompok_mulai = [], awal
    for i, (mulai, n) in enumerate(titik):
        akhir = titik[i + 1][0] if i + 1 < len(titik) else len(baris)
        kelompok_judul.append(judul(n))
        if akhir - kelompok_mulai >= 25 or i + 1 == len(titik):         # gabungkan fungsi-fungsi kecil
            potongan.append((kelompok_judul, "".join(baris[kelompok_mulai:akhir])))
            kelompok_judul, kelompok_mulai = [], akhir
    return potongan


# ---------------------------------------------------------------- notebook
SEL = []


def md(teks):
    SEL.append({"cell_type": "markdown", "metadata": {}, "source": teks.strip("\n").splitlines(True)})


def kode(teks):
    SEL.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                "source": teks.strip("\n").splitlines(True)})


def sel_tulis(tujuan, isi, tambah):
    """Sel %%writefile. Isi selalu diakhiri satu baris baru supaya potongan berikutnya mulai di baris sendiri."""
    if not isi.endswith("\n"):
        isi += "\n"
    kepala = "%%writefile " + ("-a " if tambah else "") + tujuan + "\n"
    SEL.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                "source": (kepala + isi).splitlines(True)})


def bacaan(p):
    return open(p, encoding="utf-8").read()


def susun():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(PROYEK, "notebook_lengkap.ipynb"))
    a = ap.parse_args()

    asal = {}           # tujuan -> jalur asli (untuk sel pemeriksaan)
    isi_kelompok = []
    for k in KELOMPOK:
        print("Kelompok", k["id"])
        berkas, luar = kumpulkan(k["utama"], k["folder"])
        tujuan_dipakai = {}
        daftar = []
        for p in berkas:
            t = nama_tujuan(p, k["folder"])
            if t in tujuan_dipakai and os.path.normpath(tujuan_dipakai[t]) != p:
                t = os.path.join("_" + os.path.basename(os.path.dirname(p)), os.path.basename(p))
            tujuan_dipakai[t] = p
            rel = os.path.join("kode_notebook", k["id"], t)
            asal[rel] = p
            daftar.append((p, rel))
            print("   %-42s <- %s" % (rel, p.replace(RUMAH, "~")))
        print("   pustaka luar (bukan bawaan Python):", ", ".join(luar) or "-")
        isi_kelompok.append((k, daftar, luar))

    # ---------------- pembuka
    md("""
# Deteksi, Klasifikasi, dan Penghitungan Kendaraan 3D
### Notebook lengkap: seluruh kode dan tahapnya

Notebook ini memuat **seluruh kode proyek**, disusun berurutan dari latihan model sampai evaluasi:

1. Setelan dan data
2. %s
3. %s
4. %s
5. Evaluasi hitungan terhadap ground truth
6. Ringkasan dan keterbatasan

**Bagaimana kode disimpan.** Tiap berkas `.py` ditampilkan per fungsi atau kelas, dengan penjelasan di antaranya.
Sel kodenya diawali `%%%%writefile`: saat dijalankan, sel itu menulis kode ke folder `kode_notebook/` di samping notebook
(sel pertama sebuah berkas menulis ulang berkasnya, sel berikutnya `-a` menambahkan). Setelah semua sel kode sebuah tahap
dijalankan, tahap itu dijalankan dari folder tersebut. Jadi notebook ini bisa dibaca sebagai dokumentasi kode, dan juga
bisa dijalankan.

Kode di notebook ini disusun dari kode asli di `~/projects` pada %s. Sel pemeriksaan di bagian 1 memastikan isinya sama.

**Tahap yang lama tidak dijalankan secara bawaan.** Melatih detektor dan klasifier butuh berjam-jam tanpa GPU, jadi
saklarnya `False`. Ubah di sel Setelan bila ingin melatih ulang. Hasil latihan dari notebook ditulis ke
`~/projects/hasil/notebook/`, tidak menimpa bobot yang sedang dipakai.

**Menjalankan di Google Colab atau Kaggle (GPU).** Letakkan folder `projects` dan `dataset_publik` di folder rumah
(`/root` pada Colab), karena kode memakai jalur `~/projects/...` dan `~/dataset_publik/...`.
""" % (isi_kelompok[0][0]["judul"], isi_kelompok[1][0]["judul"], isi_kelompok[2][0]["judul"],
           __import__("time").strftime("%Y-%m-%d %H:%M")))

    md("## 1. Setelan dan data")
    kode('''
import os, sys, glob, subprocess, re, time
from IPython.display import display, Image

RUMAH    = os.path.expanduser("~")
PROYEK   = os.path.join(RUMAH, "projects")
PUBLIK   = os.path.join(RUMAH, "dataset_publik")
DATA     = os.path.join(PROYEK, "data_session0_right")
HASIL    = os.path.join(PROYEK, "hasil")
HASIL_NB = os.path.join(HASIL, "notebook")          # keluaran latihan dari notebook (tidak menimpa bobot asli)
KODE     = os.path.abspath("kode_notebook")         # kode yang ditulis sel-sel %%writefile
os.makedirs(HASIL_NB, exist_ok=True)

VIDEO_UJI  = os.path.join(PROYEK, "video_uji", "uji_val_720p.mp4")
CACHE_DET  = os.path.join(PROYEK, "video_uji", "det_session0.pkl")
BOBOT_DET  = os.path.join(PROYEK, "bobot", "detektor")
BOBOT_KLAS = os.path.join(PROYEK, "bobot", "klasifikasi")
MODEL_DET  = os.path.join(BOBOT_DET, "centernet_dari_baru.pth")
FRAME_AWAL, FRAME_AKHIR = 2545, 3181      # rentang uji, tidak dipakai saat melatih detektor

LATIH_DETEKTOR  = False     # True = latih ulang detektor dari bobot lama dan bobot baru (berjam-jam tanpa GPU)
LATIH_KLASIFIER = False     # True = latih ulang klasifier (berjam-jam tanpa GPU)
PAKAI_KLASIFIER_GAMBAR = True

def jalankan(perintah, cwd, ekor=60, tampil=True):
    """Jalankan skrip dengan Python yang sama dengan kernel ini; kembalikan (kode keluar, teks keluaran)."""
    if perintah[0] == "python3":
        perintah = [sys.executable] + perintah[1:]
    p = subprocess.run(perintah, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    baris = [b for b in re.split(r"[\\r\\n]+", p.stdout) if b.strip() and "it/s]" not in b and "s/it]" not in b]
    if tampil:
        print("\\n".join(baris[-ekor:]))
        if p.returncode != 0:
            print("\\n[perintah berhenti dengan kode %d]" % p.returncode)
    return p.returncode, "\\n".join(baris)

def tampil_gambar(jalur, lebar=900):
    if os.path.exists(jalur):
        display(Image(filename=jalur, width=lebar))
    else:
        print("(gambar tidak ada: %s)" % jalur)

def tampil_frame(bgr, lebar=900):
    import cv2
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    display(Image(data=buf.tobytes(), width=lebar))
''')
    md("""
Data latihan dan uji adalah 3.182 frame dari satu kamera jalan raya (`session0_right`), dengan anotasi kotak 3D per
kendaraan (satu XML per frame) dan berkas kalibrasi kamera. Data ini dipakai sebagai **latihan**, karena kamera milik
proyek belum terpasang. Pembagiannya berurutan menurut waktu: frame 0–2544 untuk latihan, 2545–3181 untuk uji.
""")
    kode('''
import xml.etree.ElementTree as ET
from collections import Counter
ann = sorted(glob.glob(os.path.join(DATA, "annotations", "*.xml")))
print("Berkas anotasi:", len(ann))
tipe = {"latih": Counter(), "uji": Counter()}
for a in ann:
    m = re.search(r"_(\\d{6})\\.", os.path.basename(a))
    bagian = "uji" if m and int(m.group(1)) >= FRAME_AWAL else "latih"
    for o in ET.parse(a).getroot().findall("object"):
        tipe[bagian][o.findtext("type", "?")] += 1
for bagian, c in tipe.items():
    print("%-6s objek: %5d  %s" % (bagian, sum(c.values()), dict(c)))
''')

    # ---------------- tiap kelompok
    nomor = {"latih_detektor": 2, "latih_klasifikasi": 3, "pipeline": 4}
    for k, daftar, luar in isi_kelompok:
        n = nomor[k["id"]]
        md("## %d. %s" % (n, k["judul"]))
        if k["id"] == "latih_detektor":
            md("""
Detektor adalah CenterNet dengan tulang punggung ResNet-18 (stride 32). Untuk tiap kendaraan, jaringan mengeluarkan
heatmap titik sentuh tanah dan rasio lebar, tinggi, panjang. Detektor ini tidak menghasilkan kotak 2D dan tidak
membedakan jenis kendaraan.

Arahan dosen pembimbing: *"Tes aja dulu. Simpan best train epoch .pth, dan lakukan train dengan pth yang lama dan yang baru."*

| Latihan | Bobot awal (`--init`) | Bobot hasil |
|---|---|---|
| Dari bobot lama | `centernet-3d-bbox_asli.pth` (bobot penulis proyek asal) | `centernet_dari_lama.pth` |
| Dari bobot baru | `centernet_session0_right.pth` (hasil latihan sendiri) | `centernet_dari_baru.pth` |

Tafsiran "pth lama" dan "pth baru" di tabel ini belum dikonfirmasi ke dosen.
""")
        elif k["id"] == "latih_klasifikasi":
            md("""
Karena detektor tidak membedakan jenis kendaraan, dilatih klasifier gambar terpisah dengan 4 kelas: **mobil pribadi,
truk, bus, van/pickup**. Modelnya ResNet-18 (bobot awal ImageNet), masukan 128 × 128 dengan letterbox, data dari
dataset publik MIO-TCD.

Model yang hanya dilatih pada MIO-TCD banyak membaca mobil dari kamera ini sebagai van/pickup. Penyebabnya sudut pandang:
MIO-TCD kebanyakan tampak samping, kamera ini melihat dari depan dan belakang. Karena itu model disesuaikan dengan
potongan gambar dari kamera ini. Penyesuaian dengan mobil saja membuat 35 dari 71 van/truk ikut terbaca mobil; setelah
potongan van (yang di anotasi berlabel "Truck") ikut dilatih, kesalahan itu hilang. Hasilnya `klas_ft2.pth`.
""")
        else:
            md("""
| Tahap | Berkas |
|---|---|
| Deteksi | `detector.py` |
| Proyeksi ke bidang jalan dan filter | `geometry.py`, `detection_filter.py` |
| Pelacakan | `tracker.py`, `kalman_filter.py` |
| Klasifikasi gambar × panjang | `klasifikasi_gambar.py`, `classifier.py` |
| Penghitungan dua garis | `counter.py` |
| Tampilan berwarna per kelas | `visualize.py`, `box3d.py` |

Klasifikasi: `skor[c] = (rata-rata probabilitas gambar[c] + ε) × (rata-rata kecocokan panjang[c] + ε)`; kelas = skor terbesar.

Dua garis hitung: 50 m untuk jalur yang mendekat, 85 m untuk jalur yang menjauh, karena kendaraan di jalur kanan baru
terlihat pada jarak lebih dari 54 m dan tidak pernah melintasi garis 50 m.
""")
        md("Berkas di tahap ini (urutan: yang diimpor lebih dulu). Pustaka luar yang dipakai: " +
           (", ".join("`%s`" % x for x in luar) or "-") + ".\n\n" +
           "\n".join("- `%s` (asli: `%s`)" % (os.path.relpath(rel, "kode_notebook/" + k["id"]), p.replace(RUMAH, "~"))
                     for p, rel in daftar))
        for p, rel in daftar:
            teks = bacaan(p)
            nama = os.path.basename(p)
            ket = KET.get(nama) if nama in KET and not (nama == "utils.py" and "3d_bbox" not in p) else None
            if ket is None:
                ket = (ast.get_docstring(ast.parse(teks)) or "").strip().split("\n\n")[0].replace("\n", " ")
            md("### `%s`\n\n%s\n\n*Asli: `%s`, %d baris.*" % (os.path.relpath(rel, "kode_notebook/" + k["id"]),
                                                                ket or "", p.replace(RUMAH, "~"), len(teks.splitlines())))
            potongan = potong(teks)
            for i, (jd, isi) in enumerate(potongan):
                if len(potongan) > 1 and jd:
                    if isinstance(jd, str):
                        md("#### " + jd)
                    elif len(jd) == 1:
                        md("#### " + jd[0])
                    else:
                        md("#### " + jd[0] + "\n\nBersama: " + "; ".join(jd[1:]))
                sel_tulis(rel, isi, tambah=i > 0)

        # ---------------- menjalankan tahap
        if k["id"] == "latih_detektor":
            md("### Menjalankan latihan dan evaluasi detektor")
            kode('''
D = os.path.join(KODE, "latih_detektor")
perintah = [
    ["python3", "train_session0_right.py", "--init", os.path.join(BOBOT_DET, "centernet-3d-bbox_asli.pth"),
     "--out", os.path.join(HASIL_NB, "centernet_dari_lama.pth")],
    ["python3", "train_session0_right.py", "--init", os.path.join(BOBOT_DET, "centernet_session0_right.pth"),
     "--out", os.path.join(HASIL_NB, "centernet_dari_baru.pth")],
]
for p in perintah:
    print(" ".join(x.replace(RUMAH, "~") for x in p))
if LATIH_DETEKTOR:
    for p in perintah:
        jalankan(p, cwd=D, ekor=30)
else:
    print("\\n(LATIH_DETEKTOR = False: tidak dilatih; bobot yang sudah ada dipakai)")
    for f in sorted(glob.glob(os.path.join(BOBOT_DET, "*.pth"))):
        print("  %-34s %6.1f MB" % (os.path.basename(f), os.path.getsize(f) / 1048576))
''')
            kode('''
pred = sorted(glob.glob(os.path.join(HASIL, "prediksi_detektor", "*.pkl")))
print("Berkas prediksi:", [os.path.basename(p) for p in pred] or "(tidak ada; buat dengan prediksi.py)")
for p in pred:
    print("\\n" + "=" * 20, os.path.basename(p), "=" * 20)
    jalankan(["python3", "evaluasi.py", "--pred", p], cwd=D, ekor=30)
''')
        elif k["id"] == "latih_klasifikasi":
            md("### Menjalankan latihan klasifier")
            kode('''
D = os.path.join(KODE, "latih_klasifikasi")
akar = os.path.join(PUBLIK, "dataset_klasifikasi")
if os.path.isdir(os.path.join(akar, "train")):
    print("%-16s %8s %8s %8s" % ("kelas", "train", "val", "test"))
    for kl in sorted(os.listdir(os.path.join(akar, "train"))):
        print("%-16s %8d %8d %8d" % (kl, *[len(os.listdir(os.path.join(akar, b, kl))) if os.path.isdir(os.path.join(akar, b, kl)) else 0
                                          for b in ("train", "val", "test")]))
perintah = [
    ["python3", "latih_klasifikasi.py", "--epochs", "5", "--tag", "nb_klas5"],
    ["python3", "latih_klasifikasi.py", "--init", os.path.join(BOBOT_KLAS, "klas5.pth"), "--tambah-session",
     "--epochs", "3", "--max-per-class", "3000", "--lr", "1e-4", "--tag", "nb_klas_ft2"],
]
for p in perintah:
    print(" ".join(x.replace(RUMAH, "~") for x in p))
if LATIH_KLASIFIER:
    for p in perintah:
        jalankan(p, cwd=D, ekor=40)
else:
    print("\\n(LATIH_KLASIFIER = False: tidak dilatih; klas_ft2.pth yang sudah ada dipakai)")
hk = os.path.join(PUBLIK, "hasil_klasifikasi")
tampil_gambar(os.path.join(hk, "diagnosa.png"))
log = sorted(glob.glob(os.path.join(hk, "klas_ft2_*.txt")), key=os.path.getmtime)
if log:
    print("Ekor log", os.path.basename(log[-1]), "(akurasi dan matriks kebingungan):\\n")
    print("\\n".join(open(log[-1], errors="replace").read().splitlines()[-45:]))
''')
        else:
            md("### Menjalankan pipeline pada klip uji\n\nDeteksi diambil dari cache, jadi selesai dalam belasan detik.")
            kode('''
import pandas as pd, cv2
D = os.path.join(KODE, "pipeline")
VIDEO_HASIL = os.path.join(HASIL, "video", "notebook_lengkap_hasil.mp4")
cmd = ["python3", "run.py", VIDEO_UJI, MODEL_DET, "--cache", CACHE_DET, "--conf", "0.4", "--conf-low", "0.2",
       "--no-show", "--line-y", "50", "--out", VIDEO_HASIL]
if not PAKAI_KLASIFIER_GAMBAR:
    cmd.append("--tanpa-gambar")
print(" ".join(x.replace(RUMAH, "~") for x in cmd), "\\n")
_ = jalankan(cmd, cwd=D, ekor=45)
''')
            kode('''
log_csv = os.path.join(D, "counting_log.csv")
hitung = pd.read_csv(log_csv) if os.path.exists(log_csv) else pd.DataFrame()
if len(hitung):
    _c = cv2.VideoCapture(VIDEO_UJI); fps = _c.get(cv2.CAP_PROP_FPS) or 25.0; _c.release()
    hitung["detik"] = (hitung["frame"] / fps).round(1)
    hitung["arah"] = hitung["x_m"].apply(lambda x: "menjauh" if x >= 7.0 else "mendekat")
    display(hitung)
    display(hitung["kelas"].value_counts().to_frame("jumlah"))
    display(hitung["arah"].value_counts().to_frame("jumlah"))
    cap = cv2.VideoCapture(VIDEO_HASIL)
    for f in list(hitung["frame"])[:3]:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(f) + 3)
        ok, fr = cap.read()
        if ok:
            print("frame", int(f) + 3); tampil_frame(fr, lebar=800)
    cap.release()
else:
    print("(tidak ada kendaraan yang dihitung)")
''')

    md("""
## 5. Evaluasi hitungan terhadap ground truth

`hitung_gt.py` (ditulis di bagian 4) menghitung kendaraan yang sebenarnya melintasi garis dari anotasi XML, lalu
mencocokkannya dengan `counting_log.csv`. TP = dihitung dan memang ada; FP = dihitung tetapi tidak ada; FN = ada tetapi
tidak dihitung.
""")
    kode('''
_, teks_gt = jalankan(["python3", "hitung_gt.py", "--first", str(FRAME_AWAL), "--last", str(FRAME_AKHIR),
                       "--line", "50", "--log", "counting_log.csv"], cwd=D, tampil=False)
awal = teks_gt.find("PERBANDINGAN")
print(teks_gt[awal:] if awal >= 0 else teks_gt[-1500:])
m = re.search(r"TP \\(cocok\\): (\\d+) \\| FP .*?: (\\d+) \\| FN .*?: (\\d+)", teks_gt)
pasangan = re.findall(r"f(\\d+)\\s+id(\\d+)\\s+(\\w+)\\s+x=\\s*([-\\d.]+) -> GT#(\\d+)\\s+(\\w+).*?(mendekat|menjauh)\\s+([\\d.]+) vs ([\\d.]+) m", teks_gt)
if m:
    tp, fp, fn = map(int, m.groups())
    display(pd.DataFrame([{"TP": tp, "FP": fp, "FN": fn, "presisi": round(tp / (tp + fp), 2) if tp + fp else None,
                           "recall": round(tp / (tp + fn), 2) if tp + fn else None}]))
if pasangan:
    t = pd.DataFrame(pasangan, columns=["frame", "id", "kelas", "x (m)", "GT", "tipe anotasi", "arah", "panjang pipeline (m)", "panjang anotasi (m)"])
    t["selisih panjang (m)"] = (t["panjang pipeline (m)"].astype(float) - t["panjang anotasi (m)"].astype(float)).round(2)
    display(t)
''')
    md("""
## 6. Ringkasan dan keterbatasan

- **Sampel uji kecil.** Hasil di atas berasal dari satu klip sekitar 25 detik, jadi belum bisa disebut angka akurasi.
- **Kelas selain mobil belum teruji pada video.** Klip uji hanya berisi mobil pribadi.
- **Panjang kurang akurat di jarak jauh**, lebih besar selisihnya pada garis 85 m daripada garis 50 m.
- **Semua pengujian memakai data publik.** Kalibrasi, garis hitung, dan bobot perlu disesuaikan saat kamera sendiri terpasang.
- **Tanpa GPU**, deteksi berjalan sekitar 2–3 frame per detik.
- **Cara menggabungkan gambar dan panjang bersifat heuristik.**

Antarmuka web (`antarmuka/`) menjalankan `run.py` yang sama; kodenya tidak dimuat di notebook ini.
""")

    # ---------------- sel pemeriksaan: kode yang ditulis notebook == kode asli
    md("""
### Pemeriksaan: kode di notebook sama dengan kode asli

Sel ini membandingkan berkas yang ditulis notebook dengan berkas aslinya di `~/projects`. Jalankan setelah semua sel di
atas. Bila kode asli sudah diubah setelah notebook disusun, berkas yang berbeda akan disebut; susun ulang notebook dengan
`python3 ~/projects/alat/buat_notebook_lengkap.py`.
""")
    peta = {k: v.replace(RUMAH, "~") for k, v in asal.items()}
    kode('''
ASAL = %s
def _norm(t):
    return [b.rstrip() for b in t.splitlines() if b.strip()]
beda, cocok, tak_ada = [], 0, []
for rel, asli in ASAL.items():
    asli = os.path.expanduser(asli)
    if not os.path.exists(asli):
        tak_ada.append(rel); continue
    tulis = os.path.join(os.path.dirname(KODE), rel)
    if os.path.exists(tulis) and _norm(open(tulis, encoding="utf-8").read()) == _norm(open(asli, encoding="utf-8").read()):
        cocok += 1
    else:
        beda.append(rel)
print("Sama dengan aslinya:", cocok, "dari", len(ASAL))
if beda:    print("BERBEDA:", beda)
if tak_ada: print("Asli tidak ada di komputer ini (wajar di Colab):", len(tak_ada))
''' % json.dumps(peta, indent=1, ensure_ascii=False))

    # ---------------- verifikasi saat menyusun: potongan digabung == berkas asli
    tulis = {}
    for c in SEL:
        if c["cell_type"] != "code":
            continue
        src = "".join(c["source"])
        if src.startswith("%%writefile "):
            kepala, isi = src.split("\n", 1)
            argumen = kepala.split()[1:]
            tambah = argumen[0] == "-a"
            nama = argumen[-1]
            tulis[nama] = (tulis.get(nama, "") if tambah else "") + isi
    salah = [n for n, isi in tulis.items() if isi.rstrip("\n") != bacaan(asal[n]).rstrip("\n")]
    if salah:
        sys.exit("GAGAL: potongan tidak sama dengan berkas asli: %s" % salah)

    for i, c in enumerate(SEL):
        c["id"] = "sel%03d" % i
    nb = {"cells": SEL, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                      "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(nb, f, ensure_ascii=False, indent=1)
    gi = os.path.join(PROYEK, ".gitignore")
    if os.path.exists(gi) and "kode_notebook/" not in open(gi).read().split():
        ada = open(gi).read()
        with open(gi, "a") as f:
            f.write(("" if ada.endswith(chr(10)) else chr(10)) + "kode_notebook/" + chr(10) + "hasil/notebook/" + chr(10))
        print("ditambah ke .gitignore: kode_notebook/, hasil/notebook/ (salinan kode dan hasil latihan dari notebook)")
    n_kode = sum(1 for c in SEL if c["cell_type"] == "code")
    total = sum(len(bacaan(p).splitlines()) for p in asal.values())
    print("\nSELESAI: %s" % a.out.replace(RUMAH, "~"))
    print("  %d berkas kode, %d baris, %d sel (%d sel kode). Semua potongan sama persis dengan berkas aslinya."
          % (len(asal), total, len(SEL), n_kode))


if __name__ == "__main__":
    susun()