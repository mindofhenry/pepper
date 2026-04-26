"""Reading section commands. Sections are group reading assignments with a
dedicated discussion thread. One active section per guild at a time."""
import logging
import json
from services import anthropic_client
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db

log = logging.getLogger("bookclub.cogs.sections")


def _format_section_label(end_chapter: Optional[int], end_page: Optional[int]) -> str:
    """Build a human-readable label for a section based on which endpoints are set."""
    if end_chapter is not None and end_page is not None:
        return f"through ch. {end_chapter} (p. {end_page})"
    if end_chapter is not None:
        return f"through ch. {end_chapter}"
    return f"through p. {end_page}"


class Sections(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    section_group = app_commands.Group(name="section", description="Reading section commands.")

    @section_group.command(name="new", description="Open a new reading section and create its thread.")
    @app_commands.describe(
        end_chapter="Chapter to read through (optional if end_page is set).",
        end_page="Page to read through (optional if end_chapter is set).",
    )
    async def new_section(
        self,
        interaction: discord.Interaction,
        end_chapter: Optional[int] = None,
        end_page: Optional[int] = None,
    ) -> None:
        """Create a new active section. Requires at least one of end_chapter / end_page."""
        await interaction.response.defer()

        if end_chapter is None and end_page is None:
            await interaction.followup.send("Provide at least one of `end_chapter` or `end_page`.")
            return
        if (end_chapter is not None and end_chapter < 1) or (end_page is not None and end_page < 1):
            await interaction.followup.send("Chapter and page must be positive.")
            return

        async with db.pool().acquire() as conn:
            # Guard: one active section per guild.
            existing = await conn.fetchval(
                "SELECT id FROM reading_sections WHERE guild_id = $1 AND status = 'active'",
                interaction.guild_id,
            )
            if existing:
                await interaction.followup.send(
                    f"Section #{existing} is already active. Close it with `/section close` first."
                )
                return

            # Need the current book to attach the section to.
            book = await conn.fetchrow(
                """
                SELECT b.id, b.title FROM current_books cb
                JOIN books b ON b.id = cb.book_id
                WHERE cb.guild_id = $1
                """,
                interaction.guild_id,
            )
            if not book:
                await interaction.followup.send("No current book set. Run a poll first.")
                return

        label = _format_section_label(end_chapter, end_page)
        thread_name = f"{book['title']}: {label}"[:100]  # Discord caps thread name at 100 chars.

        # Create the thread off the channel the command was invoked in.
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("Run `/section new` in a regular text channel.")
            return

        try:
            thread = await channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.public_thread,
                auto_archive_duration=10080,  # 7 days; max without Nitro.
            )
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to create threads here.")
            return

        async with db.pool().acquire() as conn:
            section_id = await conn.fetchval(
                """
                INSERT INTO reading_sections
                  (guild_id, book_id, end_chapter, end_page, thread_id, created_by)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                interaction.guild_id, book["id"], end_chapter, end_page, thread.id, interaction.user.id,
            )

        await db.log_event(
            event_name="section_new",
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            metadata={
                "section_id": section_id, "book_id": book["id"],
                "end_chapter": end_chapter, "end_page": end_page, "thread_id": thread.id,
            },
        )

        await thread.send(
            f"Reading section #{section_id} for **{book['title']}**: {label}.\n"
            f"Discuss here. Run `/section prompts` in this channel if you want AI-generated discussion starters."
        )
        await interaction.followup.send(f"Section #{section_id} opened: {thread.mention}")

    @section_group.command(name="current", description="Show the active section for this server.")
    async def current(self, interaction: discord.Interaction) -> None:
        """Display the currently active section, if any."""
        async with db.pool().acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT s.id, s.end_chapter, s.end_page, s.thread_id, s.created_at, b.title
                FROM reading_sections s
                JOIN books b ON b.id = s.book_id
                WHERE s.guild_id = $1 AND s.status = 'active'
                """,
                interaction.guild_id,
            )
        if not row:
            await interaction.response.send_message("No active section.")
            return

        label = _format_section_label(row["end_chapter"], row["end_page"])
        thread = self.bot.get_channel(row["thread_id"])
        thread_mention = thread.mention if thread else f"(thread id {row['thread_id']})"
        await interaction.response.send_message(
            f"Active section #{row['id']}: **{row['title']}** {label}\nThread: {thread_mention}"
        )

    @section_group.command(name="close", description="Close the active section (usually after a meeting).")
    async def close(self, interaction: discord.Interaction) -> None:
        """Mark the active section closed and archive its thread."""
        await interaction.response.defer()

        async with db.pool().acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE reading_sections
                SET status = 'closed', closed_at = NOW()
                WHERE guild_id = $1 AND status = 'active'
                RETURNING id, thread_id, end_chapter, end_page
                """,
                interaction.guild_id,
            )
        if not row:
            await interaction.followup.send("No active section to close.")
            return

        # Best-effort: archive the thread. Don't fail if Discord refuses.
        thread = self.bot.get_channel(row["thread_id"])
        if isinstance(thread, discord.Thread):
            try:
                await thread.edit(archived=True, locked=False)
            except discord.HTTPException:
                log.warning("Couldn't archive thread %s", row["thread_id"])

        await db.log_event(
            event_name="section_closed",
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            metadata={"section_id": row["id"]},
        )
        label = _format_section_label(row["end_chapter"], row["end_page"])
        await interaction.followup.send(f"Section #{row['id']} ({label}) closed.")


    @section_group.command(name="prompts", description="Generate AI discussion prompts for the active section.")
    async def prompts(self, interaction: discord.Interaction) -> None:
        """Return 4 Haiku-generated discussion prompts. Cached per (book, endpoints)."""
        await interaction.response.defer()

        async with db.pool().acquire() as conn:
            section = await conn.fetchrow(
                """
                SELECT s.id, s.book_id, s.end_chapter, s.end_page,
                       b.title, b.authors
                FROM reading_sections s
                JOIN books b ON b.id = s.book_id
                WHERE s.guild_id = $1 AND s.status = 'active'
                """,
                interaction.guild_id,
            )
        if not section:
            await interaction.followup.send("No active section. Run `/section new` first.")
            return

        # Cache lookup. end_chapter/end_page may be NULL; NULL = NULL is false in SQL,
        # so use IS NOT DISTINCT FROM for proper NULL-aware equality.
        async with db.pool().acquire() as conn:
            cached = await conn.fetchrow(
                """
                SELECT prompts_json, generated_at FROM discussion_prompts
                WHERE book_id = $1
                  AND end_chapter IS NOT DISTINCT FROM $2
                  AND end_page IS NOT DISTINCT FROM $3
                """,
                section["book_id"], section["end_chapter"], section["end_page"],
            )

        if cached:
            prompts_list = cached["prompts_json"]
            cache_status = "cached"
        else:
            prompts_list = await anthropic_client.generate_discussion_prompts(
                title=section["title"],
                authors=section["authors"],
                end_chapter=section["end_chapter"],
                end_page=section["end_page"],
            )
            if not prompts_list:
                await interaction.followup.send("Couldn't generate prompts. Try again in a minute.")
                return
            async with db.pool().acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO discussion_prompts (book_id, end_chapter, end_page, prompts_json)
                    VALUES ($1, $2, $3, $4::jsonb)
                    ON CONFLICT (book_id, end_chapter, end_page) DO NOTHING
                    """,
                    section["book_id"], section["end_chapter"], section["end_page"],
                    json.dumps(prompts_list),
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

        lines = [f"**Discussion prompts for {section['title']}** ({cache_status})\n"]
        for i, p in enumerate(prompts_list, 1):
            lines.append(f"{i}. {p}")
        await interaction.followup.send("\n".join(lines))

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Sections(bot))
