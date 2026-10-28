"""The Discord-facing poster, against fake channels: no network, no token."""
from __future__ import annotations

import dataclasses
import itertools
import re
from types import SimpleNamespace

import discord
import pytest

from bot.client import LootBot
from bot.config import Config
from bot.iteminfo import ItemInfo
from bot.rules import COUNCIL
from bot.upload import parse_upload
from bot.views import DYNAMIC_ITEMS, PriorityButton, SuggestButton, VoteButton

from .conftest import sample_body

OFFICERS, ITEMS, PRIORITIES, LOG = 10, 11, 12, 13
_ids = itertools.count(1000)


class FakeChannel:
    def __init__(self, cid: int):
        self.id = cid
        self.messages: dict[int, dict] = {}
        self.sends = 0
        self.edits = 0
        self.threads: list[str] = []

    async def send(self, content=None, **kwargs):
        self.sends += 1
        mid = next(_ids)
        self.messages[mid] = {"content": content, **kwargs}
        channel = self

        class Msg:
            id = mid

            async def create_thread(self, name, auto_archive_duration):
                channel.threads.append(name)
                return SimpleNamespace(id=next(_ids))
        return Msg()

    def get_partial_message(self, mid: int):
        channel = self

        class Partial:
            async def edit(self, **kwargs):
                if mid not in channel.messages:
                    raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")
                if channel.messages[mid].get("embed"):  # an old-style post Discord won't turn into a layout
                    raise discord.HTTPException(SimpleNamespace(status=400, reason="Bad Request"), "Invalid Form Body")
                channel.edits += 1
                channel.messages[mid].update(kwargs)

            async def delete(self):
                channel.messages.pop(mid, None)
        return Partial()


def text(msg: dict) -> str:
    """What a sent layout message says."""
    return "\n".join(c.content for c in msg["view"].walk_children() if isinstance(c, discord.ui.TextDisplay))


def buttons(msg: dict) -> list[str]:
    items = (getattr(c, "item", c) for c in msg["view"].walk_children())  # the buttons are DynamicItems
    return [b.label for b in items if isinstance(b, discord.ui.Button)]


def make_bot(tmp_path, channels) -> LootBot:
    cfg = Config(token="x", guild_id=1, officer_role_id=2, ch_officers=OFFICERS, ch_items=ITEMS,
                 ch_priorities=PRIORITIES, ch_log=LOG, api_host="127.0.0.1", api_port=0, votes_to_decide=3,
                 db_path=tmp_path / "loot.db", timezone="Europe/London", wowhead=False)
    bot = LootBot(cfg)
    bot._text_channel = lambda cid: channels.get(cid)  # type: ignore[method-assign]
    return bot


@pytest.fixture
def channels():
    return {cid: FakeChannel(cid) for cid in (OFFICERS, ITEMS, PRIORITIES, LOG)}


async def test_upload_posts_once_and_survives_restart(tmp_path, channels):
    bot = make_bot(tmp_path, channels)
    bot.store.apply_upload(parse_upload(sample_body()), "discord:1", "Kadmai")
    await bot.sync_pending()
    assert channels[OFFICERS].sends == 3 and channels[ITEMS].sends == 3
    assert channels[LOG].sends == 1
    assert sorted(channels[OFFICERS].threads) == ["Felheart Gloves", "Item 17069", "Sash of the Unseen"]
    log_text = text(next(iter(channels[LOG].messages.values())))
    assert log_text.startswith("### Molten Core · Monday 26 Oct\n-# 2 items")

    # Restart: a new client on the same database posts nothing new.
    bot2 = make_bot(tmp_path, channels)
    bot2.store.mark_all_dirty()
    await bot2.sync_pending()
    assert channels[OFFICERS].sends == 3 and channels[ITEMS].sends == 3 and channels[LOG].sends == 1
    assert channels[OFFICERS].edits == 0 and channels[LOG].edits == 0

    # The same upload again from another officer: nothing new either.
    bot2.store.apply_upload(parse_upload(sample_body("Seren Ashvale")), "discord:2", "Seren")
    await bot2.sync_pending()
    assert channels[LOG].sends == 1 and channels[OFFICERS].sends == 3


