import asyncio

import pytest

from moodio.domain.models import QueueItem
from moodio.music.providers import ProviderTrack
from moodio.music.soundcloud import SoundCloudProvider, is_individual_track_url


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
    assert queue_item.external_url == "https://soundcloud.com/ofmonstersandmen/the-actor"


def test_soundcloud_provider_resolves_embed_url_without_api_credentials() -> None:
    seen: dict[str, object] = {}

    async def fake_fetch_json(url: str, *, params: dict, headers: dict) -> object:
        seen["url"] = url
        seen["params"] = params
        seen["headers"] = headers
        return {
            "provider_name": "SoundCloud",
            "title": "The Actor by Of Monsters and Men",
            "thumbnail_url": "https://i1.sndcdn.com/artworks-actor-large.jpg",
            "html": '<iframe src="https://w.soundcloud.com/player/?url=https%3A//api.soundcloud.com/tracks/123"></iframe>',
        }

    provider = SoundCloudProvider(fetch_json=fake_fetch_json, oembed_url="https://soundcloud.test/oembed")

    track = asyncio.run(provider.resolve_embed_url("https://soundcloud.com/ofmonstersandmen/the-actor"))

    assert seen["url"] == "https://soundcloud.test/oembed"
    assert seen["params"] == {
        "format": "json",
        "url": "https://soundcloud.com/ofmonstersandmen/the-actor",
    }
    assert seen["headers"] == {}
    assert track.provider == "soundcloud"
    assert track.provider_track_id == "https://soundcloud.com/ofmonstersandmen/the-actor"
    assert track.title == "The Actor"
    assert track.artist == "Of Monsters and Men"
    assert track.duration_seconds == 1
    assert track.playback_ref == "soundcloud:embed:https://api.soundcloud.com/tracks/123"
    assert track.embed_html == '<iframe src="https://w.soundcloud.com/player/?url=https%3A//api.soundcloud.com/tracks/123"></iframe>'
    assert track.attribution == {
        "source": "SoundCloud",
        "creator": "Of Monsters and Men",
        "external_url": "https://soundcloud.com/ofmonstersandmen/the-actor",
    }


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://soundcloud.com/ofmonstersandmen/the-actor", True),
        ("https://soundcloud.com/ofmonstersandmen", False),
        ("https://soundcloud.com/ofmonstersandmen/sets/my-playlist", False),
        ("https://soundcloud.com/ofmonstersandmen/albums", False),
        ("https://soundcloud.com/search/sounds?q=shoegaze", False),
        ("https://api.soundcloud.com/tracks/123", False),
    ],
)
def test_soundcloud_track_url_filter_accepts_only_individual_public_tracks(url: str, expected: bool) -> None:
    assert is_individual_track_url(url) is expected


def test_soundcloud_provider_rejects_collection_urls_before_oembed() -> None:
    async def fake_fetch_json(url: str, *, params: dict, headers: dict) -> object:
        raise AssertionError("collection URLs should be rejected before oEmbed")

    provider = SoundCloudProvider(fetch_json=fake_fetch_json)

    with pytest.raises(ValueError, match="individual track"):
        asyncio.run(provider.resolve_embed_url("https://soundcloud.com/ofmonstersandmen/sets/songs"))


def test_soundcloud_provider_rejects_oembed_collection_payloads() -> None:
    async def fake_fetch_json(url: str, *, params: dict, headers: dict) -> object:
        return {
            "provider_name": "SoundCloud",
            "title": "Album by Example Artist",
            "html": '<iframe src="https://w.soundcloud.com/player/?url=https%3A//api.soundcloud.com/playlists/123"></iframe>',
        }

    provider = SoundCloudProvider(fetch_json=fake_fetch_json)

    with pytest.raises(ValueError, match="individual track"):
        asyncio.run(provider.resolve_embed_url("https://soundcloud.com/example-artist/album-song"))


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
