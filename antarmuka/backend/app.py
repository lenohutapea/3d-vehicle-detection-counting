"""
app.py - server FastAPI untuk antarmuka web pipeline deteksi dan penghitungan kendaraan.

Jalankan (dari folder backend ini, dengan venv aktif):
    uvicorn app:app --host 127.0.0.1 --port 8000
lalu buka http://127.0.0.1:8000 di peramban.

Semua logika ada di layanan.py; berkas ini hanya memetakan alamat web ke fungsi di sana.
Halaman web (HTML/CSS/JS) ada di ../frontend dan disajikan oleh server ini.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import layanan

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")


@asynccontextmanager
async def _siklus(_app):
    layanan.muat_dari_disk()      # baca riwayat pekerjaan saat server mulai
    yield


app = FastAPI(title="Penghitung Kendaraan 3D", lifespan=_siklus)


@app.get("/api/info")
def info():
    return layanan.info()


@app.get("/api/jobs")
def daftar():
    return layanan.daftar_job()


@app.post("/api/jobs")
def buat(
    video: str = Form(""),
    berkas: UploadFile = File(None),
    conf: str = Form(""),
    conf_low: str = Form(""),
    line_y: str = Form(""),
    line_y_away: str = Form(""),
):
    setelan = {"conf": conf, "conf_low": conf_low, "line_y": line_y, "line_y_away": line_y_away}
    try:
        if berkas is not None and berkas.filename:
            return layanan.buat_job(unggahan=berkas.file, nama_unggahan=berkas.filename, setelan=setelan)
        return layanan.buat_job(nama_video=video, setelan=setelan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/jobs/{job_id}")
def satu(job_id: str):
    st = layanan.ambil_job(job_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Pekerjaan tidak ditemukan.")
    return st


@app.delete("/api/jobs/{job_id}")
def hapus(job_id: str):
    hasil = layanan.hapus_job(job_id)
    if hasil == "tidak ada":
        raise HTTPException(status_code=404, detail="Pekerjaan tidak ditemukan.")
    if hasil == "sedang berjalan":
        raise HTTPException(status_code=409, detail="Pekerjaan masih berjalan.")
    return {"ok": True}


@app.get("/api/jobs/{job_id}/berkas/{nama}")
def berkas_hasil(job_id: str, nama: str):
    p = layanan.jalur_berkas(job_id, nama)
    if p is None:
        raise HTTPException(status_code=404, detail="Berkas tidak ada.")
    jenis = {"hasil.mp4": "video/mp4", "counting_log.csv": "text/csv", "keluaran.txt": "text/plain"}[nama]
    return FileResponse(p, media_type=jenis, filename=None if nama == "hasil.mp4" else nama)


# halaman web (harus terakhir agar tidak menutupi /api)
app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
