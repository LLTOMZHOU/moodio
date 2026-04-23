from __future__ import annotations

from typing import TypedDict


class RuntimeEvent(TypedDict):
    event: str
    payload: dict
