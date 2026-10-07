# osas2026-games

Tiga mini game booth openSUSE.Asia Summit 2026 untuk membagikan hadiah (pin, stiker, permen).
Tiap game 30–60 detik, didesain untuk tablet tapi tetap jalan di HP.

| Game | Path | Durasi | Hadiah |
|---|---|---|---|
| Geeko Memory Match: pasangkan tool openSUSE dengan fungsinya | `/games/memory/` | 60 s | ≤40 s: Pin + sticker · selesai: Sticker pack · waktu habis: Candy |
| Distro Match: pasangkan distro dengan package manager-nya (8 pasang acak dari 16 package manager / 30 distro) | `/games/distro/` | 45 s | tanpa salah: Pin + sticker · selesai: Sticker pack · waktu habis: Candy |
| Command or Not?: perintah Linux asli atau karangan? (48 kata acak) | `/games/command/` | 30 s | ≥12 benar: Pin + sticker · 7–11: Sticker pack · <7: Candy |

Peserta mulai dari halaman pilih game di **`/games/`** (kartu tiap game menampilkan durasi dan hadiah tertinggi
dari config saat ini). Pemain daftar sekali di sana (nama + IG), lalu punya **2 kesempatan** untuk semua game
(lihat *Giliran pemain*). Hasilnya masuk **leaderboard harian** di **`/games/leaderboard/`**
(top 10 per game, refresh otomatis, cocok untuk TV booth). Hadiah di atas adalah default; kru booth bisa mengubahnya dari web di **`/games/admin/`** (lihat di bawah).

Live: https://quiz.opensuse.id/games/ (pilih game) · https://quiz.opensuse.id/games/memory/ · https://quiz.opensuse.id/games/distro/ · https://quiz.opensuse.id/games/command/

Mockup: https://claude.ai/artifact/PaZHA1CBtDvB2ukvPcFtG4

## Struktur

```
games/<game>/index.html   satu game = satu halaman statis (HTML + CSS + JS vanilla)
games/hub/index.html      halaman pilih game di /games/
shared/                   style, helper JS (timer, shuffle, layar), font self-host
Dockerfile                nginx:alpine, --build-arg GAME=<memory|distro|command>
docker-compose.yml        container: games-hub, games-memory, games-distro, games-command, games-admin
admin/                    halaman admin hadiah + API kecil (Python stdlib), container games-admin
admin/scores.py           penyimpanan leaderboard (SQLite) + cek kewajaran skor
config/<game>.json        hadiah/syarat/durasi per game (ditulis oleh admin)
data/scores.db            database leaderboard (di server, tidak di git)
games/hub/leaderboard/    halaman leaderboard di /games/leaderboard/
deploy/nginx.conf         config nginx di dalam container
deploy/Caddyfile.snippet  route yang ditambahkan ke Caddyfile.prod ClassQuiz
```

Tidak ada backend, database, atau build step. Soal ada di `games/<game>/index.html` (konstanta `PAIRS` / `WORDS`).

## Konfigurasi hadiah

Buka **https://quiz.opensuse.id/games/admin/**, login dengan user `admin` dan password `ADMIN_PASSWORD`
dari `~/osas2026-games/.env` di server. Di sana nama hadiah, syarat, jumlah tingkat, dan durasi tiap game bisa
diubah; tombol **Save** memvalidasi lalu menyimpan ke `config/<game>.json`. Perubahan berlaku saat kru menekan
**Next player** (atau reload halaman game), **tanpa rebuild atau restart**.

File `config/<game>.json` juga boleh diedit langsung lewat SSH. Kalau JSON-nya rusak, game memakai default bawaan
(cek console browser).

Format: `tiers` dicek berurutan, tier pertama yang syaratnya terpenuhi yang menang; kalau tidak ada yang cocok
dapat `fallback`. Teks panel "Prizes" di layar awal dibuat otomatis dari config.

| File | Syarat per tier |
|---|---|
| `memory.json` | Semua pasangan ketemu dan `maxSeconds` (detik terpakai ≤ nilai ini). Tanpa `maxSeconds` = asal selesai sebelum waktu habis |
| `distro.json` | Semua 6 cocok dan `maxMistakes` (salah ≤ nilai ini). Tanpa `maxMistakes` = asal selesai sebelum waktu habis |
| `command.json` | `minCorrect` (jawaban benar ≥ nilai ini). Diurutkan otomatis dari yang tertinggi |