async def test_votes_edit_posts_and_remove_suggest_button(tmp_path, channels):
    bot = make_bot(tmp_path, channels)
    bot.store.add_item(16805, "Felheart Gloves")
    await bot.sync_pending()
    items_msg = next(iter(channels[ITEMS].messages.values()))
    assert buttons(items_msg) == ["Suggest for council · 0"]
    for uid in (1, 2, 3):
        bot.store.cast_vote(16805, uid, f"O{uid}", COUNCIL)
    await bot.sync_item(16805)
    assert channels[OFFICERS].sends == 1 and channels[OFFICERS].edits == 1
    assert buttons(items_msg) == []  # council items have no Suggest button
    assert "**Council item**" in text(items_msg)


async def test_old_style_posts_are_replaced_by_layout_posts(tmp_path, channels):
    bot = make_bot(tmp_path, channels)
    bot.store.add_item(16805, "Felheart Gloves")
    await bot.sync_pending()
    for ch in (channels[OFFICERS], channels[ITEMS]):
        next(iter(ch.messages.values()))["embed"] = object()  # as the bot posted before the redesign
    bot.store.toggle_suggestion(16805, 5)
    await bot.sync_pending()
    assert channels[ITEMS].sends == 2 and len(channels[ITEMS].messages) == 1
    assert "Suggest for council · 1" in buttons(next(iter(channels[ITEMS].messages.values())))
    assert not bot.store.dirty_items()


async def test_more_awards_edit_the_nights_log_post(tmp_path, channels):
    bot = make_bot(tmp_path, channels)
    body = sample_body()
    bot.store.apply_upload(parse_upload(body), "discord:1", "Kadmai")
    await bot.sync_pending()
    body["awards"].append({"id": 17069, "who": "Doran Pike", "at": body["awards"][-1]["at"] + 600, "how": "os",
                           "roll": 12, "inst": "Molten Core", "nms": 0, "nos": 1})
    bot.store.apply_upload(parse_upload(body), "discord:1", "Kadmai")
    await bot.sync_pending()
    assert channels[LOG].sends == 1 and channels[LOG].edits == 1
    log_text = text(next(iter(channels[LOG].messages.values())))
    assert "3 items" in log_text and "Doran Pike" in log_text


async def test_deleted_post_is_posted_again(tmp_path, channels):
    bot = make_bot(tmp_path, channels)
    bot.store.add_item(18000, "Sash of the Unseen")
    await bot.sync_pending()
    channels[ITEMS].messages.clear()  # someone deleted it
    bot.store.toggle_suggestion(18000, 5)
    await bot.sync_pending()
    assert channels[ITEMS].sends == 2


async def test_missing_channel_keeps_work_for_later(tmp_path, channels):
    del channels[ITEMS]
    bot = make_bot(tmp_path, channels)
    bot.store.add_item(18000, "Sash")
    await bot.sync_pending()
    assert [i for i, _ in bot.store.dirty_items()] == [18000]


async def test_priorities_post(tmp_path, channels):
    bot = make_bot(tmp_path, channels)
    bot.store.add_item(18000, "Sash of the Unseen", source="Molten Core, Gehennas")
    for uid in (1, 2, 3):
        bot.store.cast_vote(18000, uid, f"O{uid}", COUNCIL)
    bot.store.set_priority(18000, "Warlock priority", "Seren")
    assert await bot.post_priorities("Thursday 29 Oct", "Molten Core") == 1
    post = text(next(iter(channels[PRIORITIES].messages.values())))
    assert post.splitlines()[:3] == ["### Molten Core · Thursday 29 Oct", "-# Council items",
                                     "- **Sash of the Unseen** · Warlock priority"]


