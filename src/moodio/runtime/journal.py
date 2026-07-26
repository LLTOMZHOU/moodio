"""Small durable station snapshot and append-only feed."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StationJournal:
    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.snapshot_path = self.directory / "station.json"
        self.feed_path = self.directory / "station-feed.jsonl"
        self.conversation_path = self.directory / "station-conversation.jsonl"

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

    def append(
        self,
        event: str,
        payload: dict[str, Any],
        *,
        at: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "at": at or datetime.now(timezone.utc).isoformat(),
            "event": event,
            "payload": payload,
        }
        if trace_id:
            entry["trace_id"] = trace_id
        if span_id:
            entry["span_id"] = span_id
        with self.feed_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, default=str))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._recent_from(self.feed_path, limit)

    def ensure_conversation_history(self) -> None:
        """Backfill the dedicated Station conversation once from the older feed."""
        if self.conversation_path.exists():
            return

        items: list[dict[str, Any]] = []
        awaiting_reply = False
        for entry in self._all_from(self.feed_path):
            payload = entry.get("payload", {})
            if not isinstance(payload, dict):
                continue
            if entry.get("event") == "agent.turn.started":
                input_text = str(payload.get("input", "")).strip()
                if input_text == "[startup]":
                    awaiting_reply = True
                elif input_text and not input_text.startswith("["):
                    items.append(self._conversation_item("listener", input_text, entry.get("at")))
                    awaiting_reply = True
                else:
                    awaiting_reply = False
            elif entry.get("event") == "agent.turn.completed" and awaiting_reply:
                output = str(payload.get("output", "")).strip()
                if output:
                    items.append(self._conversation_item("moodio", output, entry.get("at")))
                awaiting_reply = False

        self._rewrite_jsonl(self.conversation_path, items)

    def append_conversation(self, role: str, text: str) -> dict[str, Any]:
        item = self._conversation_item(role, text)
        with self.conversation_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, sort_keys=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return item

    def conversation_page(self, *, before: int | None, limit: int) -> dict[str, Any]:
        self.ensure_conversation_history()
        items = self._all_from(self.conversation_path)
        end = len(items) if before is None else min(max(before, 0), len(items))
        start = max(0, end - max(1, limit))
        return {
            "items": items[start:end],
            "next_before": start if start else None,
            "has_more": start > 0,
        }

    def clear_conversation(self) -> None:
        self._rewrite_jsonl(self.conversation_path, [])
        retained_feed = [
            entry
            for entry in self._all_from(self.feed_path)
            if entry.get("event")
            not in {"agent.turn.started", "agent.turn.completed", "agent.turn.failed"}
        ]
        self._rewrite_jsonl(self.feed_path, retained_feed)

    def _recent_from(self, path: Path, limit: int) -> list[dict[str, Any]]:
        return self._all_from(path)[-max(1, limit):]

    def _all_from(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def _conversation_item(self, role: str, text: str, at: object | None = None) -> dict[str, Any]:
        return {
            "id": f"conversation_{uuid.uuid4().hex}",
            "at": str(at) if at else datetime.now(timezone.utc).isoformat(),
            "role": role,
            "text": text,
        }

    def _rewrite_jsonl(self, path: Path, items: list[dict[str, Any]]) -> None:
        temporary_path = path.with_suffix(".tmp")
        with temporary_path.open("w", encoding="utf-8") as handle:
            for item in items:
                handle.write(json.dumps(item, sort_keys=True))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
