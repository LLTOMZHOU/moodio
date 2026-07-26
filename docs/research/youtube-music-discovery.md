# YouTube / yt-dlp discovery research

**Scope:** Moodio discovery only. This report covers metadata/search behaviour; it does not propose downloading, retaining, or redistributing audio. Sources were checked on 2026-07-25 and are limited to yt-dlp's official repository/documentation and Google's official YouTube Data API documentation.

## Short answer

`yt-dlp` can be a useful **candidate discovery and later stream-resolution** adapter, but it is not a structured music-catalog API. Use its YouTube Music search URL for normal Listener text search and artist/album/song result sections; treat genre and mood as query formulation/ranking problems, not provider filters. A final resolver must still decide whether a selected candidate is actually playable in the Listener's context. [yt-dlp YouTube Music extractor source](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_search.py#L102-L151) · [yt-dlp availability fields](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#output-template)

## 1. Search entry points and selectors

### YouTube

- `ytsearch<N>:<query>` is the current yt-dlp search prefix. The source defines the key as `ytsearch`; its shared search parser accepts no count (one result), a positive count, or `all`. Thus `ytsearch:query`, `ytsearch10:query`, and `ytsearchall:query` are supported forms. The built-in YouTube search extractor requests video-only results. [YouTube search extractor](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_search.py#L8-L28) · [shared prefix parser](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/common.py#L4125-L4152)
- A normal `youtube.com/results?...` URL is also accepted. yt-dlp passes the page's `sp` parameter through to its search request, so website search URLs can retain YouTube-side sort/filter selections. This is a website-query interface, not a stable yt-dlp fielded-filter API. [YouTube search-URL extractor](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_search.py#L31-L99)

### YouTube Music

- yt-dlp has a separate extractor for `https://music.youtube.com/search?q=<query>`. It uses the YouTube Music web client. [YouTube Music search-URL extractor](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_search.py#L102-L151)
- That extractor supports result-section selectors: `#songs`, `#albums`, `#artists`, `#videos`, `#featured playlists`, and `#community playlists` (or their opaque `sp` equivalents). For example: `https://music.youtube.com/search?q=FKA+twigs#albums`. [Selector map in the official source](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_search.py#L127-L151)
- The checked source exposes `ytsearch` as the prefix and exposes YouTube Music search through a Music URL extractor; it does **not** define a `ytmusicsearch` prefix in that source. That is a useful implementation distinction: construct a Music search URL rather than assuming a Music-prefixed shorthand. [YouTube search extractor](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_search.py#L8-L12) · [YouTube Music extractor](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_search.py#L102-L105)

## 2. Structured filtering versus free-text search

| Need | What is verified | Implication for Moodio |
| --- | --- | --- |
| Artist | YouTube Music can return an **Artists** section, but the artist name is still in the `q` free-text query. | Direct Listener search can query the name and show the artist section; do not present this as an ID-verified artist lookup. |
| Album | YouTube Music can return an **Albums** section, again from a free-text query. | A good direct-search mode; show candidate albums/tracks, then resolve the chosen item. |
| Song | YouTube Music can return a **Songs** section. | This should be the default for a Listener who names a track. |
| Genre | yt-dlp's Music search source has no genre parameter or genre taxonomy. | Formulate a query such as `ambient dub techno`, then rank/inspect results. |
| Mood/activity | yt-dlp's Music search source has no mood/activity parameter. | Let the DJ formulate discovery queries, and use bounded web research when it needs external editorial context. Do not claim that YouTube Music provides a semantic mood search contract. |

**Verified fact:** the selector list above is the complete `_SECTIONS` map in the current Music search extractor; it has no `genre`, `mood`, or `activity` selector. [YouTube Music selector map](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_search.py#L127-L137)

**Related official API option:** if Moodio later adds the official YouTube Data API as a separate provider, `search.list` supports a free-text `q`, result type, date, language/region, duration, and `videoCategoryId`; it also documents a small, curated set of `topicId` values, including broad music genres. It does not document artist, album, or mood as fielded filters. That API requires an API key or OAuth token. [YouTube `search.list`](https://developers.google.com/youtube/v3/docs/search/list) · [YouTube Data API overview](https://developers.google.com/youtube/v3/getting-started)

## 3. Metadata-only discovery and availability

- `-j` / `--dump-json` prints JSON information and simulates by default. `-s` / `--simulate` explicitly says it neither downloads the video nor writes to disk. `--no-cache-dir` can additionally disable yt-dlp's own filesystem cache. These make a metadata-only discovery command possible without audio download. [yt-dlp simulation and JSON options](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#verbosity-and-simulation-options) · [yt-dlp cache option](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#filesystem-options)
- `--flat-playlist` avoids fully extracting playlist URL entries, but yt-dlp explicitly warns that some entry metadata can be missing. It is appropriate for fast candidate lists, not a promise of full/accurate track metadata. [yt-dlp flat-playlist option](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#general-options)
- The YouTube search extractor builds candidates with an ID, canonical watch URL, title, description, duration when present, channel/uploader fields, thumbnails, view count, live status, and an availability classification when its badges supply one. Its availability vocabulary includes `private`, `premium_only`, `subscriber_only`, `needs_auth`, `unlisted`, and `public`. [YouTube candidate extraction](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_tab.py#L76-L169) · [availability field reference](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#output-template)
- Metadata discovery is not a playback guarantee. yt-dlp documents `--ignore-no-formats-error` specifically for extracting metadata even when a video is not actually available for download; its YouTube client documentation also says some clients/formats require a PO token or authentication. [metadata despite unavailable formats](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#verbosity-and-simulation-options) · [YouTube client constraints](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#extractor-arguments)

A safe **manual experiment** shape is:

```sh
yt-dlp --no-config --no-cache-dir --simulate --flat-playlist --dump-json \
  'https://music.youtube.com/search?q=Little+Simz#songs'
```

This command requests metadata only; it does not select or download audio. `--no-config` is included so a developer's personal yt-dlp configuration cannot quietly add download/post-processing behaviour. The command is an inference from the documented options above, not a product integration.

## 4. Practical implications for Moodio

### Direct Listener search

**Recommendation (inference):** make the provider's YouTube Music search the first path for ordinary text requests. Offer a small UI control for the relevant section—Songs, Albums, Artists, Videos, or playlists—and display real returned candidates with title, channel, duration when present, thumbnail, and an availability hint. The Listener picks a candidate; the Station controller records that choice and queues it through the same control path as the DJ. This uses the provider for what it can identify, rather than asking the model to invent a URL. The underlying source supports these sections but does not guarantee the candidate is playable. [Music result sections](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_search.py#L127-L151) · [candidate fields](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_tab.py#L76-L169)

### DJ-led mood/discovery requests

**Recommendation (inference):** let the DJ turn a mood, activity, or taste prompt into one or more free-text Music queries, then choose only among returned candidates. When it needs current editorial context (for example, a newly released album or why an artist is relevant), use bounded web research to produce the query/context—not as a replacement for provider-backed candidate selection. There is no verified yt-dlp mood filter to delegate this to. [Music selector map](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_search.py#L127-L137)

### Two-phase provider contract

**Recommendation (inference):** keep discovery and playback resolution separate:

1. `search_tracks(query, section, limit)` returns metadata candidates without audio transfer.
2. `resolve_playback(candidate_id)` runs immediately before playback and either yields a currently permitted stream handle or a typed unavailable result.

The separation is justified because search metadata can exist even where no downloadable/playable format is available, and flat results can be incomplete. Moodio should fall back to another candidate rather than attempting to work around a restriction. [yt-dlp unavailable-format behaviour](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#verbosity-and-simulation-options) · [flat-playlist limitation](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#general-options)

## Open validation work

Before committing to the adapter, run a small no-download spike against representative searches and record: result quality per Music section, metadata completeness, region/account variation, resolver success rate, and error categories. Do not store media files or use credentials/tokens to bypass access restrictions. The official yt-dlp documentation notes that some YouTube formats/features have client/token/authentication constraints, so this needs an empirical compatibility check rather than an architectural assumption. [yt-dlp YouTube client documentation](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#extractor-arguments)
