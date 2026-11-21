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
const HALAMAN = ["rekam", "kamera", "kalibrasi", "proses", "hasil"];
function rute() {
  const bagian = location.hash.replace(/^#\/?/, "").split("/");
  const hal = HALAMAN.includes(bagian[0]) ? bagian[0] : "hasil";
  clearTimeout(pengatur);
  halaman = hal;
  for (const h of HALAMAN) $("hal_" + h).hidden = h !== hal;
  document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("aktif", a.dataset.hal === hal));
  ({ rekam: bukaRekam, kamera: () => bukaKamera(bagian[1]), kalibrasi: () => bukaKalibrasi(bagian[1]), proses: bukaProses, hasil: () => bukaHasil(bagian[1]) })[hal]();
}
async function muatInfo() {
  INFO = await api("/api/info");
  const kotak = $("masalah");
  kotak.replaceChildren();
  INFO.masalah.forEach((m) => kotak.appendChild(el("p", "", m)));
  kotak.hidden = !INFO.masalah.length;
  const aktif = INFO.node.filter((n) => n.aktif !== false).map((n) => [n.id, n.nama]);   // kamera nonaktif disembunyikan
  for (const id of ["rekam_node", "kal_node", "proses_node"]) isiPilihan($(id), aktif);
  isiPilihan($("cari_node"), [["", "semua"]].concat(INFO.node.map((n) => [n.id, n.nama])));
}

// ================================================================ Pengambilan video
async function bukaRekam() {
  try { await muatJadwal(true); } catch (e) { pesan("jadwal_pesan", e.message); }
  await segarkanRekam();
}
// jadwal otomatis: bawaan di 2_automatic/schedule.json, perubahan dari web di data/schedule/
async function muatJadwal(isiFormulir) {
  const j = await api("/api/jadwal");
  const a = j.aktif;
  INFO.jadwal = Object.assign({}, a, { jam: j.jam });
  $("jadwal_n").textContent = a.video_per_hari + " video";
  $("jadwal_durasi").textContent = a.durasi_detik + " detik";
  $("jadwal_rentang").textContent = a.jam_mulai + " – " + a.jam_selesai;
  $("jadwal_sumber").textContent = j.sumber === "riwayat"
    ? "Memakai jadwal versi " + j.versi + (a.tersimpan ? " (disimpan " + a.tersimpan + ")" : "") + "."
    : "Memakai jadwal bawaan (2_automatic/schedule.json).";
  if (isiFormulir) {
    $("j_n").value = a.video_per_hari; $("j_durasi").value = a.durasi_detik;
    $("j_mulai").value = a.jam_mulai; $("j_selesai").value = a.jam_selesai;
  }
  const ul = $("jadwal_riwayat");
  ul.replaceChildren();
  j.riwayat.forEach((v) => {
    const li = el("li");
    li.appendChild(el("span", "ket", v.versi + " · " + v.video_per_hari + " video · " + v.durasi_detik + " detik · " +
      v.jam_mulai + "–" + v.jam_selesai + (v.aktif ? " · sedang dipakai" : "")));
    if (!v.aktif) {
      const b = el("button", "polos", "Pakai versi ini");
      b.type = "button";
      b.addEventListener("click", async () => {
        try { await api("/api/jadwal/riwayat/" + encodeURIComponent(v.versi), { method: "POST" }); await muatJadwal(true); segarkanRekam(); }
        catch (e) { pesan("jadwal_pesan", e.message); }
      });
      li.appendChild(b);
    }
    ul.appendChild(li);
  });
  $("jadwal_riwayat_kosong").hidden = j.riwayat.length > 0;
  $("jadwal_bawaan").hidden = j.sumber !== "riwayat";
}
$("form_jadwal").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  pesan("jadwal_pesan", ""); pesan("jadwal_ok", "");
  const data = new FormData();
  data.append("video_per_hari", $("j_n").value);
  data.append("durasi_detik", $("j_durasi").value);
  data.append("jam_mulai", $("j_mulai").value);
  data.append("jam_selesai", $("j_selesai").value);
  try {
    const j = await api("/api/jadwal", { method: "POST", body: data });
    await muatJadwal(true);
    segarkanRekam();
    pesan("jadwal_ok", "Jadwal tersimpan sebagai versi " + j.versi + " dan langsung berlaku.");
  } catch (e) { pesan("jadwal_pesan", e.message); }
});
$("jadwal_bawaan").addEventListener("click", async () => {
  if (!confirm("Kembali ke jadwal bawaan? Riwayat jadwal tetap disimpan.")) return;
  pesan("jadwal_pesan", ""); pesan("jadwal_ok", "");
  try { await api("/api/jadwal/bawaan", { method: "POST" }); await muatJadwal(true); segarkanRekam(); }
  catch (e) { pesan("jadwal_pesan", e.message); }
});
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
let profilAktif = null;                                  // profil node yang sedang dibuka
let klik = { langkah: null, A: [], B: [], P: [] };      // titik klik (piksel frame IMG_W x IMG_H)
let klikXml = null, klikData = null;
let adaUbahan = false;                                   // ada perubahan yang belum disimpan                     // hasil "Hitung kalibrasi" yang belum disimpan
const WARNA_KLIK = { A: "#2563eb", B: "#d97706", P: "#db2777" };

