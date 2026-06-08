from io import BytesIO
import math
from typing import Literal

from PIL import Image, ImageChops, ImageDraw, ImageOps
import qrcode
from qrcode.constants import ERROR_CORRECT_H

ArtStyle = Literal[
    "overlay",
    "modules",
    "halftone",
    "photo_mesh",
    "photo_stipple",
    "photo_microdot",
]
ModuleShape = Literal["square", "circle", "star"]
FitMode = Literal["cover", "contain"]
StippleDotShape = Literal["circle", "square"]
MicroFinderStyle = Literal["square", "rounded", "bullseye"]
MicrodotFinderShape = Literal["square", "circle"]


def _open_uploaded_image(data: bytes) -> Image.Image:
    """Decode bytes and apply EXIF orientation so pixel layout matches browser display."""
    im = Image.open(BytesIO(data))
    return ImageOps.exif_transpose(im)


def _make_qr_instance(
    content: str,
    box_size: int,
    border: int,
) -> qrcode.QRCode:
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_H,
        box_size=max(4, box_size),
        border=max(1, border),
    )
    qr.add_data(content)
    qr.make(fit=True)
    return qr


def _make_qr_instance_dense(
    content: str,
    box_size: int,
    border: int,
) -> qrcode.QRCode:
    """Smaller modules allowed (>=2 px) for high-density stipple / brand QR look."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_H,
        box_size=max(2, min(int(box_size), 32)),
        border=max(1, border),
    )
    qr.add_data(content)
    qr.make(fit=True)
    return qr


# 4×4 Bayer matrix (0–15) for ordered stipple inside each QR module.
_BAYER_4: tuple[tuple[int, ...], ...] = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)


def _stipple_cell_paint(is_dark_module: bool, si: int, sj: int, fill_dark: float, fill_light: float) -> bool:
    b = _BAYER_4[si % 4][sj % 4]
    if is_dark_module:
        thr = 15.0 * (1.0 - max(0.05, min(0.98, fill_dark)))
        return b >= thr
    thr = 15.0 * (1.0 - max(0.0, min(0.45, fill_light)))
    return b >= thr


def _luma_from_rgb(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return (r * 299 + g * 587 + b * 114) / 1000.0


def _stipple_dot_color(
    rpx: int,
    gpx: int,
    bpx: int,
    is_dark_module: bool,
    from_image: bool,
    mesh_dark_rgb: tuple[int, int, int],
    mesh_light_rgb: tuple[int, int, int],
    stipple_scan_boost: float,
) -> tuple[int, int, int]:
    """
    Dot fill: either ink swap by background (from_image=False) or photo-tinted
    chips blended toward dark/light inks for QR contrast (from_image=True).
    """
    lum = (rpx * 299 + gpx * 587 + bpx * 114) / 1000.0
    dr, dg, db = mesh_dark_rgb
    lr, lg, lb = mesh_light_rgb
    if not from_image:
        if lum < 140.0:
            pr, pg, pb = lr, lg, lb
        else:
            pr, pg, pb = dr, dg, db
        return _stipple_dot_rgb_scan_safe((pr, pg, pb), lum, is_dark_module)
    sb = max(0.0, min(1.0, stipple_scan_boost))
    if is_dark_module:
        t = 0.20 + sb * 0.42
        pr = int(rpx * (1.0 - t) + dr * t)
        pg = int(gpx * (1.0 - t) + dg * t)
        pb = int(bpx * (1.0 - t) + db * t)
    else:
        t = 0.38 + sb * 0.30
        pr = int(rpx * (1.0 - t) + lr * t)
        pg = int(gpx * (1.0 - t) + lg * t)
        pb = int(bpx * (1.0 - t) + lb * t)
    return _stipple_dot_rgb_scan_safe((pr, pg, pb), lum, is_dark_module)


def _stipple_dot_rgb_scan_safe(
    dot_rgb: tuple[int, int, int],
    luma_bg: float,
    is_dark_module: bool,
) -> tuple[int, int, int]:
    """
    Push stipple dot luminance away from the local background so decoders see
    dark vs light modules (pastel-on-pastel brand colors otherwise fail).
    """
    pr, pg, pb = dot_rgb
    ld = _luma_from_rgb((pr, pg, pb))
    if is_dark_module:
        if luma_bg >= 118.0:
            # Dot must sit clearly below background luminance (pastels fail if gap is tiny).
            target = max(18.0, luma_bg - 52.0)
            if ld > target:
                t = min(1.0, (ld - target) / max(40.0, luma_bg * 0.28))
                t = 0.48 + t * 0.52
                pr = int(pr * (1.0 - t))
                pg = int(pg * (1.0 - t))
                pb = int(pb * (1.0 - t))
        else:
            target = min(248.0, luma_bg + 42.0)
            if ld < target:
                t = min(1.0, (target - ld) / max(50.0, (255.0 - luma_bg) * 0.35))
                t = 0.42 + t * 0.58
                pr = int(pr + (255 - pr) * t)
                pg = int(pg + (255 - pg) * t)
                pb = int(pb + (255 - pb) * t)
    else:
        if luma_bg >= 118.0 and ld > luma_bg - 36.0:
            t = min(0.72, (ld - (luma_bg - 52.0)) / 95.0)
            pr = int(pr * (1.0 - t * 0.75))
            pg = int(pg * (1.0 - t * 0.75))
            pb = int(pb * (1.0 - t * 0.75))
        elif luma_bg < 118.0 and ld < luma_bg + 38.0:
            t = min(0.72, ((luma_bg + 48.0) - ld) / 95.0)
            pr = int(pr + (255 - pr) * t * 0.75)
            pg = int(pg + (255 - pg) * t * 0.75)
            pb = int(pb + (255 - pb) * t * 0.75)
    return max(0, min(255, pr)), max(0, min(255, pg)), max(0, min(255, pb))


def _finder_colors_scan_safe(
    mesh_dark_rgb: tuple[int, int, int],
    mesh_light_rgb: tuple[int, int, int],
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Bias finder corners toward real black/white while keeping a hint of brand tint."""
    fd = tuple(int(mesh_dark_rgb[i] * 0.32 + 0 * 0.68) for i in range(3))
    fl = tuple(int(mesh_light_rgb[i] * 0.28 + 255 * 0.72) for i in range(3))
    return fd, fl


def _stipple_sample_luma(r: int, g: int, b: int) -> float:
    return (r * 299 + g * 587 + b * 114) / 1000.0


