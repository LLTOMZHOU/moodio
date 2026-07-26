from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import plistlib
from typing import Any


_MAX_SEED_QUERIES = 12


@dataclass(frozen=True, slots=True)
class AppleMusicTasteImport:
    track_count: int
    playlist_count: int
    top_artists: list[str]
    top_genres: list[str]
    seed_queries: list[str]
    profile_text: str


@dataclass(frozen=True, slots=True)
class _TrackSignal:
    title: str
    artist: str
    album: str
    genre: str | None
    play_count: int
    rating: int
    loved: bool
    playlist_appearances: int

    @property
    def query(self) -> str:
        return f"{self.artist} - {self.title}"

    @property
    def rank(self) -> tuple[int, int, int, int, str, str]:
        return (
            -int(self.loved),
            -self.rating,
            -self.play_count,
            -self.playlist_appearances,
            self.artist.casefold(),
            self.title.casefold(),
        )


def import_apple_music_xml(content: bytes) -> AppleMusicTasteImport:
    """Turn a Music.app XML export into small, explainable taste evidence.

    The caller owns the source bytes. This function retains no file, artwork, or
    audio reference; its output is only derived metadata suitable for Moodio's
    editable Listener profile and normal provider discovery.
    """
    try:
        document = plistlib.loads(content)
    except (plistlib.InvalidFileException, ValueError, TypeError) as exc:
        raise ValueError("This is not a readable Apple Music XML export.") from exc
    if not isinstance(document, dict):
        raise ValueError("Apple Music export must contain a property-list dictionary.")

    raw_tracks = document.get("Tracks")
    if not isinstance(raw_tracks, dict):
        raise ValueError("Apple Music export did not contain track metadata.")

    playlists = [item for item in document.get("Playlists", []) if isinstance(item, dict)]
    playlist_appearances = _playlist_appearances(playlists)
    tracks = _tracks_from_export(raw_tracks, playlist_appearances)
    if not tracks:
        raise ValueError("Apple Music export contains no named artist and track pairs to import.")

    top_artists = _top_names(track.artist for track in tracks)
    top_genres = _top_names(track.genre for track in tracks if track.genre)
    seed_queries = _seed_queries(tracks, top_artists, top_genres)
    profile_text = _profile_text(
        track_count=len(tracks),
        playlist_count=len(playlists),
        top_artists=top_artists,
        top_genres=top_genres,
        has_strong_signals=any(track.loved or track.rating > 0 or track.play_count > 0 for track in tracks),
    )
    return AppleMusicTasteImport(
        track_count=len(tracks),
        playlist_count=len(playlists),
        top_artists=top_artists,
        top_genres=top_genres,
        seed_queries=seed_queries,
        profile_text=profile_text,
    )


def _tracks_from_export(raw_tracks: dict[Any, Any], playlist_appearances: Counter[str]) -> list[_TrackSignal]:
    result: list[_TrackSignal] = []
    for raw_id, raw_track in raw_tracks.items():
        if not isinstance(raw_track, dict):
            continue
        title = _text(raw_track.get("Name"))
        artist = _text(raw_track.get("Artist"))
        if not title or not artist:
            continue
        track_id = str(raw_track.get("Track ID", raw_id))
        result.append(
            _TrackSignal(
                title=title,
                artist=artist,
                album=_text(raw_track.get("Album")) or "Unknown album",
                genre=_text(raw_track.get("Genre")),
                play_count=_integer(raw_track.get("Play Count")),
                rating=_integer(raw_track.get("Rating")),
                loved=_boolean(raw_track.get("Loved")) or _boolean(raw_track.get("Favorite")),
                playlist_appearances=playlist_appearances[track_id],
            )
        )
    return result


def _playlist_appearances(playlists: list[dict[str, Any]]) -> Counter[str]:
    appearances: Counter[str] = Counter()
    for playlist in playlists:
        if _boolean(playlist.get("Master")):
            continue
        for item in playlist.get("Playlist Items", []):
            if not isinstance(item, dict):
                continue
            track_id = item.get("Track ID")
            if track_id is not None:
                appearances[str(track_id)] += 1
    return appearances


def _seed_queries(
    tracks: list[_TrackSignal], top_artists: list[str], top_genres: list[str]
) -> list[str]:
    ordered = sorted(tracks, key=lambda track: track.rank)
    queries: list[str] = []
    seen_artists: set[str] = set()
    for track in ordered:
        artist_key = track.artist.casefold()
        if artist_key in seen_artists and len(seen_artists) < 4:
            continue
        _append_unique(queries, track.query)
        seen_artists.add(artist_key)
        if len(queries) >= 6:
            break
    for artist in top_artists:
        _append_unique(queries, artist)
    for genre in top_genres[:2]:
        _append_unique(queries, f"{genre} music")
    return queries[:_MAX_SEED_QUERIES]


def _profile_text(
    *,
    track_count: int,
    playlist_count: int,
    top_artists: list[str],
    top_genres: list[str],
    has_strong_signals: bool,
) -> str:
    artist_line = ", ".join(top_artists) if top_artists else "No repeated artist signal yet"
    genre_line = ", ".join(top_genres) if top_genres else "No clear recurring genre signal yet"
    evidence = (
        "playlist membership plus available ratings, favorites, or play counts"
        if has_strong_signals
        else "playlist membership and repeated metadata only"
    )
    return "\n".join(
        [
            "# Listener profile",
            "",
            "## Explicit instructions",
            "- None yet.",
            "",
            "## Taste notes",
            "- Initial, provisional observation from an Apple Music XML import. Edit or delete this freely.",
            f"- Frequently represented artists: {artist_line}.",
            f"- Repeated genres or styles: {genre_line}.",
            "",
            "## Recent signals",
            f"- Imported {track_count} tracks across {playlist_count} playlists, using {evidence}.",
        ]
    )


def _top_names(values: Any, *, limit: int = 5) -> list[str]:
    counts: Counter[str] = Counter(value for value in values if value)
    return [name for name, _ in counts.most_common(limit)]


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    return 0


def _boolean(value: object) -> bool:
    return value is True or value == 1