async function daftarSumber(node) {
  const rekaman = await api("/api/rekaman" + (node ? "?node=" + encodeURIComponent(node) : ""));
  return rekaman.map((r) => [r.sumber, r.waktu + " · " + namaNode(r.node) + " · " + JENIS[r.mode]])
    .concat(INFO.contoh.map((c) => ["contoh/" + c, "contoh · " + c]));
}
async function bukaKalibrasi(node) {
  if (node && [...$("kal_node").options].some((o) => o.value === node)) $("kal_node").value = node;
  await muatProfil();
}
function tampilHasil(h, tersimpan) {
  $("hasil_klik").hidden = !h;
  if (!h) { pesan("klik_hasil", ""); return; }
  $("h_tinggi").textContent = Number(h.h).toFixed(2) + " m";
  $("h_sudut").textContent = Number(h.sudut_tunduk).toFixed(1) + "°";
  $("h_focal").textContent = Math.round(h.f) + " px";
  pesan("klik_hasil", tersimpan ? "Ini hasil klik yang tersimpan di versi aktif."
    : "Periksa pratinjau: kisi sejajar marka dan kotak hijau seukuran mobil. Bila sudah pas, simpan di langkah 4.");
}
function tandaiTahap() {
  const m = modeKal();
  const t2 = m === "klik" ? (klikXml || (profilAktif && profilAktif.klik && ["A", "B", "P"].every((n) => klik[n].length === 2)))
    : (m === "nilai" || !!(profilAktif && profilAktif.ada_xml) || $("xml").files.length > 0);
  const status = [true, !!t2, !!t2, !!t2 && !adaUbahan && !!profilAktif && profilAktif.sumber_profil === "riwayat"];
  const kini = status.indexOf(false);
  status.forEach((ok, i) => {
    const li = $("tahap" + (i + 1)), b = li.querySelector(".bulat");
    li.className = ok ? "selesai" : (i === kini ? "kini" : "");
    b.textContent = ok ? "✓" : String(i + 1);
    $("nomor" + (i + 1)).className = "nomor" + (ok ? " selesai" : "");
    $("nomor" + (i + 1)).textContent = ok ? "✓" : String(i + 1);
  });
  $("kartu2").classList.toggle("kartu_aktif", !t2);
}
async function muatProfil() {
  pesan("kal_pesan", ""); pesan("kal_ok", "");
  const node = $("kal_node").value;
  isiPilihan($("kal_sumber"), await daftarSumber(node));
  const p = await api("/api/kamera/" + encodeURIComponent(node) + "/profil");
  KUNCI_KAL.forEach((k) => { $(k).value = p[k]; });
  document.querySelectorAll("input[data-untuk]").forEach((r) => { r.value = $(r.dataset.untuk).value; });
  profilAktif = p;
  const k = p.klik;
  klik = { langkah: null, A: k ? k.A : [], B: k ? k.B : [], P: k ? k.P : [] };
  klikXml = null; klikData = null; adaUbahan = false;
  if (k) { $("klik_lebar").value = k.lebar; $("klik_panjang").value = k.panjang; }
  pesan("klik_pesan", "");
  tampilHasil(k && k.hasil, true);
  const metode = p.metode === "klik" ? "klik" : (p.sumber_profil === "riwayat" || p.sumber_profil === "bawaan" ? p.mode : "klik");
  document.querySelectorAll("input[name=mode]").forEach((r) => { r.checked = r.value === metode; });
  $("kal_lanjutan").open = metode === "xml";
  $("xml").value = "";
  $("kal_xml_ket").textContent = p.ada_xml ? "Berkas kalibrasi tersimpan: " + p.CALIB_XML : "Belum ada berkas kalibrasi tersimpan untuk node ini.";
  const ks = $("kal_tersimpan");
  ks.replaceChildren(el("span", "chip " + (p.sumber_profil === "riwayat" ? "chip_hijau" : "chip_abu"),
    p.sumber_profil === "riwayat" ? "Versi aktif " + p.versi : (p.sumber_profil === "bawaan" ? "Profil bawaan" : "Belum dikalibrasi")),
  document.createTextNode(p.sumber_profil === "riwayat" ? (p.tersimpan ? " disimpan " + p.tersimpan : "")
    : (p.sumber_profil === "bawaan" ? " dari 1_camera_calibration/camera_profiles" : " memakai nilai awal config.py")));
  $("kal_bawaan").hidden = p.sumber_profil !== "riwayat";
  const kanan = p.LAJUR === "kanan";
  $("kal_lajur").replaceChildren(el("strong", "", kanan ? "Lajur kanan (data latihan dari Ceko). " : "Lajur kiri (Indonesia). "),
    document.createTextNode(kanan ? "Kanan median = menjauh dari kamera, kiri median = mendekat."
      : "Kendaraan di kiri median bergerak menjauh dari kamera, di kanan median mendekat."));
  $("ket_dekat").textContent = "Dihitung saat melewati garis merah (" + (kanan ? "kiri" : "kanan") + " median).";
  $("ket_jauh").textContent = "Dihitung saat melewati garis ungu (" + (kanan ? "kanan" : "kiri") + " median).";
  muatRiwayatKal();
  tampilMode();
  pratinjau();
}
async function muatRiwayatKal() {
  const node = $("kal_node").value;
  pesan("kal_riwayat_pesan", "");
  try {
    const daftar = await api("/api/kamera/" + encodeURIComponent(node) + "/riwayat");
    const ul = $("kal_riwayat");
    ul.replaceChildren();
    daftar.forEach((v) => {
      const li = el("li");
      const isi = v.metode === "xml" ? "berkas kalibrasi"
        : (v.metode === "klik" ? "klik · " : "") + "sudut " + v.PITCH_DEG + "° · tinggi " + v.CAM_HEIGHT_M + " m · focal " + v.FOCAL_PX;
      if (v.aktif) li.className = "dipakai";
      const ket = el("div", "ket");
      ket.appendChild(el("strong", "mono", v.versi));
      ket.appendChild(el("span", "redup kecil", isi + " · garis " + v.LINE_Y_DEFAULT_M + "/" + v.LINE_Y_AWAY_M + " m"));
      li.appendChild(ket);
      if (v.aktif) li.appendChild(el("span", "chip chip_hijau", "Sedang dipakai"));
      else {
        const b = el("button", "polos", "Pakai versi ini");
        b.type = "button";
        b.addEventListener("click", async () => {
          try { await api("/api/kamera/" + encodeURIComponent(node) + "/riwayat/" + encodeURIComponent(v.versi), { method: "POST" }); await muatProfil(); }
          catch (e) { pesan("kal_riwayat_pesan", e.message); }
        });
        li.appendChild(b);
      }
      ul.appendChild(li);
    });
    $("kal_riwayat_kosong").hidden = daftar.length > 0;
  } catch (e) { pesan("kal_riwayat_pesan", e.message); }
}
$("kal_bawaan").addEventListener("click", async () => {
  if (!confirm("Kembali ke profil bawaan untuk node ini? Riwayat kalibrasi tetap disimpan.")) return;
  try { await api("/api/kamera/" + encodeURIComponent($("kal_node").value) + "/bawaan", { method: "POST" }); await muatProfil(); }
  catch (e) { pesan("kal_riwayat_pesan", e.message); }
});
function modeKal() {
  const r = document.querySelector("input[name=mode]:checked");
  return r ? r.value : "nilai";
}
function tampilMode() {
  const m = modeKal();
  $("kal_klik").hidden = m !== "klik";
  $("kal_nilai").hidden = m !== "nilai";
  $("kal_xml").hidden = m !== "xml";
  if (m !== "klik") pilihLangkah(null);
  else if (!klik.langkah && ["A", "B", "P"].some((k) => klik[k].length < 2)) pilihLangkah(["A", "B", "P"].find((k) => klik[k].length < 2));
  else pilihLangkah(klik.langkah);
}
function formulirKalibrasi() {
  const data = new FormData();
  KUNCI_KAL.forEach((k) => data.append(k, $(k).value));
  const m = modeKal();
  if (m === "klik") {
    if (klikXml) {                                   // hasil "Hitung kalibrasi" yang baru
      data.append("mode", "xml");
      data.append("xml", new File([klikXml], "klik.xml", { type: "text/xml" }));
      data.append("klik", JSON.stringify(klikData));
    } else {                                         // belum menghitung: pakai profil yang ada
      data.append("mode", profilAktif ? profilAktif.mode : "nilai");
      if (profilAktif && profilAktif.klik) data.append("klik", JSON.stringify(profilAktif.klik));
    }
  } else {
    data.append("mode", m);
    if (m === "xml" && $("xml").files.length) data.append("xml", $("xml").files[0]);
  }
  return data;
}
// ---------------------------------------------------------------- kalibrasi dengan klik
function pilihLangkah(k) {
  klik.langkah = k || null;
  document.querySelectorAll("[data-langkah]").forEach((b) => b.classList.toggle("aktif_langkah", b.dataset.langkah === klik.langkah));
  $("kal_kanvas").classList.toggle("bisa_klik", !!klik.langkah && modeKal() === "klik");
  const NAMA = { A: "garis A", B: "garis B", P: "panjang" };
  for (const n of ["A", "B", "P"]) {
    const c = $("status_" + n), jml = klik[n].length;
    c.textContent = jml === 2 ? "✓ 2 titik" : (klik.langkah === n ? "Klik " + (2 - jml) + " titik lagi" : (jml ? "1 dari 2 titik" : "Belum"));
    c.className = "chip " + (jml === 2 ? "chip_hijau" : (klik.langkah === n ? "chip_kuning" : "chip_abu"));
    document.querySelector('[data-baris="' + n + '"]').classList.toggle("sedang", klik.langkah === n);
    document.querySelector('[data-langkah="' + n + '"]').textContent = jml ? "Ulangi " + NAMA[n] : "Tandai " + NAMA[n];
  }
  const p = $("klik_petunjuk");
  if (klik.langkah && modeKal() === "klik") {
    const ke = klik[klik.langkah].length + 1;
    p.className = "petunjuk p_" + klik.langkah.toLowerCase();
    p.replaceChildren(el("span", "lencana_l l_" + klik.langkah.toLowerCase(), klik.langkah),
      el("span", "", "Sekarang: klik titik ke-" + ke + " untuk " + NAMA[klik.langkah] +
        (klik.langkah === "P" ? " (searah jalan)" : (ke === 1 ? " — titik dekat, di bawah gambar" : " — titik jauh, di depan"))));
    p.hidden = false;
  } else p.hidden = true;
  tandaiTahap();
  gambarKlik();
}
function gambarKlik() {
  const img = $("pratinjau_gbr"), kv = $("kal_kanvas");
  const w = img.clientWidth, h = img.clientHeight;
  kv.width = w; kv.height = h;
  const c = kv.getContext("2d");
  c.clearRect(0, 0, w, h);
  if (modeKal() !== "klik" || !w) return;
  const sx = w / (img.naturalWidth || 1280), sy = h / (img.naturalHeight || 720);
  for (const n of ["A", "B", "P"]) {
    const t = klik[n];
    c.strokeStyle = c.fillStyle = WARNA_KLIK[n];
    c.lineWidth = 2;
    if (t.length === 2) {
      if (n !== "P") {                                // garis A/B diperpanjang agar terlihat menuju titik hilang
        const dx = t[1][0] - t[0][0], dy = t[1][1] - t[0][1];
        c.setLineDash([6, 5]); c.globalAlpha = 0.6;
        c.beginPath(); c.moveTo((t[0][0] - 2 * dx) * sx, (t[0][1] - 2 * dy) * sy); c.lineTo((t[0][0] + 6 * dx) * sx, (t[0][1] + 6 * dy) * sy); c.stroke();
        c.setLineDash([]); c.globalAlpha = 1;
      }
      c.lineWidth = 3;
      c.beginPath(); c.moveTo(t[0][0] * sx, t[0][1] * sy); c.lineTo(t[1][0] * sx, t[1][1] * sy); c.stroke();
      c.font = "bold 13px sans-serif";
      c.fillText(n === "P" ? "panjang" : "garis " + n, t[1][0] * sx + 7, t[1][1] * sy - 7);
    }
    t.forEach(([u, v]) => { c.beginPath(); c.arc(u * sx, v * sy, 5, 0, 2 * Math.PI); c.fill(); });
  }
}
$("kal_kanvas").addEventListener("click", (ev) => {
  if (modeKal() !== "klik" || !klik.langkah) return;
  const img = $("pratinjau_gbr"), r = ev.currentTarget.getBoundingClientRect();
  const u = (ev.clientX - r.left) * (img.naturalWidth || 1280) / r.width;
  const v = (ev.clientY - r.top) * (img.naturalHeight || 720) / r.height;
  const t = klik[klik.langkah];
  if (t.length >= 2) t.length = 0;
  t.push([Math.round(u * 10) / 10, Math.round(v * 10) / 10]);
  klikXml = null; adaUbahan = true;                  // titik berubah: perlu dihitung ulang
  tampilHasil(null);
  if (t.length === 2) pilihLangkah(["A", "B", "P"].find((n) => klik[n].length < 2) || null);
  else pilihLangkah(klik.langkah);
});
document.querySelectorAll("[data-langkah]").forEach((b) => b.addEventListener("click", () => {
  klik[b.dataset.langkah] = []; adaUbahan = true;
  klikXml = null;
  pilihLangkah(b.dataset.langkah);
}));
$("klik_ulang").addEventListener("click", () => {
  klik = { langkah: null, A: [], B: [], P: [] };
  klikXml = null; klikData = null; adaUbahan = true;
  pesan("klik_pesan", ""); tampilHasil(null);
  pilihLangkah("A");
});
$("klik_hitung").addEventListener("click", async () => {
  pesan("klik_pesan", ""); tampilHasil(null); pesan("kal_ok", "");
  if (["A", "B", "P"].some((n) => klik[n].length < 2)) {
    pesan("klik_pesan", "Lengkapi dulu garis A, garis B, dan panjang (masing-masing 2 titik di gambar).");
    return;
  }
  const isi = { A: klik.A, B: klik.B, P: klik.P, lebar: Number($("klik_lebar").value), panjang: Number($("klik_panjang").value) };
  try {
    const r = await api("/api/kamera/" + encodeURIComponent($("kal_node").value) + "/kalibrasi-klik",
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(isi) });
    klikXml = r.xml; adaUbahan = true;
    klikData = Object.assign({}, isi, { hasil: { f: r.hasil.f, h: r.hasil.h, sudut_tunduk: r.hasil.sudut_tunduk } });
    for (const [n, v] of Object.entries(r.nilai)) { $(n).value = v; const g = document.querySelector('input[data-untuk="' + n + '"]'); if (g) g.value = v; }
    tampilHasil(r.hasil, false);
    pilihLangkah(null);
    pratinjau();
  } catch (e) { pesan("klik_pesan", e.message); }
});
$("pratinjau_gbr").addEventListener("load", gambarKlik);
$("buka_panduan").addEventListener("click", () => $("dlg_panduan").showModal());
window.addEventListener("resize", gambarKlik);
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
  if (t.id === "klik_lebar" || t.id === "klik_panjang") klikXml = null;
  if (t.id !== "kal_posisi" && t.id !== "kal_sumber") adaUbahan = true;
  tandaiTahap();
  pesan("kal_ok", "");
  pratinjau();
});
$("form_kal").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  pesan("kal_pesan", ""); pesan("kal_ok", "");
  if (modeKal() === "klik" && !klikXml && !(profilAktif && profilAktif.klik)) {
    pesan("kal_pesan", "Klik titik-titiknya di gambar lalu tekan Hitung kalibrasi sebelum menyimpan.");
    return;
  }
  try {
    const p = await api("/api/kamera/" + encodeURIComponent($("kal_node").value) + "/profil", { method: "POST", body: formulirKalibrasi() });
    await muatInfo();
    await muatProfil();
    pesan("kal_ok", "Kalibrasi tersimpan sebagai versi " + p.versi + ". Berlaku untuk video yang diproses setelah ini.");
  } catch (e) { pesan("kal_pesan", e.message); }
});

