# tyTel

A multi-group Telegram bot that replies with media from YouTube and Instagram links. The polling bot validates and queues links; separate `arq` workers download, compress, upload, and cache them. All user-facing responses are in Persian.

## Features

- YouTube videos, Shorts, embeds and live-page URLs (live broadcasts are rejected), plus Instagram posts, reels, TV and stories supported by yt-dlp.
- Strict domain allowlist, URL normalization, `noplaylist`, a 10-minute default duration limit, and 720p maximum video format.
- Redis queue, per-URL download locks, fixed-window per-user rate limiting (5 links/minute), and optional per-group limiting.
- SQLite cache keyed by normalized URL and quality, with Telegram `file_id` reuse.
- Per-group enable/disable, maximum duration, and audio-only settings.
- At most two retries after the initial attempt, with exponential backoff and Persian error replies.
- Temporary files are removed in a worker `finally` block.
- Structured JSON logs and graceful bot/worker shutdown.

## Quick start with Docker Compose

### 1. Configure Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. In BotFather, run `/setprivacy`, select the bot, and choose **Disable**. Group privacy must be disabled so the bot can see ordinary group messages containing links.
3. Add the bot to each group. It needs permission to read messages and send messages/videos/audio. Only group administrators can change tyTel settings.

### 2. Configure the application

```bash
cp .env.example .env
# Set BOT_TOKEN in .env. Create an empty cookie file even if cookies are not used.
touch cookies.txt
```

`cookies.txt`, `.env`, downloaded media, and the SQLite database are ignored by Git. For Instagram authentication, export a **Netscape-format** cookie file from your own browser session to `./cookies.txt`. Compose mounts it read-only at `/app/cookies/cookies.txt`; it is never committed or deliberately logged. Set `PROXY_URL` if yt-dlp needs a proxy.

### 3. Start

```bash
docker compose up --build -d
docker compose logs -f bot worker
```

The bot and worker upgrade yt-dlp when their containers start. The worker also runs an upgrade through an `arq` cron job every day at 00:00. Stop with:

```bash
docker compose down
```

The `app-data` volume retains cache and group settings. Redis uses append-only persistence for queued jobs and counters.

## Group commands

| Command | Who | Effect |
|---|---|---|
| `/enable` | Group admins | Enable link processing (groups are enabled by default). |
| `/disable` | Group admins | Ignore links until re-enabled. |
| `/settings` | Anyone in the group | Show current settings and command syntax. |
| `/settings duration 300` | Group admins | Set maximum duration in seconds (30 up to the global limit). |
| `/settings audio on` | Group admins | Download and cache MP3 audio only. |
| `/settings audio off` | Group admins | Restore video mode. |

Audio and video use separate cache entries. A group's duration can lower, but not raise, the global `MAX_DURATION_SECONDS` safety limit.

## Configuration

All settings come from `.env`; see `.env.example`.

| Variable | Default | Description |
|---|---:|---|
| `BOT_TOKEN` | required | BotFather token. |
| `WORKER_CONCURRENCY` | `2` | Maximum concurrent arq jobs per worker. |
| `USER_RATE_LIMIT` | `5` | Valid links per user per fixed clock minute. |
| `GROUP_RATE_LIMIT` | `0` | Links per group per minute; `0` disables this limit. |
| `MAX_DURATION_SECONDS` | `600` | Global maximum media duration. |
| `MAX_FILE_SIZE_MB` | automatic | Overrides the upload/output limit when set. |
| `LOCAL_BOT_API_URL` | empty | Local Bot API base URL; raises the default limit from 50 MB to 2000 MB. |
| `COOKIES_PATH` | `./cookies.txt` | Host cookie-file path for Compose. Outside Docker, it is the yt-dlp cookie path. |
| `PROXY_URL` | empty | Optional proxy passed directly to yt-dlp. |
| `JOB_TIMEOUT_SECONDS` | `1800` | Maximum arq job runtime. |
| `DEDUP_LOCK_TIMEOUT_SECONDS` | `1800` | Redis lock lifetime for one normalized URL. |

With the hosted Telegram Bot API, files above 50 MB are compressed with ffmpeg. Audio is reduced to 96 kbps; oversized video is encoded with H.264/AAC at 720p and, if necessary, 480p. Media that still exceeds the limit receives a Persian error instead of an upload attempt.

### Optional local Telegram Bot API (2 GB)

Set credentials from your Telegram API application and the local server URL in `.env`:

```dotenv
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_api_hash
LOCAL_BOT_API_URL=http://telegram-bot-api:8081
```

Start the optional profile:

```bash
docker compose --profile local-bot-api up --build -d
```

Use 2000 MB only with a local server started using `--local`, as in the supplied Compose file. Keep the API ID and hash secret.

## Running without Docker

Python 3.12, ffmpeg, ffprobe, and Redis are required:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install --upgrade yt-dlp
cp .env.example .env
# Set BOT_TOKEN and local paths such as REDIS_URL=redis://localhost:6379/0,
# DATABASE_PATH=./data/tytel.db and TEMP_DIR=./data/tmp.
python -m bot.main
# In another shell, with the same environment:
arq worker.settings.WorkerSettings
```

The non-Docker worker's daily cron performs subsequent yt-dlp updates; run the upgrade command yourself whenever restarting outside Docker.

## Tests

No additional test framework is required:

```bash
python -m unittest discover -v
```

Tests cover YouTube/Instagram extraction and normalization, domain rejection, duration/playlist limits, cookie/proxy options, SQLite cache and group settings, worker cache hits, and user/group rate limiting. Live Telegram and media-site integration require valid credentials, ffmpeg, network access to those services, and are therefore not part of the unit suite.

## Architecture

```text
Telegram groups -> bot (long polling)
                      | validate, settings, rate limit, cache lookup
                      v
                    Redis <---- per-URL locks / retry metadata
                      |
                      v
               arq worker(s) -> yt-dlp -> ffmpeg (if needed) -> Telegram
                      |                                      |
                      +---------- SQLite file_id cache <-----+
```

Only the worker calls yt-dlp or ffmpeg. The bot never downloads media.
