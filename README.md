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
