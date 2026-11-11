"""/roster settings: the guild roster channel (roster.py), a few posts the bot keeps edited, listing the
guild's characters by class. Officers only. The roster comes with the level milestones upload, so it
needs milestones on with a guild too. The bot sets no permissions: it posts in whichever channel is set."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from .. import milestones, roster
from ..checks import officer_only
from ..client import LootBot, UserError, reply


class RosterCog(commands.Cog):
    group = app_commands.Group(name="roster", description="A channel listing the guild's characters by class",
                               guild_only=True)

    def __init__(self, bot: LootBot):
        self.bot = bot

    @group.command(name="settings", description="Show or change the guild roster channel (officers)")
    @app_commands.describe(
        channel="Where the roster is posted (the bot's posts there are edited as the guild changes)",
        min_level="List characters at this level and above (default 10)",
        hide_ranks="Ranks to leave out, e.g. Trial (none: show every rank)",
        show="On: keep the roster posted. Off: leave the posts as they are")
    @officer_only()
    async def settings(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None,
                       min_level: app_commands.Range[int, 1, milestones.MAX_LEVEL] | None = None,
                       hide_ranks: app_commands.Range[str, 1, 200] | None = None,
                       show: bool | None = None) -> None:
        store = self.bot.store
        hidden = None
        if hide_ranks is not None:
            try:
                hidden = roster.parse_ranks(hide_ranks)
            except ValueError as exc:
                raise UserError(str(exc)) from exc
        before = store.roster_settings()
        if show and not (channel or before.channel_id):
            raise UserError("Set the channel first, e.g. `/roster settings channel:#roster show:True`.")
        s = store.set_roster_settings(on=show, channel_id=channel.id if channel else None, min_level=min_level,
                                      hidden_ranks=hidden)
        self.bot.notify()
        ms = store.milestone_settings()
        mention = self.bot.channel_mention(s.channel_id) if s.channel_id else None
        text = roster.settings_text(s, mention, store.roster_counts(), ms.on and bool(ms.guild))
        if not s.on and store.roster_posts():
            text += "\nThe roster posts already in the channel stay as they are; delete them if you don't want them."
        await reply(interaction, text, ephemeral=True)


async def setup(bot: LootBot) -> None:
    await bot.add_cog(RosterCog(bot))
