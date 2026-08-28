from __future__ import annotations

import re
from typing import Any

SECRET_KEY = re.compile(r"authorization|cookie|password|passwd|secret|token|api[_-]?key|private[_-]?key", re.I)
STRUCTURAL_SECRET_KEYS = {"secret_patterns_applied", "secret_refs"}
INLINE_PATTERNS = [
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.I), "[REDACTED:bearer-token]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"), "[REDACTED:api-key]"),
    (re.compile(r"\bgh[opusr]_[A-Za-z0-9]{20,}"), "[REDACTED:github-token]"),
    (
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
        "[REDACTED:private-key]",
    ),
]


def redact(value: Any, key: str | None = None) -> Any:
    if key and key.lower() not in STRUCTURAL_SECRET_KEYS and SECRET_KEY.search(key):
        return "[REDACTED:secret-field]"
    if isinstance(value, str):
        output = value
        for pattern, replacement in INLINE_PATTERNS:
            output = pattern.sub(replacement, output)
        if len(output) > 65_536:
            output = f"{output[:65_536]}\n[TRUNCATED:{len(output) - 65_536} chars]"
        return output
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {child_key: redact(child_value, child_key) for child_key, child_value in value.items()}
    return value
