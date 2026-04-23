from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from pathlib import Path


@dataclass(slots=True, frozen=True)
class CommandRecord:
    text: str


@dataclass(slots=True, frozen=True)
class PlayRecord:
    track_id: str
    title: str


@dataclass(slots=True, frozen=True)
class TranscriptRecord:
    segment_id: str
    text: str
    start_ms: int
    duration_ms: int


@dataclass(slots=True, frozen=True)
class StateContext:
    commands: list[CommandRecord]
    plays: list[PlayRecord]
    transcript: list[TranscriptRecord]


class StateStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists commands (
                  id integer primary key,
                  text text not null
                );
                create table if not exists plays (
                  id integer primary key,
                  track_id text not null,
                  title text not null
                );
                create table if not exists transcript_segments (
                  id integer primary key,
                  segment_id text not null,
                  text text not null,
                  start_ms integer not null,
                  duration_ms integer not null
                );
                """
            )

    def record_command(self, text: str) -> None:
        with self._connect() as conn:
            conn.execute("insert into commands(text) values (?)", (text,))

    def record_play(self, track_id: str, title: str) -> None:
        with self._connect() as conn:
            conn.execute("insert into plays(track_id, title) values (?, ?)", (track_id, title))

    def record_transcript(self, segment_id: str, text: str, start_ms: int, duration_ms: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "insert into transcript_segments(segment_id, text, start_ms, duration_ms) values (?, ?, ?, ?)",
                (segment_id, text, start_ms, duration_ms),
            )

    def recent_context(self, limit: int) -> StateContext:
        if limit < 0:
            raise ValueError("limit must be non-negative")

        with self._connect() as conn:
            commands = conn.execute("select text from commands order by id desc limit ?", (limit,)).fetchall()
            plays = conn.execute("select track_id, title from plays order by id desc limit ?", (limit,)).fetchall()
            transcript = conn.execute(
                "select segment_id, text, start_ms, duration_ms from transcript_segments order by id desc limit ?",
                (limit,),
            ).fetchall()

        return StateContext(
            commands=[CommandRecord(text=row[0]) for row in commands],
            plays=[PlayRecord(track_id=row[0], title=row[1]) for row in plays],
            transcript=[
                TranscriptRecord(
                    segment_id=row[0],
                    text=row[1],
                    start_ms=row[2],
                    duration_ms=row[3],
                )
                for row in transcript
            ],
        )
