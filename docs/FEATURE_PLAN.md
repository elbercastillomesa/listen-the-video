# Feature Plan

Implementation plan for a first round of improvements to `listen-the-video`.

Scope: **metadata/cover caching (#1)**, **job queue with progress feedback (#2)**,
**`/cancel` and better selection state (#4)**, **richer tags (#6)**,
**configurable filename scheme (#7)** and **health/status surface (#12)**.

The remaining ideas are tracked in the "Future Improvements" section of the
[README](../README.md).

## Guiding principles

- Keep the existing modular split: `app/bot` (Telegram), `app/core` (pure logic),
  `app/config.py` (settings).
- Core modules must stay free of Telegram imports; the bot layer is the only one
  that talks to `python-telegram-bot`.
- Every new setting is optional with a safe default so existing `.env` files keep
  working.
- Work is test-driven: each feature ships with unit tests in `tests/` (network
  mocked, deterministic).

## Proposed implementation order

1. **#2 Job queue + progress** — touches the delivery path: bounds concurrency,
   serializes per user and reports staged progress. *(implemented)*
2. **#1 Caching** — self-contained, immediately reduces latency and API pressure.
3. **#4 Selection state + `/cancel`** — bot-layer only, builds on #2.
4. **#6 Richer tags** and **#7 Filename scheme** — output quality, independent.
5. **#12 Health/status** — deferred; see the metric assessment in its section.

---

## #1 — Metadata and cover caching

**Goal.** Stop re-querying Deezer, MusicBrainz and the Cover Art Archive for
tracks already looked up. Reduce latency, API pressure and occasional rate
limits. Optionally reuse the built MP3 for repeat requests (opt-in).

**Design.**

- New module `app/core/cache.py` with a small JSON-on-disk store under
  `DATA_DIR/cache/`:
  - `MetadataCache`: key = sha256 of normalized `artist|title`; value = serialized
    [`TrackMetadata`](../app/core/metadata.py#L39) plus a `stored_at` timestamp.
  - `CoverCache`: key = sha256 of the cover URL; value = the image bytes plus the
    MIME type (stored as `<key>.bin` + `<key>.json`).
- TTL-based expiry (`CACHE_TTL_DAYS`, default 30). Corrupt or unreadable entries
  are treated as misses and overwritten, never raised.
- Wire into [`fetch_metadata`](../app/core/metadata.py#L51): check cache →
  on miss, run the existing Deezer/MusicBrainz flow → store. The cache stores the
  **merged** result, so the merge rules stay in one place.
- Wire into [`_download_cover`](../app/core/tagger.py#L49): cache hit returns the
  stored bytes without a network call. Keep the same graceful `None` fallback.

**Config (new).**

| Variable | Default | Notes |
| --- | --- | --- |
| `CACHE_ENABLED` | `true` | Global switch. |
| `CACHE_TTL_DAYS` | `30` | `0` disables expiry (never stale-check). |
| `CACHE_DIR` | `<DATA_DIR>/cache` | Kept out of the work-dir cleanup. |

**Edge cases / risks.**

- Never let a cache failure break a build: reads/writes are best-effort.
- Do not cache negative results (a miss today may hit tomorrow).
- Concurrency: writes go through a temp file + `os.replace` (atomic).
- Covered later by #2: a cached MP3 short-circuit is a separate, opt-in step and
  is **not** part of this plan.

**Tests.** `tests/test_cache.py` (round-trip, TTL expiry, corrupt file tolerated,
atomic write). Extend `tests/test_metadata.py` to assert a second lookup issues no
HTTP request (count mocked calls).

---

## #2 — Job queue with progress feedback

> **Status:** implemented (branch `job-queue-progress`). Progress reporting,
> concurrency caps and the stage enum match the design below.

**Goal.** Replace the fire-and-forget `asyncio.to_thread(build_mp3, ...)` in
[`_deliver_track`](../app/bot/handlers.py#L199) with a small job runner that
bounds concurrency, serializes a user's own jobs and reports staged progress by
editing the status message.

**Design.**

- New `app/core/progress.py`: a `ProgressCallback` type plus a no-op default.
  Stages are an enum: `SEARCHING`, `DOWNLOADING`, `CONVERTING`, `TAGGING`,
  `SENDING`.
- New `app/bot/jobs.py`: an asyncio scheduler holding
  - a global `asyncio.Semaphore(MAX_CONCURRENT_JOBS)`, and
  - one `asyncio.Lock` per user id.
  Jobs are submitted from the handler; the scheduler runs `build_mp3` via
  `asyncio.to_thread` and delivers results.
- Thread→loop progress: the worker thread reports through a thread-safe callback
  that schedules message edits on the loop (`loop.call_soon_threadsafe`), so the
  core modules stay Telegram-free.
- [`pipeline.build_mp3`](../app/core/pipeline.py#L36) gains an
  `on_progress: ProgressCallback | None = None` parameter and reports each stage.
- [`youtube.download_audio`](../app/core/youtube.py#L64) gains a `progress_hooks`
  entry that translates yt-dlp's `_percent_str` into a `DOWNLOADING` detail
  (e.g. `Downloading 45%`).
- Edits are throttled (`PROGRESS_UPDATE_INTERVAL_SECONDS`, default `1.5`) and only
  applied on meaningful change, to respect Telegram's edit rate limits.
- The final stage deletes the status message (existing behaviour) once the audio
  is sent.

**Config (new).**

| Variable | Default | Notes |
| --- | --- | --- |
| `MAX_CONCURRENT_JOBS` | `2` | Global parallelism across users. |
| `PROGRESS_UPDATE_INTERVAL_SECONDS` | `1.5` | Min interval between status edits. |

**Edge cases / risks.**

- A failed stage must still clear the status message and surface the existing
  error text; keep the current `_DELIVERY_ERRORS` handling.
- `yt-dlp` progress hook fires from its thread — propagate via the scheduler,
  never touch `asyncio` objects directly from the hook.
- ffmpeg progress is coarse; a stage-only update for `CONVERTING` is acceptable
  in this iteration (optional `-progress pipe:1` parsing is a follow-up).

**Tests.** `tests/test_jobs.py` (per-user serialization, global concurrency cap,
progress ordering); extend `tests/test_pipeline.py` to assert the callback fires
in stage order; extend `tests/test_handlers.py` to assert the status text is
edited and finally deleted.

---

## #4 — `/cancel` and better selection state

**Goal.** Bound the lifetime of the stored candidate list, let the user refresh
or request more results, and give an escape hatch so a stuck selection state does
not block the next request.

**Design.**

- Store selection state in `user_data` as a small record:
  `{track, candidates, message_id, created_at, limit}`.
- Expiry: selections older than `SELECTION_TTL_MINUTES` (default `10`) are
  treated as expired and cleared, reusing the existing
  [`EXPIRED_SELECTION_TEXT`](../app/bot/handlers.py#L69) path.
- New `/cancel` command ([`main.py`](../app/main.py#L28) registration) that clears
  the user's pending selection and confirms.
- Keyboard additions in [`keyboards.py`](../app/bot/keyboards.py#L17):
  - a "Show more" button that re-runs the search with a larger `limit`
    (e.g. `DEFAULT_SEARCH_LIMIT` → `2 × limit`) and replaces the list;
  - a "Cancel" button that clears state (same effect as `/cancel`).
  - Introduce callback prefixes (`more:`, `cancel`) alongside `pick:` and extend
    `parse_pick_callback` into a small dispatcher.

**Config (new).**

| Variable | Default | Notes |
| --- | --- | --- |
| `SELECTION_TTL_MINUTES` | `10` | Lifetime of a candidate list. |

**Edge cases / risks.**

- Keep the "one active selection per user" assumption (single-user project); no
  conversation threading needed.
- Expired-selection messages must not throw when `user_data` is empty.
- The button callback and the `/cancel` command must share the clear logic.

**Tests.** `tests/test_keyboards.py` (new buttons and callback parsing);
`tests/test_handlers.py` (TTL expiry, `/cancel` clears state, "Show more"
increases the result count).

---

## #6 — Richer tags

**Goal.** Write a more complete ID3v2.3 set so players show correct ordering,
album artist, composer, ISRC and (optionally) lyrics.

**Design.**

- Extend [`TrackMetadata`](../app/core/metadata.py#L39) with:
  `track_number`, `total_tracks`, `disc_number`, `album_artist`, `composer`,
  `isrc`, `lyrics` (all optional).
- Sources:
  - Deezer track: `track_position`, `disk_number`, `isrc`; album: `nb_tracks`,
    `artist.name` (album artist).
  - MusicBrainz recording: `isrc-list` for ISRC, existing tag-list for genre.
  - Lyrics: add **LRCLIB** (`https://lrclib.net/api/get`), free and key-less;
    stored as plain lyrics. Gate behind `ENABLE_LYRICS` (default `true`).
- Merge order in [`fetch_metadata`](../app/core/metadata.py#L63) stays
  Deezer-first for album/track fields, MusicBrainz-first for date/genre.
- Tagger ([`tagger.py`](../app/core/tagger.py#L20)) writes the new frames:
  `TRCK` (`n/total`), `TPOS` (`n/total`), `TPE2`, `TCOM`, `TSRC`, `USLT`.
- Light genre normalization (trim, title case, drop empties) before tagging.

**Config (new).**

| Variable | Default | Notes |
| --- | --- | --- |
| `ENABLE_LYRICS` | `true` | Fetch/embed lyrics from LRCLIB. |
| `LRCLIB_TIMEOUT` | `15` | Seconds. |

**Edge cases / risks.**

- The file is saved as **ID3v2.3**; verify `TDRC` survives a v2.3 save (mutagen
  may map it to `TYER`). If not, write `TYER` explicitly.
- Missing fields are simply skipped (existing `_set_text` behaviour).
- LRCLIB may 404 for unknown tracks → skip lyrics, never fail the build.

**Tests.** `tests/test_metadata.py` (ISRC, track/disc numbers, lyrics parsing with
LRCLIB mocked; 404 tolerated); `tests/test_tagger.py` (new frames present and
correctly formatted).

---

## #7 — Configurable filename scheme

**Goal.** Name delivered files from a template instead of the YouTube id, so
downloads sort cleanly (`Artist - Title.mp3` by default).

**Design.**

- New helper `app/core/naming.py`: `render_filename(template, metadata, track)`
  with token substitution (`{artist}`, `{title}`, `{album}`, `{year}`,
  `{track}`) and filesystem sanitization (strip `/ \ : * ? " < > |`, collapse
  whitespace, cap length, and fall back to the current stem when a token is
  empty).
- Assign the name after tagging in [`pipeline.build_mp3`](../app/core/pipeline.py#L36)
  (rename the produced MP3 within the work dir). The Telegram `filename`,
  `title` and `performer` in
  [`_deliver_track`](../app/bot/handlers.py#L222) already derive from
  `built.path.name` / metadata, so no handler change is needed beyond confirming
  the rename happens before the size check.
- Missing tokens degrade gracefully (e.g. no album → `Artist - Title`).

**Config (new).**

| Variable | Default | Notes |
| --- | --- | --- |
| `OUTPUT_FILENAME_TEMPLATE` | `{artist} - {title}` | Empty → keep current stem. |

**Edge cases / risks.**

- Two identical templates for different tracks is acceptable (single delivery);
  no dedupe needed now.
- Always keep the `.mp3` extension regardless of template.
- Sanitize before writing to avoid invalid paths on the host volume.

**Tests.** `tests/test_naming.py` (token substitution, sanitization, empty-token
fallback); extend `tests/test_pipeline.py` to assert the final filename.

---

## #12 — Health/status surface

**Goal.** Give operators a quick view of the bot's state and give Docker a real
liveness check.

**Design.**

- New `app/core/metrics.py`: lightweight in-memory counters (jobs started /
  succeeded / failed, per-stage durations, cache hits/misses) with a `snapshot()`
  and a `started_at` timestamp. Reused by #1 and #2.
- New `/status` command ([`handlers.py`](../app/bot/handlers.py#L99),
  registered in [`main.py`](../app/main.py#L28)), gated by `_is_authorized`:
  uptime, `yt-dlp` version (`yt_dlp.version.__version__`), `ffmpeg` version
  (cached at first call), queue depth, job counters, cache entry count and
  `DATA_DIR` disk usage.
- Docker liveness: a small `app/healthcheck.py` that calls Telegram `getMe` with
  the configured token (verifies token + connectivity) and exits non-zero on
  failure. Wire it via `HEALTHCHECK` in the
  [Dockerfile](../Dockerfile) and note it in
  [docker-compose.yml](../docker-compose.yml).
- Record a `started_at` when [`main()`](../app/main.py#L42) boots so uptime is
  accurate.

**Metric assessment (revisit before implementing).**

Not every counter above earns its place in a single-user bot. A blunt value
check, recorded here so the design can be trimmed later:

| Candidate metric | Worth it? | Why |
| --- | --- | --- |
| Failure count **per pipeline stage** + last error | **Yes** | The real pain: "3 of last 20 jobs died at download" tells you yt-dlp needs updating. |
| yt-dlp / ffmpeg versions | **Yes** | Not a metric, but the single most useful diagnostic — yt-dlp rots often. |
| Success/failure totals, uptime | Yes (cheap) | Baseline sanity. |
| `DATA_DIR` disk usage | Yes (cheap) | Cache + leftover work dirs can grow unbounded. |
| Last failure message + timestamp | Yes | Faster than grepping logs. |
| Per-stage **average** duration | Marginal | Averages hide the outliers that matter; better to log slow jobs. |
| Cache hits/misses | Later | Only meaningful once #1 exists. |
| Queue depth | Later | Only meaningful once #2 exists. |
| Prometheus/Grafana export, histograms, dashboards | **No** | Over-engineering for one user. |

Caveat: the counters described above are in-memory, so they reset on every
container restart — and this project restarts often. If history is wanted,
persist a small append-only record instead. Metrics are deferred for now.

**Config (new).** None required. Optional `HEALTHCHECK_TIMEOUT` for the script.

**Edge cases / risks.**

- `/status` must not leak the bot token; report only versions/counters.
- `ffmpeg -version` parsing is best-effort (report "unknown" on failure).
- The healthcheck relies on outbound network; a transient failure restarts the
  container — acceptable, but keep the timeout generous.

**Tests.** `tests/test_handlers.py` (`/status` formatting, authorization);
`tests/test_healthcheck.py` (success/failure exit codes with `getMe` mocked).

---

## Cross-cutting summary

**New files:** `app/core/cache.py`, `app/core/progress.py`, `app/bot/jobs.py`,
`app/core/naming.py`, `app/core/metrics.py`, `app/healthcheck.py`, plus matching
tests.

**Modified files:** `app/config.py`, `app/core/metadata.py`, `app/core/tagger.py`,
`app/core/pipeline.py`, `app/core/youtube.py`, `app/bot/handlers.py`,
`app/bot/keyboards.py`, `app/main.py`, `Dockerfile`, `docker-compose.yml`,
`.env.example`, `README.md`.

**New environment variables:** `CACHE_ENABLED`, `CACHE_TTL_DAYS`, `CACHE_DIR`,
`MAX_CONCURRENT_JOBS`, `PROGRESS_UPDATE_INTERVAL_SECONDS`,
`SELECTION_TTL_MINUTES`, `ENABLE_LYRICS`, `LRCLIB_TIMEOUT`,
`OUTPUT_FILENAME_TEMPLATE`.

All defaults preserve current behaviour, so no breaking changes to existing
deployments.
