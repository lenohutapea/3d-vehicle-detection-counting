#!/usr/bin/env python3
"""
node_kamera.py - program untuk Raspberry Pi (node kamera). Hanya memakai pustaka bawaan Python.

Tugasnya: tiap beberapa detik bertanya ke server "ada tugas apa?", lalu
  - merekam pada jam-jam jadwal otomatis yang diberikan server, dan
  - merekam saat ada permintaan manual dari halaman web,
kemudian mengirim videonya ke server. Rekaman otomatis langsung diproses server;
rekaman manual hanya disimpan.

Di Raspberry Pi (kamera asli):
    python3 node_kamera.py --server http://ALAMAT_SERVER:8000 --node kamera1 --token TOKEN
Uji tanpa kamera (kamera tiruan dari berkas video), di komputer mana pun:
    python3 node_kamera.py --server http://127.0.0.1:8000 --node kamera1 --token TOKEN \\
        --sumber ~/projects/video_uji/uji_val_720p.mp4

TOKEN ada di antarmuka/data/setelan.json ("token_node") pada server.
Perintah rekam kamera asli bisa diganti dengan --perintah; {ms} = durasi milidetik,
{detik} = durasi detik, {keluar} = berkas keluaran. Bawaannya untuk Raspberry Pi OS (rpicam-vid).
"""
import argparse
import http.client
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import uuid

PERINTAH_BAWAAN = "rpicam-vid -t {ms} --width 1280 --height 720 --framerate 25 --codec libav -o {keluar} -n"


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


class Server:
    def __init__(self, url, node, token):
        u = urllib.parse.urlparse(url)
        self.https = u.scheme == "https"
        self.host, self.port = u.hostname, u.port or (443 if self.https else 80)
        self.node, self.token = node, token

    def _sambung(self, timeout):
        kelas = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
        return kelas(self.host, self.port, timeout=timeout)

    def tugas(self):
        c = self._sambung(15)
        c.request("GET", "/api/node/%s/tugas" % self.node, headers={"X-Token": self.token})
        r = c.getresponse()
        isi = r.read()
        c.close()
        if r.status != 200:
            raise RuntimeError("server menjawab %d: %s" % (r.status, isi[:200].decode(errors="replace")))
        return json.loads(isi)

    def unggah(self, jalur, bidang):
        """Kirim berkas sebagai multipart/form-data tanpa memuat seluruh berkas ke memori."""
        batas = uuid.uuid4().hex
        kepala = b""
        for k, v in bidang.items():
            kepala += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (batas, k, v)).encode()
        kepala += ("--%s\r\nContent-Disposition: form-data; name=\"berkas\"; filename=\"rekaman.mp4\"\r\n"
                   "Content-Type: video/mp4\r\n\r\n" % batas).encode()
        ekor = ("\r\n--%s--\r\n" % batas).encode()
        panjang = len(kepala) + os.path.getsize(jalur) + len(ekor)
        c = self._sambung(600)
        c.putrequest("POST", "/api/node/%s/rekaman" % self.node)
        c.putheader("X-Token", self.token)
        c.putheader("Content-Type", "multipart/form-data; boundary=" + batas)
        c.putheader("Content-Length", str(panjang))
        c.endheaders()
        c.send(kepala)
        with open(jalur, "rb") as f:
            while True:
                potong = f.read(256 * 1024)
                if not potong:
                    break
                c.send(potong)
        c.send(ekor)
        r = c.getresponse()
        isi = r.read()
        c.close()
        if r.status != 200:
            raise RuntimeError("unggah ditolak (%d): %s" % (r.status, isi[:300].decode(errors="replace")))
        return json.loads(isi)


