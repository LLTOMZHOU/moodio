from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from agents.items import TResponseInputItem
from agents.memory import SessionABC, SessionSettings


class InMemoryListSession(SessionABC):
    """In-memory session that stores conversation history as a list of input items.

    Suitable for tests and short-lived runs. For persistence across restarts,
    use SqliteSession instead.
    """

    def __init__(self, *, session_id: str | None = None) -> None:
        self._session_id = session_id or f"moodio-{uuid.uuid4().hex[:12]}"
        self._items: list[TResponseInputItem] = []
        self.session_settings: SessionSettings | None = None

    @property
    def session_id(self) -> str:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str) -> None:
        self._session_id = value

    async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]:
        if limit is None:
            return list(self._items)
        return list(self._items[-limit:])

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        self._items.extend(items)

    async def pop_item(self) -> TResponseInputItem | None:
        if not self._items:
            return None
        return self._items.pop()

    async def clear_session(self) -> None:
        self._items.clear()


class SqliteSession(SessionABC):
    """SQLite-backed session that persists conversation history to disk.

    Items are stored as JSON rows. An in-memory cache avoids repeated reads
    within the same process. On first access the cache is populated from the
    database, so conversation history survives process restarts.
    """

    def __init__(self, db_path: Path | str, *, session_id: str | None = None) -> None:
        self._session_id = session_id or f"moodio-{uuid.uuid4().hex[:12]}"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: list[TResponseInputItem] | None = None
        self.session_settings: SessionSettings | None = None
        self._init_db()

    @property
    def session_id(self) -> str:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str) -> None:
        self._session_id = value

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists session_items (
                  id integer primary key autoincrement,
                  session_id text not null,
                  item_json text not null
                );
                create index if not exists idx_session_items_session
                  on session_items(session_id, id);
                """
            )

    def _load_items(self) -> list[TResponseInputItem]:
        with self._connect() as conn:
            rows = conn.execute(
                "select item_json from session_items where session_id = ? order by id",
                (self._session_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def _ensure_cache(self) -> list[TResponseInputItem]:
        if self._cache is None:
            self._cache = self._load_items()
        return self._cache

    async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]:
        items = self._ensure_cache()
        if limit is None:
            return list(items)
        return list(items[-limit:])

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        cache = self._ensure_cache()
        with self._connect() as conn:
            for item in items:
                conn.execute(
                    "insert into session_items(session_id, item_json) values (?, ?)",
                    (self._session_id, json.dumps(item, sort_keys=True)),
                )
        cache.extend(items)

    async def pop_item(self) -> TResponseInputItem | None:
        cache = self._ensure_cache()
        if not cache:
            return None
        item = cache.pop()
        with self._connect() as conn:
            conn.execute(
                "delete from session_items where id = ("
                "  select id from session_items where session_id = ? order by id desc limit 1"
                ")",
                (self._session_id,),
            )
        return item

    async def clear_session(self) -> None:
        self._cache = [] if self._cache is not None else None
        with self._connect() as conn:
            conn.execute(
                "delete from session_items where session_id = ?",
                (self._session_id,),
            )
