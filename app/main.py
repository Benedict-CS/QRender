import html
import os
import secrets
from contextlib import asynccontextmanager
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Annotated, cast

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import gallery_winlab, short_redirect
from app.qr_art import FitMode, build_art_qr_photo_microdot


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup: init database
    short_redirect.init_db()
    yield
    # Shutdown logic (if any) could go here


app = FastAPI(title="QRender API", version="0.1.0", lifespan=lifespan)


def require_admin(
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    secret = (os.environ.get("ADMIN_SECRET") or "").strip()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Admin API disabled: set ADMIN_SECRET in the environment.",
        )
    token = (x_admin_token or "").strip()
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token or not secrets.compare_digest(token, secret):
        raise HTTPException(status_code=403, detail="Invalid admin token")


class ShortLinkUpdateBody(BaseModel):
    target: str = Field(..., min_length=1, max_length=short_redirect.MAX_TARGET_LEN)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    raw = (value or "").strip().lstrip("#")
    if len(raw) != 6 or any(c not in "0123456789abcdefABCDEF" for c in raw):
        raise ValueError("color must be #RRGGBB")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


_STATIC_DIR = Path(__file__).resolve().parent / "static"
_DEFAULT_GITHUB_REPO_URL = "https://github.com/Benedict-CS/QRender"


@lru_cache(maxsize=1)
def _index_html() -> str:
    template = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    repo = (os.environ.get("PUBLIC_GITHUB_URL") or "").strip() or _DEFAULT_GITHUB_REPO_URL
    safe = html.escape(repo)
    # Header GitHub icon link
    gh_icon = (
        f'<a class="github-icon-link" href="{safe}" '
        'target="_blank" rel="noopener noreferrer" title="QRender on GitHub">'
        '<span class="sr-only">GitHub</span>'
        '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" '
        'viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        '<path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 '
        "0-.285-.015-1.23-.015-2.235-3.015.555-3.795-1.455-3.795-1.455-.51-1.305-1.245-1.65-1.245-1.65"
        "-1.005-.69.075-.675.075-.675 1.11.075 1.695 1.14 1.695 1.14 1.005 1.725 2.64 1.23 3.285.93.105-.735"
        ".39-1.23.705-1.515-2.4-.27-4.935-1.215-4.935-5.43 0-1.2.42-2.19 1.125-2.955-.12-.27-.495-1.365"
        ".105-2.85 0 0 .915-.285 3.005 1.125.87-.24 1.815-.36 2.745-.36s1.875.12 2.745.36c2.085-1.41 "
        "3-1.125 3-1.125.6 1.485.225 2.58.12 2.85.705.765 1.125 1.755 1.125 2.955 0 4.23-2.535 5.16-4.95 "
        "5.43.39.33.75.96.75 1.935 0 1.395-.015 2.52-.015 2.865 0 .315.225.69.825.57A12.02 12.02 0 0024 12"
        'c0-6.63-5.37-12-12-12z"/></svg></a>'
    )
    return template.replace("{{GITHUB_LINK}}", gh_icon)


@app.get("/")
async def home() -> HTMLResponse:
    return HTMLResponse(_index_html(), media_type="text/html; charset=utf-8")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _effective_public_base(request: Request) -> str:
    override = short_redirect.public_base_for_links()
    if override:
        return override.rstrip("/")
    return str(request.base_url).rstrip("/")


def _admin_short_link_qr_png(payload: str) -> bytes:
    """Standard black-on-white QR PNG for admin preview (same encoded string as micro-dot export)."""
    import qrcode
    from io import BytesIO

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=4,
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@app.get("/r/winlab-random")
def redirect_random_winlab_gallery_image() -> RedirectResponse:
    """
    302 redirect to a random still image from the WinLab public gallery (videos skipped).
    Encode this URL in a QR code for a different photo on each scan.
    """
    try:
        target = gallery_winlab.random_still_image_url()
    except RuntimeError as err:
        raise HTTPException(status_code=502, detail=str(err)) from err
    return RedirectResponse(target, status_code=302)


@app.get("/s/{code}")
def follow_short_link(code: str) -> RedirectResponse:
    target = short_redirect.resolve_target(code)
    if not target:
        raise HTTPException(status_code=404, detail="Short link not found")
    short_redirect.record_hit(code)
    return RedirectResponse(target, status_code=302)


@app.get("/admin")
async def admin_ui() -> FileResponse:
    return FileResponse(_STATIC_DIR / "admin.html", media_type="text/html; charset=utf-8")


@app.get("/api/admin/config")
def api_admin_config(
    request: Request,
    _: Annotated[None, Depends(require_admin)],
) -> dict[str, str]:
    """Same base URL used when building short-link QR payloads (PUBLIC_BASE_URL or request origin)."""
    return {"public_base_url": _effective_public_base(request)}


@app.get("/api/admin/links")
def api_admin_list_links(
    _: Annotated[None, Depends(require_admin)],
    limit: int = 500,
) -> list[dict]:
    return short_redirect.list_links(limit=limit)


