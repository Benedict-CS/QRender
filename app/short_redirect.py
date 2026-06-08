"""Short URLs: /s/{code} redirects to stored target (SQLite). Admin can edit targets and view hits."""

from __future__ import annotations

import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image

_CODE_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
MAX_TARGET_LEN = 2048
_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "short_urls.sqlite3"
_QR_ART_PREVIEW_DIR = Path(__file__).resolve().parent.parent / "data" / "qr_previews"


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(r[1]) for r in rows}


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS short_urls (
                code TEXT PRIMARY KEY,
                target TEXT NOT NULL,
                created REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS short_link_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                ts REAL NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_short_link_events_code_ts ON short_link_events(code, ts DESC)"
        )

        cols = _column_names(conn, "short_urls")
        if "hit_count" not in cols:
            conn.execute("ALTER TABLE short_urls ADD COLUMN hit_count INTEGER NOT NULL DEFAULT 0")
        if "last_hit_at" not in cols:
            conn.execute("ALTER TABLE short_urls ADD COLUMN last_hit_at REAL")
        if "updated_at" not in cols:
            conn.execute("ALTER TABLE short_urls ADD COLUMN updated_at REAL")
        if "managed" not in cols:
            # 1 = shown in admin (legacy rows after migration); new inserts default via app logic
            conn.execute(
                "ALTER TABLE short_urls ADD COLUMN managed INTEGER NOT NULL DEFAULT 1"
            )

        # Allow multiple codes to point to the same URL (admin flexibility); dedupe still happens in code.
        conn.execute("DROP INDEX IF EXISTS idx_short_urls_target")

        conn.commit()


def looks_like_http_url(value: str) -> bool:
    u = value.strip()
    if len(u) > MAX_TARGET_LEN:
        return False
    p = urlparse(u)
    return p.scheme in ("http", "https") and bool(p.netloc)


def normalize_url(value: str) -> str:
    u = value.strip()
    if not u:
        raise ValueError("URL is empty")
    if len(u) > MAX_TARGET_LEN:
        raise ValueError("URL is too long")
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    if not looks_like_http_url(u):
        raise ValueError("URL must be a valid http(s) link")
    return u


def _random_code(length: int = 7) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def get_or_create_code(target: str, *, managed_for_new: bool = False) -> str:
    """Return existing code for target, or insert a new row and return new code."""
    now = time.time()
    managed_val = 1 if managed_for_new else 0
    with _connect() as conn:
        row = conn.execute(
            "SELECT code FROM short_urls WHERE target = ?",
            (target,),
        ).fetchone()
        if row:
            return str(row["code"])
        for _ in range(12):
            code = _random_code()
            try:
                conn.execute(
                    """
                    INSERT INTO short_urls (code, target, created, hit_count, updated_at, managed)
                    VALUES (?, ?, ?, 0, ?, ?)
                    """,
                    (code, target, now, now, managed_val),
                )
                conn.commit()
                return code
            except sqlite3.IntegrityError:
                conn.rollback()
                row2 = conn.execute(
                    "SELECT code FROM short_urls WHERE target = ?",
                    (target,),
                ).fetchone()
                if row2:
                    return str(row2["code"])
                continue
    raise RuntimeError("Could not allocate short code")


def resolve_target(code: str) -> str | None:
    c = (code or "").strip().lower()
    if not c or len(c) > 32 or any(ch not in _CODE_ALPHABET for ch in c):
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT target FROM short_urls WHERE code = ?",
            (c,),
        ).fetchone()
    return str(row["target"]) if row else None


def get_link_managed(code: str) -> bool | None:
    """Return True/False for managed flag, or None if code does not exist."""
    c = (code or "").strip().lower()
    if not c or len(c) > 32 or any(ch not in _CODE_ALPHABET for ch in c):
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT managed FROM short_urls WHERE code = ?",
            (c,),
        ).fetchone()
    if not row:
        return None
    return bool(row["managed"])


def record_hit(code: str) -> None:
    """Increment counters and append one row to the event log (used when redirect succeeds)."""
    c = (code or "").strip().lower()
    if not c:
        return
    ts = time.time()
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE short_urls
            SET hit_count = hit_count + 1, last_hit_at = ?
            WHERE code = ?
            """,
            (ts, c),
        )
        if cur.rowcount > 0:
            conn.execute(
                "INSERT INTO short_link_events (code, ts) VALUES (?, ?)",
                (c, ts),
            )
        conn.commit()


def art_preview_path(code: str) -> Path:
    return _QR_ART_PREVIEW_DIR / f"{(code or '').strip().lower()}.png"


def save_art_preview_png(code: str, image: Image.Image) -> None:
    """Store the last generated art QR (micro-dot + photo) for admin preview."""
    _QR_ART_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    image.save(art_preview_path(code), format="PNG")


def delete_art_preview_png(code: str) -> None:
    path = art_preview_path(code)
    if path.is_file():
        path.unlink()


def set_managed(code: str, value: bool) -> bool:
    """Mark a short link as listed in admin (1) or one-off / hidden from list (0)."""
    c = (code or "").strip().lower()
    now = time.time()
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE short_urls SET managed = ?, updated_at = ?
            WHERE code = ?
            """,
            (1 if value else 0, now, c),
        )
        conn.commit()
        return cur.rowcount > 0


def list_links(limit: int = 500) -> list[dict[str, Any]]:
    """Only links the user chose to manage (managed=1); scans still work for all /s/ codes."""
    limit = max(1, min(5000, limit))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT code, target, created, updated_at, hit_count, last_hit_at, managed
            FROM short_urls
            WHERE managed = 1
            ORDER BY created DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out = [_row_to_link_dict(r) for r in rows]
    for d in out:
        d["has_art_preview"] = art_preview_path(str(d["code"])).is_file()
    return out


def _row_to_link_dict(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    d["hit_count"] = int(d.get("hit_count") or 0)
    return d


def update_link_target(code: str, new_target: str) -> bool:
    """Change destination URL; QR encoding /s/{code} stays the same."""
    c = (code or "").strip().lower()
    target = normalize_url(new_target)
    now = time.time()
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE short_urls SET target = ?, updated_at = ?
            WHERE code = ?
            """,
            (target, now, c),
        )
        conn.commit()
        return cur.rowcount > 0


def delete_link(code: str) -> bool:
    c = (code or "").strip().lower()
    with _connect() as conn:
        conn.execute("DELETE FROM short_link_events WHERE code = ?", (c,))
        cur = conn.execute("DELETE FROM short_urls WHERE code = ?", (c,))
        conn.commit()
        if cur.rowcount > 0:
            delete_art_preview_png(c)
            return True
        return False


def list_events_for_code(code: str, limit: int = 100) -> list[dict[str, Any]]:
    c = (code or "").strip().lower()
    limit = max(1, min(1000, limit))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, code, ts FROM short_link_events
            WHERE code = ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (c, limit),
        ).fetchall()
    return [{"id": r["id"], "code": r["code"], "ts": r["ts"]} for r in rows]


def public_base_for_links() -> str | None:
    """Optional override when behind reverse proxy (e.g. https://qr.example.com)."""
    raw = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    return raw or None


def admin_secret_configured() -> bool:
    return bool((os.environ.get("ADMIN_SECRET") or "").strip())
