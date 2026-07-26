"""Experimental YouTube discovery and just-in-time stream resolution.

The adapter only returns metadata from search and keeps resolver stream URLs in
memory.  It never requests downloads or writes media to disk.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any, Callable

from moodio.domain.models import QueueItem
from moodio.music.providers import DiscoveryPreferences, ProviderTrack


ExtractInfo = Callable[[str, dict[str, Any]], dict[str, Any]]


class YouTubeProvider:
    key = "youtube"

    def __init__(self, *, extract_info: ExtractInfo | None = None, search_pool_size: int = 10) -> None:
        self._extract_info = extract_info or _extract_with_ytdlp
        self._search_pool_size = max(1, search_pool_size)

    async def search_tracks(
        self,
        query: str,
        limit: int = 10,
        *,
        preferences: DiscoveryPreferences | None = None,
    ) -> list[ProviderTrack]:
        normalized = query.strip()
        if not normalized:
            raise ValueError("music query cannot be empty")
        preferences = preferences or DiscoveryPreferences()
        pool_size = max(limit, self._search_pool_size)
        payload = await asyncio.to_thread(
            self._extract_info,
            f"ytsearch{pool_size}:{normalized}",
            _search_options(),
        )
        candidates = [
            _track_from_payload(entry)
            for entry in payload.get("entries", [])
            if isinstance(entry, dict) and entry.get("id")
        ]
        if preferences.max_duration_seconds is not None:
            candidates = [
                track for track in candidates if track.duration_seconds <= preferences.max_duration_seconds
            ]
        candidates.sort(key=lambda track: _rank(track, preferences))
        return candidates[: max(1, min(limit, 25))]

    async def resolve_track(self, provider_track_id: str) -> ProviderTrack:
        video_id = _video_id(provider_track_id)
        payload = await asyncio.to_thread(
            self._extract_info,
            f"https://www.youtube.com/watch?v={video_id}",
            _resolve_options(),
        )
        track = _track_from_payload(payload)
        stream_url = payload.get("url")
        if not isinstance(stream_url, str) or not stream_url:
            raise ValueError("YouTube did not provide a playable audio stream")
        headers = payload.get("http_headers")
        return track.model_copy(
            update={
                "stream_url": stream_url,
                "stream_headers": {str(key): str(value) for key, value in headers.items()} if isinstance(headers, dict) else {},
                "stream_content_type": _stream_content_type(payload),
            }
        )

    async def queue_payload(self, track: ProviderTrack) -> QueueItem:
        return track.to_queue_item()


def _search_options() -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "noplaylist": True,
        "cachedir": False,
    }


def _resolve_options() -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "cachedir": False,
        "format": "bestaudio/best",
    }


def _extract_with_ytdlp(query: str, options: dict[str, Any]) -> dict[str, Any]:
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - exercised by installation, not logic
        raise RuntimeError("YouTube playback requires installing moodio[music]") from exc
    with yt_dlp.YoutubeDL(options) as downloader:
        payload = downloader.extract_info(query, download=False)
    if not isinstance(payload, dict):
        raise ValueError("YouTube returned an invalid response")
    return payload


def _track_from_payload(payload: dict[str, Any]) -> ProviderTrack:
    video_id = _video_id(str(payload["id"]))
    duration = payload.get("duration")
    return ProviderTrack(
        provider="youtube",
        provider_track_id=video_id,
        title=str(payload.get("title") or "Untitled YouTube track"),
        artist=str(payload.get("artist") or payload.get("channel") or payload.get("uploader") or "YouTube"),
        album=str(payload["album"]) if payload.get("album") else None,
        duration_seconds=max(1, int(duration or 1)),
        artwork_url=_thumbnail(payload),
        playback_ref=f"youtube:video:{video_id}",
        external_url=str(payload.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"),
        attribution={"source": "YouTube", "external_url": str(payload.get("webpage_url") or "")},
        kind="song",
        release_date=_parse_date(payload.get("release_date") or payload.get("upload_date")),
    )


def _video_id(value: str) -> str:
    prefix = "youtube:video:"
    return value.removeprefix(prefix).strip()


def _thumbnail(payload: dict[str, Any]) -> str | None:
    direct = payload.get("thumbnail")
    if isinstance(direct, str) and direct:
        return direct
    thumbnails = payload.get("thumbnails")
    if isinstance(thumbnails, list):
        for thumbnail in reversed(thumbnails):
            if isinstance(thumbnail, dict) and isinstance(thumbnail.get("url"), str):
                return thumbnail["url"]
    return None


def _stream_content_type(payload: dict[str, Any]) -> str | None:
    audio_ext = payload.get("audio_ext") or payload.get("ext")
    if audio_ext == "webm":
        return "audio/webm"
    if audio_ext in {"m4a", "mp4"}:
        return "audio/mp4"
    if audio_ext == "opus":
        return "audio/ogg; codecs=opus"
    if audio_ext == "mp3":
        return "audio/mpeg"
    return None


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _rank(track: ProviderTrack, preferences: DiscoveryPreferences) -> tuple[int, int, int, str]:
    long_form_seconds = 0
    if preferences.music_first and track.duration_seconds > 30 * 60:
        long_form_seconds = track.duration_seconds
    date_penalty = 0
    if preferences.prefer_released_after and track.release_date:
        date_penalty = 0 if track.release_date >= preferences.prefer_released_after else 1
    return (1 if long_form_seconds else 0, long_form_seconds, date_penalty, track.title.casefold())
