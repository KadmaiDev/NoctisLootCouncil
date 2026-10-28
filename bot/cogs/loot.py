"""/loot commands. Officers only, except /loot status."""
from __future__ import annotations

import dataclasses
import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands

from .. import importer, render, rules
from ..checks import officer_only
from ..client import ImportPlan, LootBot, UserError, reply

FOUND_CHOICES = [app_commands.Choice(name="Spotted on Wowhead", value=importer.WOWHEAD),
                 app_commands.Choice(name="Seen in another guild's raid", value=importer.OTHER_RAID)]
MAX_FILE = 2 * 1024 * 1024
NAMES_SHOWN = 10


def import_preview(plan: ImportPlan, items_channel: str) -> str:
    """'**31 new items**, seen in another guild's raid: Staff of Jordan, ...', then what's left out."""
    found = render.ORIGIN_TEXT[plan.origin]
    lines = []
    if plan.new:
        names = ", ".join(render.md(n) for _, n, _, _ in plan.new[:NAMES_SHOWN])
        more = len(plan.new) - NAMES_SHOWN
        lines.append(f"**{render.plural(len(plan.new), 'new item')}**, {found}: {names}"
                     + (f" and {more} more" if more > 0 else "") + ".")
    else:
        lines.append("**No new items.**")
    if plan.known:
        lines.append(f"{render.plural(len(plan.known), 'item')} already on the list: left as they are, "
                     "except that one without a source gets this one's.")
    if plan.unknown:
        ids = ", ".join(str(i) for i in plan.unknown[:NAMES_SHOWN]) + (" ..." if len(plan.unknown) > NAMES_SHOWN else "")
        why = "Wowhead isn't answering" if plan.wowhead_down else "Wowhead doesn't know them"
        lines.append(f"Left out, no name ({why}): {ids}. `/loot add` with `name:` adds one.")
    if plan.unread:
        lines.append(f"{render.plural(plan.unread, 'piece')} of the text weren't items.")
    if plan.new:
        lines.append(f"New items are posted for the officers to decide, and in {items_channel} behind a spoiler "
                     "until they drop for us.")
    return "\n".join(lines)


