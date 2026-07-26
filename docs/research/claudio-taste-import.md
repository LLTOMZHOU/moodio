# Claudio taste import research

**Scope:** canonical Claudio source at commit [`7ea3774`](https://github.com/stevenjia93/claudio/tree/7ea377447fc4ae466ba202c7a080300f54cd9387), checked 2026-07-26. This note inspects executable source only (not README or design plans).

## Short answer

Claudio does **not** implement an Apple Music, iTunes XML, plist, or local-library import. Its one automatic listening-history integration is Spotify. It keeps the Spotify data as a separate, read-only JSON input and pastes a bounded textual subset into every DJ programming prompt. It deliberately does **not** synthesize or rewrite the durable `user/taste.md` profile.

The only LLM-made taste-like artifact is a cached **DJ-card UI bio**. That card is generated from the same inputs, but it is display-only and does not feed song selection.

## What Claudio imports

### Apple Music/library import: absent

The repository has no executable parser or integration matching Apple Music, iTunes, XML, plist, or `Music Library`. The one automated source is `server/taste-sources/spotify.js`; its OAuth scopes are `user-top-read` and `user-library-read`. [OAuth scopes](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/scripts/spotify-auth.js#L14-L46) · [Spotify sync module](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/taste-sources/spotify.js#L1-L21)

### Spotify signals and exact fields

On refresh, Claudio makes seven Spotify reads in parallel:

| Signal | Amount | Persisted fields |
| --- | ---: | --- |
| Top artists — short term | up to 30 | `name`, Spotify `id`, `genres[]` |
| Top artists — medium term | up to 30 | `name`, Spotify `id`, `genres[]` |
| Top artists — long term | up to 30 | `name`, Spotify `id`, `genres[]` |
| Liked songs | up to 200 | track `name`, joined artist names as `artist`, library `addedAt` |

The data-fetch and normalization code is literal about those fields and limits. [Top-artist fetch](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/taste-sources/spotify.js#L106-L116) · [Liked-song fetch](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/taste-sources/spotify.js#L118-L140) · [Refresh payload](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/taste-sources/spotify.js#L144-L172)

Notably absent: Spotify top tracks, recently played, albums, playlist membership/order, play counts, skips, audio features, ratings, and favourite-album signals. `genres[]` is persisted on every imported artist, but the current programming prompt formatter does not render it—only artist names and liked-song name/artist pairs. [Prompt formatter](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/context.js#L130-L156)

## What it persists

| Path | Contents | Role |
| --- | --- | --- |
| `state/spotify-token.json` | OAuth access token, refresh token, expiry, granted scope | Credentials for future refreshes. [Write path](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/scripts/spotify-auth.js#L75-L116) |
| `user/spotify-listening.json` | `syncedAt`, the three artist periods, up to 200 liked songs | Separate automatic taste signal. [Write path](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/taste-sources/spotify.js#L152-L172) |
| `user/taste.md` | Manual, user-authored taste notes | Read as the higher-level durable profile; automatic sync does not write it. [Read into prompt](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/context.js#L48-L53) |
| `state/state.json` | Local messages, plays, Queue, likes/dislikes, playback settings | Additional short-/medium-term programming evidence, bounded to 200 messages, 500 plays, and 100 likes/dislikes per polarity. [State schema and retention](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/state.js#L8-L24) · [Mutation bounds](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/state.js#L57-L119) |
| `state/dj-card-cache.json` | Cached LLM-generated card bio, its input hash, generation time | UI only; not a preference source for programming. [Cache write](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/dj-card.js#L189-L227) |

At startup Claudio refreshes `spotify-listening.json` only when missing or older than 24 hours; the refresh is asynchronous and does not block the station. [TTL logic](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/taste-sources/spotify.js#L175-L199) · [Startup call](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/server.js#L509-L520)

## Does it use an LLM to synthesize taste?

**Not for its durable programming profile.** The programming context reads the user-written `taste.md` verbatim, then adds a Spotify section containing the three artist-name lists and the first 150 liked songs. It never calls an LLM to merge those data into `taste.md`, and the import module only writes the raw Spotify JSON. [Context assembly](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/context.js#L40-L124) · [Import write boundary](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/taste-sources/spotify.js#L144-L172)

**Yes, for a separate display card.** `dj-card.js` asks Anthropic for a tagline, three description lines, and 7–10 genre tags from `taste.md`, Spotify data, and Claudio’s own play/like history. It caches that JSON by a hash of its inputs. The server exposes it only from `/api/dj-card`; the normal programming context does not read the cache. [Card prompt and output schema](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/dj-card.js#L79-L163) · [Display endpoint](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/server.js#L330-L350)

## How the imported data affects programming

For every natural-language DJ request, Claudio:

1. assembles one large prompt: persona, manual taste/routines/playlists, formatted Spotify signal, recent plays, likes/dislikes, six recent messages, and the current request;
2. asks the model to return strict JSON with `say`, `play`, `reason`, and `segue`;
3. clears the existing Queue, then resolves the model's 6–10 requested titles against music providers in the background and appends the successful results.

The Spotify signal therefore influences programming only by model attention inside the prompt: it is neither a ranker nor a hard constraint, and it does not itself pick a track. [Prompt requirements](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/context.js#L79-L122) · [Programming pipeline](https://github.com/stevenjia93/claudio/blob/7ea377447fc4ae466ba202c7a080300f54cd9387/server/server.js#L85-L137)

## Useful lesson for Moodio

Claudio's strongest idea is keeping an imported signal distinct from manual instructions, which preserves transparency. Its limitation is that the automatic data is mostly passed through as a long prompt attachment: artist genres are collected but unused; albums and playlists are not represented; and its generated genre card has no effect on programming. Moodio can keep the same transparency while making a compact, versioned import-derived profile that explicitly records artists, albums, genres, playlist/context evidence, and uncertainty.
