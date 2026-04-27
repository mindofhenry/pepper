"""Admin-only commands. Hot-reload cogs without a process restart and
run a quick health check. Bot owner only."""
import logging
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from shared import db
from shared.errors import report_command_error

log = logging.getLogger("pepper.cogs.admin")


def _format_uptime(seconds: float) -> str:
    """Render seconds as 'Hh Mm Ss' for the health embed."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    admin_group = app_commands.Group(
        name="admin",
        description="Bot administration commands. Owner only.",
        default_permissions=discord.Permissions(administrator=True),
    )

    @admin_group.command(name="reload", description="Hot-reload a cog without restarting the bot.")
    @app_commands.describe(
        cog="Cog name, e.g. `book_club.search` or `admin`. The `cogs.` prefix is added automatically.",
    )
    async def reload(self, interaction: discord.Interaction, cog: str) -> None:
        """Reload a single extension. Falls back to a clear error if the cog isn't loaded."""
        await interaction.response.defer(ephemeral=True)

        if not await self.bot.is_owner(interaction.user):
            await interaction.followup.send("Owner only.", ephemeral=True)
            return

        # Accept "cogs.book_club.search" or just "book_club.search". Normalize.
        ext_name = cog if cog.startswith("cogs.") else f"cogs.{cog}"

        try:
            await self.bot.reload_extension(ext_name)
        except commands.ExtensionNotLoaded:
            await interaction.followup.send(
                f"Cog `{ext_name}` is not currently loaded. Try `/admin reload` with one of the loaded cogs.",
                ephemeral=True,
            )
            return
        except commands.ExtensionFailed as e:
            log.exception("Reload failed for %s", ext_name)
            await interaction.followup.send(
                f"Reload failed for `{ext_name}`: `{type(e.original).__name__}: {e.original}`",
                ephemeral=True,
            )
            return

        # Re-sync slash commands so any new/changed commands show up immediately.
        # Per-guild sync is instant; global sync (no guild) takes up to an hour.
        guild = interaction.guild
        if guild is not None:
            self.bot.tree.copy_global_to(guild=guild)
            await self.bot.tree.sync(guild=guild)

        await db.log_event(
            event_name="admin_reload",
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            metadata={"cog": ext_name},
        )
        await interaction.followup.send(f"Reloaded `{ext_name}`.", ephemeral=True)

    @admin_group.command(name="health", description="Show bot health: uptime, DB pool, VPN status.")
    async def health(self, interaction: discord.Interaction) -> None:
        """Quick admin status check. Owner only."""
        await interaction.response.defer(ephemeral=True)

        if not await self.bot.is_owner(interaction.user):
            await interaction.followup.send("Owner only.", ephemeral=True)
            return

        # Uptime. bot.start_time is set in setup_hook in bot.py.
        start_time: Optional[float] = getattr(self.bot, "start_time", None)
        uptime_str = _format_uptime(time.time() - start_time) if start_time else "unknown"

        # DB pool stats. asyncpg doesn't expose public size accessors, so we
        # read private attrs. This is admin-only and acceptable here.
        try:
            pool = db.pool()
            size = pool.get_size()
            max_size = pool.get_max_size()
            idle = pool.get_idle_size()
            pool_status = f"{size}/{max_size} open ({idle} idle)"
        except RuntimeError:
            pool_status = "uninitialized"
        except Exception as e:
            pool_status = f"error: {type(e).__name__}: {e}"

        # TODO(MIN-52, Phase 12): replace this placeholder with a real VPN
        # check that confirms the wgpia0 adapter is up and the public IP
        # belongs to PIA before any qBittorrent/Prowlarr operation.
        vpn_status = "not implemented (Phase 12 / MIN-52)"

        embed = discord.Embed(title="Pepper health", color=discord.Color.green())
        embed.add_field(name="Uptime", value=uptime_str, inline=False)
        embed.add_field(name="DB pool", value=pool_status, inline=False)
        embed.add_field(name="VPN", value=vpn_status, inline=False)
        embed.add_field(
            name="Loaded cogs",
            value=", ".join(sorted(self.bot.extensions.keys())) or "(none)",
            inline=False,
        )

        await db.log_event(
            event_name="admin_health",
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            metadata={"uptime_s": int(time.time() - start_time) if start_time else None},
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def cog_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        await report_command_error("admin", interaction, error)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
