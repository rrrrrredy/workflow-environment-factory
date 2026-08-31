from __future__ import annotations

import hashlib
import hmac
import secrets
from base64 import urlsafe_b64encode
from contextlib import suppress
from pathlib import Path
from uuid import UUID


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


def derive_agent_token(session_token: str, run_id: UUID | str) -> str:
    canonical_run_id = str(UUID(str(run_id)))
    digest = hmac.new(
        session_token.encode("utf-8"),
        f"workflow-environment-factory-agent-v1:{canonical_run_id}".encode(),
        hashlib.sha256,
    ).digest()
    return urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def agent_token_matches(session_token: str, run_id: UUID | str, candidate: str | None) -> bool:
    return candidate is not None and hmac.compare_digest(derive_agent_token(session_token, run_id), candidate)
