#!/usr/bin/env python3
"""bersihkan_repo_utama.py - bersihkan ~/projects/3d-car-classification-counting.

Bawaan: hanya menampilkan rencana.  --jalankan : kerjakan.
Tidak ada yang langsung dihapus kecuali __pycache__; berkas lain dipindah ke
~/projects/_buangan/repo_utama/ (hapus folder itu sendiri bila sudah yakin).
classifier.py dikembalikan ke versi asli (cadangan classifier.py.sebelum_klas di uji_session0_pipeline).
"""
import filecmp, os, shutil, sys

H = os.path.expanduser("~/projects")
R = os.path.join(H, "3d-car-classification-counting")
U = os.path.join(H, "uji_session0_pipeline")
B = os.path.join(H, "_buangan", "repo_utama")
jalan = "--jalankan" in sys.argv
rencana = []   # (aksi, asal, tujuan, keterangan)


def ada(*p):
    return os.path.exists(os.path.join(*p))


def buang(nama, ket):
    if ada(R, nama):
        rencana.append(("pindah", os.path.join(R, nama), os.path.join(B, nama), ket))


asli = os.path.join(U, "classifier.py.sebelum_klas")
if ada(R, "classifier.py") and os.path.exists(asli) and not filecmp.cmp(os.path.join(R, "classifier.py"), asli, False):
    buang("classifier.py", "versi otak-atik 12 Nov")
    rencana.append(("salin", asli, os.path.join(R, "classifier.py"), "kembalikan classifier.py asli"))
buang("klasifikasi_gambar.py", "berkas percobaan 12 Nov, bukan bagian repo")
for n in ("config.py", "geometry.py"):
    if ada(R, n + ".sebelum_kalibrasi"):
        if n == "config.py" and not filecmp.cmp(os.path.join(R, n), os.path.join(R, n + ".sebelum_kalibrasi"), False):
            sys.exit("BERHENTI: config.py berbeda dari cadangannya; periksa dulu.")
        buang(n + ".sebelum_kalibrasi", "cadangan patch kalibrasi (sudah dikembalikan)")
if ada(R, "tools/cek_kalibrasi.py"):
    buang("tools/cek_kalibrasi.py", "salinan; ada di ~/projects/alat/")
pth, pth2 = os.path.join(R, "centernet-3d-bbox.pth"), os.path.join(H, "bobot/detektor/centernet-3d-bbox_asli.pth")
if os.path.exists(pth):
    if os.path.exists(pth2) and filecmp.cmp(pth, pth2, False):
        buang("centernet-3d-bbox.pth", "duplikat bobot/detektor/centernet-3d-bbox_asli.pth")
    else:
        rencana.append(("pindah", pth, os.path.join(H, "bobot/detektor/centernet-3d-bbox_repo.pth"), "bobot (bukan duplikat)"))
for f in os.listdir(R):
    if f.endswith(".mp4"):
        rencana.append(("pindah", os.path.join(R, f), os.path.join(H, "video_uji", f), "video"))
if ada(R, "counting_log.csv"):
    rencana.append(("pindah", os.path.join(R, "counting_log.csv"), os.path.join(H, "hasil/counting/counting_log_repo_utama.csv"), "hasil lama"))
for d, _, _ in os.walk(R):
    if os.path.basename(d) == "__pycache__":
        rencana.append(("hapus", d, "", "dibuat ulang otomatis"))

for aksi, a, t, ket in rencana:
    if aksi != "hapus" and aksi != "salin" and os.path.exists(t):
        sys.exit("BERHENTI: tujuan sudah ada: " + t)
    print("  %-6s %-48s %s %s   [%s]" % (aksi, os.path.relpath(a, H), "->" if t else "", os.path.relpath(t, H) if t else "", ket))
if not rencana:
    print("Tidak ada yang perlu dibersihkan.")
if not jalan:
    print("\nBelum ada yang diubah. Jalankan dengan --jalankan bila rencana ini benar.")
    sys.exit()
for aksi, a, t, _ in rencana:
    if aksi == "hapus":
        shutil.rmtree(a, ignore_errors=True)
        continue
    os.makedirs(os.path.dirname(t), exist_ok=True)
    (shutil.move if aksi == "pindah" else shutil.copy)(a, t)
print("\nSELESAI. Isi repo sekarang:")
print("  " + "  ".join(sorted(os.listdir(R))))