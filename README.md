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

## Next roadmap ideas

- Stable Diffusion + ControlNet integration
- Masked finder/alignment protection with matrix-level control
- Scan quality benchmark (OpenCV + pyzbar)
- Docker image and self-host deployment

