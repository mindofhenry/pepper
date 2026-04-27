"""Bot entrypoint. Loads config, sets up discord.py client, dynamically
discovers cogs under cogs/book_club/ and cogs/media/, and explicitly loads
cogs/admin.py."""
import asyncio
import logging
import pkgutil
import time
import traceback
from typing import Iterable

import discord
from discord.ext import commands

import config
from shared import db
from shared.logging import setup_logging

setup_logging()
log = logging.getLogger("pepper.bot")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.start_time = 0.0  # populated in setup_hook so /admin health can read it


def _discover_cogs(package: str) -> Iterable[str]:
    """Yield fully-qualified module paths for every non-private module in `package`.

    Uses pkgutil to walk the package without importing it, so we don't pay
    the import cost just to enumerate. New cogs added to a package directory
    are picked up automatically."""
    pkg = __import__(package, fromlist=["__path__"])
    for module in pkgutil.iter_modules(pkg.__path__):
        if module.ispkg or module.name.startswith("_"):
            continue
        yield f"{package}.{module.name}"


@bot.event
async def setup_hook() -> None:
    """Runs once before the bot connects. Init DB and load cogs."""
    bot.start_time = time.time()
    await db.init_pool()

    # Dynamically discover book_club and media cogs.
    for ext in _discover_cogs("cogs.book_club"):
        try:
            await bot.load_extension(ext)
            log.info("Loaded cog: %s", ext)
        except Exception:
            # Failure isolation: one broken cog should not stop the others.
            log.exception("Failed to load cog %s", ext)

    for ext in _discover_cogs("cogs.media"):
        try:
            await bot.load_extension(ext)
            log.info("Loaded cog: %s", ext)
        except Exception:
            log.exception("Failed to load cog %s", ext)

    # Admin cog is explicit, not discovered.
    try:
        await bot.load_extension("cogs.admin")
        log.info("Loaded cog: cogs.admin")
    except Exception:
        log.exception("Failed to load cogs.admin")


@bot.event
async def on_ready() -> None:
    """Fires when the bot connects to the gateway."""
    log.info("Logged in as %s (id=%s)", bot.user, bot.user.id)
    # Per-guild sync is instant; global sync takes up to an hour.
    # Set TEST_GUILD_ID in .env for dev; leave unset for prod global sync.
    if config.TEST_GUILD_ID:
        guild = discord.Object(id=config.TEST_GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        log.info("Synced %d command(s) to guild %s", len(synced), config.TEST_GUILD_ID)
    else:
        synced = await bot.tree.sync()
        log.info("Synced %d global command(s)", len(synced))


@bot.event
async def on_error(event_method: str, *args, **kwargs) -> None:
    """Catch-all for unhandled exceptions in event handlers. Logs with full
    traceback and posts a structured report to the admin channel if configured.

    Slash command errors are caught earlier by per-cog cog_command_error;
    this handler covers everything else (gateway events, listeners, etc.)."""
    log.exception("Unhandled error in event %s", event_method)

    if not config.ADMIN_CHANNEL_ID:
        return

    try:
        channel = bot.get_channel(config.ADMIN_CHANNEL_ID) or await bot.fetch_channel(
            config.ADMIN_CHANNEL_ID
        )
    except discord.HTTPException:
        return

    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return

    tb = traceback.format_exc()
    if len(tb) > 3800:
        tb = tb[:3780] + "\n... (truncated)"
    embed = discord.Embed(
        title=f"Event handler error: {event_method}",
        description=f"```py\n{tb}\n```",
        color=discord.Color.red(),
    )
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        log.exception("Failed to deliver event-error report")


@bot.tree.command(name="ping", description="Check that the bot is alive.")
async def ping(interaction: discord.Interaction) -> None:
    """Health check. Also logs to events to verify DB instrumentation."""
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong. Latency {latency_ms}ms.")
    await db.log_event(
        event_name="ping",
        user_id=interaction.user.id,
        guild_id=interaction.guild_id,
        metadata={"latency_ms": latency_ms},
    )


async def _shutdown() -> None:
    """Close the DB pool on graceful shutdown."""
    await db.close_pool()


if __name__ == "__main__":
    try:
        bot.run(config.DISCORD_TOKEN)
    finally:
        asyncio.run(_shutdown())
