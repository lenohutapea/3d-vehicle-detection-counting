// Antarmuka web: memanggil API server (backend/app.py) dan menampilkan empat halaman.
"use strict";

const $ = (id) => document.getElementById(id);
let INFO = null;            // dari /api/info
let halaman = "";           // halaman yang sedang tampil
let pengatur = null;        // timer penyegaran halaman
let jobAktif = null;        // id job pada tampilan rinci

// ---------------------------------------------------------------- alat kecil
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
async function api(jalur, opsi, mentah) {
  const r = await fetch(jalur, opsi);
  if (!r.ok) {
    let pesan = "Permintaan gagal (" + r.status + ")";
    try { const j = await r.json(); if (j.detail) pesan = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (e) { /* bukan JSON */ }
    throw new Error(pesan);
  }
  return mentah ? r : r.json();
}
function isiPilihan(sel, daftar, nilai) {
  const lama = nilai !== undefined ? nilai : sel.value;
  sel.replaceChildren();
  daftar.forEach(([v, t]) => sel.appendChild(new Option(t, v)));
  if (daftar.some(([v]) => v === lama)) sel.value = lama;
}
function pesan(id, teks) {
  const e = $(id);
  e.textContent = teks || "";
  e.hidden = !teks;
}
function namaNode(id) {
  const n = INFO.node.find((x) => x.id === id);
  return n ? n.nama : id;
}
const LABEL = { antre: "menunggu", proses: "diproses", selesai: "selesai", gagal: "gagal" };
const JENIS = { otomatis: "otomatis", manual: "manual", contoh: "contoh" };

// ---------------------------------------------------------------- navigasi
function rute() {
  const bagian = location.hash.replace(/^#\/?/, "").split("/");
  const hal = ["rekam", "kalibrasi", "proses", "hasil"].includes(bagian[0]) ? bagian[0] : "hasil";
  clearTimeout(pengatur);
  halaman = hal;
  for (const h of ["rekam", "kalibrasi", "proses", "hasil"]) $("hal_" + h).hidden = h !== hal;
  document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("aktif", a.dataset.hal === hal));
  ({ rekam: bukaRekam, kalibrasi: bukaKalibrasi, proses: bukaProses, hasil: () => bukaHasil(bagian[1]) })[hal]();
}
async function muatInfo() {
  INFO = await api("/api/info");
  const kotak = $("masalah");
  kotak.replaceChildren();
  INFO.masalah.forEach((m) => kotak.appendChild(el("p", "", m)));
  kotak.hidden = !INFO.masalah.length;
  const node = INFO.node.map((n) => [n.id, n.nama]);
  for (const id of ["rekam_node", "kal_node", "proses_node"]) isiPilihan($(id), node);
  isiPilihan($("cari_node"), [["", "semua"]].concat(node));
}

// ================================================================ Pengambilan video
async function bukaRekam() {
  const j = INFO.jadwal;
  $("jadwal_n").textContent = j.video_per_hari + " video";
  $("jadwal_durasi").textContent = j.durasi_detik + " detik";
  $("jadwal_rentang").textContent = j.jam_mulai + " – " + j.jam_selesai;
  $("jadwal_berkas").textContent = INFO.berkas_setelan;
  await segarkanRekam();
}
async function segarkanRekam() {
  if (halaman !== "rekam") return;
  const node = $("rekam_node").value;
  try {
    const [info, rekaman, minta] = await Promise.all([
      api("/api/info"), api("/api/rekaman?node=" + encodeURIComponent(node)), api("/api/permintaan?node=" + encodeURIComponent(node))]);
    INFO.node = info.node;
    const n = info.node.find((x) => x.id === node) || {};
    $("node_lampu").classList.toggle("hidup", !!n.terhubung);
    $("node_status").textContent = n.terhubung ? "Terhubung" : (n.terakhir ? "Tidak terhubung (terakhir " + n.terakhir + ")" : "Belum pernah terhubung");

    const hariIni = new Date().toLocaleDateString("sv-SE");
    const sudah = rekaman.filter((r) => r.mode === "otomatis" && r.waktu.startsWith(hariIni)).length;
    const ul = $("jadwal_jam");
    ul.replaceChildren();
    INFO.jadwal.jam.forEach((t, i) => ul.appendChild(el("li", i < sudah ? "sudah" : "", t)));

    const pm = $("permintaan");
    pm.replaceChildren();
    minta.slice(0, 5).forEach((r) => {
      const li = el("li");
      li.appendChild(el("span", "ket", r.dibuat + " · " + r.durasi_detik + " detik · " + r.status));
      pm.appendChild(li);
    });

    const tb = $("tabel_rekaman");
    tb.replaceChildren();
    $("rekaman_kosong").hidden = rekaman.length > 0;
    rekaman.forEach((r) => {
      const tr = el("tr", "statis");
      tr.appendChild(el("td", "", r.waktu));
      const tdJenis = el("td");
      tdJenis.appendChild(el("span", "tanda " + r.mode, JENIS[r.mode]));
      tr.appendChild(tdJenis);
      tr.appendChild(el("td", "kanan", r.ukuran_mb.toFixed(1) + " MB"));
      const terakhir = r.job[r.job.length - 1];
      tr.appendChild(el("td", "", terakhir ? LABEL[terakhir.status] : "belum diproses"));
      const aksi = el("td", "aksi_sel");
      if (terakhir) {
        const a = el("a", "tautan", "Lihat hasil");
        a.href = "#/hasil/" + terakhir.id;
        aksi.appendChild(a);
      }
      const b = el("button", "polos", terakhir ? "Proses lagi" : "Proses");
      b.type = "button";
      b.addEventListener("click", () => { sessionStorage.setItem("pilih_sumber", r.sumber); location.hash = "#/proses"; });
      aksi.appendChild(b);
      const h = el("button", "polos", "Hapus");
      h.type = "button";
      h.addEventListener("click", async () => {
        if (!confirm("Hapus rekaman " + r.waktu + "?")) return;
        try { await api("/api/rekaman?sumber=" + encodeURIComponent(r.sumber), { method: "DELETE" }); } catch (e) { alert(e.message); }
        segarkanRekam();
      });
      aksi.appendChild(h);
      tr.appendChild(aksi);
      tb.appendChild(tr);
    });
  } catch (e) { /* server sedang tidak terjangkau; coba lagi */ }
  clearTimeout(pengatur);
  pengatur = setTimeout(segarkanRekam, 3000);
}
$("rekam_node").addEventListener("change", segarkanRekam);
$("form_rekam").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  pesan("rekam_pesan", "");
  const data = new FormData();
  data.append("durasi", $("rekam_durasi").value);
  try { await api("/api/kamera/" + encodeURIComponent($("rekam_node").value) + "/rekam", { method: "POST", body: data }); }
  catch (e) { pesan("rekam_pesan", e.message); }
  segarkanRekam();
});
$("form_unggah").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  pesan("unggah_pesan", "");
  if (!$("unggah_berkas").files.length) { pesan("unggah_pesan", "Pilih berkas video dulu."); return; }
  const data = new FormData();
  data.append("node", $("rekam_node").value);
  data.append("berkas", $("unggah_berkas").files[0]);
  try { await api("/api/rekaman", { method: "POST", body: data }); $("unggah_berkas").value = ""; }
  catch (e) { pesan("unggah_pesan", e.message); }
  segarkanRekam();
});

