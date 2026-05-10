#!/usr/bin/env python3
"""Ensure .env exists with ADMIN_SECRET and sane PUBLIC_BASE_URL for local dev. Never prints secrets."""

from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    env_path = root / ".env"
    example_path = root / ".env.example"
    if not example_path.is_file():
        print("Missing .env.example", file=sys.stderr)
        return 1

    if not env_path.exists():
        env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")

    text = env_path.read_text(encoding="utf-8")
    changed = False

    if not re.search(r"^ADMIN_SECRET=", text, flags=re.MULTILINE):
        tok = secrets.token_urlsafe(32)
        text = text.rstrip() + "\nADMIN_SECRET=" + tok + "\n"
        changed = True
    elif re.search(r"^ADMIN_SECRET=\s*$", text, flags=re.MULTILINE):
        tok = secrets.token_urlsafe(32)
        text = re.sub(
            r"^ADMIN_SECRET=\s*$",
            "ADMIN_SECRET=" + tok,
            text,
            count=1,
            flags=re.MULTILINE,
        )
        changed = True

    placeholder = "PUBLIC_BASE_URL=https://your-domain.example"
    if placeholder in text:
        text = text.replace(
            placeholder,
            "PUBLIC_BASE_URL=http://127.0.0.1:8000",
            1,
        )
        changed = True

    if changed:
        env_path.write_text(text, encoding="utf-8")

    print("setup_env: ok" + (" (updated)" if changed else " (no changes needed)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
