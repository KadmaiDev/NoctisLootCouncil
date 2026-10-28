"""Buttons and the priority form. Thin: each one calls the store, has the posts refreshed, and replies.

The buttons are DynamicItems whose custom IDs carry the item ID, so they keep working on every
old post after a restart without the bot remembering any views.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import discord

from . import render
from .checks import is_officer
from .rules import COUNCIL

if TYPE_CHECKING:
    from .client import LootBot

log = logging.getLogger("noctis.views")

STYLES = {"success": discord.ButtonStyle.success, "secondary": discord.ButtonStyle.secondary,
          "primary": discord.ButtonStyle.primary}


async def _officers_only(interaction: discord.Interaction) -> bool:
    bot: LootBot = interaction.client  # type: ignore[assignment]
    if is_officer(interaction.user, bot.config.officer_role_id):
        return True
    await interaction.response.send_message("Only officers can do that. Raiders can suggest council items in "
                                            f"<#{bot.config.ch_items}>.", ephemeral=True)
    return False


class VoteButton(discord.ui.DynamicItem[discord.ui.Button], template=r"nlc:vote:(?P<choice>council|roll):(?P<item>\d+)"):
    def __init__(self, item_id: int, choice: str, label: str | None = None, style: str = "secondary"):
        super().__init__(discord.ui.Button(label=label or choice.title(), style=STYLES[style],
                                           custom_id=f"nlc:vote:{choice}:{item_id}"))
        self.item_id = item_id
        self.choice = choice

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["item"]), match["choice"])

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _officers_only(interaction)

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LootBot = interaction.client  # type: ignore[assignment]
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not bot.store.item_exists(self.item_id):
            await interaction.followup.send("That item isn't on the list any more.", ephemeral=True)
            return
        user = interaction.user
        t = bot.store.cast_vote(self.item_id, user.id, user.display_name, self.choice)
        await bot.sync_item(self.item_id)
        text = f"Your vote: **{self.choice.title()}**. Council {len(t.council)} · Roll {len(t.roll)}."
        if t.decided:
            text += f" Decided: {render.handling_name(t.decided)}."
        await interaction.followup.send(text, ephemeral=True)


class PriorityModal(discord.ui.Modal):
    def __init__(self, item_id: int, name: str, current: str | None):
        super().__init__(title=f"Priority for {name}"[:45])
        self.item_id = item_id
        self.text = discord.ui.TextInput(
            label="Priority (leave empty to clear it)", default=current, required=False, max_length=100,
            placeholder="e.g. Warlock priority. Shown in #loot-items, #loot-priorities and in game")
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: LootBot = interaction.client  # type: ignore[assignment]
        await interaction.response.defer(ephemeral=True, thinking=True)
        bot.store.set_priority(self.item_id, self.text.value, interaction.user.display_name)
        await bot.sync_item(self.item_id)
        value = self.text.value.strip()
        await interaction.followup.send(f"Priority set: **{render.md(value)}**." if value else "Priority cleared.",
                                        ephemeral=True)


class PriorityButton(discord.ui.DynamicItem[discord.ui.Button], template=r"nlc:prio:(?P<item>\d+)"):
    def __init__(self, item_id: int, label: str = "Set priority", style: str = "secondary"):
        super().__init__(discord.ui.Button(label=label, style=STYLES[style], custom_id=f"nlc:prio:{item_id}"))
        self.item_id = item_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["item"]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _officers_only(interaction)

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LootBot = interaction.client  # type: ignore[assignment]
        state = bot.store.item_state(self.item_id)
        if state is None:
            await interaction.response.send_message("That item isn't on the list any more.", ephemeral=True)
            return
        await interaction.response.send_modal(PriorityModal(self.item_id, state.name, state.priority))


class SuggestButton(discord.ui.DynamicItem[discord.ui.Button], template=r"nlc:suggest:(?P<item>\d+)"):
    def __init__(self, item_id: int, label: str = "Suggest for council", style: str = "primary"):
        super().__init__(discord.ui.Button(label=label, style=STYLES[style], custom_id=f"nlc:suggest:{item_id}"))
        self.item_id = item_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["item"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: LootBot = interaction.client  # type: ignore[assignment]
        await interaction.response.defer(ephemeral=True, thinking=True)
        state = bot.store.item_state(self.item_id)
        if state is None:
            await interaction.followup.send("That item isn't on the list any more.", ephemeral=True)
            return
        if state.handling == COUNCIL:
            await interaction.followup.send("It's already a council item.", ephemeral=True)
            return
        on, count = bot.store.toggle_suggestion(self.item_id, interaction.user.id, interaction.user.display_name)
        await bot.sync_item(self.item_id)
        await interaction.followup.send(render.suggestion_reply(on, count), ephemeral=True)


DYNAMIC_ITEMS = (VoteButton, PriorityButton, SuggestButton)


def card_button(b: render.Button, item_id: int) -> discord.ui.Item:
    if b.action in ("council", "roll"):
        return VoteButton(item_id, b.action, b.label, b.style)
    if b.action == "priority":
        return PriorityButton(item_id, b.label, b.style)
    return SuggestButton(item_id, b.label, b.style)


def card_layout(card: render.Card, item_id: int | None = None) -> discord.ui.LayoutView:
    """The card as a Discord layout message: a container in the card's colour holding the heading,
    a divider, the body, a little space and the footer; the buttons in a row under the container,
    as in the mockups."""
    view = discord.ui.LayoutView(timeout=None)
    head, footer = card.head(), render.small(card.footer)
    box = discord.ui.Container(discord.ui.TextDisplay(head), accent_colour=card.colour)
    if card.body or footer:
        box.add_item(discord.ui.Separator())
    if card.body:
        box.add_item(discord.ui.TextDisplay(card.body[: 4000 - len(head) - len(footer)]))
    if footer:
        if card.body:  # space, no line: the footer's grey facts apart from the body's grey details
            box.add_item(discord.ui.Separator(visible=False))
        box.add_item(discord.ui.TextDisplay(footer))
    view.add_item(box)
    if card.buttons and item_id is not None:
        view.add_item(discord.ui.ActionRow(*(card_button(b, item_id) for b in card.buttons)))
    return view