Contoh: tambah hadiah kaos untuk ≥15 benar di Command or Not:

```json
{
  "seconds": 30,
  "tiers": [
    { "prize": "Kaos Geeko", "minCorrect": 15 },
    { "prize": "Pin + sticker", "minCorrect": 12 },
    { "prize": "Sticker pack", "minCorrect": 7 }
  ],
  "fallback": "Candy"
}
```

## Giliran pemain

- Pemain daftar **sekali** di `/games/` dengan nama dan username Instagram, lalu memilih game.
- Tiap pemain punya **2 kesempatan** untuk semua game (bukan per game).
- Setelah main pertama ada dua pilihan: **Take this prize** (selesai, ambil hadiah) atau **Use my 2nd chance**
  (kembali ke daftar game, boleh pilih game lain).
- Saat kesempatan kedua **dimulai** (tombol Start), hasil pertama **gugur**: hilang dari leaderboard, dan hadiahnya
  ikut hasil kedua. Peringatan oranye muncul sebelum Start.
- Giliran selesai saat pemain mengambil hadiah atau memulai kesempatan kedua. Setelah itu **username IG dan nama
  yang sama tidak bisa daftar lagi** (nama dibandingkan tanpa beda huruf besar/kecil).
- Kalau tablet di-reload sebelum selesai, pemain tetap login di tab itu; kalau tab ditutup, cukup daftar lagi dengan
  IG yang sama untuk melanjutkan sisa kesempatan.
- Bagian *Players* di `/games/admin/` menampilkan semua pemain: status, kesempatan terpakai, hasil yang berlaku, dan
  **hadiah final**. Ada pencarian nama/IG. Tombol **Allow again** menghapus pemain dan hasilnya (misalnya salah
  ketik IG atau tablet crash) sehingga ia bisa daftar ulang dengan 2 kesempatan baru.
- Kesempatan yang sudah di-Start tetap terhitung walaupun game ditinggal di tengah jalan.

## Leaderboard

- Leaderboard **per game**: tiga papan terpisah (Memory, Distro, Command), masing-masing top 10.
- Nama (maks. 20 karakter) dan **username Instagram** wajib diisi saat daftar. Username IG adalah identitas
  pemain; karena hasil pertama gugur saat kesempatan kedua dimulai, tiap pemain punya paling banyak satu baris
  di satu papan. IG **tidak** tampil di leaderboard publik maupun API publik,
  hanya di halaman admin (untuk menghubungi pemenang).
- Peringkat: **Memory** selesai tercepat, lalu langkah paling sedikit; **Distro** salah paling sedikit, lalu
  tercepat; **Command** benar terbanyak, lalu salah paling sedikit. Yang belum selesai diurutkan di bawahnya.
- Skor dihitung di browser, jadi server memberi token sekali pakai saat Start dan menolak hasil yang tidak
  sesuai waktu sebenarnya (Memory selesai 2 detik, 50 jawaban dalam 30 detik, kirim sebelum waktu habis, ...).
  Ini cukup untuk booth, tapi bukan anti-curang penuh.
- **Hanya admin** yang bisa menghapus pemain (misalnya nama tidak pantas) atau **reset** semua leaderboard
  (sekaligus semua pendaftaran pemain, misalnya untuk hari berikutnya), dari bagian *Leaderboard* di `/games/admin/`.
- Game memanggil `api/*` relatif ke path-nya; nginx di tiap container meneruskannya ke `games-admin:8080/play/*`,
  jadi tidak perlu route Caddy tambahan. Pendaftaran dan jatah kesempatan dicek di server, jadi game **butuh**
  container admin hidup (kalau mati, tombol Start menampilkan pesan error).

## Last Geeko Standing (main hall)

Game live untuk penutupan di main hall, **terpisah** dari 3 game booth (tidak muncul di `/games/`).
Container `games-standing` (Python aiohttp + WebSocket), kode di `standing/`.

