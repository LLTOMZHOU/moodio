"""Small durable station snapshot and append-only feed."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StationJournal:
    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.snapshot_path = self.directory / "station.json"
        self.feed_path = self.directory / "station-feed.jsonl"
        self.trace_path = self.directory / "station-trace.jsonl"

    def save_snapshot(self, snapshot: dict[str, Any]) -> None:
        temporary_path = self.snapshot_path.with_suffix(".tmp")
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(self.snapshot_path)

    def load_snapshot(self) -> dict[str, Any] | None:
        if not self.snapshot_path.exists():
            return None
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def append(self, event: str, payload: dict[str, Any]) -> None:
        with self.feed_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "at": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "payload": payload,
            }, sort_keys=True, default=str))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._recent_from(self.feed_path, limit)

    def append_trace(self, envelope: dict[str, Any]) -> None:
        self._append_jsonl(self.trace_path, envelope)

    def recent_trace(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._recent_from(self.trace_path, limit)

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _recent_from(self, path: Path, limit: int) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines()[-max(1, limit):]:
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries
