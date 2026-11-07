from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
BOT_TOKEN_RE = re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{20,}\b")
AUTHORIZATION_RE = re.compile(
    r"(?i)\bAuthorization\s*:\s*(?:Bearer\s+[^\s,;]+|[^\s,;]+)"
)
COOKIE_HEADER_RE = re.compile(
    r"(?i)\bCookie\s*:\s*[^\s;]+=[^\s;]*(?:;\s*[^\s;]+=[^\s;]*)*"
)
SECRET_FIELD_RE = re.compile(
    r"(?i)\b(token|access[_-]?token|api[_-]?(?:key|hash|secret)|session(?:id|token)|"
    r"password|cookiefile)(\s*[=:]\s*)([^\s,;&]+)"
)
COOKIE_VALUE_RE = re.compile(
    r"(?i)\b(SID|HSID|SSID|APISID|SAPISID|SIDCC|__Secure-[A-Z0-9]+)="
    r"([^\s;,&]+)"
)
COOKIE_PATH_RE = re.compile(
    r"(?i)(?:[\w./\\-]*\.yt-dlp-cookies\.txt|[\w./\\-]*cookies?\.txt)"
)


def _sanitize_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    trailing = ""
    while raw and raw[-1] in ".,!?;:،؛)":
        trailing = raw[-1] + trailing
        raw = raw[:-1]
    try:
        parsed = urlsplit(raw)
        query = ""
        values = parse_qs(parsed.query).get("v")
        if values and values[0]:
            query = urlencode({"v": values[0]})
        netloc = parsed.hostname or ""
        if parsed.port:
            netloc += f":{parsed.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, query, "")) + trailing
    except (ValueError, UnicodeError):
        return "[redacted-url]"


def sanitize_message(message: object, sensitive_values: Iterable[object] = ()) -> str:
    """Redact credentials, cookies, sensitive paths, and non-video URL queries."""

    text = str(message)
    for value in sensitive_values:
        if value is None:
            continue
        sensitive = str(value)
        if sensitive:
            text = text.replace(sensitive, "[redacted]")
    text = URL_RE.sub(_sanitize_url, text)
    text = AUTHORIZATION_RE.sub("Authorization: [redacted]", text)
    text = COOKIE_HEADER_RE.sub("Cookie: [redacted]", text)
    text = COOKIE_VALUE_RE.sub(
        lambda match: f"{match.group(1)}=[redacted-cookie]", text
    )
    text = SECRET_FIELD_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[redacted]", text
    )
    text = BOT_TOKEN_RE.sub("[redacted-token]", text)
    text = COOKIE_PATH_RE.sub("[redacted-cookie-path]", text)
    return text


def settings_secrets(values: Iterable[object]) -> tuple[str, ...]:
    """Normalize optional settings for redaction without exposing their values."""

    return tuple(str(value) for value in values if value is not None and str(value))
