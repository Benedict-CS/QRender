#!/usr/bin/env python3
"""
Standalone micro-dot QR compositor (full photo + tiny B/W dots per module).

Compared to a minimal snippet: this adds the QR **quiet zone** (border modules).
`qrcode.QRCode.modules` does not include border; drawing must offset by `border`
and size the canvas as (modules + 2 * border) * cell_size.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw


def _in_finder_corner(row: int, col: int, n: int) -> bool:
    if row < 7 and col < 7:
        return True
    if row < 7 and col >= n - 7:
        return True
    if row >= n - 7 and col < 7:
        return True
    return False


def generate_microdot_qr(
    url_data: str,
    bg_image_path: str | Path | None,
    output_path: str | Path,
    *,
    version: int | None = None,
    border: int = 4,
    cell_size: int = 20,
    dot_scale: float = 0.3,
    error_correction: int = qrcode.constants.ERROR_CORRECT_H,
) -> None:
    qr = qrcode.QRCode(
        version=version,
        error_correction=error_correction,
        box_size=1,
        border=border,
    )
    qr.add_data(url_data)
    qr.make(fit=True)
    matrix = qr.modules
    n = len(matrix)
    bd = qr.border

    inner_px = n * cell_size
    quiet_px = bd * cell_size
    img_size = inner_px + 2 * quiet_px

    if bg_image_path is not None:
        try:
            bg = Image.open(bg_image_path).convert("RGBA")
            bg = bg.resize((img_size, img_size), Image.Resampling.LANCZOS)
        except OSError as e:
            print(f"Could not load image, using gray background: {e}")
            bg = Image.new("RGBA", (img_size, img_size), (200, 200, 200, 255))
    else:
        bg = Image.new("RGBA", (img_size, img_size), (200, 200, 200, 255))

    draw = ImageDraw.Draw(bg)
    dot_radius = max(0.5, (cell_size * dot_scale) / 2.0)

    for row in range(n):
        for col in range(n):
            x0 = quiet_px + col * cell_size
            y0 = quiet_px + row * cell_size
            x_center = x0 + cell_size / 2.0
            y_center = y0 + cell_size / 2.0

            if _in_finder_corner(row, col, n):
                color = (0, 0, 0, 255) if matrix[row][col] else (255, 255, 255, 255)
                draw.rectangle([x0, y0, x0 + cell_size, y0 + cell_size], fill=color)
            else:
                is_dark = matrix[row][col]
                color = (0, 0, 0, 255) if is_dark else (255, 255, 255, 255)
                draw.ellipse(
                    [
                        x_center - dot_radius,
                        y_center - dot_radius,
                        x_center + dot_radius,
                        y_center + dot_radius,
                    ],
                    fill=color,
                )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    bg.save(output_path)
    print(f"Saved: {output_path} ({img_size}x{img_size}, quiet zone {bd} modules)")


def main() -> None:
    p = argparse.ArgumentParser(description="Micro-dot QR on a background image.")
    p.add_argument("data", help="Payload (e.g. URL)")
    p.add_argument("-i", "--image", help="Background image path")
    p.add_argument("-o", "--output", default="result_qr.png", help="Output PNG path")
    p.add_argument("--cell-size", type=int, default=20, help="Pixels per QR module")
    p.add_argument("--dot-scale", type=float, default=0.3, help="Dot diameter as fraction of cell")
    p.add_argument("--border", type=int, default=4, help="Quiet zone in modules (standard: 4)")
    p.add_argument(
        "--version",
        type=int,
        default=None,
        help="QR version (omit for auto fit)",
    )
    args = p.parse_args()
    generate_microdot_qr(
        args.data,
        args.image,
        args.output,
        version=args.version,
        border=args.border,
        cell_size=args.cell_size,
        dot_scale=args.dot_scale,
    )


if __name__ == "__main__":
    main()
