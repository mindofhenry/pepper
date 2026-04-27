"""Shared error helpers. The single most important thing in this module is
`report_command_error`: every cog calls it from `cog_command_error` so a
failure in one cog never crashes the bot or affects sibling cogs."""
import logging
import traceback
from typing import Optional

import discord
from discord import app_commands

import config

log = logging.getLogger("pepper.errors")

# Discord caps an embed description at 4096 chars. Keep a margin.
_TRACEBACK_MAX = 3800


def _friendly_user_message(error: Exception) -> str:
    """Map an exception to a short, user-facing message.

    Distinguishes app_commands errors (which carry their own user-readable
    text) from unexpected exceptions (which we hide behind a generic line)."""
    if isinstance(error, app_commands.CheckFailure):
        return "You don't have permission to run that command."
    if isinstance(error, app_commands.CommandOnCooldown):
        return f"Slow down. Try again in {error.retry_after:.1f}s."
    if isinstance(error, app_commands.MissingPermissions):
        return "You're missing permissions for that command."
    return "Something broke running that command. Henry has been notified."


async def _send_user_message(
    interaction: discord.Interaction, message: str
) -> None:
    """Reply to the user, picking the right send method based on interaction state."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        log.exception("Failed to send error message to user")


async def _send_admin_report(
    bot: discord.Client,
    cog_name: str,
    command_name: str,
    user: discord.abc.User,
    guild: Optional[discord.Guild],
    error: Exception,
) -> None:
    """Post a structured embed to the admin channel. Swallows its own errors."""
    channel_id = config.ADMIN_CHANNEL_ID
    if not channel_id:
        return
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
    except discord.HTTPException:
        log.exception("Couldn't fetch admin channel %s", channel_id)
        return

    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        log.warning("ADMIN_CHANNEL_ID %s is not a text channel", channel_id)
        return

    tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    if len(tb) > _TRACEBACK_MAX:
        tb = tb[: _TRACEBACK_MAX - 20] + "\n... (truncated)"

    embed = discord.Embed(
        title=f"Cog error: {cog_name}",
        description=f"```py\n{tb}\n```",
        color=discord.Color.red(),
    )
    embed.add_field(name="Command", value=f"/{command_name}", inline=True)
    embed.add_field(name="User", value=f"{user} ({user.id})", inline=True)
    if guild is not None:
        embed.add_field(name="Guild", value=f"{guild.name} ({guild.id})", inline=True)
    embed.add_field(
        name="Exception",
        value=f"{type(error).__name__}: {error}"[:1000],
        inline=False,
    )

    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        log.exception("Failed to send admin error report")


async def report_command_error(
    cog_name: str,
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    """Standard cog error pipeline: log full traceback, message the user,
    post a structured report to the admin channel.

    Unwraps `app_commands.CommandInvokeError` so the admin report shows the
    real underlying exception, not the wrapper."""
    real = error.original if isinstance(error, app_commands.CommandInvokeError) else error

    cmd = interaction.command.qualified_name if interaction.command else "unknown"
    log.error(
        "Unhandled error in cog=%s command=/%s user=%s: %s",
        cog_name, cmd, interaction.user.id, real,
        exc_info=real,
    )

    await _send_user_message(interaction, _friendly_user_message(real))
    await _send_admin_report(
        bot=interaction.client,
        cog_name=cog_name,
        command_name=cmd,
        user=interaction.user,
        guild=interaction.guild,
        error=real,
    )
