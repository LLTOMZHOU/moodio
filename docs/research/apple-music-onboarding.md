# Apple Music onboarding research

**Scope:** importing a Listener's existing music taste at first start without importing, downloading, retaining, or redistributing audio. Sources were checked on 2026-07-25 and are limited to Apple documentation.

## Recommendation

Use a **Listener-selected XML export from the macOS Music app** as Moodio's first import path. It is local, portable, understandable, and avoids requiring an Apple developer account, a developer token, or account authorization in Moodio.

The first-start flow should be:

1. Explain that Moodio can learn an initial, editable impression from a selected Apple Music playlist or library export.
2. Let the Listener choose a representative playlist export (the best default) or a full-library export (optional).
3. Parse the XML locally. Extract only track and playlist metadata needed for the import: title, artist, album, genre, play count, rating/favorite signal when present, date added, and playlist membership/order.
4. Derive a short provisional note in `listener-profile.md` and a compact list of seed queries. Keep explicit Listener instructions separate and higher priority.
5. Use several seed queries to find real candidates through the normal YouTube provider, validate availability, and program only a small first queue (for example, three to five tracks). The Apple export never provides playback to Moodio.
6. Do not retain the original XML by default. Persist the derived profile text, a small import summary/provenance record, and ordinary Station events. The Listener can re-import or replace the initial impression.

Apple documents both **File > Library > Export Playlist** (choose XML) and **File > Library > Export Library** (XML). A playlist export is preferable for initial onboarding because it asks the Listener to select the slice of their taste that they want the DJ to learn from. Apple describes the export as playlist information; it is not an audio transfer. [Apple Music User Guide: export a playlist or library](https://support.apple.com/guide/music/save-a-copy-of-your-playlists-mus27cd5060f/mac)

## What we found locally

This Mac has an active `Music Library.musiclibrary` bundle, but no portable XML export was found in the usual Music, Downloads, or Documents locations. Treat the `.musiclibrary` bundle as private Music-app storage, not an application contract. Moodio should detect that a local Music library may exist and offer the export instructions, but it should not scrape that bundle.

## Taste inference: useful, but explicitly provisional

Playlist membership and ordering are strong enough to form seed queries; library membership alone is weak evidence. Prefer these signals in descending order:

1. tracks appearing in a deliberately selected playlist, especially repeated artists and genres;
2. explicit ratings/favorite markers and high play counts, when the export contains them;
3. repeated artists/albums across selected playlists;
4. date-added recency as a weak tiebreaker.

The generated profile text should say that it is an *initial observation from an Apple Music import*, name the evidence at a high level, and stay easy to correct or delete. It must not turn a one-off import into rigid rules or infer sensitive traits.

## Initial queue policy

The import should not dump an entire Apple playlist into the Station. Instead it should produce a diversified seed set (distinct artists/styles where possible), then use the normal provider path:

```text
Apple Music XML -> normalized taste signals -> seed queries
    -> provider search -> availability validation -> 3-5 Queue music items
```

This preserves Moodio's provider boundary: the importer supplies preference evidence; the provider supplies the current playable candidate; Station control owns queue mutation. If matching fails or candidate playback is unavailable, skip it and try another seed rather than attempting to use Apple media URLs or alter provider restrictions.

## Connected Apple Music integration: later, optional

MusicKit can access a person's Apple Music/library data with permission, including library and playlist operations, and MusicKit JS can authorize a signed-in subscriber. [MusicKit overview](https://developer.apple.com/musickit/) · [MusicKit JS authorization and library playlists](https://js-cdn.music.apple.com/musickit/v1/index.html)

That path is materially heavier than an XML import:

- the app needs the Listener's explicit Music-library authorization; Apple requires a purpose string for native library access and the Listener can revoke it later. [Requesting access to Apple Music Library](https://developer.apple.com/documentation/storekit/requesting-access-to-apple-music-library)
- MusicKit JS requires a developer token from an Apple Developer Program member before user authorization. [MusicKit JS authentication](https://js-cdn.music.apple.com/musickit/v1/index.html)
- Apple Music API user-library endpoints require a Music User Token. [Get a Library Playlist](https://developer.apple.com/documentation/applemusicapi/get-a-library-playlist)

Therefore, keep connected import as a future opt-in adapter. It may be worthwhile for incremental refreshes, favorites, or recently played data, but it should deliver the same normalized metadata import contract and never become a playback dependency for Moodio's YouTube-backed station.

## Concrete v0.2 contract

```python
class TasteImport(Protocol):
    key: str

    def inspect(self, source: Path) -> ImportPreview: ...
    def apply(self, source: Path, selection: ImportSelection) -> ImportedTaste: ...
```

`inspect` is local and read-only; it returns playlist names/counts and a compact preview without copying the file. `apply` derives taste notes and seed queries from the Listener's selection, writes only the derived Station state, and returns the exact initial seeds for normal provider resolution. This keeps the first implementation small while leaving room for a future MusicKit adapter.

## Open product choices

- Decide whether first run defaults to importing one selected playlist or offers a library export as an explicitly stronger, broader option. The recommended default is one selected playlist.
- Decide whether to show the generated initial taste note before it is applied. Either choice should keep it editable and label it as provisional.
- Implement an XML preview before provider search, so the Listener understands what is being used without exposing raw library data in the Station feed.
