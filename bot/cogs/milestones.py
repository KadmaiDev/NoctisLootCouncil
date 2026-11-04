"""/milestones settings: level milestones on Discord (milestones.py). Officers only. The settings
live in the bot, not in each officer's companion app, so they're the same for every upload."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from .. import milestones
from ..checks import officer_only
from ..client import LootBot, UserError, reply


class MilestonesCog(commands.Cog):
    group = app_commands.Group(name="milestones", description="Congratulations on Discord when guild members level up",
                               guild_only=True)

    def __init__(self, bot: LootBot):
        self.bot = bot

    @group.command(name="settings", description="Show or change the level milestones (officers)")
    @app_commands.describe(
        guild="The in-game guild whose level-ups count, e.g. Noctis (a character in any other guild is ignored)",
        channel="Where the congratulations go",
        levels="The levels to congratulate, e.g. 10, 20, 30, 40, 50, 60",
        announce="On: post milestones from now on. Off: ignore uploads")
    @officer_only()
    async def settings(self, interaction: discord.Interaction, guild: app_commands.Range[str, 1, 64] | None = None,
                       channel: discord.TextChannel | None = None, levels: app_commands.Range[str, 1, 100] | None = None,
                       announce: bool | None = None) -> None:
        store = self.bot.store
        parsed = None
        if levels is not None:
            try:
                parsed = milestones.parse_levels(levels)
            except ValueError as exc:
                raise UserError(str(exc)) from exc
        before = store.milestone_settings()
        if announce and not ((guild or before.guild) and (channel or before.channel_id)):
            raise UserError("Set the guild and the channel first, e.g. `/milestones settings guild:Noctis "
                            "channel:#milestones announce:True`.")
        s = store.set_milestone_settings(on=announce, guild=guild, channel_id=channel.id if channel else None,
                                         levels=parsed)
        self.bot.notify()
        mention = self.bot.channel_mention(s.channel_id) if s.channel_id else None
        text = milestones.settings_text(s, mention, store.milestone_counts())
        if announce and not before.on:
            text = "Turned on: level-ups noticed from now are congratulated.\n" + text
        await reply(interaction, text, ephemeral=True)


async def setup(bot: LootBot) -> None:
    await bot.add_cog(MilestonesCog(bot))
