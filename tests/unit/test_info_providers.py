from __future__ import annotations

import json

from moodio.info import DuckDuckGoSearchProvider, FetchWeatherProvider, SearchResult, StaticWeatherProvider, WebSearchResult


def test_web_search_result_serializes_for_agent_tools() -> None:
    result = WebSearchResult(title="Docs", url="https://example.test", snippet="A useful result.")

    assert result.model_dump() == {
        "title": "Docs",
        "url": "https://example.test",
        "snippet": "A useful result.",
    }


def test_search_result_limits_items_for_agent_context() -> None:
    result = SearchResult(
        query="moodio",
        results=[
            WebSearchResult(title=str(index), url=f"https://example.test/{index}", snippet="x")
            for index in range(5)
        ],
    )

    assert [item.title for item in result.limited(2).results] == ["0", "1"]


def test_duckduckgo_search_provider_maps_instant_answer_payload() -> None:
    def fake_fetch(url: str) -> bytes:
        assert "api.duckduckgo.com" in url
        assert "q=of+monsters" in url
        return json.dumps(
            {
                "AbstractText": "Band from Iceland.",
                "AbstractURL": "https://example.test/band",
                "Heading": "Of Monsters and Men",
                "RelatedTopics": [
                    {
                        "Text": "The Actor - song",
                        "FirstURL": "https://example.test/song",
                    }
                ],
            }
        ).encode()

    provider = DuckDuckGoSearchProvider(fetch=fake_fetch)

    result = provider.search("of monsters", limit=2)

    assert result.query == "of monsters"
    assert [item.title for item in result.results] == ["Of Monsters and Men", "The Actor - song"]


def test_duckduckgo_search_provider_falls_back_to_html_results() -> None:
    calls: list[str] = []

    def fake_fetch(url: str) -> bytes:
        calls.append(url)
        if "api.duckduckgo.com" in url:
            return json.dumps({}).encode()
        return b'''
            <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fsoundcloud.com%2Fofmonstersandmen">Stream Of Monsters and Men music - SoundCloud</a>
            <a class="result__snippet">Listen to tracks and playlists.</a>
        '''

    provider = DuckDuckGoSearchProvider(fetch=fake_fetch)

    result = provider.search("of monsters", limit=1)

    assert len(calls) == 2
    assert result.results[0].model_dump() == {
        "title": "Stream Of Monsters and Men music - SoundCloud",
        "url": "https://soundcloud.com/ofmonstersandmen",
        "snippet": "Listen to tracks and playlists.",
    }


def test_static_weather_provider_returns_location_snapshot() -> None:
    provider = StaticWeatherProvider(summary="cool and clear", temperature_c=15)

    assert provider.get_weather("San Francisco").model_dump() == {
        "location": "San Francisco",
        "summary": "cool and clear",
        "temperature_c": 15,
    }


def test_fetch_weather_provider_maps_open_meteo_style_payload() -> None:
    def fake_fetch(url: str) -> bytes:
        assert "latitude=37.7749" in url
        assert "longitude=-122.4194" in url
        return json.dumps({"current": {"temperature_2m": 14.2, "weather_code": 0}}).encode()

    provider = FetchWeatherProvider(
        fetch=fake_fetch,
        geocodes={"San Francisco": (37.7749, -122.4194)},
    )

    snapshot = provider.get_weather("San Francisco")

    assert snapshot.location == "San Francisco"
    assert snapshot.summary == "clear"
    assert snapshot.temperature_c == 14.2
