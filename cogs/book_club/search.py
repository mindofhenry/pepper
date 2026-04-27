"""Book lookup commands. /book search <query> returns Google Books results."""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from shared import db
from shared.errors import report_command_error
from services import google_books

log = logging.getLogger("pepper.cogs.book_club.search")


class Search(commands.Cog):
    """Cog grouping all /book subcommands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    book_group = app_commands.Group(name="book", description="Book-related commands.")

    @book_group.command(name="search", description="Search Google Books for a title.")
    @app_commands.describe(query="Title, author, or keywords to search for.")
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        """Search Google Books and return up to 5 results as embeds."""
        # Defer so we have up to 15 min to respond (network calls can be slow).
        await interaction.response.defer()

        results = await google_books.search(query, max_results=5)

        await db.log_event(
            event_name="book_search",
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            metadata={"query": query, "result_count": len(results)},
        )

        if not results:
            await interaction.followup.send(f"No results found for: {query}")
            return

        embeds = [_book_to_embed(b) for b in results]
        await interaction.followup.send(embeds=embeds)

    async def cog_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        await report_command_error("book_club.search", interaction, error)


def _book_to_embed(book: google_books.BookResult) -> discord.Embed:
    """Format a BookResult as a Discord embed."""
    authors = ", ".join(book["authors"]) if book["authors"] else "Unknown author"
    embed = discord.Embed(
        title=book["title"],
        url=book["info_link"],
        description=_truncate(book["description"], 300) if book["description"] else None,
    )
    embed.add_field(name="Author(s)", value=authors, inline=True)
    if book["page_count"]:
        embed.add_field(name="Pages", value=str(book["page_count"]), inline=True)
    if book["published_date"]:
        embed.add_field(name="Published", value=book["published_date"], inline=True)
    if book["thumbnail_url"]:
        embed.set_thumbnail(url=book["thumbnail_url"])
    return embed


def _truncate(text: str, max_len: int) -> str:
    """Trim text to max_len, appending ... if trimmed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


async def setup(bot: commands.Bot) -> None:
    """discord.py calls this when loading the extension."""
    await bot.add_cog(Search(bot))
