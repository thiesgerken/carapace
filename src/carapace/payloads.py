from __future__ import annotations

from typing import Any


def dict_or_empty(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def dict_of_dicts(value: object) -> dict[str, dict[str, Any]]:
    raw = dict_or_empty(value)
    return {str(key): item for key, item in raw.items() if isinstance(item, dict)}


def list_of_dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def string_dict(value: object) -> dict[str, str]:
    raw = dict_or_empty(value)
    return {str(key): item for key, item in raw.items() if isinstance(item, str)}
