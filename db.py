"""Postgres access layer. Owns the asyncpg connection pool and provides
helpers for common operations. All DB access in the bot goes through here."""
import json
import logging
from typing import Any, Optional

import asyncpg

import config

log = logging.getLogger("bookclub.db")

_pool: Optional[asyncpg.Pool] = None


async def init_pool() -> asyncpg.Pool:
    """Create the connection pool. Call once on bot startup."""
    global _pool
    if _pool is not None:
        return _pool
    _pool = await asyncpg.create_pool(
        config.DATABASE_URL,
        min_size=1,
        max_size=5,
        # Neon free tier sleeps inactive connections; keep pool small.
    )
    log.info("Database pool initialized")
    return _pool


async def close_pool() -> None:
    """Close the pool on bot shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    """Return the initialized pool. Raises if init_pool wasn't called."""
    if _pool is None:
        raise RuntimeError("DB pool not initialized. Call init_pool() first.")
    return _pool


async def log_event(
    event_name: str,
    user_id: Optional[int] = None,
    guild_id: Optional[int] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Insert a row into the events table. Never raises; logs on failure
    so instrumentation bugs can't crash a slash command."""
    try:
        async with pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO events (event_name, user_id, guild_id, metadata_json)
                VALUES ($1, $2, $3, $4::jsonb)
                """,
                event_name,
                user_id,
                guild_id,
                json.dumps(metadata or {}),
            )
    except Exception:
        log.exception("Failed to log event %r", event_name)

async def upsert_book(
    google_id: str,
    title: str,
    authors: list[str],
    page_count: int | None = None,
    thumbnail_url: str | None = None,
    info_link: str | None = None,
) -> int:
    """Insert a book or return existing id. Returns books.id."""
    async with pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO books (google_id, title, authors, page_count, thumbnail_url, info_link)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (google_id) DO UPDATE SET title = EXCLUDED.title
            RETURNING id
            """,
            google_id, title, authors, page_count, thumbnail_url, info_link,
        )
        return row["id"]
