from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class ContentStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, value: bytes) -> str:
        digest = hashlib.sha256(value).hexdigest()
        reference = f"sha256:{digest}"
        path = self.root / digest[:2] / digest[2:]
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temporary = path.with_suffix(f".{id(value)}.tmp")
            temporary.write_bytes(value)
            temporary.replace(path)
        return reference

    def put_text(self, value: str) -> str:
        return self.put_bytes(value.encode("utf-8"))

    def put_json(self, value: Any) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return self.put_bytes(encoded)

    def read(self, reference: str) -> bytes:
        if not reference.startswith("sha256:") or len(reference) != 71:
            raise ValueError("content reference must be sha256:<64 lowercase hex characters>")
        digest = reference.removeprefix("sha256:")
        if any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("content reference contains invalid characters")
        return (self.root / digest[:2] / digest[2:]).read_bytes()