class Kamera:
    def __init__(self, sumber, perintah, folder):
        self.sumber, self.perintah, self.folder = sumber, perintah, folder
        self.geser = 0.0            # posisi di berkas sumber (kamera tiruan)

    def rekam(self, detik):
        keluar = os.path.join(self.folder, "rekaman_%d.mp4" % int(time.time()))
        if self.sumber:
            self._tiruan(detik, keluar)
        else:
            cmd = self.perintah.format(ms=int(detik * 1000), detik=int(detik), keluar=shlex.quote(keluar))
            log("merekam %d detik:" % detik, cmd)
            subprocess.run(cmd, shell=True, check=True, timeout=detik + 120)
        if not os.path.exists(keluar) or os.path.getsize(keluar) == 0:
            raise RuntimeError("perekaman tidak menghasilkan berkas")
        return keluar

    def _tiruan(self, detik, keluar):
        """Potong `detik` dari berkas sumber, lalu maju; kembali ke awal bila habis."""
        if not shutil.which("ffmpeg"):
            raise RuntimeError("kamera tiruan memerlukan ffmpeg (sudo apt install ffmpeg)")
        log("kamera tiruan: memotong %d detik dari %s (mulai %.0f s)" % (detik, os.path.basename(self.sumber), self.geser))
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-ss", "%.2f" % self.geser, "-i", self.sumber,
               "-t", str(detik), "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", keluar]
        subprocess.run(cmd, check=True, timeout=detik * 10 + 120)
        self.geser = (self.geser + detik) % max(1.0, self._durasi())

    def _durasi(self):
        try:
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                  self.sumber], capture_output=True, text=True, timeout=30).stdout
            return float(out.strip())
        except Exception:
            return 3600.0


def main():
    ap = argparse.ArgumentParser(description="Node kamera: merekam dan mengirim video ke server")
    ap.add_argument("--server", required=True, help="alamat server, mis. http://192.168.1.10:8000")
    ap.add_argument("--node", required=True, help="id node, harus terdaftar di setelan.json server")
    ap.add_argument("--token", required=True, help="token_node dari setelan.json server")
    ap.add_argument("--sumber", default=None, help="berkas video sebagai kamera tiruan (untuk uji)")
    ap.add_argument("--perintah", default=PERINTAH_BAWAAN, help="perintah rekam kamera asli")
    ap.add_argument("--jeda", type=float, default=5.0, help="detik antara tiap pertanyaan ke server")
    ap.add_argument("--toleransi", type=int, default=300, help="detik terlambat yang masih boleh untuk jadwal")
    ap.add_argument("--sekali", action="store_true", help="tanya server satu kali lalu berhenti (untuk uji)")
    a = ap.parse_args()

    sumber = os.path.expanduser(a.sumber) if a.sumber else None
    if sumber and not os.path.exists(sumber):
        sys.exit("Berkas sumber tidak ada: " + sumber)
    folder = tempfile.mkdtemp(prefix="node_kamera_")
    server, kamera = Server(a.server, a.node, a.token), Kamera(sumber, a.perintah, folder)
    log("node %s -> %s (%s)" % (a.node, a.server, "kamera tiruan" if sumber else "kamera asli"))

    def rekam_dan_kirim(detik, bidang):
        jalur = None
        try:
            jalur = kamera.rekam(detik)
            hasil = server.unggah(jalur, bidang)
            log("terkirim:", hasil)
        except Exception as e:
            log("GAGAL:", e)
        finally:
            if jalur and os.path.exists(jalur):
                os.remove(jalur)

    while True:
        try:
            t = server.tugas()
        except Exception as e:
            log("tidak bisa mengambil tugas dari server:", e)
            if a.sekali:
                sys.exit(1)
            time.sleep(a.jeda)
            continue
        for m in t["manual"]:
            log("permintaan manual", m["id"], "%d detik" % m["durasi_detik"])
            rekam_dan_kirim(m["durasi_detik"], {"mode": "manual", "id_permintaan": m["id"]})
        sekarang = time.localtime()
        detik_hari = sekarang.tm_hour * 3600 + sekarang.tm_min * 60 + sekarang.tm_sec
        for jam in t["jadwal"]:
            mulai = int(jam[:2]) * 3600 + int(jam[3:5]) * 60
            if jam not in t["sudah"] and mulai <= detik_hari <= mulai + a.toleransi:
                log("jadwal otomatis", jam)
                rekam_dan_kirim(t["durasi_detik"], {"mode": "otomatis", "slot": jam})
                break                       # tanya server lagi sebelum jadwal berikutnya
        if a.sekali:
            break
        time.sleep(a.jeda)


if __name__ == "__main__":
    main()