// ================================================================ Kalibrasi kamera
const KUNCI_KAL = ["PITCH_DEG", "CAM_HEIGHT_M", "FOCAL_PX", "LINE_Y_DEFAULT_M", "LINE_Y_AWAY_M", "MEDIAN_X_M", "LANE_HALF_WIDTH_M", "MAX_TRACK_DEPTH_M"];
let tundaPratinjau = null, nomorPratinjau = 0;

async function daftarSumber(node) {
  const rekaman = await api("/api/rekaman" + (node ? "?node=" + encodeURIComponent(node) : ""));
  return rekaman.map((r) => [r.sumber, r.waktu + " · " + namaNode(r.node) + " · " + JENIS[r.mode]])
    .concat(INFO.contoh.map((c) => ["contoh/" + c, "contoh · " + c]));
}
async function bukaKalibrasi() {
  await muatProfil();
}
async function muatProfil() {
  pesan("kal_pesan", ""); pesan("kal_ok", "");
  const node = $("kal_node").value;
  isiPilihan($("kal_sumber"), await daftarSumber(node));
  const p = await api("/api/kamera/" + encodeURIComponent(node) + "/profil");
  KUNCI_KAL.forEach((k) => { $(k).value = p[k]; });
  document.querySelectorAll("input[data-untuk]").forEach((r) => { r.value = $(r.dataset.untuk).value; });
  document.querySelectorAll("input[name=mode]").forEach((r) => { r.checked = r.value === p.mode; });
  $("xml").value = "";
  $("kal_xml_ket").textContent = p.ada_xml ? "Berkas kalibrasi tersimpan: " + p.CALIB_XML : "Belum ada berkas kalibrasi tersimpan untuk node ini.";
  $("kal_tersimpan").textContent = p.tersimpan ? "Terakhir disimpan " + p.tersimpan : "Belum pernah disimpan (memakai nilai bawaan pipeline).";
  tampilMode();
  pratinjau();
}
function tampilMode() {
  const xml = document.querySelector("input[name=mode]:checked").value === "xml";
  $("kal_nilai").hidden = xml;
  $("kal_xml").hidden = !xml;
}
function formulirKalibrasi() {
  const data = new FormData();
  KUNCI_KAL.forEach((k) => data.append(k, $(k).value));
  data.append("mode", document.querySelector("input[name=mode]:checked").value);
  if ($("xml").files.length) data.append("xml", $("xml").files[0]);
  return data;
}
function pratinjau() {
  clearTimeout(tundaPratinjau);
  tundaPratinjau = setTimeout(async () => {
    if (!$("kal_sumber").value) { pesan("pratinjau_pesan", "Belum ada video untuk pratinjau. Rekam atau unggah video dulu."); return; }
    const nomor = ++nomorPratinjau;
    const data = formulirKalibrasi();
    data.append("sumber", $("kal_sumber").value);
    data.append("posisi", $("kal_posisi").value);
    try {
      const r = await api("/api/kamera/" + encodeURIComponent($("kal_node").value) + "/pratinjau", { method: "POST", body: data }, true);
      const blob = await r.blob();
      if (nomor !== nomorPratinjau) return;          // sudah ada permintaan yang lebih baru
      const lama = $("pratinjau_gbr").src;
      $("pratinjau_gbr").src = URL.createObjectURL(blob);
      if (lama.startsWith("blob:")) URL.revokeObjectURL(lama);
      pesan("pratinjau_pesan", "");
    } catch (e) { if (nomor === nomorPratinjau) pesan("pratinjau_pesan", e.message); }
  }, 250);
}
$("kal_node").addEventListener("change", muatProfil);
$("form_kal").addEventListener("input", (ev) => {
  const t = ev.target;
  if (t.dataset.untuk) $(t.dataset.untuk).value = t.value;                       // penggeser -> angka
  const geser = document.querySelector('input[data-untuk="' + t.id + '"]');
  if (geser) geser.value = t.value;                                              // angka -> penggeser
  if (t.name === "mode") tampilMode();
  pesan("kal_ok", "");
  pratinjau();
});
$("form_kal").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  pesan("kal_pesan", ""); pesan("kal_ok", "");
  try {
    const p = await api("/api/kamera/" + encodeURIComponent($("kal_node").value) + "/profil", { method: "POST", body: formulirKalibrasi() });
    await muatInfo();
    await muatProfil();
    pesan("kal_ok", "Profil tersimpan (" + p.tersimpan + "). Berlaku untuk video yang diproses setelah ini.");
  } catch (e) { pesan("kal_pesan", e.message); }
});

