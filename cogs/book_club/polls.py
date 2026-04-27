"""Poll commands: nominate books, vote, close, set winner as current book."""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from shared import db
from shared.errors import report_command_error
from services import google_books

log = logging.getLogger("pepper.cogs.book_club.polls")

# Unicode regional indicator letters A-J. Used as reaction emoji for up to 10 options.
LETTER_EMOJIS = ["🇦", "🇧", "🇨", "🇩", "🇪", "🇫", "🇬", "🇭", "🇮", "🇯"]


class Polls(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    poll_group = app_commands.Group(name="poll", description="Book poll commands.")

    @poll_group.command(name="new", description="Start a new nomination round.")
    async def new_poll(self, interaction: discord.Interaction) -> None:
        """Create a poll in 'nominating' status for this guild."""
        await interaction.response.defer()

        async with db.pool().acquire() as conn:
            # Guard: only one active poll per guild at a time.
            existing = await conn.fetchval(
                "SELECT id FROM polls WHERE guild_id = $1 AND status != 'closed'",
                interaction.guild_id,
            )
            if existing:
                await interaction.followup.send(
                    f"A poll is already active (id={existing}). Close it with /poll close first."
                )
                return

            poll_id = await conn.fetchval(
                """
                INSERT INTO polls (guild_id, channel_id, created_by, status)
                VALUES ($1, $2, $3, 'nominating') RETURNING id
                """,
                interaction.guild_id, interaction.channel_id, interaction.user.id,
            )

        await db.log_event(
            event_name="poll_new",
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            metadata={"poll_id": poll_id},
        )
        await interaction.followup.send(
            f"Poll #{poll_id} started. Nominate books with `/poll nominate query:<title>`. "
            f"When ready, run `/poll start` to begin voting."
        )

    @poll_group.command(name="nominate", description="Nominate a book for the active poll.")
    @app_commands.describe(query="Title, author, or keywords. Picks the top Google Books result.")
    async def nominate(self, interaction: discord.Interaction, query: str) -> None:
        """Search Google Books, take top result, add to active poll."""
        await interaction.response.defer()

        async with db.pool().acquire() as conn:
            poll = await conn.fetchrow(
                "SELECT id, status FROM polls WHERE guild_id = $1 AND status = 'nominating'",
                interaction.guild_id,
            )
        if not poll:
            await interaction.followup.send("No poll is open for nominations. Run `/poll new`.")
            return

        results = await google_books.search(query, max_results=1)
        if not results:
            await interaction.followup.send(f"No Google Books results for: {query}")
            return
        book = results[0]

        book_id = await db.upsert_book(
            google_id=book["google_id"],
            title=book["title"],
            authors=book["authors"],
            page_count=book["page_count"],
            thumbnail_url=book["thumbnail_url"],
            info_link=book["info_link"],
        )

        async with db.pool().acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO poll_nominations (poll_id, book_id, nominated_by)
                    VALUES ($1, $2, $3)
                    """,
                    poll["id"], book_id, interaction.user.id,
                )
            except Exception:
                await interaction.followup.send(f"'{book['title']}' is already nominated.")
                return

        await db.log_event(
            event_name="poll_nominate",
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            metadata={"poll_id": poll["id"], "book_id": book_id, "title": book["title"]},
        )
        authors = ", ".join(book["authors"]) or "Unknown"
        await interaction.followup.send(f"Nominated: **{book['title']}** by {authors}")

    @poll_group.command(name="start", description="Close nominations and start voting.")
    async def start_voting(self, interaction: discord.Interaction) -> None:
        """Post a message with a reaction for each nomination; flip status to voting."""
        await interaction.response.defer()

        async with db.pool().acquire() as conn:
            poll = await conn.fetchrow(
                "SELECT id FROM polls WHERE guild_id = $1 AND status = 'nominating'",
                interaction.guild_id,
            )
            if not poll:
                await interaction.followup.send("No poll is in the nominating stage.")
                return

            nominations = await conn.fetch(
                """
                SELECT n.id AS nom_id, b.title, b.authors
                FROM poll_nominations n
                JOIN books b ON b.id = n.book_id
                WHERE n.poll_id = $1
                ORDER BY n.id
                """,
                poll["id"],
            )

        if len(nominations) < 2:
            await interaction.followup.send("Need at least 2 nominations to start voting.")
            return
        if len(nominations) > len(LETTER_EMOJIS):
            await interaction.followup.send(f"Too many nominations (max {len(LETTER_EMOJIS)}).")
            return

        lines = [f"**Poll #{poll['id']}, vote by reacting**\n"]
        for i, nom in enumerate(nominations):
            authors = ", ".join(nom["authors"]) or "Unknown"
            lines.append(f"{LETTER_EMOJIS[i]} **{nom['title']}** by {authors}")
        message = await interaction.followup.send("\n".join(lines), wait=True)

        for i in range(len(nominations)):
            await message.add_reaction(LETTER_EMOJIS[i])

        # Persist which emoji maps to which nomination for close-time tally.
        async with db.pool().acquire() as conn:
            await conn.execute(
                "UPDATE polls SET status = 'voting', message_id = $1 WHERE id = $2",
                message.id, poll["id"],
            )

        await db.log_event(
            event_name="poll_voting_started",
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            metadata={"poll_id": poll["id"], "nomination_count": len(nominations)},
        )

    @poll_group.command(name="close", description="Tally votes and set winner as current book.")
    async def close_poll(self, interaction: discord.Interaction) -> None:
        """Read reactions off the poll message, pick highest, set current book."""
        await interaction.response.defer()

        async with db.pool().acquire() as conn:
            poll = await conn.fetchrow(
                """
                SELECT id, channel_id, message_id FROM polls
                WHERE guild_id = $1 AND status = 'voting'
                """,
                interaction.guild_id,
            )
            if not poll:
                await interaction.followup.send("No poll is in the voting stage.")
                return

            nominations = await conn.fetch(
                """
                SELECT n.id AS nom_id, n.book_id, b.title
                FROM poll_nominations n
                JOIN books b ON b.id = n.book_id
                WHERE n.poll_id = $1
                ORDER BY n.id
                """,
                poll["id"],
            )

        # Fetch the poll message to read live reaction counts.
        channel = self.bot.get_channel(poll["channel_id"])
        if channel is None:
            await interaction.followup.send("Couldn't find the poll channel.")
            return
        try:
            message = await channel.fetch_message(poll["message_id"])
        except discord.NotFound:
            await interaction.followup.send("Poll message was deleted. Can't tally.")
            return

        # Count reactions per option. Subtract 1 to exclude the bot's own reaction.
        tallies: list[tuple[dict, int]] = []
        for i, nom in enumerate(nominations):
            emoji = LETTER_EMOJIS[i]
            count = 0
            for reaction in message.reactions:
                if str(reaction.emoji) == emoji:
                    count = max(0, reaction.count - 1)
                    break
            tallies.append((dict(nom), count))

        # Pick winner. Tie-breaker: earliest nomination (stable sort by nom_id).
        tallies.sort(key=lambda t: (-t[1], t[0]["nom_id"]))
        winner, winner_votes = tallies[0]

        async with db.pool().acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE polls SET status = 'closed', winner_book_id = $1, closed_at = NOW()
                    WHERE id = $2
                    """,
                    winner["book_id"], poll["id"],
                )
                # Upsert current book for this guild.
                await conn.execute(
                    """
                    INSERT INTO current_books (guild_id, book_id, set_by, from_poll_id)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (guild_id) DO UPDATE
                      SET book_id = EXCLUDED.book_id,
                          set_at = NOW(),
                          set_by = EXCLUDED.set_by,
                          from_poll_id = EXCLUDED.from_poll_id
                    """,
                    interaction.guild_id, winner["book_id"], interaction.user.id, poll["id"],
                )

        await db.log_event(
            event_name="poll_closed",
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            metadata={
                "poll_id": poll["id"],
                "winner_book_id": winner["book_id"],
                "winner_title": winner["title"],
                "winner_votes": winner_votes,
                "tallies": [{"title": t[0]["title"], "votes": t[1]} for t in tallies],
            },
        )

        lines = [f"**Poll #{poll['id']} closed.**", f"Winner: **{winner['title']}** ({winner_votes} votes)\n", "Results:"]
        for nom, votes in tallies:
            lines.append(f"- {nom['title']}: {votes}")
        await interaction.followup.send("\n".join(lines))

    @poll_group.command(name="current", description="Show the current book for this server.")
    async def current(self, interaction: discord.Interaction) -> None:
        """Display the current book picked by the most recent closed poll."""
        async with db.pool().acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT b.title, b.authors, b.page_count, b.thumbnail_url, b.info_link, cb.set_at
                FROM current_books cb
                JOIN books b ON b.id = cb.book_id
                WHERE cb.guild_id = $1
                """,
                interaction.guild_id,
            )
        if not row:
            await interaction.response.send_message("No current book set yet. Run a poll.")
            return

        authors = ", ".join(row["authors"]) or "Unknown"
        embed = discord.Embed(title=row["title"], url=row["info_link"])
        embed.add_field(name="Author(s)", value=authors, inline=True)
        if row["page_count"]:
            embed.add_field(name="Pages", value=str(row["page_count"]), inline=True)
        if row["thumbnail_url"]:
            embed.set_thumbnail(url=row["thumbnail_url"])
        await interaction.response.send_message(embed=embed)

    async def cog_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        await report_command_error("book_club.polls", interaction, error)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Polls(bot))
