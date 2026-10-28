"""The Discord client: starts the HTTP API, and keeps every post in step with the database.

Posting works from the database, not from events: anything that changes an item marks it dirty,
and `sync_pending` renders and edits (or first sends) its posts. So a restart, a failed send or
two uploads at once can't duplicate a post; at worst a post is a little late.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
import traceback
from collections import defaultdict
from zoneinfo import ZoneInfo

import aiohttp
import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands

from . import iteminfo, render
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
# After a failed Wowhead lookup, posts go out without icons for this long rather than wait on it each time.
LOOKUP_PAUSE_SECONDS = 600
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
        # Item icons and links (iteminfo.py); tests swap these for fakes.
        self.lookup = iteminfo.fetch
        self.fetch_icon = iteminfo.fetch_icon
        self._http: aiohttp.ClientSession | None = None
        self._lookup_paused_until = 0.0
        self._app_emojis: dict[str, str] | None = None
        self._emoji_failed: set[str] = set()

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
        if self._http:
            await self._http.close()
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
        try:
            await self.look_up_items()
        except Exception:  # noqa: BLE001 - icons are a nicety: post without them
            log.exception("Item lookup failed")
        for item_id, generation in self.store.dirty_items():
            if await self.sync_item(item_id):
                self.store.clear_item_dirty(item_id, generation)
        for inst, night, generation in self.store.dirty_log_groups():
            if await self.sync_log_group(inst, night):
                self.store.clear_log_dirty(inst, night, generation)

    async def look_up_items(self) -> None:
        """Icons, slots and links from Wowhead for the items about to be posted, and the icons as
        the bot's emojis for list lines. Done before posting, so the posts go out with them."""
        if not self.config.wowhead or time.monotonic() < self._lookup_paused_until:
            return
        if self._http is None:
            self._http = aiohttp.ClientSession(headers={"User-Agent": "NoctisLootBot (guild loot bot)"})
        for item_id in self.store.items_to_look_up():
            info = await self.lookup(self._http, item_id)
            if info is None:  # Wowhead or the network is down
                self._lookup_paused_until = time.monotonic() + LOOKUP_PAUSE_SECONDS
                return
            self.store.save_item_info(item_id, info)
        for icon in self.store.icons_without_emoji():
            if icon not in self._emoji_failed:
                emoji = await self._icon_emoji(icon)
                if emoji:
                    self.store.save_icon_emoji(icon, emoji)
                else:
                    self._emoji_failed.add(icon)  # not again until a restart

    async def _icon_emoji(self, icon: str) -> str | None:
        """The bot's own (application) emoji for an icon, uploading it the first time."""
        name = icon[:32]
        try:
            if self._app_emojis is None:
                self._app_emojis = {e.name: str(e) for e in await self.fetch_application_emojis()}
            if name not in self._app_emojis:
                image = await self.fetch_icon(self._http, icon)
                if image is None:
                    return None
                self._app_emojis[name] = str(await self.create_application_emoji(name=name, image=image))
        except discord.HTTPException as exc:
            log.warning("Could not make an emoji for %s: %s", icon, exc)
            return None
        return self._app_emojis[name]

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
            ok = await self._upsert_card("officer", str(item_id), self.config.ch_officers, officer, item_id)
            ok &= await self._upsert_card("items", str(item_id), self.config.ch_items,
                                          render.items_card(state, self.tz), item_id)
            return ok

    async def _upsert_card(self, kind: str, key: str, channel_id: int, card: render.Card,
                           item_id: int | None = None) -> bool:
        # No thread per post (they were dropped 2026-10-28 as clutter): officers start one with
        # Discord's own Create Thread when an item needs discussing.
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
        self.store.save_post(Post(kind, key, channel.id, msg.id, None, digest))
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
