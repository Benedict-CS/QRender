from io import BytesIO
from pathlib import Path
from typing import cast

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from app import short_redirect
from app.qr_art import FitMode, build_art_qr_photo_microdot
from app.qr_validate import validate_qr_code

app = FastAPI(title="QRender API", version="0.1.0")


@app.on_event("startup")
def _startup_init_short_db() -> None:
    short_redirect.init_db()


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    raw = (value or "").strip().lstrip("#")
    if len(raw) != 6 or any(c not in "0123456789abcdefABCDEF" for c in raw):
        raise ValueError("color must be #RRGGBB")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


_STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/")
async def home() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _effective_public_base(request: Request) -> str:
    override = short_redirect.public_base_for_links()
    if override:
        return override.rstrip("/")
    return str(request.base_url).rstrip("/")


@app.get("/s/{code}")
def follow_short_link(code: str) -> RedirectResponse:
    target = short_redirect.resolve_target(code)
    if not target:
        raise HTTPException(status_code=404, detail="Short link not found")
    return RedirectResponse(target, status_code=302)


@app.post("/qr/art")
async def qr_art(
    request: Request,
    content: str = Form(...),
    image: UploadFile = File(...),
    box_size: int = Form(12),
    border: int = Form(2),
    crop_anchor_x: float = Form(0.5),
    crop_anchor_y: float = Form(0.5),
    fit_mode: str = Form("contain"),
    cover_zoom: float = Form(1.0),
    micro_dot_radius_frac: float = Form(0.22),
    micro_smart_contrast: int = Form(1),
    finder_shape: str = Form("square"),
    finder_dark_color: str = Form("#000000"),
    finder_light_color: str = Form("#FFFFFF"),
    use_short_url: int = Form(0),
) -> StreamingResponse:
    if not content.strip():
        raise HTTPException(status_code=400, detail="content cannot be empty")
    if not (4 <= box_size <= 32):
        raise HTTPException(status_code=400, detail="box_size must be between 4 and 32")
    if not (1 <= border <= 8):
        raise HTTPException(status_code=400, detail="border must be between 1 and 8")
    if not (0 <= crop_anchor_x <= 1):
        raise HTTPException(status_code=400, detail="crop_anchor_x must be between 0 and 1")
    if not (0 <= crop_anchor_y <= 1):
        raise HTTPException(status_code=400, detail="crop_anchor_y must be between 0 and 1")
    if fit_mode not in ("cover", "contain"):
        raise HTTPException(status_code=400, detail="fit_mode must be cover or contain")
    if not (0.5 <= cover_zoom <= 3.0):
        raise HTTPException(status_code=400, detail="cover_zoom must be between 0.5 and 3")
    if not (0.08 <= micro_dot_radius_frac <= 0.35):
        raise HTTPException(
            status_code=400,
            detail="micro_dot_radius_frac must be between 0.08 and 0.35",
        )
    if micro_smart_contrast not in (0, 1):
        raise HTTPException(status_code=400, detail="micro_smart_contrast must be 0 or 1")
    if finder_shape not in ("square", "circle"):
        raise HTTPException(status_code=400, detail="finder_shape must be square or circle")
    if use_short_url not in (0, 1):
        raise HTTPException(status_code=400, detail="use_short_url must be 0 or 1")

    try:
        finder_dark_rgb = _hex_to_rgb(finder_dark_color)
        finder_light_rgb = _hex_to_rgb(finder_light_color)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    uploaded = await image.read()
    if not uploaded:
        raise HTTPException(status_code=400, detail="image file is empty")

    payload = content.strip()
    if use_short_url:
        try:
            normalized = short_redirect.normalize_url(payload)
        except ValueError as err:
            raise HTTPException(
                status_code=400,
                detail=f"Short link mode needs a valid http(s) URL: {err}",
            ) from err
        code = short_redirect.get_or_create_code(normalized)
        base = _effective_public_base(request)
        payload = f"{base}/s/{code}"

    try:
        output = build_art_qr_photo_microdot(
            content=payload,
            source_image_bytes=uploaded,
            box_size=box_size,
            border=border,
            mesh_dark_rgb=(0, 0, 0),
            mesh_light_rgb=(255, 255, 255),
            micro_dot_radius_frac=micro_dot_radius_frac,
            micro_smart_contrast=bool(micro_smart_contrast),
            finder_shape=finder_shape,  # validated: square | circle
            finder_dark_rgb=finder_dark_rgb,
            finder_light_rgb=finder_light_rgb,
            finder_decor=False,
            prepixelate_max=0,
            crop_anchor_x=crop_anchor_x,
            crop_anchor_y=crop_anchor_y,
            fit_mode=cast(FitMode, fit_mode),
            cover_zoom=cover_zoom,
            circular_mask=False,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    decode_ok = validate_qr_code(output, payload, verbose=True)

    buffer = BytesIO()
    output.save(buffer, format="PNG")
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="image/png",
        headers={
            "X-QR-Encoded-Content": payload[:512],
            "X-QR-Decode-Ok": "true" if decode_ok else "false",
        },
    )
