"""/loot commands. Officers only, except /loot status."""
from __future__ import annotations

import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands

from .. import render, rules
from ..checks import officer_only
from ..client import LootBot, UserError, reply


class LootCog(commands.Cog):
    loot = app_commands.Group(name="loot", description="The Noctis loot list", guild_only=True)

    def __init__(self, bot: LootBot):
        self.bot = bot

    # ---- autocomplete --------------------------------------------------------

    async def item_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return [app_commands.Choice(name=f"{name} ({item_id})"[:100], value=str(item_id))
                for item_id, name in self.bot.store.find_items(current)]

    async def raid_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        text = current.lower()
        return [app_commands.Choice(name=n, value=n) for n in self.bot.store.raid_names() if text in n.lower()][:25]

    # ---- commands ------------------------------------------------------------

    @loot.command(name="add", description="Put an item up for the officers to decide (posts to #loot-officers and #loot-items)")
    @app_commands.describe(item_id="The item's ID (from its link or a database site)",
                           name="The item's name as in game (Discord can't look it up)",
                           slot="Optional, e.g. Waist · Cloth", source="Optional, e.g. Molten Core, Gehennas")
    @officer_only()
    async def add(self, interaction: discord.Interaction, item_id: app_commands.Range[int, 1, 10_000_000],
                  name: app_commands.Range[str, 1, 100], slot: app_commands.Range[str, 1, 60] | None = None,
                  source: app_commands.Range[str, 1, 100] | None = None) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        created = self.bot.store.add_item(item_id, name, slot=slot, source=source, by=interaction.user.display_name)
        ok = await self.bot.sync_item(item_id)
        self.bot.notify()  # in case a post failed: the poster retries it
        links = " · ".join(u for u in (self.bot.jump_url("officer", str(item_id)), self.bot.jump_url("items", str(item_id))) if u)
        verb = "Added" if created else "Updated"
        text = f"{verb} **{render.md(name)}** ({item_id})." + (f" {links}" if links else "")
        if not ok:
            text += " Some posts couldn't be made yet; I'll keep trying (see the bot's log)."
        await reply(interaction, text, ephemeral=True)

    @loot.command(name="token", description="Get a token for the companion app (replaces your old one)")
    @officer_only()
    async def token(self, interaction: discord.Interaction) -> None:
        user = interaction.user
        token = self.bot.store.issue_token(f"discord:{user.id}", user.display_name)
        await reply(interaction,
                    "Your token for the companion app (any earlier one stops working now):\n"
                    f"```\n{token}\n```"
                    "Paste it when the companion app asks for it, or after `token =` in `companion.ini`. "
                    "Keep it to yourself: anyone with it can upload loot as you.",
                    ephemeral=True)

    @loot.command(name="priorities", description="Post the council items and their priorities to #loot-priorities")
    @app_commands.describe(raid="Only this raid's items (default: every raid)",
                           day="The raid night for the heading, e.g. Thursday 30 Oct (default: today)")
    @app_commands.autocomplete(raid=raid_autocomplete)
    @officer_only()
    async def priorities(self, interaction: discord.Interaction, raid: app_commands.Range[str, 1, 60] | None = None,
                         day: app_commands.Range[str, 1, 40] | None = None) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        today = dt.datetime.now(self.bot.tz).date()
        await self.bot.post_priorities(day or rules.day_label(today), raid)
        await reply(interaction, f"Posted to {self.bot.channel_mention(self.bot.config.ch_priorities)}.", ephemeral=True)

    @loot.command(name="status", description="What's decided: council items and their priorities")
    @app_commands.describe(item="One item (default: the whole list)")
    @app_commands.autocomplete(item=item_autocomplete)
    async def status(self, interaction: discord.Interaction, item: str | None = None) -> None:
        store = self.bot.store
        if item:
            item_id = int(item) if item.strip().isdigit() else next(iter(store.find_items(item, 1)), (None,))[0]
            state = store.item_state(item_id) if item_id else None
            if state is None:
                raise UserError(f"`{item}` isn't on the list.")
            await reply(interaction, render.item_status(state), ephemeral=True)
            return
        embed = discord.Embed(title="What's decided", description=render.status_text(store.item_states()),
                              colour=render.DEFAULT_COLOUR)
        await reply(interaction, embed=embed, ephemeral=True)


async def setup(bot: LootBot) -> None:
    await bot.add_cog(LootCog(bot))