def _stipple_luma_adjust_rgb(
    r: int,
    g: int,
    b: int,
    is_dark_module: bool,
    ink_dark: tuple[int, int, int],
    ink_light: tuple[int, int, int],
    threshold: float = 128.0,
    margin: float = 10.0,
) -> tuple[int, int, int]:
    """
    Luminance-aware stipple color: keep image hue where possible, but enforce QR contrast.
    Dark modules must sit clearly below ``threshold``; light modules above it.
    Blends toward ink_dark / ink_light (typically black / white) only as much as needed.
    """
    dr, dg, db = ink_dark
    lr, lg, lb = ink_light
    dark_bound = max(0.0, min(255.0, threshold - margin))
    light_bound = max(0.0, min(255.0, threshold + margin))
    L = _stipple_sample_luma(r, g, b)

    if is_dark_module:
        if L <= dark_bound:
            return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
        lo, hi = 0.0, 1.0
        for _ in range(18):
            t = (lo + hi) / 2.0
            rr = int(r * (1.0 - t) + dr * t)
            gg = int(g * (1.0 - t) + dg * t)
            bb = int(b * (1.0 - t) + db * t)
            if _stipple_sample_luma(rr, gg, bb) <= dark_bound:
                hi = t
            else:
                lo = t
        t = hi
        return (
            max(0, min(255, int(r * (1.0 - t) + dr * t))),
            max(0, min(255, int(g * (1.0 - t) + dg * t))),
            max(0, min(255, int(b * (1.0 - t) + db * t))),
        )

    if L >= light_bound:
        return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
    lo, hi = 0.0, 1.0
    for _ in range(18):
        t = (lo + hi) / 2.0
        rr = int(r * (1.0 - t) + lr * t)
        gg = int(g * (1.0 - t) + lg * t)
        bb = int(b * (1.0 - t) + lb * t)
        if _stipple_sample_luma(rr, gg, bb) >= light_bound:
            hi = t
        else:
            lo = t
    t = hi
    return (
        max(0, min(255, int(r * (1.0 - t) + lr * t))),
        max(0, min(255, int(g * (1.0 - t) + lg * t))),
        max(0, min(255, int(b * (1.0 - t) + lb * t))),
    )


def _apply_stipple_module_scan_boost(
    img: Image.Image,
    matrix: list[list[bool]],
    bd: int,
    bs: int,
    height: int,
    width: int,
    strength: float,
) -> Image.Image:
    """
    Phones average each module; fine stipple on a photo often lands in the mid-gray.
    Add a soft ellipse per module to pull mean luminance toward black vs white.
    """
    if strength <= 0.02:
        return img
    wim = img.convert("RGBA")
    boost = Image.new("RGBA", wim.size, (0, 0, 0, 0))
    db = ImageDraw.Draw(boost)
    s = max(0.0, min(1.0, strength))
    pad = max(0.5, bs * 0.06)
    for i in range(height):
        for j in range(width):
            if _in_finder_corner(i, j, height, width):
                continue
            y0 = (i + bd) * bs
            x0 = (j + bd) * bs
            x1, y1 = x0 + bs, y0 + bs
            crop = wim.crop((x0, y0, x1, y1))
            if crop.size[0] < 1 or crop.size[1] < 1:
                continue
            r, g, b = crop.resize((1, 1), Image.Resampling.BOX).convert("RGB").getpixel((0, 0))
            ml = (r * 299 + g * 587 + b * 114) / 1000.0
            is_dark = bool(matrix[i][j])
            if is_dark:
                if ml > 115:
                    excess = (ml - 115) / 140.0
                    alpha = int(255 * s * (0.26 + min(1.0, excess) * 0.55))
                    alpha = max(0, min(218, alpha))
                    if alpha > 6:
                        db.ellipse(
                            [x0 + pad, y0 + pad, x1 - pad, y1 - pad],
                            fill=(0, 0, 0, alpha),
                        )
            else:
                if ml < 178:
                    deficit = (178 - ml) / 178.0
                    alpha = int(255 * s * (0.20 + min(1.0, deficit) * 0.48))
                    alpha = max(0, min(205, alpha))
                    if alpha > 6:
                        db.ellipse(
                            [x0 + pad, y0 + pad, x1 - pad, y1 - pad],
                            fill=(255, 255, 255, alpha),
                        )
    return Image.alpha_composite(wim, boost)


def _apply_circular_alpha_mask(im: Image.Image) -> Image.Image:
    """Clip image to an inscribed circle (transparent outside)."""
    rgba = im.convert("RGBA")
    w, h = rgba.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, w - 1, h - 1), fill=255)
    r, g, b, a = rgba.split()
    a = ImageChops.multiply(a, mask)
    return Image.merge("RGBA", (r, g, b, a))


def build_basic_qr(content: str, box_size: int = 12, border: int = 2) -> Image.Image:
    qr = _make_qr_instance(content, box_size, border)
    return qr.make_image(fill_color="black", back_color="white").convert("RGBA")


def _in_finder_corner(i: int, j: int, height: int, width: int) -> bool:
    """Return True if module (i, j) belongs to a 7x7 finder pattern region."""
    if i < 7 and j < 7:
        return True
    if i < 7 and j >= width - 7:
        return True
    if i >= height - 7 and j < 7:
        return True
    return False


def _tile_color_darkened(
    fitted: Image.Image,
    x0: int,
    y0: int,
    bs: int,
    black: Image.Image,
    module_darken: float,
) -> tuple[int, int, int]:
    tile_img = fitted.crop((x0, y0, x0 + bs, y0 + bs))
    dark_tile = Image.blend(tile_img, black, module_darken)
    return dark_tile.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))


def _base_canvas(fitted: Image.Image, photo_wash: float) -> Image.Image:
    """White background with optional full-image wash so silhouettes stay visible."""
    white = Image.new("RGB", fitted.size, (255, 255, 255))
    if photo_wash <= 0:
        return white.copy()
    w = max(0.0, min(photo_wash, 0.55))
    return Image.blend(white, fitted, w)


def _star_points(cx: float, cy: float, outer: float, inner: float, points: int = 5) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(points * 2):
        ang = -math.pi / 2 + i * math.pi / points
        r = outer if i % 2 == 0 else inner
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def _draw_dark_module(
    draw: ImageDraw.ImageDraw,
    module_shape: ModuleShape,
    x0: int,
    y0: int,
    bs: int,
    dot_scale: float,
    rgb: tuple[int, int, int],
) -> None:
    if module_shape == "square":
        margin = max(0.0, (1.0 - dot_scale) * bs / 2)
        draw.rectangle(
            [x0 + margin, y0 + margin, x0 + bs - margin, y0 + bs - margin],
            fill=rgb,
        )
        return
    cx = x0 + bs / 2
    cy = y0 + bs / 2
    outer = (bs * dot_scale) / 2
    if module_shape == "circle":
        draw.ellipse([cx - outer, cy - outer, cx + outer, cy + outer], fill=rgb)
        return
    inner = outer * 0.42
    draw.polygon(_star_points(cx, cy, outer, inner, 5), fill=rgb)