@app.get("/api/admin/links/{code}/art.png")
def api_admin_link_art_png(
    code: str,
    _: Annotated[None, Depends(require_admin)],
) -> FileResponse:
    """Last micro-dot + photo QR saved when this short link was generated (if any)."""
    if not short_redirect.resolve_target(code):
        raise HTTPException(status_code=404, detail="Short link not found")
    managed = short_redirect.get_link_managed(code)
    if managed is False:
        raise HTTPException(
            status_code=404,
            detail="This short link was not added to admin — enable Save — Manage in Admin when generating.",
        )
    path = short_redirect.art_preview_path(code)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="No saved art QR yet — enable Short link + Save — Manage in Admin on the generator, then generate.",
        )
    return FileResponse(path, media_type="image/png")


@app.get("/api/admin/links/{code}/qr.png")
def api_admin_link_qr_png(
    request: Request,
    code: str,
    _: Annotated[None, Depends(require_admin)],
) -> Response:
    if not short_redirect.resolve_target(code):
        raise HTTPException(status_code=404, detail="Short link not found")
    c = code.strip().lower()
    payload = f"{_effective_public_base(request)}/s/{c}"
    return Response(
        content=_admin_short_link_qr_png(payload),
        media_type="image/png",
    )


@app.patch("/api/admin/links/{code}")
def api_admin_update_link(
    code: str,
    body: ShortLinkUpdateBody,
    _: Annotated[None, Depends(require_admin)],
) -> dict:
    try:
        normalized = short_redirect.normalize_url(body.target)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    if not short_redirect.update_link_target(code, normalized):
        raise HTTPException(status_code=404, detail="Short link not found")
    return {"ok": True, "code": code.strip().lower(), "target": normalized}


@app.delete("/api/admin/links/{code}")
def api_admin_delete_link(
    code: str,
    _: Annotated[None, Depends(require_admin)],
) -> dict:
    if not short_redirect.delete_link(code):
        raise HTTPException(status_code=404, detail="Short link not found")
    return {"ok": True}


@app.get("/api/admin/links/{code}/events")
def api_admin_link_events(
    code: str,
    _: Annotated[None, Depends(require_admin)],
    limit: int = 100,
) -> list[dict]:
    if not short_redirect.resolve_target(code):
        raise HTTPException(status_code=404, detail="Short link not found")
    if short_redirect.get_link_managed(code) is False:
        raise HTTPException(
            status_code=404,
            detail="This short link was not added to admin — scan stats are hidden for one-off links.",
        )
    return short_redirect.list_events_for_code(code, limit=limit)


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
    finder_shape: str = Form("square"),
    finder_dark_color: str = Form("#000000"),
    finder_light_color: str = Form("#FFFFFF"),
    photo_wash: float = Form(0.0),
    use_short_url: int = Form(0),
    save_to_admin: int = Form(0),
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
    if not (0.25 <= cover_zoom <= 3.0):
        raise HTTPException(status_code=400, detail="cover_zoom must be between 0.25 and 3")
    if not (0.08 <= micro_dot_radius_frac <= 0.35):
        raise HTTPException(
            status_code=400,
            detail="micro_dot_radius_frac must be between 0.08 and 0.35",
        )
    if finder_shape not in ("square", "circle"):
        raise HTTPException(status_code=400, detail="finder_shape must be square or circle")
    if use_short_url not in (0, 1):
        raise HTTPException(status_code=400, detail="use_short_url must be 0 or 1")
    if save_to_admin not in (0, 1):
        raise HTTPException(status_code=400, detail="save_to_admin must be 0 or 1")
    if save_to_admin and not use_short_url:
        raise HTTPException(
            status_code=400,
            detail="save_to_admin requires use_short_url (short link mode).",
        )

    try:
        finder_dark_rgb = _hex_to_rgb(finder_dark_color)
        finder_light_rgb = _hex_to_rgb(finder_light_color)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    uploaded = await image.read()
    if not uploaded:
        raise HTTPException(status_code=400, detail="image file is empty")

    payload = content.strip()
    code: str | None = None
    want_admin = bool(save_to_admin)
    if use_short_url:
        try:
            normalized = short_redirect.normalize_url(payload)
        except ValueError as err:
            raise HTTPException(
                status_code=400,
                detail=f"Short link mode needs a valid http(s) URL: {err}",
            ) from err
        code = short_redirect.get_or_create_code(normalized, managed_for_new=want_admin)
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
            micro_smart_contrast=True,
            finder_shape=finder_shape,  # validated: square | circle
            finder_dark_rgb=finder_dark_rgb,
            finder_light_rgb=finder_light_rgb,
            photo_wash=photo_wash,
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

    if use_short_url and code is not None and want_admin:
        short_redirect.set_managed(code, True)
        short_redirect.save_art_preview_png(code, output)

    buffer = BytesIO()
    output.save(buffer, format="PNG")
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="image/png",
        headers={"X-QR-Encoded-Content": payload[:512]},
    )


app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