| Untuk | URL |
|---|---|
| Peserta (QR di layar host) | https://quiz.opensuse.id/games/last-geeko-standing/ |
| Host / proyektor | https://quiz.opensuse.id/games/last-geeko-standing/host (password = `ADMIN_PASSWORD`) |
| Buka / kunci join | bagian **Last Geeko Standing** di `/games/admin/` |

- Selama **Locked**, peserta tidak bisa join (pesan "not open yet"). Peserta yang sudah di dalam tidak terpengaruh.
- 5 putaran x 3 item. Putaran kuis: soal benar/salah (benar = 500 + bonus kecepatan sampai 500).
  Putaran game (poin menurut peringkat, 1000 untuk yang terbaik): putaran 2 Color Rush, Reflex (tap Geeko hijau yang berkedip, hindari Geeko merah/oranye), Geeko Sort (drag Geeko ke toples sewarna);
  putaran 4 Bug Squash, Geeko Simon, Geeko Dash.
  Item dalam satu putaran berjalan otomatis; di akhir putaran yang lolos hanya peringkat teratas
  (`keep`: `0.5` = 50%, `10` = 10 orang), lalu host menekan **Next round**. Final menyisakan 5 orang,
  diumumkan satu per satu dari #5 ke #1 setelah **Reveal winners**, dengan confetti (`standing/static/confetti.js`). Skor dihitung per putaran.
- Putaran, soal, waktu, dan `keep` ada di `config/last-geeko-standing-questions.json` (`spare_questions` = cadangan).
  Berlaku saat **Start game** berikutnya.
- Refresh browser aman (sesi di `localStorage`, progres mini game di `sessionStorage`); tombol **Leave game**
  untuk keluar. Join setelah game mulai ditolak. Restart container melanjutkan game dari `data/last-geeko-standing.json`.
- Musik dan efek suara hanya dari layar host: sambungkan laptop host ke speaker. Semua loop orisinal (CC0).
  Tombol **Style** di layar host memilih gaya musik (tersimpan di browser host):
  - **Congdut** (default, `standing/music/congdut.py`): keroncong + kendang dangdut koplo dan suling;
    *Congdut Koplo* (132 BPM) saat soal dan mini game, *Congdut Santai* (108 BPM) di lobby, hasil, antar putaran.
  - **Keroncong** (`standing/music/keroncong.py`): *Keroncong Rancak* (134 BPM) saat soal dan mini game,
    *Langgam Senja* (108 BPM) di lobby, hasil, dan antar putaran.
  - **Funk** (`standing/music/compose.py`): *Jogja Funk* (120 BPM) dan *Desa Riang* (104 BPM).
- Setiap Start game dan Next round diawali hitung mundur **3, 2, 1, START!** (animasi di proyektor dan HP, suara di host;
  host bisa **Skip**). Background halaman: `standing/static/bg.png`.
- Penjelasan tiap mini game tampil `intro_seconds` (30 detik) sebelum game mulai; host bisa **Skip**.
- **Tes dengan bot** (`standing/bots.py`, butuh `pip install aiohttp`). Buka game di admin, jalankan bot,
  join dari HP, lalu Start. Bot join ulang otomatis setelah **Reset**; hentikan dengan Ctrl-C.
  Bot tidak benar-benar memainkan mini game, hanya mengirim skor yang wajar.

  ```bash
  python standing/bots.py 200                  # 200 bot, skill normal
  python standing/bots.py 200 --skill weak     # bot sengaja kalah, supaya Anda bisa sampai final
  python standing/bots.py 50 --start 200       # tambahan 50 bot dengan nama lain
  ```

## Geeko Pixel Mural (penutupan)

Semua peserta mewarnai satu mural piksel bersama dari HP. Terpisah dari game booth (tidak muncul di `/games/`).
Container `games-mural`, kode di `mural/` (memakai ulang Geeko, background, musik, efek suara, dan confetti
dari `standing/static/`).

| Untuk | URL |
|---|---|
| Peserta (QR di layar host) | https://quiz.opensuse.id/games/pixel-mural/ |
| Host / proyektor | https://quiz.opensuse.id/games/pixel-mural/host (password = `ADMIN_PASSWORD`) |
| Buka / kunci join | bagian **Geeko Pixel Mural** di `/games/admin/` |

