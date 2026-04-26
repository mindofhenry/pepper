"""Bot entrypoint. Loads config, sets up discord.py client, loads cogs."""
import logging

import discord
from discord.ext import commands

import config
import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bookclub")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Cogs to load on startup. Each file under cogs/ that has a setup() function.
COGS = [
    "cogs.books",
    "cogs.polls",
    "cogs.progress",
    "cogs.sections",
]


@bot.event
async def setup_hook() -> None:
    """Runs once before the bot connects. Init DB and load cogs."""
    await db.init_pool()
    for cog in COGS:
        await bot.load_extension(cog)
        log.info("Loaded cog: %s", cog)


@bot.event
async def on_ready() -> None:
    """Fires when the bot connects to the gateway."""
    log.info("Logged in as %s (id=%s)", bot.user, bot.user.id)
    # Per-guild sync is instant; global sync takes up to an hour.
    # Set TEST_GUILD_ID in .env for dev; remove for prod global sync.
    if config.TEST_GUILD_ID:
        guild = discord.Object(id=config.TEST_GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        log.info("Synced %d command(s) to guild %s", len(synced), config.TEST_GUILD_ID)
    else:
        synced = await bot.tree.sync()
        log.info("Synced %d global command(s)", len(synced))

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


if __name__ == "__main__":
    bot.run(config.DISCORD_TOKEN)
