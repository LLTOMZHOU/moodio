from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from moodio.domain.models import QueueItem
from moodio.music.providers import ProviderTrack

FetchJson = Callable[..., Awaitable[object]]


async def _default_fetch_json(url: str, *, params: dict[str, object], headers: dict[str, str]) -> object:
    request_url = f"{url}?{urlencode(params)}" if params else url

    def fetch() -> object:
        request = Request(request_url, headers=headers)
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    import asyncio

    return await asyncio.to_thread(fetch)


class SoundCloudProvider:
    def __init__(
        self,
        *,
        client_id: str | None = None,
        oauth_token: str | None = None,
        fetch_json: FetchJson | None = None,
        api_base_url: str = "https://api.soundcloud.com",
        oembed_url: str = "https://soundcloud.com/oembed",
    ) -> None:
        self.client_id = client_id
        self.oauth_token = oauth_token
        self._fetch_json = fetch_json or _default_fetch_json
        self.api_base_url = api_base_url.rstrip("/")
        self.oembed_url = oembed_url

    async def search_tracks(self, query: str, limit: int = 10) -> list[ProviderTrack]:
        params: dict[str, object] = {"q": query, "limit": limit}
        headers, auth_params = self._auth_options()
        params.update(auth_params)

        payload = await self._fetch_json(f"{self.api_base_url}/tracks", params=params, headers=headers)
        return [_track_from_payload(item) for item in _items(payload)]

    async def resolve_track(self, provider_track_id: str) -> ProviderTrack:
        headers, params = self._auth_options()

        payload = await self._fetch_json(
            f"{self.api_base_url}/tracks/{provider_track_id}",
            params=params,
            headers=headers,
        )
        if not isinstance(payload, dict):
            raise ValueError("SoundCloud track response must be an object")
        return _track_from_payload(payload)

    async def resolve_embed_url(self, soundcloud_url: str) -> ProviderTrack:
        payload = await self._fetch_json(
            self.oembed_url,
            params={"format": "json", "url": soundcloud_url},
            headers={},
        )
        if not isinstance(payload, dict):
            raise ValueError("SoundCloud oEmbed response must be an object")
        return _track_from_oembed(soundcloud_url, payload)

    async def queue_payload(self, track: ProviderTrack) -> QueueItem:
        return track.to_queue_item()

    def _auth_options(self) -> tuple[dict[str, str], dict[str, object]]:
        if self.oauth_token:
            return {"Authorization": f"OAuth {self.oauth_token}"}, {}
        if self.client_id:
            return {}, {"client_id": self.client_id}
        raise ValueError("SoundCloud credentials required: set SOUNDCLOUD_CLIENT_ID or SOUNDCLOUD_OAUTH_TOKEN")


def _items(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        collection = payload.get("collection")
        if isinstance(collection, list):
            return [item for item in collection if isinstance(item, dict)]
    return []


def _track_from_payload(payload: dict[str, Any]) -> ProviderTrack:
    track_id = str(payload["id"])
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    artist = str(user.get("username") or "SoundCloud")
    external_url = payload.get("permalink_url")
    duration_ms = int(payload.get("duration") or 1)

    return ProviderTrack(
        provider="soundcloud",
        provider_track_id=track_id,
        title=str(payload.get("title") or "Untitled Track"),
        artist=artist,
        album=None,
        duration_seconds=max(1, round(duration_ms / 1000)),
        artwork_url=payload.get("artwork_url"),
        playback_ref=f"soundcloud:track:{track_id}",
        external_url=external_url,
        stream_url=payload.get("stream_url"),
        attribution={
            "source": "SoundCloud",
            "creator": artist,
            "external_url": str(external_url or user.get("permalink_url") or ""),
        },
    )


def _track_from_oembed(soundcloud_url: str, payload: dict[str, Any]) -> ProviderTrack:
    title = str(payload.get("title") or "SoundCloud Track")
    track_title, artist = _split_title_and_artist(title)

    return ProviderTrack(
        provider="soundcloud",
        provider_track_id=soundcloud_url,
        title=track_title,
        artist=artist,
        album=None,
        duration_seconds=1,
        artwork_url=payload.get("thumbnail_url"),
        playback_ref=f"soundcloud:embed:{soundcloud_url}",
        external_url=soundcloud_url,
        stream_url=None,
        embed_html=payload.get("html"),
        attribution={
            "source": "SoundCloud",
            "creator": artist,
            "external_url": soundcloud_url,
        },
    )


def _split_title_and_artist(title: str) -> tuple[str, str]:
    if " by " in title:
        track_title, artist = title.rsplit(" by ", maxsplit=1)
        return track_title.strip() or title, artist.strip() or "SoundCloud"
    return title, "SoundCloud"
