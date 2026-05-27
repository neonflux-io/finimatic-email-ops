from __future__ import annotations

import re

from app.core.crypto import fingerprint


def parse_keys(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        parts = raw
    else:
        parts = re.split(r"[\s,;]+", raw)
    seen: set[str] = set()
    parsed: list[str] = []
    for part in parts:
        key = str(part).strip()
        if key and key not in seen:
            seen.add(key)
            parsed.append(key)
    return parsed


def fingerprints(keys: list[str]) -> list[str]:
    return [fingerprint(key) for key in keys]
