from __future__ import annotations

import asyncio
from pathlib import Path

from moodio.runtime.session import InMemoryListSession, SqliteSession


def test_in_memory_session_stores_and_retrieves_items() -> None:
    session = InMemoryListSession()

    asyncio.run(session.add_items([{"role": "user", "content": "hello"}]))
    items = asyncio.run(session.get_items())

    assert len(items) == 1
    assert items[0]["content"] == "hello"


def test_in_memory_session_respects_limit() -> None:
    session = InMemoryListSession()

    asyncio.run(session.add_items([
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second"},
        {"role": "user", "content": "third"},
    ]))
    items = asyncio.run(session.get_items(limit=2))

    assert [item["content"] for item in items] == ["second", "third"]


def test_in_memory_session_pop_removes_last_item() -> None:
    session = InMemoryListSession()

    asyncio.run(session.add_items([
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second"},
    ]))
    popped = asyncio.run(session.pop_item())

    assert popped["content"] == "second"
    assert len(asyncio.run(session.get_items())) == 1


def test_in_memory_session_clear_empties_all_items() -> None:
    session = InMemoryListSession()

    asyncio.run(session.add_items([{"role": "user", "content": "hello"}]))
    asyncio.run(session.clear_session())

    assert asyncio.run(session.get_items()) == []


def test_sqlite_session_persists_items_across_restarts(tmp_path: Path) -> None:
    db_path = tmp_path / "session.db"

    first_session = SqliteSession(db_path)
    asyncio.run(first_session.add_items([
        {"role": "user", "content": "play something warmer"},
        {"role": "assistant", "content": "Warming things up."},
    ]))

    # Simulate process restart by creating a new session pointing at the same db
    second_session = SqliteSession(db_path, session_id=first_session.session_id)
    items = asyncio.run(second_session.get_items())

    assert len(items) == 2
    assert items[0]["content"] == "play something warmer"
    assert items[1]["content"] == "Warming things up."


def test_sqlite_session_respects_limit(tmp_path: Path) -> None:
    session = SqliteSession(tmp_path / "session.db")

    asyncio.run(session.add_items([
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second"},
        {"role": "user", "content": "third"},
    ]))
    items = asyncio.run(session.get_items(limit=2))

    assert [item["content"] for item in items] == ["second", "third"]


def test_sqlite_session_pop_removes_last_item(tmp_path: Path) -> None:
    session = SqliteSession(tmp_path / "session.db")

    asyncio.run(session.add_items([
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second"},
    ]))
    popped = asyncio.run(session.pop_item())

    assert popped["content"] == "second"
    assert len(asyncio.run(session.get_items())) == 1


def test_sqlite_session_clear_empties_all_items(tmp_path: Path) -> None:
    session = SqliteSession(tmp_path / "session.db")

    asyncio.run(session.add_items([{"role": "user", "content": "hello"}]))
    asyncio.run(session.clear_session())

    assert asyncio.run(session.get_items()) == []


def test_sqlite_session_isolates_different_session_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "session.db"

    session_a = SqliteSession(db_path, session_id="session-a")
    session_b = SqliteSession(db_path, session_id="session-b")

    asyncio.run(session_a.add_items([{"role": "user", "content": "hello A"}]))
    asyncio.run(session_b.add_items([{"role": "user", "content": "hello B"}]))

    items_a = asyncio.run(session_a.get_items())
    items_b = asyncio.run(session_b.get_items())

    assert len(items_a) == 1
    assert items_a[0]["content"] == "hello A"
    assert len(items_b) == 1
    assert items_b[0]["content"] == "hello B"


def test_sqlite_session_add_items_after_restart_preserves_existing(tmp_path: Path) -> None:
    db_path = tmp_path / "session.db"

    first = SqliteSession(db_path)
    asyncio.run(first.add_items([{"role": "user", "content": "first turn"}]))

    second = SqliteSession(db_path, session_id=first.session_id)
    asyncio.run(second.add_items([{"role": "user", "content": "second turn"}]))

    items = asyncio.run(second.get_items())
    assert len(items) == 2
    assert items[0]["content"] == "first turn"
    assert items[1]["content"] == "second turn"
