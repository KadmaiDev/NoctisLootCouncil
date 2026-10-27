"""The Discord client: starts the HTTP API, and keeps every post in step with the database.

Posting works from the database, not from events: anything that changes an item marks it dirty,
and `sync_pending` renders and edits (or first sends) its posts. So a restart, a failed send or
two uploads at once can't duplicate a post; at worst a post is a little late.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import traceback
from collections import defaultdict
from zoneinfo import ZoneInfo

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands

from . import render
from .api import create_app
from .checks import NotOfficer
from .config import Config
from .db import connect
from .model import Post
from .store import Store
from .views import DYNAMIC_ITEMS, card_layout

log = logging.getLogger("noctis")

# How often the poster retries work that failed (a missing channel, Discord down) without a new event.
RETRY_SECONDS = 300
NO_MENTIONS = discord.AllowedMentions.none()


class UserError(Exception):
    """Raised inside a command to show a friendly, ephemeral message."""


class LootBot(commands.Bot):
    def __init__(self, config: Config):
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default(), help_command=None)
        self.config = config
        self.tz = ZoneInfo(config.timezone)
        self.store = Store(connect(config.db_path), self.tz, config.votes_to_decide)
        self.guild_obj = discord.Object(id=config.guild_id)
        self._wake = asyncio.Event()
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._runner: web.AppRunner | None = None
        self._poster_task: asyncio.Task | None = None
        self._missing_channels: set[int] = set()

    # ---- lifecycle ---------------------------------------------------------

    async def setup_hook(self) -> None:
        await self.load_extension("bot.cogs.loot")
        self.add_dynamic_items(*DYNAMIC_ITEMS)
        self.tree.error(self._on_app_error)
        self.tree.copy_global_to(guild=self.guild_obj)
        synced = await self.tree.sync(guild=self.guild_obj)
        log.info("Synced %d commands to guild %s", len(synced), self.config.guild_id)
        self._runner = web.AppRunner(create_app(self.store, self.notify), access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, self.config.api_host, self.config.api_port).start()
        log.info("API listening on http://%s:%d", self.config.api_host, self.config.api_port)
        # Recheck every post once: a new version may word or lay them out differently (posts that
        # come out the same are skipped by their digest).
        self.store.mark_all_dirty()
        self._poster_task = asyncio.create_task(self._poster())

    async def close(self) -> None:
        if self._poster_task:
            self._poster_task.cancel()
        if self._runner:
            await self._runner.cleanup()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "?")
        self.notify()

    # ---- posting -----------------------------------------------------------

    def notify(self) -> None:
        """Something changed: wake the poster."""
        self._wake.set()

    async def _poster(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.sync_pending()
            except Exception:  # noqa: BLE001 - the poster must keep running; the work stays dirty
                log.exception("Posting failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=RETRY_SECONDS)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def sync_pending(self) -> None:
        for item_id, generation in self.store.dirty_items():
            if await self.sync_item(item_id):
                self.store.clear_item_dirty(item_id, generation)
        for inst, night, generation in self.store.dirty_log_groups():
            if await self.sync_log_group(inst, night):
                self.store.clear_log_dirty(inst, night, generation)

    def _text_channel(self, channel_id: int) -> discord.TextChannel | None:
        ch = self.get_channel(channel_id)
        if not isinstance(ch, discord.TextChannel):
            # Once per channel, not once per post: a wrong ID would otherwise flood the log.
            if channel_id not in self._missing_channels:
                log.warning("Channel %s not found (or not a text channel): check .env and the bot's access",
                            channel_id)
                self._missing_channels.add(channel_id)
            return None
        self._missing_channels.discard(channel_id)
        return ch

    def channel_mention(self, channel_id: int) -> str:
        return f"<#{channel_id}>"

    def jump_url(self, kind: str, key: str) -> str | None:
        post = self.store.get_post(kind, key)
        if post is None:
            return None
        return f"https://discord.com/channels/{self.config.guild_id}/{post.channel_id}/{post.message_id}"

    async def sync_item(self, item_id: int) -> bool:
        """Bring an item's two posts up to date. Returns False if something has to be retried."""
        async with self._locks[f"item:{item_id}"]:
            state = self.store.item_state(item_id)
            if state is None:
                return True
            officer = render.officer_card(state, self.tz, self.channel_mention(self.config.ch_items))
            ok = await self._upsert_card("officer", str(item_id), self.config.ch_officers, officer, item_id,
                                         thread_name=state.name)
            ok &= await self._upsert_card("items", str(item_id), self.config.ch_items,
                                          render.items_card(state, self.tz), item_id)
            return ok

    async def _upsert_card(self, kind: str, key: str, channel_id: int, card: render.Card, item_id: int | None = None,
                           thread_name: str | None = None) -> bool:
        digest = card.digest()
        post = self.store.get_post(kind, key)
        if post and post.channel_id == channel_id and post.digest == digest:
            return True
        channel = self._text_channel(channel_id)
        if channel is None:
            return False
        view = card_layout(card, item_id)
        if post and post.channel_id == channel_id:
            message = channel.get_partial_message(post.message_id)
            try:
                await message.edit(content=None, embed=None, view=view, allowed_mentions=NO_MENTIONS)
                self.store.save_post(dataclasses.replace(post, digest=digest))
                return True
            except discord.NotFound:
                log.info("The %s post for %s was deleted; posting it again", kind, key)
            except discord.HTTPException as exc:
                if exc.status != 400:
                    log.warning("Could not edit the %s post for %s: %s", kind, key, exc)
                    return False
                # A post from before the layout redesign that Discord won't convert: replace it.
                log.info("Replacing the %s post for %s (old format): %s", kind, key, exc)
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
        try:
            msg = await channel.send(view=view, allowed_mentions=NO_MENTIONS)
        except discord.HTTPException as exc:
            log.warning("Could not post %s %s: %s", kind, key, exc)
            return False
        thread_id = None
        if thread_name:
            try:
                thread = await msg.create_thread(name=thread_name[:100], auto_archive_duration=10080)
                thread_id = thread.id
            except discord.HTTPException as exc:
                log.warning("Could not open a thread for %s: %s", key, exc)
        self.store.save_post(Post(kind, key, channel.id, msg.id, thread_id, digest))
        return True

    async def sync_log_group(self, inst: str, night: str) -> bool:
        """One #loot-log post per raid and night, edited as more awards arrive (split if it gets long)."""
        async with self._locks[f"log:{inst}|{night}"]:
            parts = render.log_cards(self.store.log_group(inst, night))
            ok = True
            for i, card in enumerate(parts):
                ok &= await self._upsert_card("log", f"{inst}|{night}|{i}", self.config.ch_log, card)
                if not ok:
                    break
            return ok

    async def post_priorities(self, day: str, raid: str | None) -> int:
        channel = self._text_channel(self.config.ch_priorities)
        if channel is None:
            raise UserError("I can't find the #loot-priorities channel: check CHANNEL_LOOT_PRIORITIES in .env.")
        parts = render.priorities_cards(self.store.item_states(), day, raid,
                                        self.channel_mention(self.config.ch_items))
        for card in parts:
            await channel.send(view=card_layout(card), allowed_mentions=NO_MENTIONS)
        return len(parts)

    # ---- errors ------------------------------------------------------------

    async def _on_app_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, NotOfficer):
            msg = "That's for officers."
        elif isinstance(original, UserError):
            msg = str(original)
        elif isinstance(original, app_commands.CheckFailure):
            msg = "You can't use that here."
        else:
            name = interaction.command.qualified_name if interaction.command else "?"
            log.error("Error in /%s: %s", name, "".join(traceback.format_exception(original)))
            msg = "Something went wrong; it's in the bot's log."
        await reply(interaction, msg, ephemeral=True)


async def reply(interaction: discord.Interaction, content: str | None = None, *, embed: discord.Embed | None = None,
                ephemeral: bool = False) -> None:
    kwargs: dict = {"ephemeral": ephemeral, "allowed_mentions": NO_MENTIONS}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    try:
        if interaction.response.is_done():
            await interaction.followup.send(**kwargs)
        else:
            await interaction.response.send_message(**kwargs)
    except discord.HTTPException as exc:
        log.warning("Reply failed: %s", exc)
