# tyTel

A multi-group Telegram bot that replies with media from YouTube and Instagram links. The polling bot validates and queues links; separate `arq` workers download, compress, upload, and cache them. All user-facing responses are in Persian.

## Features

- YouTube videos, Shorts, embeds and live-page URLs (live broadcasts are rejected), plus Instagram posts, reels, TV and stories supported by yt-dlp.
- Strict domain allowlist, URL normalization, `noplaylist`, a 10-minute default duration limit, and 720p maximum video format.
- Redis queue, per-URL download locks, fixed-window per-user rate limiting (5 links/minute), and optional per-group limiting.
- SQLite cache keyed by normalized URL and quality, with Telegram `file_id` reuse.
- Per-group enable/disable, maximum duration, and audio-only settings.
- At most two retries after the initial attempt, with exponential backoff only for transient network, server, ffmpeg, or Telegram failures. Authentication, private/unavailable, restricted, unsupported, oversized, and permission failures stop immediately.
- Temporary files are removed in a worker `finally` block. yt-dlp writes only to a per-job mode-600 cookie copy; the mounted source stays read-only.
- Deno and `yt-dlp[default]` (including the JavaScript challenge solver) are installed in the worker image.
- Structured, sanitized JSON logs, actionable startup self-checks, and graceful bot/worker shutdown.

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

`cookies.txt`, `.env`, downloaded media, and the SQLite database are ignored by Git. Compose mounts the source read-only at `/app/cookies/cookies.txt`. For every job, the worker copies it into the job directory with mode 600 and gives that writable copy to yt-dlp; the existing job cleanup deletes it. Cookie contents and paths are redacted from logs.

The non-root container user is UID/GID `10001`. Make the bind-mounted file readable without making it writable by that user:

```bash
sudo chown 10001:10001 cookies.txt
sudo chmod 600 cookies.txt
```

For YouTube authentication, use a **separate Google account**, not your primary account. Open a Private/Incognito window, sign in to YouTube, visit `https://youtube.com/robots.txt`, then export a **Netscape-format** cookie file from that window to `./cookies.txt`. Close the Private window immediately after exporting. The same file can also support Instagram when valid Instagram cookies are present. Set `PROXY_URL` if yt-dlp needs a proxy.

### 3. Start

```bash
docker compose up --build -d
docker compose logs -f bot worker
```

The bot and worker upgrade `yt-dlp[default]` when their containers start. The worker also runs an upgrade through an `arq` cron job every day at 00:00. Deno is copied into the image, so no separate Deno container or host installation is needed. At worker startup, JSON logs report the yt-dlp version, Deno/ffmpeg/ffprobe availability, and cookie-file header status; missing components produce warnings with fix hints but do not prevent startup. Stop with:

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
| `ADMIN_CHAT_ID` | empty | Private chat/user ID for a cookie-expiry warning, rate limited to one message per hour. |
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

Python 3.12, Deno, ffmpeg, ffprobe, and Redis are required. Deno must be on `PATH` for YouTube's JavaScript challenges:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install --upgrade 'yt-dlp[default]'
cp .env.example .env
# Set BOT_TOKEN and local paths such as REDIS_URL=redis://localhost:6379/0,
# DATABASE_PATH=./data/tytel.db and TEMP_DIR=./data/tmp.
python -m bot.main
# In another shell, with the same environment:
arq worker.settings.WorkerSettings
```

The non-Docker worker's daily cron performs subsequent yt-dlp updates; run the upgrade command yourself whenever restarting outside Docker.

## Troubleshooting

### Bot does not see links in a group

Open BotFather, run `/setprivacy`, select the bot, and choose **Disable**. Remove and re-add the bot if Telegram does not apply the changed privacy mode to an existing group. Also confirm that `/enable` has been run and that the bot can read group messages.

### `Sign in to confirm you're not a bot`

YouTube is rejecting the current anonymous/authenticated session. This is not retried. The group receives a generic temporary-service message; if `ADMIN_CHAT_ID` is set, the admin receives at most one private warning per hour that cookies may have expired. Re-export fresh Netscape cookies using the Private-window procedure above, replace `cookies.txt`, and recreate the worker. Cookie expiry can also appear as missing formats or repeated sign-in requirements.

### `No supported JavaScript runtime`

Deno is missing or not on the worker's `PATH`. Rebuild the supplied image so the `COPY --from=denoland/deno:bin` step runs, and ensure upgrades install `yt-dlp[default]`, not bare `yt-dlp`. Check the worker startup self-check. To inspect formats manually with a writable copy of the cookies:

```bash
docker compose exec worker sh -c \
  'cp "$COOKIES_PATH" /tmp/check-cookies.txt && chmod 600 /tmp/check-cookies.txt && yt-dlp --cookies /tmp/check-cookies.txt -v -F "https://www.youtube.com/watch?v=VIDEO_ID"; status=$?; rm -f /tmp/check-cookies.txt; exit $status'
```

The verbose yt-dlp output should list Deno among its JavaScript runtimes and show real formats.

### `does not look like a Netscape format cookies file`

The file has the wrong format, is empty, or does not begin with `# Netscape HTTP Cookie File` or `# HTTP Cookie File`. Export actual browser cookies in Netscape format rather than copying JSON or a browser's internal SQLite database. Check the startup cookie warning, then fix the export and file permissions.

### Read-only cookie errors or permission failures

Do not remove `:ro` from the Compose mount. Current workers never give the mounted source to yt-dlp; they use a per-job writable copy. Ensure the source is readable by UID `10001`, `/data` is writable, and rebuild/recreate both services. Permission and read-only filesystem errors are deliberately not retried.

## Tests

No additional test framework is required:

```bash
python -m unittest discover -v
```

Tests cover YouTube/Instagram extraction and normalization, domain rejection, duration/playlist limits, read-only cookie copying and cleanup, log sanitization, retry classification, startup self-checks, admin alerts, SQLite cache and group settings, worker cache hits, and user/group rate limiting. Live Telegram and media-site integration require valid credentials, ffmpeg, network access to those services, and are therefore not part of the unit suite.

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