// ================================================================ Kamera (kelola node)
let kamDaftar = [], kamPilih = null, kamToken = null, kamSalin = null;
const STATUS_KAM = (k) => !k.aktif ? ["Nonaktif", "s_abu"] : k.jenis === "data" ? ["Data latihan", "s_biru"]
  : k.terhubung ? ["Terhubung", "s_hijau"] : k.terakhir ? ["Terputus", "s_merah"] : ["Menunggu perangkat", "s_kuning"];

async function bukaKamera(id) {
  if (id) kamPilih = decodeURIComponent(id);
  await segarkanKamera();
}
async function segarkanKamera() {
  if (halaman !== "kamera") return;
  try {
    kamDaftar = await api("/api/kamera");
    pesan("kam_pesan", "");
  } catch (e) { pesan("kam_pesan", e.message); }
  if (!kamDaftar.some((k) => k.id === kamPilih)) kamPilih = kamDaftar.length ? kamDaftar[0].id : null;
  gambarDaftarKamera();
  gambarRinciKamera();
  clearTimeout(pengatur);
  pengatur = setTimeout(segarkanKamera, 5000);
}
function waktuLalu(d) {
  if (d === null || d === undefined) return "belum pernah";
  if (d < 60) return d + " detik lalu";
  if (d < 3600) return Math.round(d / 60) + " menit lalu";
  if (d < 86400) return Math.round(d / 3600) + " jam lalu";
  return Math.round(d / 86400) + " hari lalu";
}
function teksKal(k) {
  const s = k.kalibrasi && k.kalibrasi.sumber;
  return s === "riwayat" ? "versi " + k.kalibrasi.versi : s === "bawaan" ? "profil bawaan" : "belum dikalibrasi";
}
function gambarDaftarKamera() {
  const box = $("kam_daftar");
  box.replaceChildren();
  const nyambung = kamDaftar.filter((k) => k.terhubung).length;
  $("kam_ringkas").textContent = kamDaftar.length + " kamera · " + nyambung + " terhubung";
  kamDaftar.forEach((k) => {
    const b = el("button", "item_kamera" + (k.id === kamPilih ? " dipilih" : "") + (k.aktif ? "" : " mati"));
    b.type = "button";
    const [st, kls] = STATUS_KAM(k);
    const atas = el("div", "atas_item");
    atas.appendChild(el("strong", "", k.nama));
    atas.appendChild(el("span", "st_kam " + kls, st));
    b.appendChild(atas);
    b.appendChild(el("span", "redup kecil", k.id + " · " + k.jenis_nama));
    const chip = el("div", "chips");
    chip.appendChild(el("span", "chip " + (k.kalibrasi.sumber === "riwayat" ? "chip_hijau" : "chip_abu"), "Kalibrasi: " + teksKal(k)));
    if (k.jenis !== "data") chip.appendChild(el("span", "chip chip_abu", "Lapor: " + waktuLalu(k.detik_lalu)));
    b.appendChild(chip);
    b.addEventListener("click", () => { kamPilih = k.id; kamToken = null; history.replaceState(null, "", "#/kamera/" + encodeURIComponent(k.id)); gambarDaftarKamera(); gambarRinciKamera(); });
    box.appendChild(b);
  });
  if (!kamDaftar.length) box.appendChild(el("p", "redup", "Belum ada kamera. Tekan Tambah kamera."));
}
function gambarRinciKamera() {
  const k = kamDaftar.find((x) => x.id === kamPilih);
  $("kam_rinci").hidden = !k;
  if (!k) return;
  const [st, kls] = STATUS_KAM(k);
  $("kr_nama").textContent = k.nama;
  $("kr_status").className = "status_teks " + kls;
  $("kr_status").textContent = st + (k.jenis !== "data" && k.terakhir ? " · lapor terakhir " + waktuLalu(k.detik_lalu) : "");
  $("kr_id").textContent = k.id;
  $("kr_jenis").textContent = k.jenis === "data" ? "Data latihan" : k.jenis === "ip" ? "IP camera" : "Raspberry Pi";
  $("kr_jenis_ket").textContent = k.jenis === "ip" ? "RTSP, direkam lewat perangkat" : k.jenis === "pi" ? "Modul kamera Pi" : "Tanpa perangkat";
  $("kr_kal").textContent = teksKal(k);
  $("kr_kal_link").href = "#/kalibrasi/" + encodeURIComponent(k.id);
  $("kr_kal_link").textContent = k.kalibrasi.sumber === "riwayat" ? "Buka kalibrasi" : "Kalibrasi sekarang";
  $("kr_catatan").textContent = k.catatan ? "Lokasi: " + k.catatan : "";
  $("kr_catatan").hidden = !k.catatan;
  const perangkat = k.jenis !== "data";
  $("kr_hub").hidden = !perangkat || !k.aktif;
  $("kr_tok").hidden = !perangkat;
  $("kr_data").hidden = perangkat;
  $("kr_hub").classList.toggle("kartu_aktif", !k.terhubung);
  $("kr_aktif").textContent = k.aktif ? "Nonaktifkan" : "Aktifkan lagi";
  $("kr_unduh").href = "/api/kamera/" + encodeURIComponent(k.id) + "/program";
  if (!document.querySelector("input[name=kr_jenis_cmd]:checked") || $("kr_hub").dataset.untuk !== k.id) {
    document.querySelectorAll("input[name=kr_jenis_cmd]").forEach((r) => { r.checked = r.value === (k.jenis === "ip" ? "ip" : "pi"); });
    $("kr_hub").dataset.untuk = k.id;
  }
  if (!$("kr_server").value) $("kr_server").value = /^(127\.|localhost)/.test(location.hostname) ? "" : location.origin;
  $("kr_token").textContent = kamToken ? kamToken.token : "••••••••••••••••••••";
  $("kr_tampil").textContent = kamToken ? "Sembunyikan" : "Tampilkan";
  $("kr_token_ket").textContent = k.token_sendiri
    ? "Token ini khusus untuk " + k.id + ". Bila bocor, buat token baru; perangkat lama langsung ditolak sampai perintahnya diganti."
    : "Kamera ini masih memakai token bersama dari data/settings.json (token_node). Tekan Buat token baru agar punya token sendiri.";
  susunPerintah();
}
function susunPerintah() {
  const k = kamDaftar.find((x) => x.id === kamPilih);
  if (!k) return;
  const jenis = (document.querySelector("input[name=kr_jenis_cmd]:checked") || {}).value || "pi";
  $("kr_rtsp_wadah").hidden = jenis !== "ip";
  const server = $("kr_server").value.trim() || "https://DOMAIN-ANDA";
  const tok = kamToken ? kamToken.token : "TOKEN_KAMERA";
  let cmd = "python3 node_camera.py --server " + server + " --node " + k.id + " --token " + tok;
  if (jenis === "ip") {
    const rtsp = $("kr_rtsp").value.trim().replace(/'/g, "");
    cmd += " \\\n  --perintah \"ffmpeg -y -loglevel error -rtsp_transport tcp -i '" + rtsp + "' -t {detik} -an -c:v copy {keluar}\"";
  }
  $("kr_perintah").textContent = cmd;
  $("kr_salin_teks").textContent = kamToken ? "Salin" : "Salin (token disamarkan)";
}
async function ambilToken(baru) {
  pesan("kr_token_pesan", "");
  try {
    kamToken = await api("/api/kamera/" + encodeURIComponent(kamPilih) + "/token", baru ? { method: "POST" } : undefined);
    if (baru) await segarkanKamera(); else gambarRinciKamera();
  } catch (e) { pesan("kr_token_pesan", e.message); }
}
$("kr_tampil").addEventListener("click", () => { if (kamToken) { kamToken = null; gambarRinciKamera(); } else ambilToken(false); });
$("kr_token_baru").addEventListener("click", () => {
  if (confirm("Buat token baru untuk " + kamPilih + "? Perangkat yang memakai token lama akan ditolak sampai perintahnya diganti.")) ambilToken(true);
});
document.querySelectorAll("input[name=kr_jenis_cmd]").forEach((r) => r.addEventListener("change", susunPerintah));
$("kr_server").addEventListener("input", susunPerintah);
$("kr_rtsp").addEventListener("input", susunPerintah);
$("kr_salin").addEventListener("click", async () => {
  if (!kamToken) await ambilToken(false);
  susunPerintah();
  const teks = $("kr_perintah").textContent;
  try { await navigator.clipboard.writeText(teks); }
  catch (e) {                                          // http biasa: clipboard API tidak tersedia
    const r = document.createRange(); r.selectNodeContents($("kr_perintah"));
    const s = getSelection(); s.removeAllRanges(); s.addRange(r); document.execCommand("copy");
  }
  $("kr_salin_teks").textContent = "Tersalin ✓";
  clearTimeout(kamSalin); kamSalin = setTimeout(susunPerintah, 2000);
});
async function ubahKamera(data) {
  const f = new FormData();
  Object.entries(data).forEach(([a, b]) => f.append(a, b));
  try { await api("/api/kamera/" + encodeURIComponent(kamPilih), { method: "POST", body: f }); await muatInfo(); await segarkanKamera(); }
  catch (e) { pesan("kam_pesan", e.message); }
}
$("kr_ubah_nama").addEventListener("click", () => {
  const k = kamDaftar.find((x) => x.id === kamPilih);
  const nama = prompt("Nama baru untuk " + k.id + ":", k.nama);
  if (nama && nama.trim() && nama.trim() !== k.nama) ubahKamera({ nama: nama.trim() });
});
$("kr_aktif").addEventListener("click", () => {
  const k = kamDaftar.find((x) => x.id === kamPilih);
  if (k.aktif && !confirm("Nonaktifkan " + k.nama + "? Perangkatnya akan ditolak dan kamera disembunyikan dari pilihan rekam, kalibrasi, dan proses.")) return;
  ubahKamera({ aktif: !k.aktif });
});
$("kr_hapus").addEventListener("click", async () => {
  const k = kamDaftar.find((x) => x.id === kamPilih);
  if (!confirm("Hapus " + k.nama + " dari daftar? Rekaman, hasil, dan riwayat kalibrasinya tetap tersimpan di folder data.")) return;
  try {
    await api("/api/kamera/" + encodeURIComponent(k.id), { method: "DELETE" });
    kamPilih = null; kamToken = null;
    await muatInfo(); await segarkanKamera();
  } catch (e) { pesan("kam_pesan", e.message); }
});
// ---------------------------------------------------------------- dialog Tambah kamera
let idDiubah = false;
function slug(t) {
  return t.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
}
function cekIdBaru() {
  const id = $("tk_id").value.trim(), s = $("tk_id_status");
  const ok = /^[a-z0-9][a-z0-9_-]{0,39}$/.test(id), dipakai = kamDaftar.some((k) => k.id === id);
  s.textContent = !id ? "" : !ok ? "✗ Tidak sah" : dipakai ? "✗ Sudah dipakai" : "✓ Tersedia";
  s.className = !id ? "" : ok && !dipakai ? "teks_hijau" : "teks_merah";
  return ok && !dipakai;
}
$("tambah_kamera").addEventListener("click", () => {
  $("form_tambah").reset(); idDiubah = false;
  let n = kamDaftar.length + 1;
  while (kamDaftar.some((k) => k.id === "kamera" + n)) n++;
  $("tk_id").value = "kamera" + n;
  cekIdBaru(); pesan("tk_pesan", "");
  $("dlg_tambah").showModal();
  $("tk_nama").focus();
});
$("tk_nama").addEventListener("input", () => { if (idDiubah) return; const s = slug($("tk_nama").value); if (s) { $("tk_id").value = s; cekIdBaru(); } });
$("tk_id").addEventListener("input", () => { idDiubah = true; cekIdBaru(); });
$("tk_batal").addEventListener("click", () => $("dlg_tambah").close());
$("tk_tutup").addEventListener("click", () => $("dlg_tambah").close());
$("form_tambah").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  pesan("tk_pesan", "");
  if (!$("tk_nama").value.trim()) { pesan("tk_pesan", "Nama kamera wajib diisi."); return; }
  if (!cekIdBaru()) { pesan("tk_pesan", "Periksa ID kamera: hanya huruf kecil, angka, _ dan -, dan belum dipakai."); return; }
  const f = new FormData();
  f.append("nama", $("tk_nama").value.trim()); f.append("id", $("tk_id").value.trim());
  f.append("jenis", document.querySelector("input[name=tk_jenis]:checked").value); f.append("catatan", $("tk_catatan").value);
  try {
    const k = await api("/api/kamera", { method: "POST", body: f });
    $("dlg_tambah").close();
    kamPilih = k.id; kamToken = { token: k.token, bersama: false };
    history.replaceState(null, "", "#/kamera/" + encodeURIComponent(k.id));
    await muatInfo(); await segarkanKamera();
    $("kr_hub").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) { pesan("tk_pesan", e.message); }
});

