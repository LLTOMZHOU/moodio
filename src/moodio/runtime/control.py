from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from datetime import datetime, timedelta, timezone
from moodio.api.schemas import FavoriteRequest
from moodio.domain.models import ProgramItem, QueueItem
from moodio.music.soundcloud import SoundCloudProvider, is_individual_track_url
from moodio.music.providers import DiscoveryPreferences
from moodio.runtime.tasks import StationTask

if TYPE_CHECKING:
    from moodio.runtime.service import RuntimeService


TalkDensityInput = Literal["low", "balanced", "high"]


class StationControl:
    def __init__(self, runtime: RuntimeService, *, soundcloud_provider: SoundCloudProvider | None = None) -> None:
        self.runtime = runtime
        self.soundcloud_provider = soundcloud_provider or runtime.soundcloud_provider

    async def get_station_state(self) -> dict:
        return self.runtime.snapshot().model_dump()

    async def get_playback_state(self) -> dict:
        state = self.runtime.station_state
        return {
            "status": state.status,
            "mode": state.mode,
            "now_playing": state.now_playing.model_dump(),
            "queue_depth": len(state.queue),
        }

    async def get_queue(self) -> dict:
        return {
            **self.runtime._queue_payload(),
            "current_item": self.runtime.station_state.now_playing.model_dump(),
            "playback_status": self.runtime.station_state.status,
        }

    async def get_transcript(self) -> dict:
        return self.runtime.transcript_snapshot()

    async def get_recent_context(self, limit: int = 5) -> dict:
        bounded_limit = max(1, min(limit, 20))
        return self.runtime.state_store.recent_context(limit=bounded_limit).model_dump()

    async def read_listener_profile(self) -> dict:
        path = self.runtime.station_dir / "listener-profile.md"
        if path.exists():
            return {"content": path.read_text(encoding="utf-8")}
        preferences = self.runtime.state_store.get_listener_preferences()
        return {"content": preferences.raw_text if preferences else ""}

    async def update_listener_profile(self, content: str, reason: str) -> dict:
        if not content.strip():
            raise ValueError("listener profile cannot be empty")
        self.runtime.import_listener_preferences(content, source="station_profile")
        payload = {"reason": reason, "path": "listener-profile.md"}
        await self.runtime.broadcast("profile.updated", payload)
        return payload

    async def schedule_station_task(self, instruction: str, run_at_or_recurrence: str) -> dict:
        next_run_at, recurrence_seconds = _parse_schedule(run_at_or_recurrence)
        task = StationTask(
            instruction=instruction,
            next_run_at=next_run_at,
            recurrence_seconds=recurrence_seconds,
        )
        tasks = self.runtime.task_store.list()
        tasks.append(task)
        self.runtime.task_store.save(tasks)
        payload = task.model_dump(mode="json")
        await self.runtime.broadcast("task.scheduled", payload)
        return payload

    async def list_station_tasks(self) -> dict:
        return {"tasks": [task.model_dump(mode="json") for task in self.runtime.task_store.list()]}

    async def cancel_station_task(self, task_id: str) -> dict:
        tasks = self.runtime.task_store.list()
        found = False
        updated = []
        for task in tasks:
            if task.task_id == task_id:
                found = True
                updated.append(task.model_copy(update={"enabled": False}))
            else:
                updated.append(task)
        if not found:
            raise ValueError("station task does not exist")
        self.runtime.task_store.save(updated)
        await self.runtime.broadcast("task.cancelled", {"task_id": task_id})
        return {"task_id": task_id, "cancelled": True}

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

    async def search_music(
        self,
        query: str,
        limit: int = 10,
        preferences: dict | None = None,
    ) -> dict:
        bounded_limit = max(1, min(limit, 25))
        parsed_preferences = DiscoveryPreferences.model_validate(preferences or {})
        await self.runtime.broadcast("agent.tool.call", {
            "tool": "search_music",
            "arguments": {"query": query, "limit": bounded_limit, "preferences": parsed_preferences.model_dump(mode="json")},
        })
        tracks = await self.runtime.music_provider.search_tracks(
            query,
            limit=bounded_limit,
            preferences=parsed_preferences,
        )
        self.runtime.remember_candidates(tracks)
        payload = {"query": query, "results": [track.model_dump(mode="json") for track in tracks]}
        await self.runtime.broadcast("agent.tool.result", {"tool": "search_music", "result": payload})
        return payload

    async def inspect_candidates(self, candidate_ids: list[str]) -> dict:
        tracks = [self.runtime._candidates[candidate_id] for candidate_id in candidate_ids if candidate_id in self.runtime._candidates]
        return {"candidates": [track.model_dump(mode="json") for track in tracks]}

    async def queue_music(
        self,
        candidate_id: str,
        reason: str = "Station programming",
        *,
        listener_priority: bool = False,
        expected_revision: int | None = None,
    ) -> dict:
        if expected_revision is not None and expected_revision != self.runtime.station_state.queue_revision:
            return self._stale_queue_result()
        track = await self.runtime.resolve_candidate(candidate_id)
        result = await self.runtime.queue_track(
            track.to_queue_item(),
            listener_priority=listener_priority,
            origin="listener" if listener_priority else "dj",
            reason=reason,
        )
        return {**result, "track": track.model_dump(mode="json"), "reason": reason}

    async def queue_commentary(
        self,
        text: str,
        reason: str,
        *,
        expected_revision: int,
        for_music_item_id: str | None = None,
    ) -> dict:
        if expected_revision != self.runtime.station_state.queue_revision:
            return self._stale_queue_result()
        if for_music_item_id is not None and not any(
            item.program_item_id == for_music_item_id and item.kind == "music"
            for item in self.runtime.station_state.queue
        ):
            raise ValueError("anchored commentary must target an upcoming music item")
        commentary = ProgramItem.commentary(
            text,
            origin="dj",
            reason=reason,
            for_music_item_id=for_music_item_id,
        )
        if for_music_item_id is None:
            # General commentary must lead into some music, never become the tail.
            music_positions = [
                index for index, item in enumerate(self.runtime.station_state.queue) if item.kind == "music"
            ]
            if not music_positions:
                raise ValueError("commentary requires an upcoming music item")
            insert_at = music_positions[-1]
        else:
            insert_at = next(
                index for index, item in enumerate(self.runtime.station_state.queue)
                if item.program_item_id == for_music_item_id
            )
        self.runtime.station_state.queue.insert(insert_at, commentary)
        self.runtime._bump_queue_revision()
        payload = self.runtime._queue_payload()
        await self.runtime.broadcast("queue.updated", payload)
        await self.runtime.broadcast("station.state.updated", self.runtime.station_state.model_dump())
        return {"accepted": True, **payload, "program_item": commentary.model_dump(mode="json")}

    async def remove_from_queue(self, program_item_id: str) -> dict:
        queue = self.runtime.station_state.queue
        target = next((item for item in queue if item.program_item_id == program_item_id), None)
        if target is None:
            raise ValueError("program item is not queued")
        removed_ids = {target.program_item_id}
        if target.kind == "music":
            removed_ids.update(
                item.program_item_id for item in queue if item.for_music_item_id == target.program_item_id
            )
        self.runtime.station_state.queue[:] = [item for item in queue if item.program_item_id not in removed_ids]
        self.runtime._bump_queue_revision()
        payload = self.runtime._queue_payload()
        await self.runtime.broadcast("queue.updated", payload)
        await self.runtime.broadcast("station.state.updated", self.runtime.station_state.model_dump())
        return {"accepted": True, "removed": sorted(removed_ids), **payload}

    def _stale_queue_result(self) -> dict:
        return {
            "accepted": False,
            "error": "stale_queue_revision",
            "revision": self.runtime.station_state.queue_revision,
        }


