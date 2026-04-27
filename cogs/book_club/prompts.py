"""Implementation of /section prompts. Lives in its own module (per MIN-54)
so that sections.py stays focused on section lifecycle. The command itself
is registered on the Sections cog's `section_group` over in sections.py;
this module provides the heavy lifting it delegates to.

Includes the MIN-28 fix: prompts are sent as a header message followed by
one message per prompt, never a single message that could exceed Discord's
2000-character limit.
"""
import json
import logging
from typing import Optional

import discord

from shared import db
from services import anthropic_client

log = logging.getLogger("pepper.cogs.book_club.prompts")

# Discord's hard cap is 2000 chars per message. Leave headroom for the
# numbering prefix ("99. ") and any future tweaks; chunk if a single prompt
# overshoots this.
_MAX_MESSAGE_CHARS = 1900


async def _fetch_active_section(guild_id: int) -> Optional[dict]:
    """Return the active section row joined with its book, or None."""
    async with db.pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.id, s.book_id, s.end_chapter, s.end_page,
                   b.title, b.authors
            FROM reading_sections s
            JOIN books b ON b.id = s.book_id
            WHERE s.guild_id = $1 AND s.status = 'active'
            """,
            guild_id,
        )
    return dict(row) if row else None


async def _fetch_cached_prompts(
    book_id: int, end_chapter: Optional[int], end_page: Optional[int]
) -> Optional[list[str]]:
    """Look up cached prompts. NULL-aware match on end_chapter / end_page."""
    async with db.pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT prompts_json FROM discussion_prompts
            WHERE book_id = $1
              AND end_chapter IS NOT DISTINCT FROM $2
              AND end_page IS NOT DISTINCT FROM $3
            """,
            book_id, end_chapter, end_page,
        )
    return list(row["prompts_json"]) if row else None


async def _store_prompts(
    book_id: int,
    end_chapter: Optional[int],
    end_page: Optional[int],
    prompts: list[str],
) -> None:
    """Cache generated prompts. ON CONFLICT DO NOTHING handles concurrent inserts."""
    async with db.pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO discussion_prompts (book_id, end_chapter, end_page, prompts_json)
            VALUES ($1, $2, $3, $4::jsonb)
            ON CONFLICT (book_id, end_chapter, end_page) DO NOTHING
            """,
            book_id, end_chapter, end_page, json.dumps(prompts),
        )


def _chunk_prompt_text(text: str) -> list[str]:
    """Split a single prompt body if it would exceed the 2000 char Discord cap.
    99% of Haiku prompts fit in one message, but we chunk defensively so MIN-28
    can never regress. Splits on whitespace boundaries when possible."""
    if len(text) <= _MAX_MESSAGE_CHARS:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > _MAX_MESSAGE_CHARS:
        cut = remaining.rfind(" ", 0, _MAX_MESSAGE_CHARS)
        if cut <= 0:
            cut = _MAX_MESSAGE_CHARS
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def generate_and_send(
    interaction: discord.Interaction,
) -> None:
    """Full /section prompts flow: locate active section, hit cache or call
    Haiku, persist, then dispatch as one header message + one message per prompt."""
    section = await _fetch_active_section(interaction.guild_id)
    if not section:
        await interaction.followup.send("No active section. Run `/section new` first.")
        return

    prompts_list = await _fetch_cached_prompts(
        section["book_id"], section["end_chapter"], section["end_page"]
    )
    cache_status = "cached"

    if prompts_list is None:
        prompts_list = await anthropic_client.generate_discussion_prompts(
            title=section["title"],
            authors=section["authors"],
            end_chapter=section["end_chapter"],
            end_page=section["end_page"],
        )
        if not prompts_list:
            await interaction.followup.send("Couldn't generate prompts. Try again in a minute.")
            return
        await _store_prompts(
            section["book_id"], section["end_chapter"], section["end_page"], prompts_list
        )
        cache_status = "generated"

    await db.log_event(
        event_name="section_prompts",
        user_id=interaction.user.id,
        guild_id=interaction.guild_id,
        metadata={
            "section_id": section["id"], "book_id": section["book_id"],
            "cache_status": cache_status, "prompt_count": len(prompts_list),
        },
    )

    # MIN-28: header first, then one message per prompt. Never combine.
    await interaction.followup.send(
        f"**Discussion prompts for {section['title']}** ({cache_status})"
    )
    for i, prompt in enumerate(prompts_list, 1):
        body = f"{i}. {prompt}"
        for chunk in _chunk_prompt_text(body):
            await interaction.followup.send(chunk)
