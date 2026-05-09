"""
Decode generated QR artwork to verify the payload is still scannable.

OpenCV often *detects* micro-dot QRs but returns an empty payload; ZXing-C++ with
multi-scale upsampling matches phone behavior much more closely.

Requires::

    pip install opencv-python-headless zxing-cpp
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import cv2
except ImportError as err:  # pragma: no cover - exercised when dependency missing
    raise ImportError(
        "QR validation needs OpenCV. Install with: pip install opencv-python-headless"
    ) from err

try:
    import zxingcpp
except ImportError:
    zxingcpp = None  # type: ignore[misc, assignment]

import numpy as np
from PIL import Image

# Cap upscaled longest side so validation stays fast on huge exports (e.g. module size 30+).
_MAX_DECODE_DIM = 4096

_SCALE_SEQUENCE = (1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0)


def _normalize_decoded(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace").strip()
    return str(raw).strip()


def _pil_to_bgr(
    pil_image: Image.Image,
    *,
    bg_rgb: tuple[int, int, int] = (255, 255, 255),
) -> np.ndarray:
    """Flatten alpha onto a solid background, then RGB → BGR for OpenCV."""
    img = pil_image
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, bg_rgb)
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    return cv2.cvtColor(np.asarray(img, dtype=np.uint8), cv2.COLOR_RGB2BGR)


def _collect_opencv_decodes(detector: cv2.QRCodeDetector, image: np.ndarray) -> list[str]:
    found: list[str] = []

    data, _, _ = detector.detectAndDecode(image)
    if data:
        found.append(_normalize_decoded(data))

    ok, infos, _, _ = detector.detectAndDecodeMulti(image)
    if ok and infos is not None:
        for item in infos:
            if item:
                found.append(_normalize_decoded(item))

    return found


def _opencv_variants_bgr(bgr: np.ndarray) -> list[str]:
    detector = cv2.QRCodeDetector()
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    h, w = gray.shape[:2]
    blk = max(21, min(151, int(round(min(h, w) / 12)) | 1))
    adapt = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blk, 8
    )

    variants: list[np.ndarray] = [
        bgr,
        gray,
        otsu,
        adapt,
        cv2.bitwise_not(gray),
        cv2.bitwise_not(otsu),
        cv2.bitwise_not(adapt),
    ]
    found: list[str] = []
    for v in variants:
        found.extend(_collect_opencv_decodes(detector, v))
    return found


def _zxing_decode_bgr(bgr: np.ndarray) -> list[str]:
    if zxingcpp is None:
        return []
    try:
        codes = zxingcpp.read_barcodes(
            bgr,
            formats=zxingcpp.BarcodeFormat.QRCode,
        )
    except Exception:  # noqa: BLE001
        return []
    return [_normalize_decoded(t.text) for t in codes if t.text]


def _scale_bgr(bgr: np.ndarray, scale: float) -> np.ndarray:
    if scale == 1.0 or abs(scale - 1.0) < 1e-6:
        return bgr
    h, w = bgr.shape[:2]
    nw = max(16, int(round(w * scale)))
    nh = max(16, int(round(h * scale)))
    return cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_CUBIC)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _scale_candidates(h: int, w: int) -> list[float]:
    """Upsampling helps decoders on micro-dot art (similar to a phone held closer)."""
    out: list[float] = []
    for s in _SCALE_SEQUENCE:
        nh, nw = int(round(h * s)), int(round(w * s))
        if max(nh, nw) < 16:
            continue
        if max(nh, nw) > _MAX_DECODE_DIM:
            continue
        out.append(s)
    return out if out else [1.0]


def _try_decode_bgr_at_scales_fast(bgr: np.ndarray, expected: str) -> bool:
    h, w = bgr.shape[:2]
    for s in _scale_candidates(h, w):
        scaled = _scale_bgr(bgr, s)
        for dec in _opencv_variants_bgr(scaled) + _zxing_decode_bgr(scaled):
            if dec == expected:
                return True
    return False


def _collect_all_decodes_bgr(bgr: np.ndarray) -> list[str]:
    h, w = bgr.shape[:2]
    collected: list[str] = []
    for s in _scale_candidates(h, w):
        scaled = _scale_bgr(bgr, s)
        collected.extend(_opencv_variants_bgr(scaled) + _zxing_decode_bgr(scaled))
    return _dedupe_preserve_order(collected)


def _bgr_backdrops_for_pil(pil: Image.Image) -> list[np.ndarray]:
    """White background matches typical print; black can help some decoders on light halftone."""
    bases = [_pil_to_bgr(pil, bg_rgb=(255, 255, 255))]
    if pil.mode == "RGBA":
        bases.append(_pil_to_bgr(pil, bg_rgb=(0, 0, 0)))
    return bases


def validate_qr_code(
    image_path: str | Path | Image.Image,
    expected_data: str,
    *,
    verbose: bool = True,
) -> bool:
    """
    Try to read a QR code from an image file or a PIL image and check the payload.

    Returns True if any decoded string equals ``expected_data`` (after strip on both).
    """
    expected = expected_data.strip()

    try:
        if isinstance(image_path, Image.Image):
            pil = image_path.copy()
        else:
            pil = Image.open(image_path)
            if not isinstance(image_path, Image.Image):
                pil.load()
    except FileNotFoundError:
        if verbose:
            print("❌ QR validation: image file not found.", file=sys.stderr)
        return False
    except OSError as err:
        if verbose:
            print(f"❌ QR validation: could not read image ({err}).", file=sys.stderr)
        return False

    backdrops = _bgr_backdrops_for_pil(pil)
    for bgr in backdrops:
        if bgr.size == 0:
            continue
        if _try_decode_bgr_at_scales_fast(bgr, expected):
            if verbose:
                print("✅ QR validation: decoded payload matches (scan-safe).")
            return True

    decoded_list: list[str] = []
    for bgr in backdrops:
        if bgr.size == 0:
            continue
        decoded_list.extend(_collect_all_decodes_bgr(bgr))
    decoded_list = _dedupe_preserve_order(decoded_list)

    if verbose:
        if not decoded_list:
            print(
                "❌ QR validation: no QR decoded after multi-scale attempts. "
                "Try a larger dot size, quiet zone, or contrast. "
                "Ensure zxing-cpp is installed (pip install zxing-cpp).",
                file=sys.stderr,
            )
        else:
            preview = decoded_list[0]
            if len(preview) > 80:
                preview = preview[:77] + "…"
            print(
                f"❌ QR validation: payload mismatch (decoded {preview!r}). "
                "Try increasing dot size or contrast.",
                file=sys.stderr,
            )
    return False
