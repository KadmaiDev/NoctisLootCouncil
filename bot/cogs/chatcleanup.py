"""Keeps #in-game-chat readable. The game's Discord link posts "Sent a message to guild chat but has
not yet linked their Discord account." for every line from a player who hasn't linked, and Discord
has no setting for it, so the bot deletes those lines (CHANNEL_IN_GAME_CHAT; without it this isn't
loaded). Only that exact line, and only as the game sends it: everything else in the channel stays.
Text isn't kept. Needs the Message Content intent and Manage Messages in that channel."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from ..client import LootBot

log = logging.getLogger("noctis")

PLACEHOLDER = "Sent a message to guild chat but has not yet linked their Discord account."
FROM_THE_GAME = 1 << 16  # the flag Discord sets on messages sent through a game's link
BACKLOG = 500  # how far back to look at each start: what came in while the bot was away


def is_placeholder(message: discord.Message) -> bool:
    """A player typing the same sentence on Discord doesn't have the flag, and stays."""
    return message.content.strip() == PLACEHOLDER and bool(message.flags.value & FROM_THE_GAME)


class ChatCleanupCog(commands.Cog):
    def __init__(self, bot: LootBot):
        self.bot = bot
        self.channel_id = bot.config.ch_in_game_chat

    @staticmethod
    async def _remove(message: discord.Message) -> bool:
        try:
            await message.delete()
        except discord.NotFound:
            return False  # already gone
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.channel.id != self.channel_id or not is_placeholder(message):
            return
        try:
            await self._remove(message)
        except discord.HTTPException as exc:
            log.warning("Could not remove a line from in-game chat: %s", exc)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        removed = 0
        try:
            async for message in self.bot.get_partial_messageable(self.channel_id).history(limit=BACKLOG):
                if is_placeholder(message) and await self._remove(message):
                    removed += 1
        except discord.HTTPException as exc:  # no permission, most likely: no use trying the rest
            log.warning("Could not clear in-game chat: %s", exc)
        if removed:
            log.info("Removed %d \"not linked\" lines from in-game chat", removed)


async def setup(bot: LootBot) -> None:
    await bot.add_cog(ChatCleanupCog(bot))
