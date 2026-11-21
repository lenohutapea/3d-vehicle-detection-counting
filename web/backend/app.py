"""
app.py - server FastAPI untuk antarmuka web.

Jalankan dengan ./run.sh, lalu buka http://127.0.0.1:8000 di peramban.
Berkas ini hanya memetakan alamat web ke fungsi di tiga bagian utama:
    /api/kamera/<node>/profil, /pratinjau    -> 1_camera_calibration/calibration.py
    /api/node/<node>/...  (Raspberry Pi)     -> 2_automatic/receive_recording.py
    /api/kamera/<node>/rekam, /api/permintaan -> 3_manual/manual_record.py
    /api/rekaman                               -> 3_manual/upload_video.py
    /api/jobs                                  -> 3_manual/manual_process.py + centernet3d_bbox/job_worker.py
Halaman web (HTML/CSS/JS) ada di ../frontend dan disajikan oleh server ini.

Keamanan: halaman web dan API-nya hanya melayani komputer ini sendiri (127.0.0.1), kecuali
lewat Cloudflare Tunnel bila "izinkan_publik": true di data/settings.json.
Dari jaringan, alamat /api/node/... milik Raspberry Pi selalu dilayani, tetapi wajib membawa token.
"""

import os
import sys
from contextlib import asynccontextmanager

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _d in ("web/backend", "1_camera_calibration", "2_automatic", "3_manual", "centernet3d_bbox"):
    sys.path.insert(0, os.path.join(ROOT, _d))

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response                   # noqa: E402
from fastapi.staticfiles import StaticFiles                                          # noqa: E402

import calibration          # noqa: E402  UTAMA 1
import job_worker           # noqa: E402  inti
import manual_process       # noqa: E402  UTAMA 3
import manual_record        # noqa: E402  UTAMA 3
import receive_recording    # noqa: E402  UTAMA 2
import settings             # noqa: E402
import upload_video         # noqa: E402  UTAMA 3

FRONTEND = os.path.join(ROOT, "web", "frontend")
LOKAL = ("127.0.0.1", "::1", "localhost")


@asynccontextmanager
async def _siklus(_app):
    job_worker.muat_dari_disk()      # baca riwayat pekerjaan saat server mulai
    yield


app = FastAPI(title="Penghitung Kendaraan 3D", lifespan=_siklus)


@app.middleware("http")
async def _hanya_lokal(request: Request, call_next):
    asal = request.client.host if request.client else ""
    lewat_cloudflare = bool(request.headers.get("cf-ray")) and settings.setelan().get("izinkan_publik", False)
    if asal not in LOKAL and not request.url.path.startswith("/api/node/") and not lewat_cloudflare:
        return JSONResponse({"detail": "Halaman ini hanya bisa dibuka dari komputer server."}, status_code=403)
    return await call_next(request)


@app.exception_handler(settings.Salah)
async def _masukan_salah(_request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def _cek_token(token):
    if not receive_recording.token_sah(token):
        raise HTTPException(status_code=401, detail="Token node salah.")


# ---------------------------------------------------------------- umum
@app.get("/api/info")
def info():
    return settings.info()


# ---------------------------------------------------------------- UTAMA 1: kalibrasi kamera
@app.get("/api/kamera/{node_id}/profil")
def profil(node_id: str):
    return calibration.profil(node_id)


async def _formulir(request: Request):
    """Formulir multipart -> (dict nilai teks, isi berkas 'xml' atau None)."""
    form = await request.form()
    data, xml = {}, None
    for k, v in form.items():
        if hasattr(v, "read"):
            if k == "xml" and getattr(v, "filename", ""):
                xml = await v.read()
        else:
            data[k] = v
    return data, xml


@app.post("/api/kamera/{node_id}/profil")
async def simpan_profil(node_id: str, request: Request):
    data, xml = await _formulir(request)
    return calibration.simpan_profil(node_id, data, xml)


@app.post("/api/kamera/{node_id}/pratinjau")
async def pratinjau(node_id: str, request: Request):
    data, xml = await _formulir(request)
    gambar = calibration.pratinjau(node_id, data, data.get("sumber", ""), data.get("posisi", 0.5), xml)
    return Response(content=gambar, media_type="image/jpeg")


# ---------------------------------------------------------------- UTAMA 3: rekaman manual & unggah
@app.get("/api/rekaman")
def rekaman(node: str = ""):
    return upload_video.daftar_rekaman(node or None)


@app.post("/api/rekaman")
def unggah_manual(node: str = Form(...), berkas: UploadFile = File(...)):
    return {"sumber": upload_video.simpan_rekaman(node, berkas.file, "manual", berkas.filename)}


@app.delete("/api/rekaman")
def hapus_rekaman(sumber: str):
    upload_video.hapus_rekaman(sumber)
    return {"ok": True}


@app.post("/api/kamera/{node_id}/rekam")
def minta_rekam(node_id: str, durasi: str = Form(...)):
    return manual_record.minta_rekam(node_id, durasi)


@app.get("/api/permintaan")
def permintaan(node: str = ""):
    return manual_record.daftar_permintaan(node or None)


# ---------------------------------------------------------------- UTAMA 2: untuk Raspberry Pi (wajib token)
@app.get("/api/node/{node_id}/tugas")
def node_tugas(node_id: str, x_token: str = Header("")):
    _cek_token(x_token)
    return receive_recording.node_tugas(node_id)


@app.post("/api/node/{node_id}/rekaman")
def node_unggah(node_id: str, berkas: UploadFile = File(...), mode: str = Form(...), slot: str = Form(""),
                id_permintaan: str = Form(""), x_token: str = Header("")):
    _cek_token(x_token)
    return receive_recording.node_unggah(node_id, berkas.file, mode, slot, id_permintaan,
                                         berkas.filename or "rekaman.mp4")


# ---------------------------------------------------------------- proses dan hasil
@app.get("/api/jobs")
def daftar():
    return job_worker.daftar_job()


@app.post("/api/jobs")
def buat(sumber: str = Form(...), node: str = Form(...), model: str = Form(""), conf: str = Form(""),
         conf_low: str = Form("")):
    return manual_process.proses(sumber, node, model or None, conf, conf_low)


@app.get("/api/jobs/{job_id}")
def satu(job_id: str):
    st = job_worker.ambil_job(job_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Pekerjaan tidak ditemukan.")
    return st


@app.delete("/api/jobs/{job_id}")
def hapus(job_id: str):
    hasil = job_worker.hapus_job(job_id)
    if hasil == "tidak ada":
        raise HTTPException(status_code=404, detail="Pekerjaan tidak ditemukan.")
    if hasil == "sedang berjalan":
        raise HTTPException(status_code=409, detail="Pekerjaan masih berjalan.")
    return {"ok": True}


@app.get("/api/jobs/{job_id}/berkas/{nama}")
def berkas_hasil(job_id: str, nama: str):
    p = job_worker.jalur_berkas(job_id, nama)
    if p is None:
        raise HTTPException(status_code=404, detail="Berkas tidak ada.")
    jenis = {"result.mp4": "video/mp4", "hasil.mp4": "video/mp4", "counting_log.csv": "text/csv",
             "keluaran.txt": "text/plain"}[nama]
    return FileResponse(p, media_type=jenis, filename=None if nama.endswith(".mp4") else nama)


# halaman web (harus terakhir agar tidak menutupi /api)
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="web")