// ================================================================ Proses
async function bukaProses() {
  pesan("galat_form", "");
  isiPilihan($("proses_model"), INFO.model.map((m) => [m, m]));
  if (!$("conf").value) { $("conf").value = INFO.bawaan.conf; $("conf_low").value = INFO.bawaan.conf_low; }
  const pilih = sessionStorage.getItem("pilih_sumber");    // dari tombol "Proses" di Pengambilan video
  sessionStorage.removeItem("pilih_sumber");
  if (pilih) {
    const b = pilih.split("/");
    if (b[0] === "rekaman" && INFO.node.some((n) => n.id === b[1])) $("proses_node").value = b[1];
  }
  await isiVideoNode(pilih || undefined);
  await isiVersiKal();
  await segarkanAntrean();
}
// versi kalibrasi untuk pemrosesan ini (bawaan: yang sedang dipakai node)
async function isiVersiKal() {
  const node = $("proses_node").value;
  let daftar = [];
  try { daftar = await api("/api/kamera/" + encodeURIComponent(node) + "/riwayat"); } catch (e) { /* tetap pakai bawaan */ }
  const aktif = daftar.find((v) => v.aktif);
  const pilihan = [["", "Yang sedang dipakai" + (aktif ? " (versi " + aktif.versi + ")" : " (profil bawaan)")]];
  if (aktif) pilihan.push(["bawaan", "Profil bawaan (tanpa kalibrasi dari web)"]);
  daftar.filter((v) => !v.aktif).forEach((v) => pilihan.push([v.versi, "versi " + v.versi + " · " +
    (v.metode === "xml" ? "berkas kalibrasi" : (v.metode === "klik" ? "klik · " : "") + "sudut " + v.PITCH_DEG + "° · tinggi " + v.CAM_HEIGHT_M + " m") +
    " · garis " + v.LINE_Y_DEFAULT_M + "/" + v.LINE_Y_AWAY_M + " m"]));
  isiPilihan($("proses_kal"), pilihan, "");
}
$("proses_node").addEventListener("change", async () => { await isiVideoNode(); await isiVersiKal(); });
// pilih kamera dulu, lalu yang tampil hanya video yang direkam/diunggah untuk kamera itu
async function isiVideoNode(pilih) {
  const node = $("proses_node").value;
  const sel = $("proses_sumber");
  const lama = pilih !== undefined ? pilih : sel.value;
  let rekaman = [];
  try { rekaman = await api("/api/rekaman?node=" + encodeURIComponent(node)); } catch (e) { pesan("galat_form", e.message); }
  sel.replaceChildren();
  const grup = (label, isi) => {
    if (!isi.length) return;
    const g = document.createElement("optgroup");
    g.label = label;
    isi.forEach(([v, t]) => g.appendChild(new Option(t, v)));
    sel.appendChild(g);
  };
  const baris = (r) => [r.sumber, r.waktu + " · " + r.ukuran_mb.toFixed(1) + " MB" + (r.job.length ? " · sudah diproses" : "")];
  grup("Rekaman manual", rekaman.filter((r) => r.mode === "manual").map(baris));
  grup("Rekaman otomatis", rekaman.filter((r) => r.mode === "otomatis").map(baris));
  grup("Video contoh (data uji, bukan rekaman kamera ini)", INFO.contoh.map((c) => ["contoh/" + c, c]));
  if ([...sel.options].some((o) => o.value === lama)) sel.value = lama;
  const adaRekaman = rekaman.length > 0;
  $("proses_kosong").hidden = adaRekaman;
  $("tombol").disabled = sel.options.length === 0;
}

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
  data.append("kalibrasi", $("proses_kal").value);
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
    (g.mendekat !== undefined ? " · garis " + g.mendekat + " m / " + g.menjauh + " m" : "") +
    (j.kalibrasi ? " · kalibrasi " + (j.kalibrasi.versi ? "versi " + j.kalibrasi.versi : (j.kalibrasi.sumber === "bawaan" ? "profil bawaan" : "config.py")) : "");
  $("unduh_csv").href = dasar + "counting_log.csv";
  const v = $("pemutar");
  v.hidden = !j.ada_video;
  $("tanpa_video").hidden = !!j.ada_video;
  if (j.ada_video && v.dataset.id !== j.id) { v.src = dasar + "result.mp4"; v.dataset.id = j.id; }

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
