"""Pure helpers for Langfuse public model API upsert (no DB imports)."""
from __future__ import annotations

from typing import Tuple


def parse_http_error(detail: str) -> Tuple[int, str]:
    if not detail.startswith("HTTP "):
        return 0, detail
    try:
        status_str, _, rest = detail[5:].partition(":")
        return int(status_str.strip()), rest.strip()
    except ValueError:
        return 0, detail


def is_model_name_exists_error(status_code: int, body: str) -> bool:
    if status_code != 400:
        return False
    text = (body or "").lower()
    return "already exists" in text and "model name" in text
