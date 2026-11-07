from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+", re.IGNORECASE)
MEDIA_URL_RE = re.compile(
    r"https?://[^\s<>()\[\]{}\"']+|"
    r"(?<![\w.-])(?:www\.)?(?:youtube\.com|youtu\.be|instagram\.com)/[^\s<>()\[\]{}\"']+",
    re.IGNORECASE,
)
YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
INSTAGRAM_PATH_RE = re.compile(
    r"^/(?:p|reel|reels|tv|stories)/[^/]+(?:/[^/]+)?/?$", re.IGNORECASE
)
ALLOWED_DOMAINS = frozenset({"youtube.com", "youtu.be", "instagram.com"})
TRAILING_PUNCTUATION = ".,!?;:،؛"

# Video heights (in pixels) the user can pick after sending a link.
# 720 stays the maximum, matching the documented safety/upload cap;
# the lower options trade sharpness for a smaller, faster download.
VIDEO_HEIGHTS: tuple[int, ...] = (720, 480, 360)
DEFAULT_VIDEO_HEIGHT = VIDEO_HEIGHTS[0]
_VIDEO_QUALITY_RE = re.compile(r"^video-(\d+)p$")


def _domain_matches(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def normalize_url(raw_url: str) -> str | None:
    """Return a canonical media URL, or None for unsupported/unsafe URLs."""

    candidate = raw_url.strip().rstrip(TRAILING_PUNCTUATION)
    if not candidate.lower().startswith(("http://", "https://")):
        candidate = f"https://{candidate}"
    try:
        parsed = urlsplit(candidate)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None

        if _domain_matches(hostname, "youtu.be"):
            video_id = parsed.path.strip("/").split("/")[0]
            if not YOUTUBE_ID_RE.fullmatch(video_id):
                return None
            return f"https://www.youtube.com/watch?v={video_id}"

        if _domain_matches(hostname, "youtube.com"):
            path = parsed.path.rstrip("/")
            video_id: str | None = None
            if path == "/watch":
                video_id = parse_qs(parsed.query).get("v", [""])[0]
            else:
                match = re.fullmatch(
                    r"/(?:shorts|embed|live)/([^/]+)", path, re.IGNORECASE
                )
                if match:
                    video_id = match.group(1)
            if not video_id or not YOUTUBE_ID_RE.fullmatch(video_id):
                return None
            return f"https://www.youtube.com/watch?v={video_id}"

        if _domain_matches(hostname, "instagram.com"):
            path = re.sub(r"/{2,}", "/", parsed.path).rstrip("/")
            if not INSTAGRAM_PATH_RE.fullmatch(path + "/"):
                return None
            return urlunsplit(("https", "www.instagram.com", path, "", ""))
    except (ValueError, UnicodeError):
        return None
    return None


def extract_urls(text: str | None) -> list[str]:
    """Extract, validate, normalize, and de-duplicate URLs in message text."""

    if not text:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for match in MEDIA_URL_RE.finditer(text):
        url = normalize_url(match.group(0))
        if url and url not in seen:
            normalized.append(url)
            seen.add(url)
    return normalized


def cache_quality(audio_only: bool, max_height: int | None = None) -> str:
    """Cache key for one quality: each height is cached separately."""

    if audio_only:
        return "audio"
    height = DEFAULT_VIDEO_HEIGHT if max_height is None else max_height
    if height not in VIDEO_HEIGHTS:
        raise ValueError(f"unsupported video height: {height}")
    return f"video-{height}p"


def parse_video_height(quality: str) -> int | None:
    """Return the height encoded in a ``video-<height>p`` quality, or None.

    None is returned for audio, legacy, and malformed quality strings, so
    callers can fall back to DEFAULT_VIDEO_HEIGHT.
    """

    match = _VIDEO_QUALITY_RE.fullmatch(quality or "")
    if not match:
        return None
    height = int(match.group(1))
    return height if height in VIDEO_HEIGHTS else None


def video_format(max_height: int) -> str:
    """yt-dlp format selector capping video at ``max_height`` pixels."""

    if max_height not in VIDEO_HEIGHTS:
        raise ValueError(f"unsupported video height: {max_height}")
    return f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]"
