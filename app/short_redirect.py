"""Optional short URLs: /s/{code} redirects to stored target (SQLite)."""

from __future__ import annotations

import os
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

_CODE_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
_MAX_TARGET_LEN = 2048
_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "short_urls.sqlite3"


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


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
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_short_urls_target ON short_urls(target)"
        )
        conn.commit()


def looks_like_http_url(value: str) -> bool:
    u = value.strip()
    if len(u) > _MAX_TARGET_LEN:
        return False
    p = urlparse(u)
    return p.scheme in ("http", "https") and bool(p.netloc)


def normalize_url(value: str) -> str:
    u = value.strip()
    if not u:
        raise ValueError("URL is empty")
    if len(u) > _MAX_TARGET_LEN:
        raise ValueError("URL is too long")
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    if not looks_like_http_url(u):
        raise ValueError("URL must be a valid http(s) link")
    return u


def _random_code(length: int = 7) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def get_or_create_code(target: str) -> str:
    """Return existing code for target, or insert a new row and return new code."""
    now = time.time()
    with _connect() as conn:
        row = conn.execute(
            "SELECT code FROM short_urls WHERE target = ?",
            (target,),
        ).fetchone()
        if row:
            return str(row[0])
        for _ in range(12):
            code = _random_code()
            try:
                conn.execute(
                    "INSERT INTO short_urls (code, target, created) VALUES (?, ?, ?)",
                    (code, target, now),
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
                    return str(row2[0])
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
    return str(row[0]) if row else None


def public_base_for_links() -> str | None:
    """Optional override when behind reverse proxy (e.g. https://qr.example.com)."""
    raw = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    return raw or None
