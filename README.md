# listen-the-video

Telegram bot that takes a **song name** or a **YouTube/Spotify link**, searches for the track on YouTube, downloads the audio as a **high-quality MP3 (320 kbps)**, attaches **metadata** (album, artist/band, date, cover art, genre, etc.), and returns the final file as a reply in the chat.

> **Experimental, personal-use** project. Not intended for commercial use.

---

## Legal Disclaimer

This project is developed **strictly for educational and technical experimentation purposes**.

- **YouTube**: downloading content from YouTube **violates its Terms of Service**. This project is neither affiliated with nor endorsed by YouTube/Google.
- **Spotify**: this bot **does not download audio from Spotify**. When it receives a Spotify link, that link is only used as a metadata reference to locate the track and obtain its audio from another source.
- **Copyright**: downloaded music is protected by copyright. **You are solely responsible** for how you use the generated files, including any distribution or reproduction.
- **Intended use**: local testing, learning, and strictly personal use. Commercial use is **not** allowed, nor is any exploitation to redistribute copyrighted content.

If you are a rights holder and want content or the project taken down, please open an issue.

---

## What It Does

Intended flow:

1. The user sends the bot a song name or a link (YouTube / Spotify).
2. The bot resolves the track identity (artist + title). If the typed order looks
   inverted ("Title - Artist"), it is corrected against MusicBrainz and Deezer
   before the metadata lookup.
3. If the input is ambiguous, the bot **shows options** for the user to pick from.
4. It searches for and downloads the best available audio on YouTube (`yt-dlp`).
5. It converts the audio to **MP3 320 kbps** (`ffmpeg`).
6. It fetches metadata and cover art (MusicBrainz, Cover Art Archive, Deezer).
7. It writes ID3 tags and embeds the cover art (`mutagen`).
8. It sends the MP3 back to the user in the Telegram chat.

While a track is being prepared, a status message reports the current stage
(downloading, converting, tagging, uploading). Builds are queued: a global cap
bounds how many run at once and a user's own jobs run one after another.

## Status

In development. The initial version targets **personal use** (single user). Planned follow-ups: multi-user support, song library, AI integration (natural-language parsing and disambiguation), and automatic transcription/tagging.

---

## Stack

- **Language**: Python
- **Bot framework**: `python-telegram-bot`
- **Downloader**: `yt-dlp`
- **Conversion**: `ffmpeg`
- **ID3 tagging**: `mutagen`
- **Metadata**: MusicBrainz + Cover Art Archive + Deezer (all freely accessible, no API key)
- **Deployment**: Docker on WSL2 / OrbStack (Ubuntu)

## Requirements

- A Telegram bot token (via [@BotFather](https://t.me/BotFather)).
- `ffmpeg` available on the system (bundled in the Docker image).
- Docker (recommended) or Python 3.11+ installed locally.

## Testing

Tests live in `tests/` and run with pytest. Network calls are mocked, so the
suite is deterministic and runs offline.

| File | Covers |
| --- | --- |
| `tests/conftest.py` | Shared fixtures (`make_settings`). |
| `tests/test_config.py` | Environment loading, defaults, and validation errors. |
| `tests/test_resolver.py` | Input detection and track resolution for plain text, YouTube, and Spotify. |
| `tests/test_matching.py` | Fuzzy artist/title identity resolution, including inverted input. |
| `tests/test_youtube.py` | YouTube search and audio download (yt-dlp mocked). |
| `tests/test_converter.py` | MP3 conversion with ffmpeg (subprocess mocked). |
| `tests/test_metadata.py` | Metadata lookup across MusicBrainz and Deezer (both mocked). |
| `tests/test_tagger.py` | ID3 tagging and cover art embedding with mutagen. |
| `tests/test_keyboards.py` | Candidate buttons and callback data parsing. |
| `tests/test_pipeline.py` | Download, convert and tag pipeline plus work-dir cleanup and progress reporting. |
| `tests/test_jobs.py` | Job runner: progress edits, per-user serialization, global concurrency cap, and delivery errors. |
| `tests/test_handlers.py` | Commands, search, result selection, job dispatch, authorization, and the error handler. |

```bash
pip install -r requirements-dev.txt
pytest
```

Or inside the Docker image:

```bash
docker run --rm -v "$PWD:/src" -w /src listen-the-video:latest \
  sh -c "pip install -q -r requirements-dev.txt && pytest"
```

---

## Future Improvements

Ideas not yet scheduled. The ones under active planning live in
[docs/FEATURE_PLAN.md](docs/FEATURE_PLAN.md).

### Features

- **Album / playlist batch mode**: given a Spotify album or playlist link, resolve
  every track and deliver them as a ZIP (or sequentially), respecting the 50 MB
  Telegram upload cap per file.
- **Selectable output quality and formats**: choose the bitrate and container at
  request time (MP3 320/128, FLAC, M4A), and rank YouTube candidates by
  "official audio / highest views" so the top match is more often correct.
- **Natural-language input**: parse free-form requests ("the live version of X
  from 2019") with an LLM to drive resolution and disambiguation, collapsing the
  manual pick-a-match flow into a single message.
- **Album/group inference**: use the LLM (or Deezer album data) to auto-fill
  album artist and sort order, especially useful for batch downloads.

### Multi-user and scale

- **Multi-user support**: replace the single `ALLOWED_USER_ID` with an allow-list
  (or a `USERS` table) plus per-user rate limiting. Prerequisite for the items
  below.
- **Persistent library and history**: store built tracks per user to enable
  `/history`, `/redownload`, and de-duplication by returning a cached file.
- **Structured job storage**: move in-memory `user_data` state to a small SQLite
  store so in-flight selections survive restarts.

### Operations and robustness

- **Observability**: structured JSON logging with a job id threaded through
  resolver → search → pipeline, plus counters and per-stage timings.
- **Automatic yt-dlp updates**: `yt-dlp` requires frequent updates; run a
  scheduled update (or an admin `/reload`) so extraction does not quietly rot.
- **Limits and abuse protection**: per-user daily quota, rejection of over-long
  tracks/playlists *before* download, and a pre-conversion size check when a
  track would exceed the Telegram cap.
