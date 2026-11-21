"""
receive_recording.py - UTAMA 2: komunikasi dengan node kamera (Raspberry Pi / IP camera).

Node menanyakan tugas tiap beberapa detik (node_tugas), merekam, lalu mengirim videonya (node_unggah).
  - rekaman otomatis (sesuai jadwal) -> disimpan lalu LANGSUNG diproses (auto_process.py)
  - rekaman manual (tombol Rekam di web) -> disimpan saja (lihat 3_manual)
Semua alamat /api/node/... wajib membawa token (X-Token) dari data/settings.json.
Isi ini berasal dari layanan.py lama (bagian 4. node).
"""
import hmac
import time

import auto_process
import schedule
import upload_video
from settings import Salah, _cek_node, _kunci, _permintaan, _terlihat, setelan


def token_sah(token):
    return bool(token) and hmac.compare_digest(str(token), str(setelan()["token_node"]))


def node_tugas(node_id):
    """Dipanggil node tiap beberapa detik. Mengembalikan jadwal hari ini dan permintaan manual yang menunggu."""
    _cek_node(node_id)
    _terlihat[node_id] = time.time()
    manual = []
    with _kunci:
        for r in _permintaan:
            if r["node"] == node_id and r["status"] == "menunggu node":
                r["status"] = "merekam"
                manual.append({"id": r["id"], "durasi_detik": r["durasi_detik"]})
    tanggal = time.strftime("%Y%m%d")
    return {"waktu_server": time.strftime("%Y-%m-%d %H:%M:%S"), "tanggal": tanggal,
            "durasi_detik": int(setelan()["jadwal"]["durasi_detik"]), "jadwal": schedule.jadwal_harian(),
            "sudah": schedule.slot_terisi(node_id, tanggal), "manual": manual}


def node_unggah(node_id, berkas, mode, slot="", id_permintaan="", nama_asli="rekaman.mp4"):
    """Node mengirim hasil rekaman. Otomatis -> langsung diproses. Manual -> disimpan saja."""
    _cek_node(node_id)
    _terlihat[node_id] = time.time()
    tanggal = time.strftime("%Y%m%d")
    if mode == "otomatis":
        if slot not in schedule.jadwal_harian():
            raise Salah("Jam jadwal tidak dikenal: %s" % slot)
        if slot in schedule.slot_terisi(node_id, tanggal):
            raise Salah("Rekaman untuk jadwal %s sudah diterima." % slot)
    sumber = upload_video.simpan_rekaman(node_id, berkas, mode, nama_asli)
    hasil = {"sumber": sumber}
    if mode == "otomatis":
        schedule.tandai_slot(node_id, tanggal, slot)
        try:
            hasil["job"] = auto_process.proses(sumber, node_id)["id"]
        except Exception as e:                    # rekaman tetap tersimpan walau gagal masuk antrean
            hasil["galat"] = str(e)
    else:
        with _kunci:
            for r in _permintaan:
                if r["id"] == id_permintaan:
                    r["status"] = "selesai"
                    r["sumber"] = sumber
    return hasil
