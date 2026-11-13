// Antarmuka web: memanggil API server (app.py) dan menampilkan hasil.
"use strict";

const $ = (id) => document.getElementById(id);
let INFO = null;          // dari /api/info
let aktif = null;         // id job yang sedang ditampilkan
let pengatur = null;      // timer polling

function el(tag, kelas, teks) {
  const e = document.createElement(tag);
  if (kelas) e.className = kelas;
  if (teks !== undefined) e.textContent = teks;
  return e;
}
function warna(kelas) {
  const k = INFO.kelas.find((x) => x.nama === kelas);
  return k ? k.warna : "#999999";
}
function jam(detik) {
  const m = Math.floor(detik / 60), s = detik - m * 60;
  return m + ":" + (s < 10 ? "0" : "") + s.toFixed(1);
}
async function api(jalur, opsi) {
  const r = await fetch(jalur, opsi);
  if (!r.ok) {
    let pesan = "Permintaan gagal (" + r.status + ")";
    try { const j = await r.json(); if (j.detail) pesan = j.detail; } catch (e) { /* bukan JSON */ }
    throw new Error(pesan);
  }
  return r.json();
}

// ---------------------------------------------------------------- awal
async function mulai() {
  INFO = await api("/api/info");
  $("model").textContent = "Model: " + INFO.model;
  if (INFO.masalah.length) {
    const kotak = $("masalah");
    INFO.masalah.forEach((m) => kotak.appendChild(el("p", "", m)));
    kotak.hidden = false;
  }
  const pilih = $("video");
  if (!INFO.video.length) pilih.appendChild(new Option("(tidak ada video di server)", ""));
  INFO.video.forEach((v) => pilih.appendChild(new Option(v.nama + (v.ada_cache ? "  (cepat: ada cache)" : ""), v.nama)));
  for (const k of ["conf", "conf_low", "line_y", "line_y_away"]) $(k).value = INFO.bawaan[k];
  await muatRiwayat();
}

// ---------------------------------------------------------------- riwayat
const LABEL = { antre: "menunggu", proses: "diproses", selesai: "selesai", gagal: "gagal" };
async function muatRiwayat() {
  const jobs = await api("/api/jobs");
  const ul = $("riwayat");
  ul.replaceChildren();
  $("riwayat_kosong").hidden = jobs.length > 0;
  jobs.forEach((j) => {
    const b = el("button", j.id === aktif ? "aktif" : "");
    b.type = "button";
    b.appendChild(el("span", "nama", j.nama_video));
    let ket = j.dibuat + " · " + LABEL[j.status];
    if (j.status === "selesai") ket += " · " + j.total + " kendaraan";
    b.appendChild(el("span", "ket", ket));
    b.addEventListener("click", () => buka(j.id));
    const li = el("li");
    li.appendChild(b);
    ul.appendChild(li);
  });
  return jobs;
}

// ---------------------------------------------------------------- form
$("form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const galat = $("galat_form");
  galat.hidden = true;
  const data = new FormData($("form"));
  if (!$("berkas").files.length) data.delete("berkas");
  if (!$("berkas").files.length && !data.get("video")) {
    galat.textContent = "Pilih video di server atau unggah berkas video.";
    galat.hidden = false;
    return;
  }
  $("tombol").disabled = true;
  $("tombol").textContent = "Mengirim…";
  try {
    const j = await api("/api/jobs", { method: "POST", body: data });
    $("berkas").value = "";
    await buka(j.id);
  } catch (e) {
    galat.textContent = e.message;
    galat.hidden = false;
  } finally {
    $("tombol").disabled = false;
    $("tombol").textContent = "Proses";
  }
});

// ---------------------------------------------------------------- tampilan job
function tampil(nama) {
  for (const n of ["kosong", "berjalan", "gagal", "hasil"]) $(n).hidden = n !== nama;
}
async function buka(id) {
  aktif = id;
  clearTimeout(pengatur);
  await segarkan();
}
async function segarkan() {
  if (!aktif) return;
  let j;
  try {
    j = await api("/api/jobs/" + aktif);
  } catch (e) {
    aktif = null;
    tampil("kosong");
    await muatRiwayat();
    return;
  }
  if (j.status === "antre" || j.status === "proses") {
    tampil("berjalan");
    $("berjalan_judul").textContent = j.nama_video;
    $("berjalan_tahap").textContent = j.tahap;
    const p = Math.round((j.progres || 0) * 100);
    $("batang_isi").style.width = p + "%";
    $("batang_isi").parentElement.setAttribute("aria-valuenow", p);
    $("berjalan_persen").textContent = p + "%" + (j.frame_total ? " dari " + j.frame_total + " frame" : "");
    pengatur = setTimeout(segarkan, 1000);
    await muatRiwayat();
  } else if (j.status === "gagal") {
    tampil("gagal");
    $("gagal_judul").textContent = j.nama_video;
    $("gagal_pesan").textContent = j.pesan || "(tidak ada keterangan)";
    await muatRiwayat();
  } else {
    gambarHasil(j);
    tampil("hasil");
    await muatRiwayat();
  }
}
async function hapusAktif() {
  if (!aktif || !confirm("Hapus hasil ini dari riwayat? Video hasil dan lognya ikut terhapus.")) return;
  try { await api("/api/jobs/" + aktif, { method: "DELETE" }); } catch (e) { alert(e.message); return; }
  aktif = null;
  tampil("kosong");
  await muatRiwayat();
}
$("hasil_hapus").addEventListener("click", hapusAktif);
$("gagal_hapus").addEventListener("click", hapusAktif);