// ================================================================ Proses
async function bukaProses() {
  pesan("galat_form", "");
  isiPilihan($("proses_model"), INFO.model.map((m) => [m, m]));
  if (!$("conf").value) { $("conf").value = INFO.bawaan.conf; $("conf_low").value = INFO.bawaan.conf_low; }
  const pilih = sessionStorage.getItem("pilih_sumber");
  sessionStorage.removeItem("pilih_sumber");
  isiPilihan($("proses_sumber"), await daftarSumber(""), pilih || undefined);
  ikutiNode();
  await segarkanAntrean();
}
function ikutiNode() {                       // rekaman -> profil node pemiliknya
  const b = $("proses_sumber").value.split("/");
  if (b[0] === "rekaman" && INFO.node.some((n) => n.id === b[1])) $("proses_node").value = b[1];
}
$("proses_sumber").addEventListener("change", ikutiNode);
async function segarkanAntrean() {
  if (halaman !== "proses") return;
  try {
    const jobs = (await api("/api/jobs")).filter((j) => j.status === "antre" || j.status === "proses");
    const tb = $("tabel_antrean");
    tb.replaceChildren();
    $("antrean_kosong").hidden = jobs.length > 0;
    jobs.reverse().forEach((j) => {
      const tr = el("tr");
      tr.appendChild(el("td", "", j.nama_video));
      tr.appendChild(el("td", "", j.model));
      tr.appendChild(el("td", "", j.status === "proses" ? j.tahap : LABEL[j.status]));
      tr.appendChild(el("td", "kanan", Math.round((j.progres || 0) * 100) + "%"));
      tr.addEventListener("click", () => { location.hash = "#/hasil/" + j.id; });
      tb.appendChild(tr);
    });
  } catch (e) { /* coba lagi */ }
  clearTimeout(pengatur);
  pengatur = setTimeout(segarkanAntrean, 1500);
}
$("form_proses").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  pesan("galat_form", "");
  if (!$("proses_sumber").value) { pesan("galat_form", "Belum ada video. Rekam atau unggah video di halaman Pengambilan video."); return; }
  const data = new FormData();
  data.append("sumber", $("proses_sumber").value);
  data.append("node", $("proses_node").value);
  data.append("model", $("proses_model").value);
  data.append("conf", $("conf").value);
  data.append("conf_low", $("conf_low").value);
  $("tombol").disabled = true;
  try {
    const j = await api("/api/jobs", { method: "POST", body: data });
    location.hash = "#/hasil/" + j.id;
  } catch (e) { pesan("galat_form", e.message); }
  finally { $("tombol").disabled = false; }
});

