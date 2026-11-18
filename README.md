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
2. The bot resolves the track identity (artist + title).
3. If the input is ambiguous, the bot **shows options** for the user to pick from.
4. It searches for and downloads the best available audio on YouTube (`yt-dlp`).
5. It converts the audio to **MP3 320 kbps** (`ffmpeg`).
6. It fetches metadata and cover art (MusicBrainz, Cover Art Archive, Deezer).
7. It writes ID3 tags and embeds the cover art (`mutagen`).
8. It sends the MP3 back to the user in the Telegram chat.

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
| `tests/test_handlers.py` | Commands, message handling, authorization, and the error handler. |

```bash
pip install -r requirements-dev.txt
pytest
```

Or inside the Docker image:

```bash
docker run --rm -v "$PWD:/src" -w /src listen-the-video:latest \
  sh -c "pip install -q -r requirements-dev.txt && pytest"
```
