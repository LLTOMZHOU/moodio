from __future__ import annotations

from typing import Any, TypedDict


class RuntimeEvent(TypedDict):
    event: str
    payload: dict[str, Any]