// ================================================================ Hasil
async function bukaHasil(id) {
  jobAktif = id || null;
  $("hasil_daftar").hidden = !!id;
  $("hasil_rinci").hidden = !id;
  if (id) await segarkanRinci(); else await segarkanDaftar();
}
async function segarkanDaftar() {
  if (halaman !== "hasil" || jobAktif) return;
  try {
    const jobs = await api("/api/jobs");
    const nama = $("cari_nama").value.trim().toLowerCase(), tgl = $("cari_tanggal").value, node = $("cari_node").value;
    const cocok = jobs.filter((j) => (!nama || j.nama_video.toLowerCase().includes(nama)) &&
      (!tgl || (j.waktu_video || "").startsWith(tgl)) && (!node || j.node === node))
      .sort((x, y) => (y.waktu_video || y.dibuat).localeCompare(x.waktu_video || x.dibuat));   // rekaman terbaru di atas
    $("kepala_kelas").textContent = INFO.kelas.map((k) => k.nama).join(" / ");
    const tb = $("tabel_hasil");
    tb.replaceChildren();
    $("hasil_kosong").hidden = cocok.length > 0;
    cocok.forEach((j) => {
      const tr = el("tr");
      tr.appendChild(el("td", "", j.waktu_video || j.dibuat));
      tr.appendChild(el("td", "", j.nama_video));
      tr.appendChild(el("td", "", namaNode(j.node || "")));
      tr.appendChild(el("td", "", j.model || "-"));
      const tdJenis = el("td");
      tdJenis.appendChild(el("span", "tanda " + (j.pemicu || ""), JENIS[j.pemicu] || "-"));
      tr.appendChild(tdJenis);
      tr.appendChild(el("td", "", j.status === "proses" ? "diproses " + Math.round((j.progres || 0) * 100) + "%" : LABEL[j.status]));
      tr.appendChild(el("td", "kanan", j.status === "selesai" ? String(j.total) : "-"));
      tr.appendChild(el("td", "", j.status === "selesai" && j.per_kelas ? INFO.kelas.map((k) => j.per_kelas[k.nama] || 0).join(" / ") : "-"));
      tr.addEventListener("click", () => { location.hash = "#/hasil/" + j.id; });
      tb.appendChild(tr);
    });
  } catch (e) { /* coba lagi */ }
  clearTimeout(pengatur);
  pengatur = setTimeout(segarkanDaftar, 3000);
}
for (const id of ["cari_nama", "cari_tanggal", "cari_node"]) $(id).addEventListener("input", segarkanDaftar);
$("kembali").addEventListener("click", () => { location.hash = "#/hasil"; });