- Dinding 96 x 54 piksel dengan pola samar: **OPENSUSE.ASIA / SUMMIT 2026 / YOGYAKARTA** di atas batik kawung.
  Pola dibuat di `mural/server.py` (`build_target`).
- Tiap peserta dapat sektor 12 x 9 (A1 sampai F8). Pilih warna, tap kotak samar; satu piksel tiap `cooldown` detik.
  Piksel yang sudah benar tidak bisa ditimpa. Sektor selesai: pemainnya otomatis dipindah ke sektor yang paling butuh bantuan.
  Peserta boleh join di tengah sesi (selama tidak dikunci).
- Host: **Start painting** (hitung mundur 3, 2, 1, PAINT!), **Finish now**, **Reset mural**. Saat waktu habis, piksel
  yang belum selesai terisi otomatis, mural utuh tampil dengan confetti dan daftar pelukis teraktif.
- Durasi dan cooldown: `config/pixel-mural-settings.json` `{"seconds": 180, "cooldown": 3}` (opsional; berlaku saat Start).
- Tes dengan bot: `python mural/bots.py 150` (opsi `--accuracy 0.85`, `--start`, `--url`).

## Coba lokal

```bash
mkdir -p /tmp/g && for g in memory distro command; do mkdir -p /tmp/g/$g && cp -r games/$g/* shared config /tmp/g/$g/; done
python3 -m http.server -d /tmp/g 8000   # buka http://localhost:8000/memory/
```

## Deploy (quiz.opensuse.id)

Server sudah menjalankan stack ClassQuiz (`~/ClassQuiz`, compose project `classquiz`). Caddy di stack itu
memegang port 80/443, jadi container game **tidak** membuka port sendiri. Mereka bergabung ke network
`classquiz_default` dan Caddy meneruskan path `/games/<game>/` ke container masing-masing.

Backup leaderboard: `sudo docker compose exec admin python -c "import sqlite3; sqlite3.connect('/data/scores.db').backup(sqlite3.connect('/data/backup.db'))"`
lalu salin `data/backup.db`.

```bash
# 1. kirim kode ke server (repo private, jadi pakai rsync).
#    config/ dikecualikan agar hadiah yang sudah diedit kru di server tidak tertimpa;
#    baris kedua hanya menyalin file config yang belum ada di server.
rsync -az --delete --exclude .git --exclude config/ --exclude data/ --exclude .env ./ aryulianto@quiz.opensuse.id:osas2026-games/
rsync -az --ignore-existing config/ aryulianto@quiz.opensuse.id:osas2026-games/config/

# 2. hanya pertama kali: buat password admin dan folder data (milik user biasa, bukan root)
ssh aryulianto@quiz.opensuse.id 'cd osas2026-games && mkdir -p data && ([ -f .env ] || (umask 077; echo "ADMIN_PASSWORD=$(openssl rand -base64 18)" > .env))'

# 3. build & jalankan
ssh aryulianto@quiz.opensuse.id 'cd osas2026-games && sudo docker compose up -d --build'
```

Hanya untuk pertama kali: tempel isi `deploy/Caddyfile.snippet` ke dalam blok `quiz.opensuse.id { ... }`
di `~/ClassQuiz/Caddyfile.prod` (sebelum baris `reverse_proxy`), lalu reload Caddy tanpa downtime:

```bash
cd ~/ClassQuiz && sudo docker compose -f docker-compose.prod.yml exec caddy caddy reload --config /etc/caddy/Caddyfile
```

> Caddyfile di-bind-mount sebagai satu file. Edit file **di tempat** (editor biasa / `cat > file`), jangan
> `sed -i`, karena `sed -i` membuat inode baru dan container tetap melihat file lama.

Operasional:

```bash
cd ~/osas2026-games
sudo docker compose ps
sudo docker compose logs -f memory
grep ADMIN_PASSWORD .env                    # lihat password admin; ubah di sini lalu: sudo docker compose up -d admin
sudo docker compose up -d --build command   # deploy ulang satu game saja
nano config/command.json                    # ubah hadiah, lalu tekan "Next player" di tablet
```

## Lisensi

Font Source Sans 3 dan Source Code Pro: SIL Open Font License 1.1 (Adobe).
