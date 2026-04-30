from __future__ import annotations

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect

from moodio.api.schemas import CommandRequest, FavoriteRequest, PlaybackEventRequest
from moodio.runtime.service import RuntimeService, build_runtime_from_env


def create_app(runtime: RuntimeService | None = None) -> FastAPI:
    app = FastAPI()
    app.state.runtime = runtime or build_runtime_from_env()

    @app.get("/api/now")
    async def get_now() -> dict:
        runtime: RuntimeService = app.state.runtime
        return runtime.snapshot().model_dump()

    @app.get("/api/transcript/current")
    async def get_current_transcript() -> dict:
        runtime: RuntimeService = app.state.runtime
        return runtime.transcript_snapshot()

    @app.post("/api/command", status_code=202)
    async def post_command(request: CommandRequest) -> dict:
        runtime: RuntimeService = app.state.runtime
        return (await runtime.accept_command(request)).model_dump()

    @app.post("/api/next")
    async def post_next() -> dict:
        runtime: RuntimeService = app.state.runtime
        return await runtime.next_track()

    @app.post("/api/previous")
    async def post_previous() -> dict:
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

    return app