function tampilRinci(nama) {
  for (const n of ["berjalan", "gagal", "hasil"]) $(n).hidden = n !== nama;
}
async function segarkanRinci() {
  if (halaman !== "hasil" || !jobAktif) return;
  let j;
  try { j = await api("/api/jobs/" + jobAktif); }
  catch (e) { location.hash = "#/hasil"; return; }
  if (j.status === "antre" || j.status === "proses") {
    tampilRinci("berjalan");
    $("berjalan_judul").textContent = j.nama_video;
    $("berjalan_tahap").textContent = j.tahap;
    const p = Math.round((j.progres || 0) * 100);
    $("batang_isi").style.width = p + "%";
    $("batang_isi").parentElement.setAttribute("aria-valuenow", p);
    $("berjalan_persen").textContent = p + "%" + (j.frame_total ? " dari " + j.frame_total + " frame" : "");
    clearTimeout(pengatur);
    pengatur = setTimeout(segarkanRinci, 1000);
  } else if (j.status === "gagal") {
    tampilRinci("gagal");
    $("gagal_judul").textContent = j.nama_video;
    $("gagal_pesan").textContent = j.pesan || "(tidak ada keterangan)";
  } else {
    gambarHasil(j);
    tampilRinci("hasil");
  }
}
async function hapusAktif() {
  if (!jobAktif || !confirm("Hapus hasil ini? Video hasil dan lognya ikut terhapus. Rekaman aslinya tidak dihapus.")) return;
  try { await api("/api/jobs/" + jobAktif, { method: "DELETE" }); } catch (e) { alert(e.message); return; }
  location.hash = "#/hasil";
}
$("hasil_hapus").addEventListener("click", hapusAktif);
$("gagal_hapus").addEventListener("click", hapusAktif);

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
  const g = j.garis || {};
  $("hasil_info").textContent = "Direkam " + (j.waktu_video || "-") + " · " + namaNode(j.node || "") + " · model " + (j.model || "-") +
    " · durasi " + jam(r.durasi_detik) + " · " + j.frame_total + " frame · diproses " + j.dibuat + " dalam " + j.lama_detik + " detik" +
    (g.mendekat !== undefined ? " · garis " + g.mendekat + " m / " + g.menjauh + " m" : "");
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

// ---------------------------------------------------------------- mulai
window.addEventListener("hashchange", rute);
muatInfo().then(rute).catch((e) => {
  const kotak = $("masalah");
  kotak.appendChild(el("p", "", "Tidak bisa menghubungi server: " + e.message));
  kotak.hidden = false;
});
