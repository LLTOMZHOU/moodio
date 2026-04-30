from __future__ import annotations

import json
import re
from html import unescape
from typing import Callable, Protocol
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field


class WebSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    snippet: str = Field(min_length=1)


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    results: list[WebSearchResult]

    def limited(self, limit: int) -> "SearchResult":
        return self.model_copy(update={"results": self.results[: max(0, limit)]})


class WeatherSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    temperature_c: float | None = None


class WebSearchProvider(Protocol):
    def search(self, query: str, limit: int = 5) -> SearchResult:
        """Return web search results suitable for agent context."""
        ...


class WeatherProvider(Protocol):
    def get_weather(self, location: str) -> WeatherSnapshot:
        """Return current weather for a human-readable location."""
        ...


class NoopWebSearchProvider:
    def search(self, query: str, limit: int = 5) -> SearchResult:
        return SearchResult(query=query, results=[])


class DuckDuckGoSearchProvider:
    def __init__(
        self,
        *,
        fetch: Callable[[str], bytes] | None = None,
        base_url: str = "https://api.duckduckgo.com/",
    ) -> None:
        self.fetch = fetch or _fetch_bytes
        self.base_url = base_url

    def search(self, query: str, limit: int = 5) -> SearchResult:
        params = urlencode(
            {
                "q": query,
                "format": "json",
                "no_html": 1,
                "skip_disambig": 1,
            }
        )
        payload = json.loads(self.fetch(f"{self.base_url}?{params}").decode("utf-8"))
        results: list[WebSearchResult] = []
        if isinstance(payload, dict):
            heading = str(payload.get("Heading") or query)
            abstract = payload.get("AbstractText")
            abstract_url = payload.get("AbstractURL")
            if abstract and abstract_url:
                results.append(
                    WebSearchResult(title=heading, url=str(abstract_url), snippet=str(abstract))
                )
            results.extend(_related_topic_results(payload.get("RelatedTopics")))
        if not results:
            results.extend(self._html_results(query))
        return SearchResult(query=query, results=results[: max(0, limit)])

    def _html_results(self, query: str) -> list[WebSearchResult]:
        params = urlencode({"q": query})
        html = self.fetch(f"https://html.duckduckgo.com/html/?{params}").decode("utf-8", "ignore")
        links = re.findall(
            r'class="result__a" href="(?P<href>[^"]+)">(?P<title>.*?)</a>',
            html,
            flags=re.DOTALL,
        )
        snippets = re.findall(
            r'class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
            html,
            flags=re.DOTALL,
        )
        results: list[WebSearchResult] = []
        for index, (href, title) in enumerate(links):
            snippet = snippets[index] if index < len(snippets) else title
            results.append(
                WebSearchResult(
                    title=_clean_html(title),
                    url=_duckduckgo_result_url(href),
                    snippet=_clean_html(snippet),
                )
            )
        return results


class StaticWeatherProvider:
    def __init__(self, *, summary: str = "unavailable", temperature_c: float | None = None) -> None:
        self.summary = summary
        self.temperature_c = temperature_c

    def get_weather(self, location: str) -> WeatherSnapshot:
        return WeatherSnapshot(location=location, summary=self.summary, temperature_c=self.temperature_c)


class FetchWeatherProvider:
    def __init__(
        self,
        *,
        fetch: Callable[[str], bytes] | None = None,
        geocodes: dict[str, tuple[float, float]] | None = None,
        base_url: str = "https://api.open-meteo.com/v1/forecast",
    ) -> None:
        self.fetch = fetch or _fetch_bytes
        self.geocodes = geocodes or {
            "San Francisco": (37.7749, -122.4194),
            "New York": (40.7128, -74.0060),
            "Los Angeles": (34.0522, -118.2437),
        }
        self.base_url = base_url

    def get_weather(self, location: str) -> WeatherSnapshot:
        if location not in self.geocodes:
            raise ValueError(f"unknown weather location: {location}")
        latitude, longitude = self.geocodes[location]
        query = urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,weather_code",
            }
        )
        payload = json.loads(self.fetch(f"{self.base_url}?{query}").decode("utf-8"))
        current = payload.get("current") if isinstance(payload, dict) else None
        if not isinstance(current, dict):
            raise ValueError("weather response did not include current conditions")
        return WeatherSnapshot(
            location=location,
            summary=_weather_summary(int(current.get("weather_code", -1))),
            temperature_c=current.get("temperature_2m"),
        )


def _fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "moodio/0.1"})
    with urlopen(request, timeout=10) as response:
        return response.read()


def _duckduckgo_result_url(href: str) -> str:
    cleaned = unescape(href)
    if cleaned.startswith("//"):
        cleaned = f"https:{cleaned}"
    parsed = urlparse(cleaned)
    uddg = parse_qs(parsed.query).get("uddg")
    if uddg and uddg[0]:
        return unquote(uddg[0])
    return cleaned


def _clean_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(unescape(without_tags).split())


def _related_topic_results(topics: object) -> list[WebSearchResult]:
    if not isinstance(topics, list):
        return []

    results: list[WebSearchResult] = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        nested_topics = topic.get("Topics")
        if isinstance(nested_topics, list):
            results.extend(_related_topic_results(nested_topics))
            continue

        text = topic.get("Text")
        url = topic.get("FirstURL")
        if text and url:
            results.append(WebSearchResult(title=str(text), url=str(url), snippet=str(text)))
    return results


def _weather_summary(code: int) -> str:
    if code == 0:
        return "clear"
    if code in {1, 2, 3}:
        return "partly cloudy"
    if code in {45, 48}:
        return "foggy"
    if 51 <= code <= 67:
        return "drizzle"
    if 71 <= code <= 77:
        return "snow"
    if 80 <= code <= 82:
        return "rain showers"
    if 95 <= code <= 99:
        return "thunderstorm"
    return "unknown"
