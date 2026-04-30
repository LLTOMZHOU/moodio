from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from moodio.api.schemas import FavoriteRequest
from moodio.domain.models import QueueItem
from moodio.music.soundcloud import SoundCloudProvider

if TYPE_CHECKING:
    from moodio.runtime.service import RuntimeService


TalkDensityInput = Literal["low", "balanced", "high"]


class StationControl:
    def __init__(self, runtime: RuntimeService, *, soundcloud_provider: SoundCloudProvider | None = None) -> None:
        self.runtime = runtime
        self.soundcloud_provider = soundcloud_provider or SoundCloudProvider()

    async def get_station_state(self) -> dict:
        return self.runtime.snapshot().model_dump()

    async def get_queue(self) -> dict:
        return {"queue": [track.model_dump() for track in self.runtime.station_state.queue]}

    async def get_transcript(self) -> dict:
        return self.runtime.transcript_snapshot()

    async def get_recent_context(self, limit: int = 5) -> dict:
        bounded_limit = max(1, min(limit, 20))
        return self.runtime.state_store.recent_context(limit=bounded_limit).model_dump()

    async def web_search(self, query: str, limit: int = 5) -> dict:
        bounded_limit = max(1, min(limit, 10))
        return self.runtime.web_search_provider.search(query, limit=bounded_limit).model_dump()

    async def get_weather(self, location: str) -> dict:
        return self.runtime.weather_provider.get_weather(location).model_dump()

    async def queue_soundcloud_embed(self, url: str) -> dict:
        provider_track = await self.soundcloud_provider.resolve_embed_url(url)
        return await self.runtime.queue_track(provider_track.to_queue_item())

    async def queue_track(self, track: QueueItem) -> dict:
        return await self.runtime.queue_track(track)

    async def next_track(self) -> dict:
        return await self.runtime.next_track()

    async def previous_track(self) -> dict:
        return await self.runtime.previous_track()

    async def play(self) -> dict:
        return (await self.runtime.play()).model_dump()

    async def pause(self) -> dict:
        return (await self.runtime.pause()).model_dump()

    async def favorite_track(self, track_id: str) -> dict:
        return (await self.runtime.favorite_track(FavoriteRequest(track_id=track_id))).model_dump()

    async def set_talk_density(self, level: TalkDensityInput) -> dict:
        self.runtime.station_state = self.runtime.station_state.model_copy(update={"talk_density": level})
        payload = self.runtime.station_state.model_dump()
        await self.runtime.broadcast("station.state.updated", payload)
        return {"talk_density": level}
