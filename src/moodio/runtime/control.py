from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from moodio.api.schemas import FavoriteRequest
from moodio.domain.models import QueueItem
from moodio.music.soundcloud import SoundCloudProvider, is_individual_track_url

if TYPE_CHECKING:
    from moodio.runtime.service import RuntimeService


TalkDensityInput = Literal["low", "balanced", "high"]


class StationControl:
    def __init__(self, runtime: RuntimeService, *, soundcloud_provider: SoundCloudProvider | None = None) -> None:
        self.runtime = runtime
        self.soundcloud_provider = soundcloud_provider or runtime.soundcloud_provider

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
        await self.runtime.broadcast("agent.tool.call", {
            "tool": "web_search",
            "arguments": {"query": query, "limit": bounded_limit},
        })
        await self.runtime.broadcast("provider.request", {
            "provider": "web_search",
            "action": "search.started",
            "query": query,
            "limit": bounded_limit,
        })
        result = self.runtime.web_search_provider.search(query, limit=bounded_limit).model_dump()
        await self.runtime.broadcast("provider.request", {
            "provider": "web_search",
            "action": "search.completed",
            "query": query,
            "limit": bounded_limit,
            "result_count": len(result.get("results", [])),
        })
        await self.runtime.broadcast("agent.tool.result", {
            "tool": "web_search",
            "result": result,
        })
        return result

    async def get_weather(self, location: str) -> dict:
        return self.runtime.weather_provider.get_weather(location).model_dump()

    async def queue_soundcloud_embed(self, url: str) -> dict:
        provider_track = await self.soundcloud_provider.resolve_embed_url(url)
        return await self.runtime.queue_track(provider_track.to_queue_item())

    async def find_and_play_soundcloud(self, query: str) -> dict:
        search_query = query if "soundcloud" in query.lower() else f"{query} SoundCloud"
        await self.runtime.broadcast("agent.tool.call", {
            "tool": "find_and_play_soundcloud",
            "arguments": {"query": query},
        })
        await self.runtime.broadcast("provider.request", {
            "provider": "soundcloud_discovery",
            "action": "search.started",
            "query": search_query,
            "mode": "play_now",
        })
        search = self.runtime.web_search_provider.search(search_query, limit=5)
        for result in search.results:
            if not _is_soundcloud_playable_candidate(result.url):
                await self.runtime.broadcast("provider.request", {
                    "provider": "soundcloud_discovery",
                    "action": "candidate.skipped",
                    "query": search_query,
                    "url": result.url,
                    "reason": "not_individual_track",
                })
                continue
            try:
                provider_track = await self.soundcloud_provider.resolve_embed_url(result.url)
            except Exception as exc:
                await self.runtime.broadcast("provider.error", {
                    "provider": "soundcloud_discovery",
                    "action": "resolve.failed",
                    "query": search_query,
                    "url": result.url,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                })
                continue
            await self.runtime.queue_track(provider_track.to_queue_item())
            playback = await self.runtime.next_track()
            await self.runtime.broadcast("provider.request", {
                "provider": "soundcloud_discovery",
                "action": "search.completed",
                "query": search_query,
                "chosen_url": result.url,
                "title": provider_track.title,
                "result_count": len(search.results),
            })
            await self.runtime.broadcast("agent.tool.result", {
                "tool": "find_and_play_soundcloud",
                "result": playback,
            })
            return playback
        await self.runtime.broadcast("provider.error", {
            "provider": "soundcloud_discovery",
            "action": "search.failed",
            "query": search_query,
            "error": f"no playable SoundCloud result found for: {query}",
            "error_type": "ValueError",
        })
        raise ValueError(f"no playable SoundCloud result found for: {query}")

    async def find_and_queue_soundcloud_multiple(self, queries: list[str]) -> dict:
        await self.runtime.broadcast("agent.tool.call", {
            "tool": "find_and_queue_soundcloud_multiple",
            "arguments": {"queries": queries},
        })
        queued: list[dict] = []
        failed: list[str] = []

        for query in queries:
            search_query = query if "soundcloud" in query.lower() else f"{query} SoundCloud"
            await self.runtime.broadcast("provider.request", {
                "provider": "soundcloud_discovery",
                "action": "search.started",
                "query": search_query,
                "mode": "queue_multiple",
            })
            search = self.runtime.web_search_provider.search(search_query, limit=5)
            found = False
            for result in search.results:
                if not _is_soundcloud_playable_candidate(result.url):
                    await self.runtime.broadcast("provider.request", {
                        "provider": "soundcloud_discovery",
                        "action": "candidate.skipped",
                        "query": search_query,
                        "url": result.url,
                        "reason": "not_individual_track",
                    })
                    continue
                try:
                    provider_track = await self.soundcloud_provider.resolve_embed_url(result.url)
                except Exception as exc:
                    await self.runtime.broadcast("provider.error", {
                        "provider": "soundcloud_discovery",
                        "action": "resolve.failed",
                        "query": search_query,
                        "url": result.url,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    })
                    continue
                await self.runtime.queue_track(provider_track.to_queue_item())
                queued.append({"query": query, "title": provider_track.title, "track_id": provider_track.playback_ref})
                await self.runtime.broadcast("provider.request", {
                    "provider": "soundcloud_discovery",
                    "action": "search.completed",
                    "query": search_query,
                    "chosen_url": result.url,
                    "title": provider_track.title,
                    "result_count": len(search.results),
                })
                found = True
                break
            if not found:
                failed.append(query)

        result = {"queued": queued, "failed": failed, "total_queued": len(queued)}
        await self.runtime.broadcast("agent.tool.result", {
            "tool": "find_and_queue_soundcloud_multiple",
            "result": result,
        })
        return result

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


def _is_soundcloud_playable_candidate(url: str) -> bool:
    return is_individual_track_url(url)
