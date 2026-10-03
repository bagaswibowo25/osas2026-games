# osas2026-games

Tiga mini game booth openSUSE.Asia Summit 2026 untuk membagikan hadiah (pin, stiker, permen).
Tiap game 30–60 detik, didesain untuk tablet tapi tetap jalan di HP.

| Game | Path | Durasi | Hadiah |
|---|---|---|---|
| Geeko Memory Match: pasangkan tool openSUSE dengan fungsinya | `/games/memory/` | 60 s | ≤40 s: Pin + sticker · selesai: Sticker pack · waktu habis: Candy |
| Distro Match: pasangkan distro dengan package manager-nya | `/games/distro/` | 45 s | tanpa salah: Pin + sticker · selesai: Sticker pack · waktu habis: Candy |
| Command or Not?: perintah Linux asli atau karangan? | `/games/command/` | 30 s | ≥12 benar: Pin + sticker · 7–11: Sticker pack · <7: Candy |

Live: https://quiz.opensuse.id/games/memory/ · https://quiz.opensuse.id/games/distro/ · https://quiz.opensuse.id/games/command/

Mockup: https://claude.ai/artifact/PaZHA1CBtDvB2ukvPcFtG4

## Struktur

```
games/<game>/index.html   satu game = satu halaman statis (HTML + CSS + JS vanilla)
shared/                   style, helper JS (timer, shuffle, layar), font self-host
Dockerfile                nginx:alpine, --build-arg GAME=<memory|distro|command>
docker-compose.yml        3 container: games-memory, games-distro, games-command
deploy/nginx.conf         config nginx di dalam container
deploy/Caddyfile.snippet  route yang ditambahkan ke Caddyfile.prod ClassQuiz
```

Tidak ada backend, database, atau build step. Ubah teks/soal/hadiah langsung di `games/<game>/index.html`
(konstanta `PAIRS` / `WORDS` / `SECONDS` dan fungsi `end()`).

## Coba lokal

```bash
mkdir -p /tmp/g && for g in memory distro command; do mkdir -p /tmp/g/$g && cp -r games/$g/* shared /tmp/g/$g/; done
python3 -m http.server -d /tmp/g 8000   # buka http://localhost:8000/memory/
```

## Deploy (quiz.opensuse.id)

Server sudah menjalankan stack ClassQuiz (`~/ClassQuiz`, compose project `classquiz`). Caddy di stack itu
memegang port 80/443, jadi container game **tidak** membuka port sendiri. Mereka bergabung ke network
`classquiz_default` dan Caddy meneruskan path `/games/<game>/` ke container masing-masing.

```bash
# 1. kirim kode ke server (repo private, jadi pakai rsync)
rsync -az --delete --exclude .git ./ aryulianto@quiz.opensuse.id:osas2026-games/

# 2. build & jalankan
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
sudo docker compose up -d --build command   # deploy ulang satu game saja
```

## Lisensi

Font Source Sans 3 dan Source Code Pro: SIL Open Font License 1.1 (Adobe).
