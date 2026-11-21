"""
manual_process.py - UTAMA 3: memproses video yang dipilih di halaman Proses.

Pengguna memilih video (rekaman atau video contoh), node (profil kamera), versi kalibrasi
(bawaan: yang sedang dipakai node), bobot detektor .pth, dan ambang deteksi. Hasil disimpan di data/results/manual/<job>/.
"""
import job_worker
from settings import daftar_contoh, daftar_model   # noqa: F401  (dipakai halaman Proses lewat /api/info)


def proses(sumber, node_id, model=None, conf=None, conf_low=None, kalibrasi=None):
    return job_worker.buat_job(sumber, node_id, model, conf, conf_low, kalibrasi=kalibrasi)
