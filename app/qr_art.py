from io import BytesIO
from typing import Literal

from PIL import Image, ImageChops, ImageDraw, ImageOps
import qrcode
from qrcode.constants import ERROR_CORRECT_H

ArtStyle = Literal["photo_microdot"]
FitMode = Literal["cover", "contain"]
MicrodotFinderShape = Literal["square", "circle"]


def _open_uploaded_image(data: bytes) -> Image.Image:
    """Decode bytes and apply EXIF orientation."""
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


def _luma_from_rgb(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return (r * 299 + g * 587 + b * 114) / 1000.0


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
    
    L = _luma_from_rgb((br, bg, bb))
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


def _ellipse_mask_binary(size: tuple[int, int], box: tuple[float, float, float, float]) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse(box, fill=255)
    return mask


def draw_finder_pattern(
    out: Image.Image,
    px: int,
    py: int,
    bs: int,
    shape: MicrodotFinderShape,
    dark_rgb: tuple[int, int, int],
    light_rgb: tuple[int, int, int],
) -> None:
    """Draw one 7×7-module position marker (finder) in pixel space."""
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
        draw.rectangle([x1 + inset1, y1 + inset1, x2 - inset1, y2 - inset1], fill=lt)
        inset2 = float(2 * bs)
        draw.rectangle([x1 + inset2, y1 + inset2, x2 - inset2, y2 - inset2], fill=dk)
        return
        
    tile = Image.new("RGBA", (w7, w7), (0, 0, 0, 0))
    cx, cy = w7 / 2.0, w7 / 2.0
    r_outer = 3.5 * bs
    r_ring_inner = 2.5 * bs
    r_center_dot = 1.5 * bs
    
    outer_m = _ellipse_mask_binary((w7, w7), (cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer))
    inner_m = _ellipse_mask_binary((w7, w7), (cx - r_ring_inner, cy - r_ring_inner, cx + r_ring_inner, cy + r_ring_inner))
    ring_mask = ImageChops.subtract(outer_m, inner_m)
    ring_layer = Image.new("RGBA", (w7, w7), dk)
    tile = Image.composite(ring_layer, tile, ring_mask)
    
    dot_m = _ellipse_mask_binary((w7, w7), (cx - r_center_dot, cy - r_center_dot, cx + r_center_dot, cy + r_center_dot))
    dot_layer = Image.new("RGBA", (w7, w7), lt)
    tile.paste(dot_layer, (0, 0), mask=dot_m)
    out.alpha_composite(tile, (px, py))


def _in_finder_corner(i: int, j: int, height: int, width: int) -> bool:
    if i < 7 and j < 7:
        return True
    if i < 7 and j >= width - 7:
        return True
    if i >= height - 7 and j < 7:
        return True
    return False


def _fit_source_for_art(
    source: Image.Image,
    target_size: tuple[int, int],
    prepixelate_max: int,
    anchor_x: float,
    anchor_y: float,
    fit_mode: FitMode,
    zoom: float,
) -> Image.Image:
    tw, th = target_size
    sw, sh = source.size

    if fit_mode == "contain":
        scale = min(tw / sw, th / sh)
        new_w, new_h = int(sw * scale), int(sh * scale)
        res = source.resize((new_w, new_h), Image.Resampling.LANCZOS)
        out = Image.new("RGB", target_size, (255, 255, 255))
        out.paste(res, ((tw - new_w) // 2, (th - new_h) // 2))
    else:
        scale = max(tw / sw, th / sh) * zoom
        new_w, new_h = int(sw * scale), int(sh * scale)
        res = source.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = int((new_w - tw) * anchor_x)
        top = int((new_h - th) * anchor_y)
        out = res.crop((left, top, left + tw, top + th))

    if prepixelate_max > 1:
        small_w = max(1, tw // prepixelate_max)
        small_h = max(1, th // prepixelate_max)
        out = out.resize((small_w, small_h), Image.Resampling.BOX).resize((tw, th), Image.Resampling.NEAREST)
    return out


def _apply_circular_alpha_mask(im: Image.Image) -> Image.Image:
    rgba = im.convert("RGBA")
    w, h = rgba.size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse([0, 0, w, h], fill=255)
    rgba.putalpha(mask)
    return rgba


def build_basic_qr(content: str, box_size: int = 12, border: int = 2) -> Image.Image:
    qr = _make_qr_instance(content, box_size, border)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


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
    finder_dark_rgb: tuple[int, int, int] | None = None,
    finder_light_rgb: tuple[int, int, int] | None = None,
    prepixelate_max: int = 0,
    crop_anchor_x: float = 0.5,
    crop_anchor_y: float = 0.5,
    fit_mode: FitMode = "cover",
    cover_zoom: float = 1.0,
    circular_mask: bool = False,
) -> Image.Image:
    qr = _make_qr_instance(content, box_size, border)
    matrix = qr.modules
    height, width = len(matrix), len(matrix[0])
    bs, bd = qr.box_size, qr.border

    try:
        source = _open_uploaded_image(source_image_bytes).convert("RGB")
    except Exception as err:
        raise ValueError("Invalid image file") from err

    tw, th = width * bs, height * bs
    fitted = _fit_source_for_art(source, (tw, th), prepixelate_max, crop_anchor_x, crop_anchor_y, fit_mode, cover_zoom)

    out = fitted.convert("RGBA")
    overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    dot_rad = max(0.5, bs * micro_dot_radius_frac)
    ink_dr, ink_dg, ink_db = mesh_dark_rgb
    ink_lr, ink_lg, ink_lb = mesh_light_rgb

    for i in range(height):
        for j in range(width):
            if _in_finder_corner(i, j, height, width):
                continue
            
            y0, x0 = (i + bd) * bs, (j + bd) * bs
            cx, cy = x0 + bs / 2.0, y0 + bs / 2.0
            
            # Sample background color for smart contrast
            br, bg, bb = fitted.getpixel((int(cx), int(cy)))
            rgba = _microdot_rgba(bool(matrix[i][j]), br, bg, bb, (ink_dr, ink_dg, ink_db), (ink_lr, ink_lg, ink_lb), micro_smart_contrast)
            draw.ellipse([cx - dot_rad, cy - dot_rad, cx + dot_rad, cy + dot_rad], fill=rgba)

    out = Image.alpha_composite(out, overlay)

    fd = finder_dark_rgb if finder_dark_rgb is not None else mesh_dark_rgb
    fl = finder_light_rgb if finder_light_rgb is not None else mesh_light_rgb
    
    # Draw finders
    draw_finder_pattern(out, bd * bs, bd * bs, bs, finder_shape, fd, fl)
    draw_finder_pattern(out, (width - 7 + bd) * bs, bd * bs, bs, finder_shape, fd, fl)
    draw_finder_pattern(out, bd * bs, (height - 7 + bd) * bs, bs, finder_shape, fd, fl)

    if circular_mask:
        out = _apply_circular_alpha_mask(out)

    return out
