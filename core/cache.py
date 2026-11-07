from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import aiosqlite


@dataclass(frozen=True, slots=True)
class CacheEntry:
    file_id: str
    media_type: str


@dataclass(frozen=True, slots=True)
class GroupSettings:
    chat_id: int
    enabled: bool = True
    max_duration: int | None = None


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = await aiosqlite.connect(self.path, timeout=30)
        connection.row_factory = aiosqlite.Row
        try:
            await connection.execute("PRAGMA foreign_keys=ON")
            await connection.execute("PRAGMA busy_timeout=30000")
            yield connection
        finally:
            await connection.close()

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as connection:
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS media_cache (
                    normalized_url TEXT NOT NULL,
                    quality TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (normalized_url, quality)
                );

                -- Audio is a per-link choice now, not a group setting.
                -- Databases created by older versions may still carry an
                -- audio_only column; it is ignored and harmless.
                CREATE TABLE IF NOT EXISTS group_settings (
                    chat_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    max_duration INTEGER
                );
                """
            )
            await connection.commit()

    async def get_cached(self, normalized_url: str, quality: str) -> CacheEntry | None:
        async with self.connect() as connection:
            cursor = await connection.execute(
                "SELECT file_id, media_type FROM media_cache "
                "WHERE normalized_url=? AND quality=?",
                (normalized_url, quality),
            )
            row = await cursor.fetchone()
        return CacheEntry(row["file_id"], row["media_type"]) if row else None

    async def store_cached(
        self, normalized_url: str, quality: str, file_id: str, media_type: str
    ) -> None:
        async with self.connect() as connection:
            await connection.execute(
                """
                INSERT INTO media_cache (normalized_url, quality, file_id, media_type)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(normalized_url, quality) DO UPDATE SET
                    file_id=excluded.file_id,
                    media_type=excluded.media_type,
                    created_at=CURRENT_TIMESTAMP
                """,
                (normalized_url, quality, file_id, media_type),
            )
            await connection.commit()

    async def delete_cached(self, normalized_url: str, quality: str) -> None:
        async with self.connect() as connection:
            await connection.execute(
                "DELETE FROM media_cache WHERE normalized_url=? AND quality=?",
                (normalized_url, quality),
            )
            await connection.commit()

    async def get_group_settings(self, chat_id: int) -> GroupSettings:
        async with self.connect() as connection:
            cursor = await connection.execute(
                "SELECT chat_id, enabled, max_duration "
                "FROM group_settings WHERE chat_id=?",
                (chat_id,),
            )
            row = await cursor.fetchone()
        if not row:
            return GroupSettings(chat_id=chat_id)
        return GroupSettings(
            chat_id=row["chat_id"],
            enabled=bool(row["enabled"]),
            max_duration=row["max_duration"],
        )

    async def set_group_enabled(self, chat_id: int, enabled: bool) -> None:
        await self._update_group(chat_id, "enabled", int(enabled))

    async def set_group_duration(self, chat_id: int, seconds: int) -> None:
        await self._update_group(chat_id, "max_duration", seconds)

    async def _update_group(self, chat_id: int, field: str, value: int) -> None:
        if field not in {"enabled", "max_duration"}:
            raise ValueError("invalid group setting")
        async with self.connect() as connection:
            await connection.execute(
                f"""
                INSERT INTO group_settings (chat_id, {field}) VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET {field}=excluded.{field}
                """,
                (chat_id, value),
            )
            await connection.commit()