class FakeWowhead:
    """Stands in for Wowhead and the bot's application emojis."""

    def __init__(self, known: dict[int, ItemInfo], up: bool = True):
        self.known, self.up = known, up
        self.asked: list[int] = []
        self.emojis: list[str] = []

    def install(self, bot: LootBot) -> None:
        bot.config = dataclasses.replace(bot.config, wowhead=True)
        bot.lookup = self.lookup
        bot.fetch_icon = self.fetch_icon
        bot.fetch_application_emojis = self.fetch_application_emojis
        bot.create_application_emoji = self.create_application_emoji

    async def lookup(self, session, item_id):
        self.asked.append(item_id)
        return self.known.get(item_id, ItemInfo(found=False)) if self.up else None

    async def fetch_icon(self, session, icon):
        return b"jpeg"

    async def fetch_application_emojis(self):
        return []

    async def create_application_emoji(self, *, name, image):
        self.emojis.append(name)
        return f"<:{name}:{len(self.emojis)}>"


async def test_posts_get_the_icon_link_and_emoji(tmp_path, channels):
    bot = make_bot(tmp_path, channels)
    wowhead = FakeWowhead({16805: ItemInfo(found=True, env="forever", name="Felheart Gloves", quality=4,
                                           icon="inv_gauntlets_19", slot="Hands · Cloth")})
    wowhead.install(bot)
    bot.store.apply_upload(parse_upload(sample_body()), "discord:1", "Kadmai")
    await bot.sync_pending()
    assert sorted(wowhead.asked) == [16805, 17069, 18000] and wowhead.emojis == ["inv_gauntlets_19"]
    officer = next(m for m in channels[OFFICERS].messages.values() if "Felheart" in text(m))
    thumbs = [c for c in officer["view"].walk_children() if isinstance(c, discord.ui.Thumbnail)]
    assert [t.media.url for t in thumbs] == ["https://wow.zamimg.com/images/wow/icons/large/inv_gauntlets_19.jpg"]
    assert "### [Felheart Gloves](https://www.wowhead.com/forever/item=16805/felheart-gloves)" in text(officer)
    log_text = text(next(iter(channels[LOG].messages.values())))
    assert "<:inv_gauntlets_19:1> Felheart Gloves → **Corvin Dusk**" in log_text
    # Items Wowhead doesn't know go without, and nothing is asked again on the next pass.
    sash = next(m for m in channels[OFFICERS].messages.values() if "Sash" in text(m))
    assert "### Sash of the Unseen" in text(sash)
    assert not [c for c in sash["view"].walk_children() if isinstance(c, discord.ui.Thumbnail)]
    bot.store.mark_all_dirty()
    await bot.sync_pending()
    assert len(wowhead.asked) == 3 and channels[OFFICERS].edits == 0


async def test_wowhead_down_posts_without_icons_and_pauses_lookups(tmp_path, channels):
    bot = make_bot(tmp_path, channels)
    wowhead = FakeWowhead({}, up=False)
    wowhead.install(bot)
    bot.store.add_item(16805, "Felheart Gloves")
    await bot.sync_pending()
    assert channels[ITEMS].sends == 1 and "### Felheart Gloves" in text(next(iter(channels[ITEMS].messages.values())))
    bot.store.toggle_suggestion(16805, 5)
    await bot.sync_pending()
    assert wowhead.asked == [16805]  # paused, not asked on every change
    assert bot.store.items_to_look_up() == [16805]  # still owed a lookup


def test_button_custom_ids_round_trip():
    for item, cid in ((VoteButton(18000, "council"), "nlc:vote:council:18000"),
                      (VoteButton(18000, "roll"), "nlc:vote:roll:18000"),
                      (PriorityButton(18000), "nlc:prio:18000"),
                      (SuggestButton(18000), "nlc:suggest:18000")):
        assert item.custom_id == cid
        assert any(re.fullmatch(cls.__discord_ui_compiled_template__, cid) for cls in DYNAMIC_ITEMS)


async def test_cog_loads_with_the_commands(tmp_path, channels):
    bot = make_bot(tmp_path, channels)
    await bot.load_extension("bot.cogs.loot")
    group = bot.tree.get_command("loot")
    assert sorted(c.name for c in group.commands) == ["add", "priorities", "status", "token"]
