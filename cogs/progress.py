"""Reading progress commands. Tracks per-user page/chapter for the current book."""
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db

log = logging.getLogger("bookclub.cogs.progress")


async def _get_current_book(guild_id: int) -> Optional[dict]:
    """Return the current book row for a guild, or None if not set."""
    async with db.pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT b.id, b.title, b.page_count
            FROM current_books cb
            JOIN books b ON b.id = cb.book_id
            WHERE cb.guild_id = $1
            """,
            guild_id,
        )
    return dict(row) if row else None


class Progress(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    progress_group = app_commands.Group(name="progress", description="Reading progress commands.")

    @progress_group.command(name="update", description="Update your progress on the current book.")
    @app_commands.describe(
        chapter="Chapter number you're currently on.",
        page="Page number you're currently on (optional).",
    )
    async def update(
        self,
        interaction: discord.Interaction,
        chapter: int,
        page: Optional[int] = None,
    ) -> None:
        """Upsert the user's progress row for the current book."""
        await interaction.response.defer(ephemeral=True)

        if chapter < 0 or (page is not None and page < 0):
            await interaction.followup.send("Chapter and page must be non-negative.")
            return

        book = await _get_current_book(interaction.guild_id)
        if not book:
            await interaction.followup.send("No current book set. Run a poll first.")
            return

        if book["page_count"] and page and page > book["page_count"]:
            await interaction.followup.send(
                f"Page {page} is beyond the book's {book['page_count']} pages. Double-check?"
            )
            return

        async with db.pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO reading_progress (guild_id, user_id, book_id, current_chapter, current_page)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (guild_id, user_id, book_id) DO UPDATE
                  SET current_chapter = EXCLUDED.current_chapter,
                      current_page = EXCLUDED.current_page,
                      updated_at = NOW()
                """,
                interaction.guild_id, interaction.user.id, book["id"], chapter, page,
            )

        await db.log_event(
            event_name="progress_update",
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            metadata={"book_id": book["id"], "chapter": chapter, "page": page},
        )

        page_str = f", page {page}" if page else ""
        await interaction.followup.send(
            f"Updated: chapter {chapter}{page_str} of **{book['title']}**."
        )

    @progress_group.command(name="show", description="Show everyone's progress on the current book.")
    async def show(self, interaction: discord.Interaction) -> None:
        """List all users' progress on the current book, sorted by chapter desc."""
        await interaction.response.defer()

        book = await _get_current_book(interaction.guild_id)
        if not book:
            await interaction.followup.send("No current book set.")
            return

        async with db.pool().acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id, current_chapter, current_page, updated_at
                FROM reading_progress
                WHERE guild_id = $1 AND book_id = $2
                ORDER BY current_chapter DESC NULLS LAST, current_page DESC NULLS LAST
                """,
                interaction.guild_id, book["id"],
            )

        if not rows:
            await interaction.followup.send(
                f"No progress logged yet for **{book['title']}**. Update with `/progress update`."
            )
            return

        lines = [f"**Progress on {book['title']}**"]
        for r in rows:
            # Resolve user mention; fall back to ID if user left the guild.
            user = interaction.guild.get_member(r["user_id"])
            name = user.display_name if user else f"User {r['user_id']}"
            page_str = f", p.{r['current_page']}" if r["current_page"] else ""
            lines.append(f"- {name}: ch. {r['current_chapter']}{page_str}")
        await interaction.followup.send("\n".join(lines))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Progress(bot))