def _draw_shape_rgba(
    draw: ImageDraw.ImageDraw,
    module_shape: ModuleShape,
    x0: int,
    y0: int,
    bs: int,
    dot_scale: float,
    rgba: tuple[int, int, int, int],
) -> None:
    if module_shape == "square":
        margin = max(0.0, (1.0 - dot_scale) * bs / 2)
        draw.rectangle(
            [x0 + margin, y0 + margin, x0 + bs - margin, y0 + bs - margin],
            fill=rgba,
        )
        return
    cx = x0 + bs / 2
    cy = y0 + bs / 2
    outer = (bs * dot_scale) / 2
    if module_shape == "circle":
        draw.ellipse([cx - outer, cy - outer, cx + outer, cy + outer], fill=rgba)
        return
    inner = outer * 0.42
    draw.polygon(_star_points(cx, cy, outer, inner, 5), fill=rgba)


def _apply_finder_rings(
    draw: ImageDraw.ImageDraw,
    bd: int,
    bs: int,
    height: int,
    width: int,
    color: tuple[int, int, int],
    line_w: int,
) -> None:
    """Experimental: concentric rings around each finder (decorative)."""

    def center(mi: int, mj: int) -> tuple[float, float]:
        return (
            (mj + bd) * bs + 3.5 * bs,
            (mi + bd) * bs + 3.5 * bs,
        )

    corners = [(0, 0), (0, width - 7), (height - 7, 0)]
    for mi, mj in corners:
        cx, cy = center(mi, mj)
        for rk in (5.35, 6.25, 7.05):
            r = rk * bs
            draw.ellipse(
                [cx - r, cy - r, cx + r, cy + r],
                outline=color,
                width=line_w,
            )


def _accent_color(fitted: Image.Image) -> tuple[int, int, int]:
    return fitted.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))


def _recolor_qr_tile_rgba(
    tile: Image.Image,
    dark_rgb: tuple[int, int, int],
    light_rgb: tuple[int, int, int],
) -> Image.Image:
    """Map QR reference black/white (and grays) to two brand colors for finder corners."""
    t = tile.convert("RGBA")
    w, h = t.size
    px_in = t.load()
    out = Image.new("RGBA", (w, h))
    px_out = out.load()
    dr, dg, db = dark_rgb
    lr, lg, lb = light_rgb
    for y in range(h):
        for x in range(w):
            r, g, b, a = px_in[x, y]
            lum = (r * 299 + g * 587 + b * 114) // 1000
            if lum < 128:
                px_out[x, y] = (dr, dg, db, a)
            else:
                px_out[x, y] = (lr, lg, lb, a)
    return out


def _cover_crop_to_size(
    img: Image.Image,
    target_size: tuple[int, int],
    anchor_x: float,
    anchor_y: float,
    resample: int,
    cover_zoom: float = 1.0,
) -> Image.Image:
    """
    Scale image to cover target_size (aspect preserved), then crop to exact size.
    anchor_x / anchor_y in [0, 1] choose crop position when excess remains
    (0,0 = top-left of scaled image, 1,1 = bottom-right, 0.5,0.5 = center).
    cover_zoom < 1 zooms out (image may not fill the square; letterboxed on white).
    cover_zoom > 1 zooms in before cropping (tighter framing).
    """
    tw, th = target_size
    iw, ih = img.size
    if iw < 1 or ih < 1:
        raise ValueError("Invalid image dimensions")
    ax = max(0.0, min(1.0, anchor_x))
    ay = max(0.0, min(1.0, anchor_y))
    zm = max(0.25, min(cover_zoom, 3.0))
    scale = max(tw / iw, th / ih) * zm
    nw = max(1, int(round(iw * scale)))
    nh = max(1, int(round(ih * scale)))
    resized = img.resize((nw, nh), resample)
    if nw >= tw and nh >= th:
        left_max = max(0, nw - tw)
        top_max = max(0, nh - th)
        left = int(round(left_max * ax))
        top = int(round(top_max * ay))
        return resized.crop((left, top, left + tw, top + th))
    out = Image.new("RGB", (tw, th), (255, 255, 255))
    left_max = max(0, tw - nw)
    top_max = max(0, th - nh)
    left = int(round(left_max * ax))
    top = int(round(top_max * ay))
    out.paste(resized, (left, top))
    return out


def _contain_in_size(
    img: Image.Image,
    target_size: tuple[int, int],
    anchor_x: float,
    anchor_y: float,
    resample: int,
) -> Image.Image:
    """
    Scale image to fit entirely inside target_size (aspect preserved), on white.
    anchor_x / anchor_y in [0, 1] shift placement when letterboxing (margins exist).
    """
    tw, th = target_size
    iw, ih = img.size
    if iw < 1 or ih < 1:
        raise ValueError("Invalid image dimensions")
    ax = max(0.0, min(1.0, anchor_x))
    ay = max(0.0, min(1.0, anchor_y))
    scale = min(tw / iw, th / ih)
    nw = max(1, int(round(iw * scale)))
    nh = max(1, int(round(ih * scale)))
    resized = img.resize((nw, nh), resample)
    out = Image.new("RGB", (tw, th), (255, 255, 255))
    left_max = max(0, tw - nw)
    top_max = max(0, th - nh)
    left = int(round(left_max * ax))
    top = int(round(top_max * ay))
    out.paste(resized, (left, top))
    return out


def _fit_source_for_art(
    source_rgb: Image.Image,
    target_size: tuple[int, int],
    prepixelate_max: int = 0,
    crop_anchor_x: float = 0.5,
    crop_anchor_y: float = 0.5,
    fit_mode: FitMode = "contain",
    cover_zoom: float = 1.0,
) -> Image.Image:
    """
    Optional pixel-art prepass, then fit into the QR pixel grid:
    - contain: whole image stays inside the square (letterbox), nothing cropped off.
    - cover: scale to fill square then crop; use crop_anchor_* to pan the crop.
    """
    if not (0 <= prepixelate_max <= 512):
        raise ValueError("prepixelate_max must be between 0 and 512")
    if not (0 <= crop_anchor_x <= 1) or not (0 <= crop_anchor_y <= 1):
        raise ValueError("crop anchors must be between 0 and 1")
    if fit_mode not in ("cover", "contain"):
        raise ValueError("fit_mode must be cover or contain")
    if not (0.25 <= cover_zoom <= 3.0):
        raise ValueError("cover_zoom must be between 0.25 and 3")
    img = source_rgb
    if prepixelate_max > 0:
        w, h = img.size
        m = max(w, h)
        if m > prepixelate_max:
            scale = prepixelate_max / m
            nw = max(1, int(w * scale))
            nh = max(1, int(h * scale))
            img = img.resize((nw, nh), Image.Resampling.NEAREST)
    resample = Image.Resampling.NEAREST if prepixelate_max > 0 else Image.Resampling.LANCZOS
    if fit_mode == "contain":
        return _contain_in_size(img, target_size, crop_anchor_x, crop_anchor_y, resample)
    return _cover_crop_to_size(
        img,
        target_size,
        crop_anchor_x,
        crop_anchor_y,
        resample,
        cover_zoom=cover_zoom,
    )


