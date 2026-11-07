from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from typing import Any, Protocol


class _PendingRedis(Protocol):
    """The slice of the async Redis client the pending store relies on."""

    async def set(self, name: str, value: str, **kwargs: Any) -> Any: ...

    async def getdel(self, name: str) -> Any: ...


PENDING_KEY_PREFIX = "tytel:pending-quality"
# Callback data is limited to 64 bytes by Telegram; a 12-hex-char token
# plus the "tyq:<token>:<height>" framing stays well under that limit.
_TOKEN_BYTES = 6


@dataclass(frozen=True, slots=True)
class PendingDownload:
    """A link waiting for its sender to pick a video quality."""

    chat_id: int
    message_id: int  # Original link message; the download replies to it.
    user_id: int  # Only this user may pick the quality.
    url: str  # Already normalized by core.url_utils.
    max_duration: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str | bytes) -> "PendingDownload | None":
        try:
            data = json.loads(raw)
            return cls(
                chat_id=int(data["chat_id"]),
                message_id=int(data["message_id"]),
                user_id=int(data["user_id"]),
                url=str(data["url"]),
                max_duration=int(data["max_duration"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _key(token: str) -> str:
    return f"{PENDING_KEY_PREFIX}:{token}"


async def store_pending_download(
    redis: _PendingRedis, pending: PendingDownload, *, ttl_seconds: int
) -> str:
    """Store ``pending`` under a fresh random token and return the token."""

    for _ in range(3):
        token = secrets.token_hex(_TOKEN_BYTES)
        # nx=True: never overwrite someone else's pending request on the
        # (astronomically unlikely) token collision; just mint a new one.
        stored = await redis.set(
            _key(token), pending.to_json(), ex=ttl_seconds, nx=True
        )
        if stored:
            return token
    raise RuntimeError("could not allocate a pending-download token")


async def claim_pending_download(
    redis: _PendingRedis, token: str
) -> PendingDownload | None:
    """Atomically read and delete a pending request (one-shot selection).

    GETDEL makes a double tap, or a tap racing the TTL, resolve to exactly
    one download: every later claim for the same token returns None.
    """

    if not token or not all(char in "0123456789abcdef" for char in token):
        return None
    raw = await redis.getdel(_key(token))
    if raw is None:
        return None
    return PendingDownload.from_json(raw)
