from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from starlette.exceptions import HTTPException

from moodio.api.schemas import (
    CommandRequest,
    CandidateActionRequest,
    CommentaryRequest,
    FavoriteRequest,
    PlaybackEventRequest,
    MusicSearchRequest,
    PreferenceImportRequest,
    QueueSoundCloudEmbedRequest,
)
from moodio.runtime.service import RuntimeService, build_runtime_from_env


_WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@asynccontextmanager
async def _runtime_lifespan(app: FastAPI):
    runtime: RuntimeService = app.state.runtime
    await runtime.start()
    yield
    await runtime.stop()


def create_app(runtime: RuntimeService | None = None) -> FastAPI:
    app = FastAPI(lifespan=_runtime_lifespan)
    app.state.runtime = runtime or build_runtime_from_env()

    @app.get("/")
    async def get_frontend() -> FileResponse:
        return FileResponse(_WEB_DIR / "index.html", media_type="text/html")

    @app.get("/app.js")
    async def get_frontend_script() -> FileResponse:
        return FileResponse(_WEB_DIR / "app.js", media_type="application/javascript")

    @app.get("/styles.css")
    async def get_frontend_styles() -> FileResponse:
        return FileResponse(_WEB_DIR / "styles.css", media_type="text/css")

    @app.get("/dev")
    async def get_dev_console() -> FileResponse:
        return FileResponse(_WEB_DIR / "dev" / "index.html", media_type="text/html")

    @app.get("/api/now")
    async def get_now() -> dict:
        runtime: RuntimeService = app.state.runtime
        return runtime.snapshot().model_dump()

    @app.get("/api/transcript/current")
    async def get_current_transcript() -> dict:
        runtime: RuntimeService = app.state.runtime
        return runtime.transcript_snapshot()

    @app.get("/api/feed")
    async def get_feed(limit: int = 100) -> dict:
        runtime: RuntimeService = app.state.runtime
        return {"items": runtime.journal.recent(min(max(limit, 1), 500))}

    @app.post("/api/command", status_code=202)
    async def post_command(request: CommandRequest) -> dict:
        runtime: RuntimeService = app.state.runtime
        return (await runtime.accept_command(request)).model_dump()

    @app.post("/api/next")
    async def post_next() -> dict:
        runtime: RuntimeService = app.state.runtime
        return await runtime.next_track()

    @app.post("/api/previous")
    async def get_previous() -> dict:
        runtime: RuntimeService = app.state.runtime
        return await runtime.previous_track()

    @app.post("/api/play")
    async def post_play() -> dict:
        runtime: RuntimeService = app.state.runtime
        return (await runtime.play()).model_dump()

    @app.post("/api/pause")
    async def post_pause() -> dict:
        runtime: RuntimeService = app.state.runtime
        return (await runtime.pause()).model_dump()

    @app.post("/api/favorite")
    async def post_favorite(request: FavoriteRequest) -> dict:
        runtime: RuntimeService = app.state.runtime
        return (await runtime.favorite_track(request)).model_dump()

    @app.post("/api/queue/soundcloud-embed")
    async def post_soundcloud_embed(request: QueueSoundCloudEmbedRequest) -> dict:
        runtime: RuntimeService = app.state.runtime
        return await runtime.queue_soundcloud_embed(request.url)

    @app.post("/api/music/search")
    async def post_music_search(request: MusicSearchRequest) -> dict:
        return await runtime_control(runtime).search_music(request.query, request.limit, request.preferences)

    @app.post("/api/music/queue-next")
    async def post_music_queue_next(request: CandidateActionRequest) -> dict:
        return await runtime_control(runtime).queue_music(
            request.candidate_id,
            request.reason,
            listener_priority=True,
            expected_revision=request.expected_revision,
        )

    @app.post("/api/music/play-now")
    async def post_music_play_now(request: CandidateActionRequest) -> dict:
        return await runtime_control(runtime).play_now(request.candidate_id, request.reason)

    @app.post("/api/program/commentary")
    async def post_program_commentary(request: CommentaryRequest) -> dict:
        runtime: RuntimeService = app.state.runtime
        return await runtime_control(runtime).queue_commentary(
            request.text,
            request.reason,
            expected_revision=request.expected_revision,
            for_music_item_id=request.for_music_item_id,
        )

    @app.delete("/api/program/{program_item_id}")
    async def delete_program_item(program_item_id: str) -> dict:
        runtime: RuntimeService = app.state.runtime
        return await runtime_control(runtime).remove_from_queue(program_item_id)

    @app.get("/api/music/stream/{track_ref:path}")
    async def get_music_stream(track_ref: str, request: Request) -> StreamingResponse:
        """Proxy a short-lived provider stream without disclosing its URL to the browser."""
        track = await runtime.resolve_candidate(track_ref)
        if not track.stream_url:
            raise HTTPException(status_code=503, detail="track is not currently streamable")
        upstream_headers = dict(track.stream_headers)
        if request.headers.get("range"):
            upstream_headers["Range"] = request.headers["range"]

        async def stream_body():
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                async with client.stream("GET", track.stream_url, headers=upstream_headers) as upstream:
                    upstream.raise_for_status()
                    async for chunk in upstream.aiter_bytes(64 * 1024):
                        yield chunk

        return StreamingResponse(
            stream_body(),
            media_type="audio/mpeg",
            headers={"Accept-Ranges": "bytes"},
        )

    @app.post("/api/preferences/import")
    async def post_preferences_import(request: PreferenceImportRequest) -> dict:
        runtime: RuntimeService = app.state.runtime
        preferences = runtime.import_listener_preferences(request.profile_text, source=request.source)
        return {
            "source": preferences.source,
            "raw_text": preferences.raw_text,
            "seed_queries": preferences.seed_queries,
        }

    @app.post("/api/events/playback", status_code=202)
    async def post_playback_event(request: PlaybackEventRequest) -> dict:
        runtime: RuntimeService = app.state.runtime
        return (await runtime.ingest_playback_event(request)).model_dump()

    @app.post("/api/transcribe")
    async def post_transcribe(request: Request, filename: str = "audio.webm") -> dict:
        runtime: RuntimeService = app.state.runtime
        return runtime.transcribe_audio(
            await request.body(),
            filename=filename,
            content_type=request.headers.get("content-type", "application/octet-stream"),
        )

    @app.get("/api/tts/{filename}")
    async def get_tts_audio(filename: str) -> FileResponse:
        runtime: RuntimeService = app.state.runtime
        audio_path = (runtime.tts_cache_dir / filename).resolve()
        cache_dir = runtime.tts_cache_dir.resolve()
        if cache_dir not in audio_path.parents or not audio_path.exists():
            raise HTTPException(status_code=404)
        return FileResponse(audio_path, media_type=_audio_media_type(audio_path))

    @app.websocket("/api/stream")
    async def stream_events(websocket: WebSocket) -> None:
        runtime: RuntimeService = app.state.runtime
        await websocket.accept()
        queue = await runtime.subscribe()
        await websocket.send_json({"event": "station.state.updated", "payload": runtime.snapshot().model_dump()})

        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            runtime.unsubscribe(queue)

    @app.get("/api/events")
    async def stream_events(request: Request) -> StreamingResponse:
        runtime: RuntimeService = app.state.runtime
        queue = await runtime.subscribe()

        async def event_body():
            try:
                initial = {"event": "station.state.updated", "payload": runtime.snapshot().model_dump()}
                yield f"event: {initial['event']}\ndata: {json.dumps(initial)}\n\n"
                while not await request.is_disconnected():
                    try:
                        message = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"event: {message['event']}\ndata: {json.dumps(message)}\n\n"
            finally:
                runtime.unsubscribe(queue)

        return StreamingResponse(event_body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    return app


def runtime_control(runtime: RuntimeService):
    from moodio.runtime.control import StationControl

    return StationControl(runtime)


def _audio_media_type(path: Path) -> str:
    if path.suffix == ".mp3":
        return "audio/mpeg"
    if path.suffix == ".wav":
        return "audio/wav"
    if path.suffix == ".opus":
        return "audio/opus"
    return "application/octet-stream"
