from __future__ import annotations

from urllib.parse import unquote, urlsplit

from arq.connections import RedisSettings
from redis.asyncio import Redis


def create_redis(url: str) -> Redis:
    return Redis.from_url(url, decode_responses=True)


def arq_redis_settings(url: str) -> RedisSettings:
    parsed = urlsplit(url)
    if parsed.scheme not in {"redis", "rediss"}:
        raise ValueError("REDIS_URL must use redis:// or rediss://")
    try:
        database = int(parsed.path.lstrip("/") or "0")
        port = parsed.port or 6379
    except ValueError as exc:
        raise ValueError("Invalid Redis port or database") from exc
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=port,
        database=database,
        username=unquote(parsed.username) if parsed.username else None,
        password=unquote(parsed.password) if parsed.password else None,
        ssl=parsed.scheme == "rediss",
    )


def lock_key(normalized_url: str) -> str:
    import hashlib

    digest = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
    return f"tytel:download-lock:{digest}"
