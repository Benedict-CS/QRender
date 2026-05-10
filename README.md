# QRender

Open-source starter project for generating QR codes, including an "art-style" image overlay mode.

## Why this repo

This project gives you a practical base to build the visual QR idea:
- Standard QR output (`/qr/basic`)
- Art-style QR output with image blending (`/qr/art`)
- High error correction mode (`H`) for better scan tolerance

> Note: This starter uses deterministic image blending, not Stable Diffusion/ControlNet yet.
> You can later extend this API with an AI pipeline.

## Quick Start

### 1) Create virtual environment

```bash
cd /home/ben/QRender
python3 -m venv .venv
source .venv/bin/activate
```

### 2) Install dependencies

```bash
python -m ensurepip --upgrade
python -m pip install --upgrade pip
python -m pip install -e .
```

### 3) Run server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4) Open the frontend UI

After server startup, open:

```text
http://127.0.0.1:8000/
```

You can also use Swagger:

```text
http://127.0.0.1:8000/docs
```

## API examples

### Health check

```bash
curl http://127.0.0.1:8000/health
```

### Basic QR

```bash
curl -X POST "http://127.0.0.1:8000/qr/basic" \
  -F "content=https://example.com" \
  -o basic.png
```

### Art QR

```bash
curl -X POST "http://127.0.0.1:8000/qr/art" \
  -F "content=https://example.com" \
  -F "overlay_alpha=0.40" \
  -F "image=@./your-image.png" \
  -o art.png
```

## Short links (`/s/...`)

With **“Use short link”** in the UI, the QR encodes `https://your-host/s/<code>` while the real URL is stored in SQLite under `data/short_urls.sqlite3`. That means:

- The **same printed QR** keeps working if you **change the destination** in the admin UI (the path `/s/abc` stays the same).
- **No built-in expiry**; delete a link manually if you need to retire it.
- **Scan counts** and **per-scan timestamps** are recorded on each redirect (302).

Set **`ADMIN_SECRET`** in the environment, then open **`/admin`**, paste the token, and manage links or view recent scans.

API (same token as header `X-Admin-Token`):

- `GET /api/admin/links` — list all
- `PATCH /api/admin/links/{code}` — JSON `{ "target": "https://..." }`
- `DELETE /api/admin/links/{code}`
- `GET /api/admin/links/{code}/events` — recent scan times

In production, set **`PUBLIC_BASE_URL`** to your public `https://…` origin so generated QR payloads use the correct host.

## Docker

Bootstrap `.env` (creates file, fills `ADMIN_SECRET` if empty, fixes placeholder URL):

```bash
python3 scripts/setup_env.py
```

Install Docker Engine once (Ubuntu/Debian; requires sudo password in your terminal):

```bash
chmod +x install-docker.sh docker-run.sh
./install-docker.sh
```

Log out and back in, then:

```bash
./docker-run.sh
```

Foreground build+run; for background: `./docker-run.sh up -d`. See `./docker-run.sh help`.

Alternatively: `docker compose up --build` (same as the script).

SQLite and QR previews live in `./data` on the host (mounted at `/app/data`) so data survives container restarts.

## Next roadmap ideas

- Stable Diffusion + ControlNet integration
- Masked finder/alignment protection with matrix-level control

