"""
auto_process.py - UTAMA 2: rekaman otomatis langsung diproses.

Memakai model detektor bawaan (model pertama di data/weights/detector, MODEL_BAWAAN di depan),
ambang bawaan, dan profil kamera node tersebut. Hasil disimpan di data/results/automatic/<job>/.
"""
import job_worker


def proses(sumber, node_id):
    """Masukkan rekaman otomatis ke antrean proses. Mengembalikan status job."""
    return job_worker.buat_job(sumber=sumber, node_id=node_id, pemicu="otomatis")
