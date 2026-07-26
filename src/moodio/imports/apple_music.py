from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import plistlib
from typing import Any


_MAX_EVIDENCE_ROWS = 12
_MAX_TRACK_EXAMPLES = 18


@dataclass(frozen=True, slots=True)
class AppleMusicTasteImport:
    """A bounded evidence packet for the DJ, not a deterministic taste profile.

    The importer extracts only descriptive facts from a Listener-selected XML
    export. The Station harness decides which facts form useful taste notes,
    writes the editable profile, and chooses seed queries. No XML, file path,
    artwork, or audio reference is retained by this value.
    """

    track_count: int
    playlist_count: int
    evidence: dict[str, object]


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
    def favorite_rank(self) -> tuple[int, int, int, int, str, str]:
        return (
            -int(self.loved),
            -self.rating,
            -self.play_count,
            -self.playlist_appearances,
            self.artist.casefold(),
            self.title.casefold(),
        )


def import_apple_music_xml(content: bytes) -> AppleMusicTasteImport:
    """Extract compact, explainable evidence from a Music.app XML export.

    This deliberately does not label a Listener's taste or choose a profile.
    Those are harness decisions made from the evidence packet in a normal DJ
    run. The caller owns the source bytes and must not persist them.
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

    return AppleMusicTasteImport(
        track_count=len(tracks),
        playlist_count=len(playlists),
        evidence=_build_evidence(tracks, playlists),
    )


def _build_evidence(tracks: list[_TrackSignal], playlists: list[dict[str, Any]]) -> dict[str, object]:
    favorites = [track for track in tracks if track.loved]
    played = [track for track in tracks if track.play_count > 0]
    rated = [track for track in tracks if track.rating > 0]
    strong = [track for track in tracks if track.loved or track.rating > 0 or track.play_count > 0]

    return {
        "scope": {
            "track_count": len(tracks),
            "playlist_count": len(playlists),
            "available_signals": {
                "favorites": len(favorites),
                "ratings": len(rated),
                "played_tracks": len(played),
                "tracks_with_any_positive_signal": len(strong),
            },
            "interpretation": (
                "This is descriptive import evidence, not a verdict about the Listener. "
                "Library-only counts can reflect collecting, soundtracks, or one-off exploration."
            ),
        },
        "explicit_favorites": _evidence_slice(favorites),
        "repeated_listening": _evidence_slice(played, examples_key="play_count"),
        "rated_music": _evidence_slice(rated, examples_key="rating"),
        "whole_library_context": _evidence_slice(tracks),
        "playlist_context": _playlist_evidence(playlists),
    }


def _evidence_slice(
    tracks: list[_TrackSignal],
    *,
    examples_key: str = "favorite_rank",
) -> dict[str, object]:
    examples = _track_examples(tracks, sort_by=examples_key)
    return {
        "track_count": len(tracks),
        "top_artists": _ranked_names(track.artist for track in tracks),
        "top_genres": _ranked_names(track.genre for track in tracks if track.genre),
        "top_albums": _ranked_albums(tracks),
        "representative_tracks": examples,
    }


def _ranked_names(values: Any, *, limit: int = _MAX_EVIDENCE_ROWS) -> list[dict[str, object]]:
    counts: Counter[str] = Counter(value for value in values if value)
    return [{"name": name, "track_count": count} for name, count in counts.most_common(limit)]


def _ranked_albums(tracks: list[_TrackSignal], *, limit: int = _MAX_EVIDENCE_ROWS) -> list[dict[str, object]]:
    counts: Counter[tuple[str, str]] = Counter((track.artist, track.album) for track in tracks if track.album)
    return [
        {"artist": artist, "album": album, "track_count": count}
        for (artist, album), count in counts.most_common(limit)
    ]


def _track_examples(tracks: list[_TrackSignal], *, sort_by: str) -> list[dict[str, object]]:
    if sort_by == "play_count":
        ordered = sorted(
            tracks,
            key=lambda track: (-track.play_count, -int(track.loved), track.artist.casefold(), track.title.casefold()),
        )
    elif sort_by == "rating":
        ordered = sorted(
            tracks,
            key=lambda track: (-track.rating, -int(track.loved), -track.play_count, track.artist.casefold(), track.title.casefold()),
        )
    else:
        ordered = sorted(tracks, key=lambda track: track.favorite_rank)

    return [
        {
            "artist": track.artist,
            "title": track.title,
            "album": track.album,
            "genre": track.genre,
            "play_count": track.play_count,
            "favorite": track.loved,
            "rating": track.rating,
        }
        for track in ordered[:_MAX_TRACK_EXAMPLES]
    ]


def _playlist_evidence(playlists: list[dict[str, Any]]) -> dict[str, object]:
    named = []
    for playlist in playlists:
        if _boolean(playlist.get("Master")):
            continue
        name = _text(playlist.get("Name"))
        if not name:
            continue
        item_count = sum(1 for item in playlist.get("Playlist Items", []) if isinstance(item, dict))
        if item_count:
            named.append({"name": name, "track_count": item_count})
    named.sort(key=lambda playlist: (-int(playlist["track_count"]), str(playlist["name"]).casefold()))
    return {"named_playlists": named[:_MAX_EVIDENCE_ROWS]}


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
                loved=_boolean(raw_track.get("Loved")) or _boolean(raw_track.get("Favorited")),
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
