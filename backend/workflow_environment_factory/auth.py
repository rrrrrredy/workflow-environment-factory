from __future__ import annotations

import hmac
import secrets
from contextlib import suppress
from pathlib import Path


def load_or_create_token(path: Path) -> str:
    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if len(existing) >= 32:
            return existing
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{token}\n", encoding="utf-8")
    with suppress(OSError):
        path.chmod(0o600)
    return token


def token_matches(expected: str, candidate: str | None) -> bool:
    return candidate is not None and hmac.compare_digest(expected, candidate)
