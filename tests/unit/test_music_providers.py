import asyncio

import pytest

from moodio.domain.models import QueueItem
from moodio.music.providers import ProviderTrack
from moodio.music.soundcloud import SoundCloudProvider


def test_provider_track_converts_to_stable_queue_item() -> None:
    track = ProviderTrack(
        provider="soundcloud",
        provider_track_id="123",
        title="The Actor",
        artist="Of Monsters and Men",
        album=None,
        duration_seconds=211,
        artwork_url="https://i1.sndcdn.com/artworks-actor.jpg",
        playback_ref="soundcloud:track:123",
        external_url="https://soundcloud.com/ofmonstersandmen/the-actor",
        stream_url=None,
        attribution={
            "source": "SoundCloud",
            "creator": "Of Monsters and Men",
            "external_url": "https://soundcloud.com/ofmonstersandmen/the-actor",
        },
    )

    queue_item = QueueItem.model_validate(track.to_queue_item().model_dump())

    assert queue_item.track_id == "soundcloud:track:123"
    assert queue_item.title == "The Actor"
    assert queue_item.artist == "Of Monsters and Men"
    assert queue_item.album == "SoundCloud"
    assert queue_item.playback_ref == "soundcloud:track:123"


def test_soundcloud_provider_maps_search_results_to_provider_tracks() -> None:
    seen: dict[str, object] = {}

    async def fake_fetch_json(url: str, *, params: dict, headers: dict) -> object:
        seen["url"] = url
        seen["params"] = params
        seen["headers"] = headers
        return {
            "collection": [
                {
                    "id": 123,
                    "title": "The Actor",
                    "duration": 211_000,
                    "artwork_url": "https://i1.sndcdn.com/artworks-actor-large.jpg",
                    "permalink_url": "https://soundcloud.com/ofmonstersandmen/the-actor",
                    "stream_url": "https://api.soundcloud.com/tracks/123/stream",
                    "user": {
                        "username": "Of Monsters and Men",
                        "permalink_url": "https://soundcloud.com/ofmonstersandmen",
                    },
                }
            ]
        }

    provider = SoundCloudProvider(
        client_id="client-123",
        fetch_json=fake_fetch_json,
        api_base_url="https://api.soundcloud.test",
    )

    tracks = asyncio.run(provider.search_tracks("of monsters and men", limit=3))

    assert seen["url"] == "https://api.soundcloud.test/tracks"
    assert seen["params"] == {"q": "of monsters and men", "limit": 3, "client_id": "client-123"}
    assert tracks[0].provider == "soundcloud"
    assert tracks[0].provider_track_id == "123"
    assert tracks[0].title == "The Actor"
    assert tracks[0].artist == "Of Monsters and Men"
    assert tracks[0].duration_seconds == 211
    assert tracks[0].playback_ref == "soundcloud:track:123"
    assert tracks[0].attribution == {
        "source": "SoundCloud",
        "creator": "Of Monsters and Men",
        "external_url": "https://soundcloud.com/ofmonstersandmen/the-actor",
    }


def test_soundcloud_provider_uses_bearer_token_without_client_id_param() -> None:
    seen: dict[str, object] = {}

    async def fake_fetch_json(url: str, *, params: dict, headers: dict) -> object:
        seen["params"] = params
        seen["headers"] = headers
        return []

    provider = SoundCloudProvider(
        oauth_token="token-123",
        fetch_json=fake_fetch_json,
        api_base_url="https://api.soundcloud.test",
    )

    asyncio.run(provider.search_tracks("little talks"))

    assert seen["params"] == {"q": "little talks", "limit": 10}
    assert seen["headers"] == {"Authorization": "OAuth token-123"}


def test_soundcloud_provider_requires_credentials_before_searching() -> None:
    async def fake_fetch_json(url: str, *, params: dict, headers: dict) -> object:
        raise AssertionError("fetch should not be called without credentials")

    provider = SoundCloudProvider(fetch_json=fake_fetch_json)

    with pytest.raises(ValueError, match="SOUNDCLOUD_CLIENT_ID"):
        asyncio.run(provider.search_tracks("of monsters and men"))
