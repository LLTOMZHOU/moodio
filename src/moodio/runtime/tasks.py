"""Persisted, plain-language station follow-ups."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class StationTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}")
    instruction: str = Field(min_length=1, max_length=1_500)
    next_run_at: datetime
    recurrence_seconds: int | None = Field(default=None, gt=0)
    enabled: bool = True


class StationTaskStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[StationTask]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [StationTask.model_validate(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

    def save(self, tasks: list[StationTask]) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps([task.model_dump(mode="json") for task in tasks], indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def due(self, now: datetime | None = None) -> list[StationTask]:
        now = now or datetime.now(timezone.utc)
        return [task for task in self.list() if task.enabled and task.next_run_at <= now]

    @staticmethod
    def advance(task: StationTask, now: datetime | None = None) -> StationTask:
        now = now or datetime.now(timezone.utc)
        if task.recurrence_seconds is None:
            return task.model_copy(update={"enabled": False})
        next_run = task.next_run_at
        while next_run <= now:
            next_run += timedelta(seconds=task.recurrence_seconds)
        return task.model_copy(update={"next_run_at": next_run})