def _parse_schedule(value: str) -> tuple[datetime, int | None]:
    normalized = value.strip().lower()
    now = datetime.now(timezone.utc)
    if normalized.startswith("every ") and normalized.endswith(" hours"):
        hours = int(normalized.removeprefix("every ").removesuffix(" hours").strip())
        return now + timedelta(hours=hours), hours * 3600
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("schedule must be an ISO timestamp or 'every N hours'") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), None

    async def play_now(self, candidate_id: str, reason: str = "Listener selection") -> dict:
        # Resolve first: an unavailable result must not disturb current playback.
        track = await self.runtime.resolve_candidate(candidate_id)
        await self.runtime.queue_track(track.to_queue_item())
        result = await self.runtime.next_track()
        return {**result, "track": track.model_dump(mode="json"), "reason": reason}

    async def find_and_queue_music_multiple(self, queries: list[str]) -> dict:
        queued: list[dict] = []
        failed: list[str] = []
        for query in queries:
            try:
                search = await self.search_music(query, limit=5)
                candidate = next((item for item in search["results"] if item["kind"] in {"song", "video"}), None)
                if candidate is None:
                    failed.append(query)
                    continue
                result = await self.queue_music(candidate["playback_ref"], reason="Station refill")
                queued.append({"query": query, "title": result["track"]["title"], "track_id": candidate["playback_ref"]})
            except Exception:
                failed.append(query)
        return {"queued": queued, "failed": failed, "total_queued": len(queued)}

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
