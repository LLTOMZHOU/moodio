import asyncio
import json
from types import SimpleNamespace

from moodio.api.schemas import CommandRequest, FinalAction
from moodio.domain.events import RuntimeEvent
from moodio.domain.models import QueueItem, STATION_PLACEHOLDER_TRACK_ID, StationState, TranscriptSegment
from moodio.executor import execute_action
from moodio.info import SearchResult, StaticWeatherProvider, WebSearchResult, WeatherSnapshot
from moodio.runtime.service import RuntimeService, build_runtime_from_env
from moodio.state_store import StateStore
from moodio.runtime.control import StationControl
from moodio.station_agent import build_model_config, build_station_agent, load_local_env, run_station_turn
from moodio.voice import SpeechAudio
from tests.fixtures.fake_model import fake_agent_result


def test_station_agent_runs_structured_final_action_through_runner(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def fake_run(agent, input, *, run_config=None):
        seen["agent"] = agent
        seen["input"] = input
        seen["run_config"] = run_config
        return SimpleNamespace(final_output="Staying warm and gentle here.")

    monkeypatch.setattr("moodio.station_agent.Runner.run", fake_run)
    monkeypatch.setattr("moodio.station_agent.build_model_config", lambda: None)

    result = asyncio.run(run_station_turn({"turn_id": "soft-turn-1"}))

    assert result == "Staying warm and gentle here."
    assert json.loads(seen["input"]) == {"turn_id": "soft-turn-1"}
    assert seen["agent"].output_type is str
    assert seen["agent"].tools == []
    assert seen["run_config"] is None


def test_station_agent_returns_plain_text_on_soft_turns(monkeypatch) -> None:
    async def fake_run(agent, input, *, run_config=None):
        return SimpleNamespace(final_output="Queued that up with less talk.")

    monkeypatch.setattr("moodio.station_agent.Runner.run", fake_run)
    monkeypatch.setattr("moodio.station_agent.build_model_config", lambda: None)

    result = asyncio.run(run_station_turn({"turn_id": "soft-turn-2"}))

    assert result == "Queued that up with less talk."


def test_station_agent_delegates_result_parsing(monkeypatch) -> None:
    payload = "A warm turn is ready."
    expected = "parsed: A warm turn is ready."
    seen: dict[str, object] = {}

    async def fake_run(agent, input, *, run_config=None):
        return SimpleNamespace(final_output=payload)

    def fake_parse_agent_result(raw_payload):
        seen["payload"] = raw_payload
        return expected

    monkeypatch.setattr("moodio.station_agent.Runner.run", fake_run)
    monkeypatch.setattr("moodio.station_agent.parse_agent_result", fake_parse_agent_result)
    monkeypatch.setattr("moodio.station_agent.build_model_config", lambda: None)

    result = asyncio.run(run_station_turn({"turn_id": "soft-turn-3"}))

    assert seen["payload"] == payload
    assert result is expected


def test_station_agent_registers_state_control_tools(tmp_path) -> None:
    runtime = RuntimeService(state_store=StateStore(tmp_path / "moodio.db"))
    agent = build_station_agent(StationControl(runtime))

    tool_names = {tool.name for tool in agent.tools}

    assert {
        "get_station_state",
        "get_queue",
        "get_transcript",
        "get_recent_context",
        "web_search",
        "get_weather",
        "queue_soundcloud_embed",
        "next_track",
        "previous_track",
        "play",
        "pause",
        "favorite_track",
        "set_talk_density",
    }.issubset(tool_names)


def test_station_control_updates_shared_runtime_state(tmp_path) -> None:
    runtime = RuntimeService(state_store=StateStore(tmp_path / "moodio.db"))
    control = StationControl(runtime)

    result = asyncio.run(control.set_talk_density("low"))

    assert result["talk_density"] == "low"
    assert runtime.station_state.talk_density == "low"


def test_station_control_reads_web_and_weather_providers(tmp_path) -> None:
    class FakeSearchProvider:
        def search(self, query: str, limit: int = 5) -> SearchResult:
            assert query == "latest indie releases"
            assert limit == 3
            return SearchResult(
                query=query,
                results=[WebSearchResult(title="Release", url="https://example.test", snippet="new music")],
            )

    runtime = RuntimeService(
        state_store=StateStore(tmp_path / "moodio.db"),
        web_search_provider=FakeSearchProvider(),
        weather_provider=StaticWeatherProvider(summary="foggy", temperature_c=12),
    )
    control = StationControl(runtime)

    search_payload = asyncio.run(control.web_search("latest indie releases", limit=3))
    weather_payload = asyncio.run(control.get_weather("San Francisco"))

    assert search_payload["results"][0]["title"] == "Release"
    assert weather_payload == {
        "location": "San Francisco",
        "summary": "foggy",
        "temperature_c": 12,
    }


def test_runtime_service_synthesizes_agent_message_audio(tmp_path) -> None:
    class FakeSynthesizer:
        def synthesize(self, text: str, *, voice: str | None = None) -> SpeechAudio:
            assert text == "Fallback line."
            assert voice == "default_male_1"
            return SpeechAudio(
                url="file:///tmp/fallback.mp3",
                path=tmp_path / "fallback.mp3",
                content_type="audio/mpeg",
                text=text,
                voice=voice or "default_male_1",
            )

    async def fake_run_station_turn(_: dict, control: StationControl) -> str:
        return "Fallback line."

    runtime = RuntimeService(
        state_store=StateStore(tmp_path / "moodio.db"),
        station_turn_runner=fake_run_station_turn,
        speech_synthesizer=FakeSynthesizer(),
    )

    async def run_command_and_collect_events() -> list[dict]:
        subscriber = await runtime.subscribe()
        try:
            await runtime.accept_command(CommandRequest(text="recover"))
            events: list[dict] = []
            while not subscriber.empty():
                events.append(subscriber.get_nowait())
            return events
        finally:
            runtime.unsubscribe(subscriber)

    events = asyncio.run(run_command_and_collect_events())

    assert [event["event"] for event in events] == [
        "tts.segment.started",
        "tts.audio.ready",
        "tts.segment.completed",
        "station.state.updated",
    ]
    assert events[1]["payload"]["url"] == "file:///tmp/fallback.mp3"


def test_runtime_service_transcribes_audio_with_configured_provider(tmp_path) -> None:
    class FakeTranscriber:
        def transcribe(self, audio: bytes, *, filename: str, content_type: str) -> str:
            assert audio == b"audio-bytes"
            assert filename == "command.wav"
            assert content_type == "audio/wav"
            return "play something softer"

    runtime = RuntimeService(
        state_store=StateStore(tmp_path / "moodio.db"),
        speech_transcriber=FakeTranscriber(),
    )

    payload = runtime.transcribe_audio(b"audio-bytes", filename="command.wav", content_type="audio/wav")

    assert payload == {"text": "play something softer"}


def test_build_runtime_from_env_configures_openai_audio_when_key_present(monkeypatch) -> None:
    created: list[str] = []

    class FakeSynthesizer:
        def __init__(self) -> None:
            created.append("synthesizer")

    class FakeTranscriber:
        def __init__(self) -> None:
            created.append("transcriber")

    monkeypatch.setenv("OPENAI_API_KEY", "local-key")
    monkeypatch.setattr("moodio.runtime.service.OpenAISpeechSynthesizer", FakeSynthesizer)
    monkeypatch.setattr("moodio.runtime.service.OpenAITranscriber", FakeTranscriber)

    runtime = build_runtime_from_env()

    assert created == ["synthesizer", "transcriber"]
    assert isinstance(runtime.speech_synthesizer, FakeSynthesizer)
    assert isinstance(runtime.speech_transcriber, FakeTranscriber)


def test_load_local_env_reads_repo_local_env_without_overriding_shell_values(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENROUTER_API_KEY=local-key\n"
        "OPENROUTER_MODEL=openai/gpt-4o-mini\n"
        "OPENAI_API_KEY=local-openai-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "shell-openai-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)

    loaded = load_local_env(env_file)

    assert loaded == {
        "OPENROUTER_API_KEY": "local-key",
        "OPENROUTER_MODEL": "openai/gpt-4o-mini",
    }
    assert "OPENAI_API_KEY" not in loaded


def test_build_model_config_prefers_openrouter_and_chat_completions(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    run_config = build_model_config()

    assert run_config is not None
    assert run_config.model == "openai/gpt-4o-mini"
    assert run_config.model_provider._stored_base_url == "https://openrouter.ai/api/v1"
    assert run_config.model_provider._use_responses is False


def test_station_agent_passes_openrouter_run_config(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def fake_run(agent, input, *, run_config=None):
        seen["run_config"] = run_config
        return SimpleNamespace(final_output="A warmer track is ready.")

    monkeypatch.setattr("moodio.station_agent.Runner.run", fake_run)
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")

    result = asyncio.run(run_station_turn({"turn_id": "soft-turn-openrouter"}))

    assert result == "A warmer track is ready."
    assert seen["run_config"] is not None
    assert seen["run_config"].model == "openai/gpt-4o-mini"


def test_station_agent_times_out_slow_model_calls(monkeypatch) -> None:
    async def slow_run(agent, input, *, run_config=None):
        await asyncio.sleep(0.1)
        return SimpleNamespace(final_output="Slow response")

    monkeypatch.setattr("moodio.station_agent.Runner.run", slow_run)
    monkeypatch.setattr("moodio.station_agent.build_model_config", lambda: None)
    monkeypatch.setenv("MOODIO_AGENT_TIMEOUT_SECONDS", "0.01")

    try:
        asyncio.run(run_station_turn({"turn_id": "slow-turn"}))
    except TimeoutError as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("expected station turn to time out")


def test_execute_action_emits_tts_before_queue_update() -> None:
    action = FinalAction.model_validate(
        {
            "mode": "radio_continue",
            "say": {
                "text": "A softer turn here.",
                "voice": "default_male_1",
                "interruptible": True,
            },
            "queue_tracks": [
                {
                    "track_id": "apple:track:rainy-focus-02",
                    "reason": "keep the station warm",
                    "start_policy": "after_tts",
                }
            ],
            "player_actions": [],
            "talk_density": "balanced",
        }
    )

    events: list[RuntimeEvent] = execute_action(action)

    assert [event["event"] for event in events] == [
        "tts.segment.started",
        "tts.segment.completed",
        "queue.updated",
        "station.state.updated",
    ]

    tts_started, tts_completed, queue_updated, state_updated = events

    started_segment = TranscriptSegment.model_validate(tts_started["payload"])
    completed_segment = TranscriptSegment.model_validate(tts_completed["payload"])
    assert completed_segment.model_dump() == started_segment.model_dump()

    queue_payload = queue_updated["payload"]
    queue = [QueueItem.model_validate(item) for item in queue_payload["queue"]]
    assert [item.track_id for item in queue] == ["apple:track:rainy-focus-02"]

    station_state = StationState.model_validate(state_updated["payload"])
    assert station_state.mode == "radio_continue"
    assert station_state.status == "speaking"
    assert station_state.talk_density == "balanced"
    assert station_state.now_playing.track_id == STATION_PLACEHOLDER_TRACK_ID
    assert station_state.queue[0].track_id == "apple:track:rainy-focus-02"


def test_execute_action_with_no_queue_tracks_keeps_station_queue_empty() -> None:
    action = FinalAction.model_validate(
        {
            "mode": "radio_continue",
            "say": {
                "text": "Staying with the current track.",
                "voice": "default_male_1",
                "interruptible": True,
            },
            "queue_tracks": [],
            "player_actions": [],
            "talk_density": "balanced",
        }
    )

    events: list[RuntimeEvent] = execute_action(action)

    assert [event["event"] for event in events] == [
        "tts.segment.started",
        "tts.segment.completed",
        "station.state.updated",
    ]

    station_state = StationState.model_validate(events[-1]["payload"])
    assert station_state.queue == []
    assert station_state.status == "speaking"


def test_execute_action_maps_unknown_track_id_to_deterministic_queue_payload() -> None:
    action = FinalAction.model_validate(
        {
            "mode": "user_request",
            "say": None,
            "queue_tracks": [
                {
                    "track_id": "apple:track:brand-new-id",
                    "reason": "requested next",
                    "start_policy": "immediate",
                }
            ],
            "player_actions": [],
            "talk_density": None,
        }
    )

    events: list[RuntimeEvent] = execute_action(action)

    assert [event["event"] for event in events] == [
        "queue.updated",
        "station.state.updated",
    ]

    queue_item = QueueItem.model_validate(events[0]["payload"]["queue"][0])
    assert queue_item.model_dump() == {
        "track_id": "apple:track:brand-new-id",
        "title": "Brand New Id",
        "artist": "Moodio Runtime",
        "album": "Pending Queue",
        "duration_seconds": 180,
        "playback_ref": "apple:track:brand-new-id",
        "artwork_url": "https://example.test/artwork/pending-queue.jpg",
    }

    station_state = StationState.model_validate(events[1]["payload"])
    assert station_state.queue[0].model_dump() == queue_item.model_dump()
    assert station_state.talk_density == "balanced"
    assert station_state.status == "playing"


def test_execute_action_handles_tts_failure_with_music_only_fallback() -> None:
    action = FinalAction.model_validate(
        {
            "mode": "recovery",
            "say": {
                "text": "Fallback line.",
                "voice": "default_male_1",
                "interruptible": True,
            },
            "queue_tracks": [
                {
                    "track_id": "apple:track:rainy-focus-02",
                    "reason": "safe fallback",
                    "start_policy": "immediate",
                }
            ],
            "player_actions": [],
            "talk_density": "low",
        }
    )

    events: list[RuntimeEvent] = execute_action(action, tts_should_fail=True)

    assert [event["event"] for event in events] == [
        "queue.updated",
        "station.state.updated",
    ]

    queue_item = QueueItem.model_validate(events[0]["payload"]["queue"][0])
    assert queue_item.track_id == "apple:track:rainy-focus-02"

    station_state = StationState.model_validate(events[1]["payload"])
    assert station_state.mode == "recovery"
    assert station_state.status == "playing"
    assert station_state.talk_density == "low"
    assert station_state.queue[0].track_id == "apple:track:rainy-focus-02"


def test_runtime_service_command_records_plain_text_agent_message(tmp_path) -> None:
    async def fake_run_station_turn(_: dict, control: StationControl) -> str:
        await control.set_talk_density("low")
        return "Fallback line."

    runtime = RuntimeService(
        state_store=StateStore(tmp_path / "moodio.db"),
        station_turn_runner=fake_run_station_turn,
    )

    async def run_command_and_collect_events() -> list[dict]:
        subscriber = await runtime.subscribe()
        try:
            await runtime.accept_command(CommandRequest(text="recover"))
            events: list[dict] = []
            while not subscriber.empty():
                events.append(subscriber.get_nowait())
            return events
        finally:
            runtime.unsubscribe(subscriber)

    events = asyncio.run(run_command_and_collect_events())
    after_transcript = runtime.state_store.recent_context(limit=5).transcript

    assert [event["event"] for event in events] == [
        "station.state.updated",
        "tts.segment.started",
        "tts.segment.completed",
        "station.state.updated",
    ]
    assert runtime.transcript_segments[0].text == "Fallback line."
    assert after_transcript[0].text == "Fallback line."
    assert runtime.station_state.mode == "user_request"
    assert runtime.station_state.status == "speaking"
    assert runtime.station_state.talk_density == "low"
