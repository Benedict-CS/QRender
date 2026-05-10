# QRender

Open-source web app for **photo micro-dot style QR codes** (art QR with a background image, corner finders, and short-link mode).

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Uvicorn](https://img.shields.io/badge/Uvicorn-0.30+-4051B5?style=for-the-badge)](https://www.uvicorn.org/)
[![Pillow](https://img.shields.io/badge/Pillow-10+-fbbf24?style=for-the-badge)](https://python-pillow.org/)
[![qrcode](https://img.shields.io/badge/qrcode-PIL-111827?style=for-the-badge)](https://github.com/lincolnloop/python-qrcode)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docs.docker.com/compose/)

## Demo

**Live site:** [https://qrender.ben.winlab.tw](https://qrender.ben.winlab.tw)

- Generator UI at `/`
- Admin (needs `ADMIN_SECRET`) at `/admin`

## Why this repo

- **Micro-dot art QR** — `POST /qr/art` blends your photo under a scannable QR pattern.
- **Short links** — optional `https://your-host/s/<code>` in the QR; change the destination later in admin without reprinting.
- **WinLab gallery roulette** — `GET /r/winlab-random` returns a **302** to a random **still image** from the public [WinLab gallery](https://gallery.winlab.tw/) (videos skipped). Cache TTL: `WINLAB_GALLERY_CACHE_SECONDS` (default 300). Good for a QR that shows a different lab photo on each open.

> This is deterministic image compositing (Pillow + `qrcode`), not an SD/ControlNet pipeline — easy to extend later.

## Quick start

### 1) Virtual environment

```bash
cd QRender
python3 -m venv .venv
source .venv/bin/activate
```

### 2) Install

```bash
python -m pip install -U pip
python -m pip install -e .
```

### 3) Run server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4) Open the UI

- App: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- OpenAPI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

Static assets (e.g. logo) are served under `/static/`.

## API examples

### Health

```bash
curl http://127.0.0.1:8000/health
```

### Art QR (micro-dot)

```bash
curl -X POST "http://127.0.0.1:8000/qr/art" \
  -F "content=https://example.com" \
  -F "image=@./your-image.jpg" \
  -F "fit_mode=cover" \
  -F "cover_zoom=0.5" \
  -F "crop_anchor_x=0.5" \
  -F "crop_anchor_y=0.5" \
  -F "micro_dot_radius_frac=0.22" \
  -F "finder_shape=square" \
  -F "finder_dark_color=#000000" \
  -F "finder_light_color=#ffffff" \
  -F "use_short_url=0" \
  -F "save_to_admin=0" \
  -o art.png
```

Response header `X-QR-Encoded-Content` reflects the string encoded in the QR (after short-link rewrite when enabled).

### Random WinLab gallery image (redirect)

```bash
curl -sSI "http://127.0.0.1:8000/r/winlab-random" | grep -i '^location:'
```

Each request may redirect to a different image URL. Configure scrape URL / cache in `.env` — see `.env.example`.

## Short links (`/s/...`)

With **“Use short link”** in the UI, the QR can encode `https://your-host/s/<code>` while the real URL is stored in SQLite under `data/short_urls.sqlite3`:

- The **same printed QR** can keep working if you **change the destination** in admin (path `/s/abc` unchanged).
- **Scan counts** and timestamps are recorded on each **302** redirect.

Set **`ADMIN_SECRET`**, open **`/admin`**, paste the token, and manage links or view events.

Production: set **`PUBLIC_BASE_URL`** (e.g. `https://qrender.ben.winlab.tw`) so generated QR payloads use the correct host.

Admin API (header `X-Admin-Token`):

- `GET /api/admin/links`
- `PATCH /api/admin/links/{code}` — JSON `{ "target": "https://..." }`
- `DELETE /api/admin/links/{code}`
- `GET /api/admin/links/{code}/events`

## Docker

Bootstrap `.env`:

```bash
python3 scripts/setup_env.py
```

Then either:

```bash
chmod +x install-docker.sh docker-run.sh
./install-docker.sh
# log out/in for docker group, then:
./docker-run.sh
```

or `docker compose up --build`. SQLite and previews persist in `./data` (mounted at `/app/data`).

If admin token fails after a secret change: restart the app and sign in again on `/admin` (browser may cache an old token).

## Roadmap ideas

- Heavier AI / ControlNet pipelines
- Stronger finder/alignment protection options
