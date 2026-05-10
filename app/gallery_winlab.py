"""
Fetch WinLab gallery (https://gallery.winlab.tw/) and pick a random still image URL.

The site embeds a JSON array of works in the RSC payload; we parse it to honor
media_type and skip videos (only image_path for media_type == image).
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_GALLERY_URL = "https://gallery.winlab.tw/"
DEFAULT_SUPABASE_PREFIX = (
    "https://yissfqcdmzsxwfnzrflz.supabase.co/storage/v1/object/public/gallery/"
)

_IMAGES_KEY = '\\"images\\":'

_cache_urls: list[str] | None = None
_cache_expires: float = 0.0


def _gallery_url() -> str:
    return (os.environ.get("WINLAB_GALLERY_URL") or DEFAULT_GALLERY_URL).strip()


def _public_prefix() -> str:
    return (os.environ.get("WINLAB_SUPABASE_PUBLIC_PREFIX") or DEFAULT_SUPABASE_PREFIX).strip().rstrip(
        "/"
    ) + "/"


def _cache_ttl_seconds() -> int:
    raw = (os.environ.get("WINLAB_GALLERY_CACHE_SECONDS") or "300").strip()
    try:
        return max(30, min(86_400, int(raw)))
    except ValueError:
        return 300


def _fetch_html(url: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "QRender/1.0 (+https://github.com/Benedict-CS/QRender)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _extract_images_array_json(html: str) -> str:
    """Return JSON text of the images array (with normal double quotes)."""
    i = html.find(_IMAGES_KEY)
    if i < 0:
        raise ValueError("gallery page missing embedded images payload (layout may have changed)")
    j = html.find("[", i)
    if j < 0:
        raise ValueError("gallery images array start not found")
    depth = 0
    end: int | None = None
    for k in range(j, len(html)):
        if html[k] == "[":
            depth += 1
        elif html[k] == "]":
            depth -= 1
            if depth == 0:
                end = k
                break
    if end is None:
        raise ValueError("gallery images array end not found")
    blob = html[j : end + 1]
    return blob.replace('\\"', '"')


def _parse_still_image_urls(html: str) -> list[str]:
    jtxt = _extract_images_array_json(html)
    data: list[dict[str, Any]] = json.loads(jtxt)
    prefix = _public_prefix()
    urls: list[str] = []
    for item in data:
        if item.get("media_type") != "image":
            continue
        path = item.get("image_path")
        if not path or not isinstance(path, str):
            continue
        path = path.strip().lstrip("/")
        if path.lower().endswith((".mp4", ".webm", ".mov", ".m4v")):
            continue
        urls.append(prefix + path)
    # stable unique order
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def list_still_image_urls(*, force_refresh: bool = False) -> list[str]:
    """Return direct Supabase public URLs for all non-video works."""
    global _cache_urls, _cache_expires
    now = time.monotonic()
    if not force_refresh and _cache_urls is not None and now < _cache_expires:
        return list(_cache_urls)
    try:
        html = _fetch_html(_gallery_url())
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"gallery HTTP {err.code}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"gallery fetch failed: {err.reason}") from err
    urls = _parse_still_image_urls(html)
    if not urls:
        raise RuntimeError("no still images found on gallery page")
    _cache_urls = urls
    _cache_expires = now + float(_cache_ttl_seconds())
    return list(urls)


def random_still_image_url(*, force_refresh: bool = False) -> str:
    """Pick one random still image URL (new choice on each call)."""
    urls = list_still_image_urls(force_refresh=force_refresh)
    return random.choice(urls)