// ---------------------------------------------------------------- hasil
function kartuAngka(judul, nilai, warnaTitik) {
  const k = el("div", "kartu");
  const j = el("div", "judul");
  if (warnaTitik) { const t = el("span", "titik"); t.style.background = warnaTitik; j.appendChild(t); }
  j.appendChild(document.createTextNode(judul));
  k.appendChild(j);
  k.appendChild(el("div", "nilai", String(nilai)));
  return k;
}
function gambarHasil(j) {
  const r = j.ringkasan;
  const dasar = "/api/jobs/" + j.id + "/berkas/";
  $("hasil_judul").textContent = j.nama_video;
  const s = j.setelan;
  $("hasil_info").textContent = "Diproses " + j.dibuat + " · durasi video " + jam(r.durasi_detik) + " · " + j.frame_total +
    " frame · selesai dalam " + j.lama_detik + " detik · garis " + s.line_y + " m" + (r.ada_arah ? " / " + s.line_y_away + " m" : "");
  $("unduh_csv").href = dasar + "counting_log.csv";
  const v = $("pemutar");
  v.hidden = !j.ada_video;
  $("tanpa_video").hidden = !!j.ada_video;
  if (j.ada_video && v.dataset.id !== j.id) { v.src = dasar + "hasil.mp4"; v.dataset.id = j.id; }

  const angka = $("kartu_angka");
  angka.replaceChildren(kartuAngka("Total", r.total));
  INFO.kelas.forEach((k) => angka.appendChild(kartuAngka(k.nama, r.per_kelas[k.nama] || 0, k.warna)));
  if (r.ada_arah) {
    angka.appendChild(kartuAngka("Mendekat", r.per_arah.mendekat));
    angka.appendChild(kartuAngka("Menjauh", r.per_arah.menjauh));
  }
  gambarGrafik(r);

  const tb = $("tabel");
  tb.replaceChildren();
  $("tabel_kosong").hidden = r.kendaraan.length > 0;
  r.kendaraan.forEach((k) => {
    const tr = el("tr");
    tr.appendChild(el("td", "", jam(k.detik)));
    tr.appendChild(el("td", "", String(k.id)));
    const td = el("td");
    const t = el("span", "titik"); t.style.background = warna(k.kelas);
    td.appendChild(t); td.appendChild(document.createTextNode(k.kelas));
    tr.appendChild(td);
    tr.appendChild(el("td", "", r.ada_arah ? k.arah : "-"));
    tr.appendChild(el("td", "kanan", k.panjang_m.toFixed(2)));
    tr.appendChild(el("td", "kanan", k.skor === null ? "-" : k.skor.toFixed(2)));
    tr.addEventListener("click", () => {
      if (!j.ada_video) return;
      v.currentTime = Math.max(0, k.detik - 1);
      v.play().catch(() => {});
      v.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    tb.appendChild(tr);
  });
}

// grafik batang bertumpuk (SVG), satu batang per rentang waktu
function gambarGrafik(r) {
  const NS = "http://www.w3.org/2000/svg";
  const W = 720, H = 220, kiri = 30, bawah = 24, atas = 10;
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Jumlah kendaraan per rentang waktu");
  const buat = (tag, attr, teks) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attr) e.setAttribute(k, attr[k]);
    if (teks !== undefined) e.textContent = teks;
    svg.appendChild(e);
    return e;
  };
  const data = r.per_waktu;
  const jumlah = data.map((d) => INFO.kelas.reduce((a, k) => a + (d[k.nama] || 0), 0));
  const maks = Math.max(1, ...jumlah);
  const tinggi = H - bawah - atas, lebar = (W - kiri - 8) / data.length;
  const langkahY = Math.max(1, Math.ceil(maks / 4));
  for (let y = 0; y <= maks; y += langkahY) {
    const py = atas + tinggi - (y / maks) * tinggi;
    buat("line", { x1: kiri, x2: W - 8, y1: py, y2: py, class: "sumbu" });
    buat("text", { x: kiri - 6, y: py + 4, "text-anchor": "end" }, String(y));
  }
  data.forEach((d, i) => {
    let dasar = atas + tinggi;
    const x = kiri + i * lebar + lebar * 0.18, w = lebar * 0.64;
    INFO.kelas.forEach((k) => {
      const n = d[k.nama] || 0;
      if (!n) return;
      const h = (n / maks) * tinggi;
      dasar -= h;
      const rect = buat("rect", { x: x, y: dasar, width: w, height: h, fill: k.warna, rx: 2 });
      const judul = document.createElementNS(NS, "title");
      judul.textContent = jam(d.mulai) + " – " + jam(d.mulai + r.langkah_detik) + ": " + n + " " + k.nama;
      rect.appendChild(judul);
    });
    if (data.length <= 14 || i % 2 === 0) buat("text", { x: x + w / 2, y: H - 7, "text-anchor": "middle" }, jam(d.mulai).replace(".0", ""));
  });
  $("grafik").replaceChildren(svg);
  const leg = $("legenda");
  leg.replaceChildren();
  INFO.kelas.forEach((k) => {
    const s = el("span");
    const t = el("span", "titik"); t.style.background = k.warna;
    s.appendChild(t); s.appendChild(document.createTextNode(k.nama));
    leg.appendChild(s);
  });
  leg.appendChild(el("span", "", "Tiap batang = " + r.langkah_detik + " detik"));
}

mulai().catch((e) => {
  const kotak = $("masalah");
  kotak.appendChild(el("p", "", "Tidak bisa menghubungi server: " + e.message));
  kotak.hidden = false;
});