def build_art_qr_modules(
    content: str,
    source_image_bytes: bytes,
    module_darken: float = 0.50,
    box_size: int = 12,
    border: int = 2,
    module_shape: ModuleShape = "square",
    dot_scale: float = 0.92,
    photo_wash: float = 0.0,
    finder_decor: bool = False,
    prepixelate_max: int = 0,
    crop_anchor_x: float = 0.5,
    crop_anchor_y: float = 0.5,
    fit_mode: FitMode = "contain",
    cover_zoom: float = 1.0,
) -> Image.Image:
    if not (0 <= module_darken <= 1):
        raise ValueError("module_darken must be between 0 and 1")
    if not (0.35 <= dot_scale <= 1.0):
        raise ValueError("dot_scale must be between 0.35 and 1")
    if not (0 <= photo_wash <= 0.55):
        raise ValueError("photo_wash must be between 0 and 0.55")

    qr = _make_qr_instance(content, box_size, border)
    matrix = qr.modules
    height = len(matrix)
    width = len(matrix[0])
    bs = qr.box_size
    bd = qr.border

    try:
        source = _open_uploaded_image(source_image_bytes).convert("RGB")
    except Exception as err:  # noqa: BLE001
        raise ValueError("Invalid image file") from err

    ref = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    pix_w = ref.size[0]
    pix_h = ref.size[1]
    fitted = _fit_source_for_art(
        source,
        (pix_w, pix_h),
        prepixelate_max,
        crop_anchor_x,
        crop_anchor_y,
        fit_mode,
        cover_zoom,
    )

    out = _base_canvas(fitted, photo_wash)
    draw = ImageDraw.Draw(out)
    black = Image.new("RGB", (bs, bs), (0, 0, 0))

    for i in range(height):
        for j in range(width):
            y0 = (i + bd) * bs
            x0 = (j + bd) * bs
            if _in_finder_corner(i, j, height, width):
                tile = ref.crop((x0, y0, x0 + bs, y0 + bs))
                out.paste(tile, (x0, y0))
                continue
            if matrix[i][j]:
                rgb = _tile_color_darkened(fitted, x0, y0, bs, black, module_darken)
                _draw_dark_module(draw, module_shape, x0, y0, bs, dot_scale, rgb)

    if finder_decor:
        accent = _accent_color(fitted)
        lw = max(1, min(6, bs // 5))
        _apply_finder_rings(draw, bd, bs, height, width, accent, lw)

    return out.convert("RGBA")


def build_art_qr_halftone(
    content: str,
    source_image_bytes: bytes,
    module_darken: float = 0.48,
    box_size: int = 12,
    border: int = 2,
    dot_scale: float = 0.78,
    light_dots: bool = False,
    light_dot_scale: float = 0.22,
    light_dot_strength: float = 0.35,
    module_shape: ModuleShape = "square",
    photo_wash: float = 0.0,
    finder_decor: bool = False,
    prepixelate_max: int = 0,
    crop_anchor_x: float = 0.5,
    crop_anchor_y: float = 0.5,
    fit_mode: FitMode = "contain",
    cover_zoom: float = 1.0,
) -> Image.Image:
    if not (0 <= module_darken <= 1):
        raise ValueError("module_darken must be between 0 and 1")
    if not (0.35 <= dot_scale <= 1.0):
        raise ValueError("dot_scale must be between 0.35 and 1")
    if not (0.05 <= light_dot_scale <= 0.45):
        raise ValueError("light_dot_scale must be between 0.05 and 0.45")
    if not (0 <= light_dot_strength <= 1):
        raise ValueError("light_dot_strength must be between 0 and 1")
    if not (0 <= photo_wash <= 0.55):
        raise ValueError("photo_wash must be between 0 and 0.55")

    qr = _make_qr_instance(content, box_size, border)
    matrix = qr.modules
    height = len(matrix)
    width = len(matrix[0])
    bs = qr.box_size
    bd = qr.border

    try:
        source = _open_uploaded_image(source_image_bytes).convert("RGB")
    except Exception as err:  # noqa: BLE001
        raise ValueError("Invalid image file") from err

    ref = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    pix_w = ref.size[0]
    pix_h = ref.size[1]
    fitted = _fit_source_for_art(
        source,
        (pix_w, pix_h),
        prepixelate_max,
        crop_anchor_x,
        crop_anchor_y,
        fit_mode,
        cover_zoom,
    )

    out = _base_canvas(fitted, photo_wash)
    draw = ImageDraw.Draw(out)
    black = Image.new("RGB", (bs, bs), (0, 0, 0))
    white = Image.new("RGB", (bs, bs), (255, 255, 255))

    for i in range(height):
        for j in range(width):
            y0 = (i + bd) * bs
            x0 = (j + bd) * bs
            if _in_finder_corner(i, j, height, width):
                tile = ref.crop((x0, y0, x0 + bs, y0 + bs))
                out.paste(tile, (x0, y0))
                continue

            cx = x0 + bs / 2
            cy = y0 + bs / 2

            if matrix[i][j]:
                rgb = _tile_color_darkened(fitted, x0, y0, bs, black, module_darken)
                _draw_dark_module(draw, module_shape, x0, y0, bs, dot_scale, rgb)
            elif light_dots:
                tint = _tile_color_darkened(fitted, x0, y0, bs, white, 0.0)
                speck = Image.blend(white, Image.new("RGB", (1, 1), tint), light_dot_strength)
                rgb = speck.getpixel((0, 0))
                r = (bs * light_dot_scale) / 2
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rgb)

    if finder_decor:
        accent = _accent_color(fitted)
        lw = max(1, min(6, bs // 5))
        _apply_finder_rings(draw, bd, bs, height, width, accent, lw)

    return out.convert("RGBA")


def build_art_qr_photo_mesh(
    content: str,
    source_image_bytes: bytes,
    box_size: int = 12,
    border: int = 2,
    module_shape: ModuleShape = "square",
    dot_scale: float = 0.68,
    mesh_dark_alpha: float = 0.55,
    mesh_light_alpha: float = 0.42,
    mesh_dark_rgb: tuple[int, int, int] = (0, 0, 0),
    mesh_light_rgb: tuple[int, int, int] = (255, 255, 255),
    finder_decor: bool = False,
    prepixelate_max: int = 0,
    crop_anchor_x: float = 0.5,
    crop_anchor_y: float = 0.5,
    fit_mode: FitMode = "contain",
    cover_zoom: float = 1.0,
) -> Image.Image:
    """
    Full photo under a dot mesh: translucent dark dots on 'black' modules and
    light dots on 'white' modules (Spotify / portrait style references).
    """
    if not (0.35 <= dot_scale <= 1.0):
        raise ValueError("dot_scale must be between 0.35 and 1")
    if not (0.02 <= mesh_dark_alpha <= 0.92):
        raise ValueError("mesh_dark_alpha must be between 0.02 and 0.92")
    if not (0.02 <= mesh_light_alpha <= 0.92):
        raise ValueError("mesh_light_alpha must be between 0.02 and 0.92")

    qr = _make_qr_instance(content, box_size, border)
    matrix = qr.modules
    height = len(matrix)
    width = len(matrix[0])
    bs = qr.box_size
    bd = qr.border

    try:
        source = _open_uploaded_image(source_image_bytes).convert("RGB")
    except Exception as err:  # noqa: BLE001
        raise ValueError("Invalid image file") from err

    ref = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    pix_w = ref.size[0]
    pix_h = ref.size[1]
    fitted = _fit_source_for_art(
        source,
        (pix_w, pix_h),
        prepixelate_max,
        crop_anchor_x,
        crop_anchor_y,
        fit_mode,
        cover_zoom,
    )

    base = fitted.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    da = int(255 * mesh_dark_alpha)
    la = int(255 * mesh_light_alpha)
    dr, dg, db = mesh_dark_rgb
    lr, lg, lb = mesh_light_rgb

    for i in range(height):
        for j in range(width):
            y0 = (i + bd) * bs
            x0 = (j + bd) * bs
            if _in_finder_corner(i, j, height, width):
                continue
            if matrix[i][j]:
                _draw_shape_rgba(draw, module_shape, x0, y0, bs, dot_scale, (dr, dg, db, da))
            else:
                _draw_shape_rgba(draw, module_shape, x0, y0, bs, dot_scale, (lr, lg, lb, la))

    out = Image.alpha_composite(base, overlay)
    ref_rgba = ref.convert("RGBA")

    for i in range(height):
        for j in range(width):
            y0 = (i + bd) * bs
            x0 = (j + bd) * bs
            if _in_finder_corner(i, j, height, width):
                tile = ref_rgba.crop((x0, y0, x0 + bs, y0 + bs))
                tile = _recolor_qr_tile_rgba(tile, mesh_dark_rgb, mesh_light_rgb)
                out.paste(tile, (x0, y0))

    if finder_decor:
        accent = _accent_color(fitted)
        lw = max(1, min(6, bs // 5))
        draw2 = ImageDraw.Draw(out)
        _apply_finder_rings(draw2, bd, bs, height, width, accent, lw)

    return out


def build_art_qr_photo_stipple(
    content: str,
    source_image_bytes: bytes,
    box_size: int = 8,
    border: int = 2,
    mesh_dark_rgb: tuple[int, int, int] = (0, 0, 0),
    mesh_light_rgb: tuple[int, int, int] = (255, 255, 255),
    stipple_grid: int = 4,
    stipple_dark_fill: float = 0.78,
    stipple_light_fill: float = 0.06,
    stipple_alpha: float = 0.94,
    stipple_scan_boost: float = 0.74,
    stipple_dot_shape: StippleDotShape = "square",
    stipple_image_dots: bool = True,
    stipple_dot_size_scale: float = 0.70,
    stipple_luma_threshold: float = 128.0,
    stipple_luma_margin: float = 10.0,
    finder_decor: bool = False,
    prepixelate_max: int = 0,
    crop_anchor_x: float = 0.5,
    crop_anchor_y: float = 0.5,
    fit_mode: FitMode = "contain",
    cover_zoom: float = 1.0,
    circular_mask: bool = False,
) -> Image.Image:
    """
    Full photo as background; Bayer stipple per QR module.
    Image-dot mode: sample underlying RGB, then luminance-aware blend toward dark/light
    inks so dark modules read darker than threshold and light modules lighter. Dots are
    scaled below the sub-cell so the photo shows in gaps. Finder patterns use raw B/W.
    """
    if stipple_dot_shape not in ("circle", "square"):
        raise ValueError("stipple_dot_shape must be circle or square")
    if not (0.0 <= stipple_scan_boost <= 1.0):
        raise ValueError("stipple_scan_boost must be between 0 and 1")
    if not (3 <= stipple_grid <= 10):
        raise ValueError("stipple_grid must be between 3 and 10")
    if not (0.35 <= stipple_dark_fill <= 0.98):
        raise ValueError("stipple_dark_fill must be between 0.35 and 0.98")
    if not (0.02 <= stipple_light_fill <= 0.22):
        raise ValueError("stipple_light_fill must be between 0.02 and 0.22 (higher hides light modules)")
    if not (0.58 <= stipple_alpha <= 1.0):
        raise ValueError("stipple_alpha must be between 0.58 and 1.0 (lower values rarely scan)")
    if not (0.55 <= stipple_dot_size_scale <= 0.85):
        raise ValueError("stipple_dot_size_scale must be between 0.55 and 0.85")
    if not (80.0 <= stipple_luma_threshold <= 176.0):
        raise ValueError("stipple_luma_threshold must be between 80 and 176")
    if not (4.0 <= stipple_luma_margin <= 28.0):
        raise ValueError("stipple_luma_margin must be between 4 and 28")

    qr = _make_qr_instance_dense(content, box_size, border)
    matrix = qr.modules
    height = len(matrix)
    width = len(matrix[0])
    bs = qr.box_size
    bd = qr.border

    try:
        source = _open_uploaded_image(source_image_bytes).convert("RGB")
    except Exception as err:  # noqa: BLE001
        raise ValueError("Invalid image file") from err

    ref = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    pix_w = ref.size[0]
    pix_h = ref.size[1]
    fitted = _fit_source_for_art(
        source,
        (pix_w, pix_h),
        prepixelate_max,
        crop_anchor_x,
        crop_anchor_y,
        fit_mode,
        cover_zoom,
    )
    fitted_px = fitted.load()

    base = fitted.convert("RGBA")
    canvas = base

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    a_full = int(255 * stipple_alpha)
    gw = max(1, stipple_grid)
    sub = bs / gw
    dot_scale = max(0.55, min(0.85, stipple_dot_size_scale))
    half = sub * 0.5
    rad = max(0.5, half * dot_scale)

    for i in range(height):
        for j in range(width):
            y0 = (i + bd) * bs
            x0 = (j + bd) * bs
            if _in_finder_corner(i, j, height, width):
                continue
            is_dark = bool(matrix[i][j])
            for si in range(gw):
                for sj in range(gw):
                    if not _stipple_cell_paint(is_dark, si, sj, stipple_dark_fill, stipple_light_fill):
                        continue
                    cx = int(round(x0 + (si + 0.5) * sub))
                    cy = int(round(y0 + (sj + 0.5) * sub))
                    cx = max(0, min(fitted.size[0] - 1, cx))
                    cy = max(0, min(fitted.size[1] - 1, cy))
                    rpx, gpx, bpx = fitted_px[cx, cy]
                    if stipple_image_dots:
                        pr, pg, pb = _stipple_luma_adjust_rgb(
                            rpx,
                            gpx,
                            bpx,
                            is_dark,
                            mesh_dark_rgb,
                            mesh_light_rgb,
                            threshold=stipple_luma_threshold,
                            margin=stipple_luma_margin,
                        )
                        a_dot = a_full
                    else:
                        pr, pg, pb = _stipple_dot_color(
                            rpx,
                            gpx,
                            bpx,
                            is_dark,
                            False,
                            mesh_dark_rgb,
                            mesh_light_rgb,
                            stipple_scan_boost,
                        )
                        a_dot = a_full
                    x1, y1, x2, y2 = cx - rad, cy - rad, cx + rad, cy + rad
                    if stipple_dot_shape == "square":
                        draw.rectangle([x1, y1, x2, y2], fill=(pr, pg, pb, a_dot))
                    else:
                        draw.ellipse([x1, y1, x2, y2], fill=(pr, pg, pb, a_dot))

    out = Image.alpha_composite(canvas, overlay)
    if not stipple_image_dots:
        out = _apply_stipple_module_scan_boost(
            out, matrix, bd, bs, height, width, stipple_scan_boost,
        )
    elif stipple_scan_boost > 0.08:
        out = _apply_stipple_module_scan_boost(
            out, matrix, bd, bs, height, width, stipple_scan_boost * 0.18,
        )
    ref_rgba = ref.convert("RGBA")
    finder_dark, finder_light = _finder_colors_scan_safe(mesh_dark_rgb, mesh_light_rgb)

    for i in range(height):
        for j in range(width):
            y0 = (i + bd) * bs
            x0 = (j + bd) * bs
            if _in_finder_corner(i, j, height, width):
                tile = ref_rgba.crop((x0, y0, x0 + bs, y0 + bs))
                if stipple_image_dots:
                    out.paste(tile, (x0, y0))
                else:
                    tile = _recolor_qr_tile_rgba(tile, finder_dark, finder_light)
                    out.paste(tile, (x0, y0))

    if finder_decor:
        accent = _accent_color(fitted)
        lw = max(1, min(6, bs // 5))
        draw2 = ImageDraw.Draw(out)
        _apply_finder_rings(draw2, bd, bs, height, width, accent, lw)

    if circular_mask:
        out = _apply_circular_alpha_mask(out)

    return out


def _microdot_rgba(
    is_dark_module: bool,
    br: int,
    bg: int,
    bb: int,
    ink_dark: tuple[int, int, int],
    ink_light: tuple[int, int, int],
    smart_contrast: bool,
) -> tuple[int, int, int, int]:
    """Solid micro-dot colors; optional tweaks when dots would disappear into the background."""
    dr, dg, db = ink_dark
    lr, lg, lb = ink_light
    if not smart_contrast:
        return (dr, dg, db, 255) if is_dark_module else (lr, lg, lb, 255)
    L = _stipple_sample_luma(br, bg, bb)
    if is_dark_module:
        if L < 52:
            t = max(0.0, (52.0 - L) / 52.0)
            return (
                int(dr + (min(100, lr) - dr) * t * 0.4),
                int(dg + (min(100, lg) - dg) * t * 0.4),
                int(db + (min(100, lb) - db) * t * 0.4),
                255,
            )
        return (dr, dg, db, 255)
    if L > 215:
        t = min(1.0, (L - 215.0) / 40.0)
        return (
            int(lr - (lr - 228) * t * 0.35),
            int(lg - (lg - 228) * t * 0.35),
            int(lb - (lb - 228) * t * 0.35),
            255,
        )
    return (lr, lg, lb, 255)


def _finder_corner_origins_px(bd: int, bs: int, height: int, width: int) -> list[tuple[int, int]]:
    return [
        ((0 + bd) * bs, (0 + bd) * bs),
        ((width - 7 + bd) * bs, (0 + bd) * bs),
        ((0 + bd) * bs, (height - 7 + bd) * bs),
    ]


def _ellipse_mask_binary(
    size: tuple[int, int],
    bounds: tuple[float, float, float, float],
) -> Image.Image:
    """Filled ellipse as L-mode mask with edges forced to 0/255 (no anti-aliased semitransparency)."""
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).ellipse(bounds, fill=255)
    return m.point(lambda p: 255 if p >= 128 else 0, mode="L")


def draw_finder_pattern(
    out: Image.Image,
    px: int,
    py: int,
    bs: int,
    shape: MicrodotFinderShape,
    dark_rgb: tuple[int, int, int],
    light_rgb: tuple[int, int, int],
) -> None:
    """
    Draw one 7×7-module position marker (finder) in pixel space. Solid fills only — no micro-dots.
    Square: light 7×7 base (clears photo), then 7×7 dark, 5×5 light, 3×3 dark (standard topology).
    Circle (bullseye): opaque dark_rgb ring and light_rgb center dot on a transparent tile; middle
    band and area outside the ring (square corners) stay clear over the photo.
    """
    if shape not in ("square", "circle"):
        raise ValueError("shape must be square or circle")
    w7 = 7 * bs
    dk = dark_rgb + (255,)
    lt = light_rgb + (255,)
    x1, y1 = float(px), float(py)
    x2, y2 = float(px + w7), float(py + w7)
    if shape == "square":
        draw = ImageDraw.Draw(out)
        draw.rectangle([x1, y1, x2, y2], fill=lt)
        draw.rectangle([x1, y1, x2, y2], fill=dk)
        inset1 = float(bs)
        draw.rectangle(
            [x1 + inset1, y1 + inset1, x2 - inset1, y2 - inset1],
            fill=lt,
        )
        inset2 = float(2 * bs)
        draw.rectangle(
            [x1 + inset2, y1 + inset2, x2 - inset2, y2 - inset2],
            fill=dk,
        )
        return
    tile = Image.new("RGBA", (w7, w7), (0, 0, 0, 0))
    cx = w7 / 2.0
    cy = w7 / 2.0
    r_outer = 3.5 * bs
    r_ring_inner = 2.5 * bs
    r_center_dot = 1.5 * bs
    outer_m = _ellipse_mask_binary(
        (w7, w7),
        (cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer),
    )
    inner_m = _ellipse_mask_binary(
        (w7, w7),
        (cx - r_ring_inner, cy - r_ring_inner, cx + r_ring_inner, cy + r_ring_inner),
    )
    ring_mask = ImageChops.subtract(outer_m, inner_m)
    ring_layer = Image.new("RGBA", (w7, w7), dk)
    tile = Image.composite(ring_layer, tile, ring_mask)
    dot_m = _ellipse_mask_binary(
        (w7, w7),
        (
            cx - r_center_dot,
            cy - r_center_dot,
            cx + r_center_dot,
            cy + r_center_dot,
        ),
    )
    dot_layer = Image.new("RGBA", (w7, w7), lt)
    tile.paste(dot_layer, (0, 0), mask=dot_m)
    out.alpha_composite(tile, (px, py))


def _paste_finder_square(out: Image.Image, ref_rgba: Image.Image, px: int, py: int, bs: int) -> None:
    w = 7 * bs
    tile = ref_rgba.crop((px, py, px + w, py + w))
    out.paste(tile, (px, py))


def _draw_finder_rounded_modules(
    draw: ImageDraw.ImageDraw,
    ref_rgba: Image.Image,
    px: int,
    py: int,
    bs: int,
) -> None:
    """Standard finder topology with circular module caps (high-contrast from reference)."""
    rad = max(0.38 * bs, 0.75)
    for di in range(7):
        for dj in range(7):
            tcx = px + dj * bs
            tcy = py + di * bs
            cx = tcx + bs / 2.0
            cy = tcy + bs / 2.0
            r, g, b, a = ref_rgba.getpixel((int(cx), int(cy)))
            draw.ellipse(
                [cx - rad, cy - rad, cx + rad, cy + rad],
                fill=(r, g, b, min(255, a)),
            )


def _draw_finder_bullseye(
    draw: ImageDraw.ImageDraw,
    px: int,
    py: int,
    bs: int,
    ink_dark: tuple[int, int, int],
    ink_light: tuple[int, int, int],
) -> None:
    """Concentric rings approximating a position marker (brand / Target style)."""
    cx = px + 3.5 * bs
    cy = py + 3.5 * bs
    r0 = 3.45 * bs
    r1 = 2.72 * bs
    r2 = 1.88 * bs
    r3 = 0.88 * bs
    bk = ink_dark + (255,)
    wh = ink_light + (255,)
    draw.ellipse([cx - r0, cy - r0, cx + r0, cy + r0], fill=bk)
    draw.ellipse([cx - r1, cy - r1, cx + r1, cy + r1], fill=wh)
    draw.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=bk)
    draw.ellipse([cx - r3, cy - r3, cx + r3, cy + r3], fill=wh)


def build_art_qr_photo_microdot(
    content: str,
    source_image_bytes: bytes,
    box_size: int = 12,
    border: int = 2,
    mesh_dark_rgb: tuple[int, int, int] = (0, 0, 0),
    mesh_light_rgb: tuple[int, int, int] = (255, 255, 255),
    micro_dot_radius_frac: float = 0.22,
    micro_smart_contrast: bool = True,
    finder_shape: MicrodotFinderShape = "square",
    finder_dark_rgb: tuple[int, int, int] = (0, 0, 0),
    finder_light_rgb: tuple[int, int, int] = (255, 255, 255),
    finder_decor: bool = False,
    photo_wash: float = 0.0,
    prepixelate_max: int = 0,
    crop_anchor_x: float = 0.5,
    crop_anchor_y: float = 0.5,
    fit_mode: FitMode = "contain",
    cover_zoom: float = 1.0,
    circular_mask: bool = False,
) -> Image.Image:
    """
    Full photo base; one tiny B/W (or ink) dot at each data module center; solid finders on top.
    """
    if not (0.08 <= micro_dot_radius_frac <= 0.35):
        raise ValueError("micro_dot_radius_frac must be between 0.08 and 0.35")
    if finder_shape not in ("square", "circle"):
        raise ValueError("finder_shape must be square or circle")

    qr = _make_qr_instance_dense(content, box_size, border)
    matrix = qr.modules
    height = len(matrix)
    width = len(matrix[0])
    bs = qr.box_size
    bd = qr.border

    try:
        source = _open_uploaded_image(source_image_bytes).convert("RGB")
    except Exception as err:  # noqa: BLE001
        raise ValueError("Invalid image file") from err

    ref_size_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    pix_w, pix_h = ref_size_img.size
    fitted = _fit_source_for_art(
        source,
        (pix_w, pix_h),
        prepixelate_max,
        crop_anchor_x,
        crop_anchor_y,
        fit_mode,
        cover_zoom,
    )

    if abs(photo_wash) > 1e-4:
        if photo_wash > 0:
            white = Image.new("RGB", fitted.size, (255, 255, 255))
            fitted = Image.blend(fitted, white, min(0.8, photo_wash))
        else:
            black = Image.new("RGB", fitted.size, (0, 0, 0))
            fitted = Image.blend(fitted, black, min(0.8, abs(photo_wash)))

    base = fitted.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    r_frac = max(0.08, min(0.35, micro_dot_radius_frac))
    rdot = max(0.5, bs * r_frac)
    w1, h1 = fitted.size
    fitted_px = fitted.load()

    for i in range(height):
        for j in range(width):
            if _in_finder_corner(i, j, height, width):
                continue
            cx = (j + bd) * bs + bs / 2.0
            cy = (i + bd) * bs + bs / 2.0
            ix = int(max(0, min(w1 - 1, round(cx))))
            iy = int(max(0, min(h1 - 1, round(cy))))
            br, bg, bb = fitted_px[ix, iy]
            is_dark = bool(matrix[i][j])
            prgba = _microdot_rgba(
                is_dark,
                br,
                bg,
                bb,
                mesh_dark_rgb,
                mesh_light_rgb,
                micro_smart_contrast,
            )
            draw.ellipse(
                [cx - rdot, cy - rdot, cx + rdot, cy + rdot],
                fill=prgba,
            )

    out = Image.alpha_composite(base, overlay)
    for fpx, fpy in _finder_corner_origins_px(bd, bs, height, width):
        draw_finder_pattern(
            out,
            fpx,
            fpy,
            bs,
            finder_shape,
            finder_dark_rgb,
            finder_light_rgb,
        )

    draw_f = ImageDraw.Draw(out)
    if finder_decor:
        accent = _accent_color(fitted)
        lw = max(1, min(6, bs // 5))
        _apply_finder_rings(draw_f, bd, bs, height, width, accent, lw)

    if circular_mask:
        out = _apply_circular_alpha_mask(out)

    return out


def build_art_qr_overlay(
    content: str,
    source_image_bytes: bytes,
    overlay_alpha: float = 0.40,
    box_size: int = 12,
    border: int = 2,
    prepixelate_max: int = 0,
    crop_anchor_x: float = 0.5,
    crop_anchor_y: float = 0.5,
    fit_mode: FitMode = "contain",
    cover_zoom: float = 1.0,
) -> Image.Image:
    """Legacy: full-image overlay under the QR pattern."""
    qr_image = build_basic_qr(content=content, box_size=box_size, border=border)

    try:
        source = _open_uploaded_image(source_image_bytes).convert("RGBA")
    except Exception as err:  # noqa: BLE001
        raise ValueError("Invalid image file") from err

    fitted = _fit_source_for_art(
        source.convert("RGB"),
        qr_image.size,
        prepixelate_max,
        crop_anchor_x,
        crop_anchor_y,
        fit_mode,
        cover_zoom,
    ).convert("RGBA")

    blend_alpha = int(255 * max(0.0, min(overlay_alpha, 1.0)))
    mask = Image.new("L", qr_image.size, blend_alpha)
    blended = Image.composite(fitted, qr_image, mask)

    finder_size = int(qr_image.size[0] * 0.17)
    corner_pad = int(qr_image.size[0] * 0.03)
    finder = qr_image.crop((0, 0, finder_size, finder_size))
    blended.paste(finder, (corner_pad, corner_pad))
    blended.paste(finder, (qr_image.size[0] - finder_size - corner_pad, corner_pad))
    blended.paste(finder, (corner_pad, qr_image.size[1] - finder_size - corner_pad))

    return blended


def build_art_qr(
    content: str,
    source_image_bytes: bytes,
    style: ArtStyle = "halftone",
    overlay_alpha: float = 0.40,
    module_darken: float = 0.50,
    box_size: int = 12,
    border: int = 2,
    module_shape: ModuleShape = "square",
    dot_scale: float = 0.78,
    halftone_light_dots: bool = False,
    light_dot_scale: float = 0.22,
    light_dot_strength: float = 0.35,
    photo_wash: float = 0.0,
    finder_decor: bool = False,
    mesh_dark_alpha: float = 0.55,
    mesh_light_alpha: float = 0.42,
    mesh_dark_rgb: tuple[int, int, int] = (0, 0, 0),
    mesh_light_rgb: tuple[int, int, int] = (255, 255, 255),
    stipple_grid: int = 4,
    stipple_dark_fill: float = 0.78,
    stipple_light_fill: float = 0.06,
    stipple_alpha: float = 0.94,
    stipple_scan_boost: float = 0.74,
    stipple_dot_shape: StippleDotShape = "square",
    stipple_image_dots: bool = True,
    stipple_dot_size_scale: float = 0.70,
    stipple_luma_threshold: float = 128.0,
    stipple_luma_margin: float = 10.0,
    circular_mask: bool = False,
    prepixelate_max: int = 0,
    crop_anchor_x: float = 0.5,
    crop_anchor_y: float = 0.5,
    fit_mode: FitMode = "contain",
    cover_zoom: float = 1.0,
    micro_dot_radius_frac: float = 0.22,
    micro_smart_contrast: bool = True,
    micro_finder_style: MicroFinderStyle = "square",
    finder_shape: MicrodotFinderShape = "square",
    finder_dark_rgb: tuple[int, int, int] | None = None,
    finder_light_rgb: tuple[int, int, int] | None = None,
) -> Image.Image:
    if style == "overlay":
        return build_art_qr_overlay(
            content=content,
            source_image_bytes=source_image_bytes,
            overlay_alpha=overlay_alpha,
            box_size=box_size,
            border=border,
            prepixelate_max=prepixelate_max,
            crop_anchor_x=crop_anchor_x,
            crop_anchor_y=crop_anchor_y,
            fit_mode=fit_mode,
            cover_zoom=cover_zoom,
        )
    if style == "photo_mesh":
        return build_art_qr_photo_mesh(
            content=content,
            source_image_bytes=source_image_bytes,
            box_size=box_size,
            border=border,
            module_shape=module_shape,
            dot_scale=dot_scale,
            mesh_dark_alpha=mesh_dark_alpha,
            mesh_light_alpha=mesh_light_alpha,
            mesh_dark_rgb=mesh_dark_rgb,
            mesh_light_rgb=mesh_light_rgb,
            finder_decor=finder_decor,
            prepixelate_max=prepixelate_max,
            crop_anchor_x=crop_anchor_x,
            crop_anchor_y=crop_anchor_y,
            fit_mode=fit_mode,
            cover_zoom=cover_zoom,
        )
    if style == "photo_stipple":
        return build_art_qr_photo_stipple(
            content=content,
            source_image_bytes=source_image_bytes,
            box_size=box_size,
            border=border,
            mesh_dark_rgb=mesh_dark_rgb,
            mesh_light_rgb=mesh_light_rgb,
            stipple_grid=stipple_grid,
            stipple_dark_fill=stipple_dark_fill,
            stipple_light_fill=stipple_light_fill,
            stipple_alpha=stipple_alpha,
            stipple_scan_boost=stipple_scan_boost,
            stipple_dot_shape=stipple_dot_shape,
            stipple_image_dots=stipple_image_dots,
            stipple_dot_size_scale=stipple_dot_size_scale,
            stipple_luma_threshold=stipple_luma_threshold,
            stipple_luma_margin=stipple_luma_margin,
            finder_decor=finder_decor,
            prepixelate_max=prepixelate_max,
            crop_anchor_x=crop_anchor_x,
            crop_anchor_y=crop_anchor_y,
            fit_mode=fit_mode,
            cover_zoom=cover_zoom,
            circular_mask=circular_mask,
        )
    if style == "photo_microdot":
        fs: MicrodotFinderShape = (
            "circle" if micro_finder_style == "bullseye" else finder_shape
        )
        fd = finder_dark_rgb if finder_dark_rgb is not None else mesh_dark_rgb
        fl = finder_light_rgb if finder_light_rgb is not None else mesh_light_rgb
        return build_art_qr_photo_microdot(
            content=content,
            source_image_bytes=source_image_bytes,
            box_size=box_size,
            border=border,
            mesh_dark_rgb=mesh_dark_rgb,
            mesh_light_rgb=mesh_light_rgb,
            micro_dot_radius_frac=micro_dot_radius_frac,
            micro_smart_contrast=micro_smart_contrast,
            finder_shape=fs,
            finder_dark_rgb=fd,
            finder_light_rgb=fl,
            finder_decor=finder_decor,
            photo_wash=photo_wash,
            prepixelate_max=prepixelate_max,
            crop_anchor_x=crop_anchor_x,
            crop_anchor_y=crop_anchor_y,
            fit_mode=fit_mode,
            cover_zoom=cover_zoom,
            circular_mask=circular_mask,
        )
    if style == "halftone":
        return build_art_qr_halftone(
            content=content,
            source_image_bytes=source_image_bytes,
            module_darken=module_darken,
            box_size=box_size,
            border=border,
            dot_scale=dot_scale,
            light_dots=halftone_light_dots,
            light_dot_scale=light_dot_scale,
            light_dot_strength=light_dot_strength,
            module_shape=module_shape,
            photo_wash=photo_wash,
            finder_decor=finder_decor,
            prepixelate_max=prepixelate_max,
            crop_anchor_x=crop_anchor_x,
            crop_anchor_y=crop_anchor_y,
            fit_mode=fit_mode,
            cover_zoom=cover_zoom,
        )
    return build_art_qr_modules(
        content=content,
        source_image_bytes=source_image_bytes,
        module_darken=module_darken,
        box_size=box_size,
        border=border,
        module_shape=module_shape,
        dot_scale=dot_scale,
        photo_wash=photo_wash,
        finder_decor=finder_decor,
        prepixelate_max=prepixelate_max,
        crop_anchor_x=crop_anchor_x,
        crop_anchor_y=crop_anchor_y,
        fit_mode=fit_mode,
        cover_zoom=cover_zoom,
    )