class ImportView(discord.ui.View):
    """Import / Cancel under /loot import's preview, for the officer who asked."""

    def __init__(self, bot: LootBot, user_id: int, plan: ImportPlan):
        super().__init__(timeout=600)
        self.bot, self.user_id, self.plan = bot, user_id, plan

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("That's another officer's import.", ephemeral=True)
        return False

    @discord.ui.button(label="Import", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        added, filled = self.bot.store.import_items(self.plan.new + self.plan.known, self.plan.origin,
                                                    by=interaction.user.display_name)
        self.bot.notify()
        text = f"Imported {render.plural(added, 'new item')}; they're being posted now."
        if filled:
            text += f" {render.plural(filled, 'item')} already on the list got a source."
        await interaction.response.edit_message(content=text, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Cancelled: nothing was imported.", view=None)


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
    @app_commands.describe(item="Its Wowhead link, in-game link or item ID",
                           name="Its name as in game (default: Wowhead's)",
                           slot="Optional, e.g. Waist · Cloth", source="Optional, e.g. Molten Core, Gehennas",
                           quality="Its colour in game (default: Wowhead's, else Epic); the game corrects it once it drops",
                           found="Where it was seen, if it hasn't dropped for us")
    @app_commands.choices(quality=[app_commands.Choice(name=n, value=q) for q, n in ((4, "Epic"), (3, "Rare"),
                                                                                       (5, "Legendary"))],
                          found=FOUND_CHOICES)
    @officer_only()
    async def add(self, interaction: discord.Interaction, item: app_commands.Range[str, 1, 300],
                  name: app_commands.Range[str, 1, 100] | None = None, slot: app_commands.Range[str, 1, 60] | None = None,
                  source: app_commands.Range[str, 1, 100] | None = None,
                  quality: app_commands.Choice[int] | None = None,
                  found: app_commands.Choice[str] | None = None) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        item_id = importer.item_id(item)
        if item_id is None:
            raise UserError("That isn't an item: give its Wowhead link (wowhead.com/forever/item=873/...), "
                            "an in-game link or its ID.")
        if not name:
            existing = self.bot.store.item_state(item_id)
            info = None if existing else await self.bot.wowhead_info(item_id)
            name = existing.name if existing else (info.name if info and info.found else None)
            if not name:
                why = ("isn't answering" if self.bot.config.wowhead and info is None
                       else "doesn't know it" if self.bot.config.wowhead else "lookups are off")
                raise UserError(f"I need item {item_id}'s name: Wowhead {why}. Add `name:` and try again.")
        created = self.bot.store.add_item(item_id, name, slot=slot, source=source,
                                          quality=quality.value if quality else 4, by=interaction.user.display_name,
                                          origin=found.value if found else None)
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

    @loot.command(name="import", description="Put items found outside our raids on the list: Wowhead links, or another guild's RCLootCouncil CSV")
    @app_commands.describe(text="Wowhead links, in-game links or item IDs, separated by spaces or commas",
                           file="Another guild's RCLootCouncil or oxm.gg CSV export (or a text file of links)",
                           found="Where they were seen (default: Wowhead for links, another guild's raid for a CSV)")
    @app_commands.choices(found=FOUND_CHOICES)
    @officer_only()
    async def import_(self, interaction: discord.Interaction, text: app_commands.Range[str, 1, 6000] | None = None,
                      file: discord.Attachment | None = None, found: app_commands.Choice[str] | None = None) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if file is not None:
            if file.size > MAX_FILE:
                raise UserError("That file is too big for a loot export (over 2 MB).")
            text = (await file.read()).decode("utf-8", errors="replace")
        if not text:
            raise UserError("Paste links or IDs in `text:`, or attach a CSV in `file:`.")
        parsed = importer.parse(text)
        if found is not None:
            parsed = dataclasses.replace(parsed, origin=found.value)
        if not parsed.items:
            raise UserError("I couldn't find any items in that: paste Wowhead links (wowhead.com/forever/item=873/...), "
                            "in-game links or item IDs, or attach an RCLootCouncil CSV.")
        plan = await self.bot.plan_import(parsed)
        text = import_preview(plan, self.bot.channel_mention(self.bot.config.ch_items))
        if not plan.new and not any(source for _, _, source, _ in plan.known):
            await reply(interaction, text, ephemeral=True)
            return
        await interaction.followup.send(text, view=ImportView(self.bot, interaction.user.id, plan), ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())

    @loot.command(name="wcl", description="Link a Warcraft Logs report to its night's #loot-log post")
    @app_commands.describe(link="The report's link, e.g. https://classic.warcraftlogs.com/reports/AbCd1234EfGh5678")
    @officer_only()
    async def wcl(self, interaction: discord.Interaction, link: app_commands.Range[str, 1, 200]) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        report, linked = await self.bot.link_report(link, interaction.user.display_name)
        title = f"**{render.md(report.title or report.code)}**"
        kills = render.plural(len(report.fights), "boss kill")
        if not linked:
            day = rules.day_label(rules.night_of(report.start_at, self.bot.tz))
            text = (f"Saved {title} ({day}, {kills}). It goes on {self.bot.channel_mention(self.bot.config.ch_log)} "
                    "once that night's loot is uploaded.")
        else:
            posts = []
            for inst, night in linked:
                label = f"{render.md(inst or 'Raid')} · {rules.day_label(dt.date.fromisoformat(night))}"
                url = self.bot.jump_url("log", f"{inst}|{night}|0")
                posts.append(f"[{label}]({url})" if url else label)
            text = f"Linked {title} ({kills}) to {', '.join(posts)}."
        await reply(interaction, text, ephemeral=True)

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
