"""Level milestones: the upload, which milestone a level-up earns, the store, the API and the posts."""
from __future__ import annotations

import pytest

from bot import milestones
from bot.api import create_app
from bot.milestones import Milestone, milestone_for, parse_levels, parse_milestone_upload
from bot.upload import BadUpload

from .conftest import TZ, Clock
from .test_poster import FakeChannel, make_bot, text

MS_CHANNEL = 20


def body(levels=(), members=(), guild="Noctis", uploader="Kadmai Moonwhisper") -> dict:
    return {"uploader": uploader, "guild": guild, "realm": "Forever",
            "members": [{"name": n, "level": lv, "class": c, "rank": r} for n, lv, c, r in members],
            "levels": [{"name": n, "from": f, "to": t, "at": at, "class": c} for n, f, t, at, c in levels]}


def turn_on(store, guild="Noctis"):
    return store.set_milestone_settings(on=True, guild=guild, channel_id=MS_CHANNEL)


def apply(store, *levels, members=(), guild="Noctis", who="Kadmai"):
    return store.apply_milestones(parse_milestone_upload(body(levels, members, guild)), who)


# ---- pure ----------------------------------------------------------------------------------------

def test_levels_are_parsed_sorted_and_checked():
    assert parse_levels("10, 20,30 40") == (10, 20, 30, 40)
    assert parse_levels("60,10,10") == (10, 60)
    for bad in ("", "ten", "1", "10,-5", "999"):
        with pytest.raises(ValueError):
            parse_levels(bad)


def test_a_level_up_earns_the_highest_milestone_it_passed():
    levels = milestones.DEFAULT_LEVELS
    assert milestone_for(19, 20, levels) == 20
    assert milestone_for(18, 31, levels) == 30
    assert milestone_for(20, 29, levels) is None
    assert milestone_for(59, 60, levels) == 60
    assert milestone_for(1, 9, levels) is None


def test_bad_uploads_are_refused():
    ok = body([("Vespera Ashward", 19, 20, 100, "DRUID")])
    parse_milestone_upload(ok)
    for broken in ({**ok, "guild": ""}, {**ok, "guild": None}, {**ok, "levels": {}},
                   {**ok, "levels": [{"name": "X", "from": 20, "to": 19, "at": 1}]},
                   {**ok, "levels": [{"name": "X", "from": 1, "to": 900, "at": 1}]},
                   {**ok, "members": [{"name": "X", "level": "60"}]}, []):
        with pytest.raises(BadUpload):
            parse_milestone_upload(broken)


def test_the_card_congratulates_in_the_class_colour():
    m = Milestone(key="vespera ashward", name="Vespera Ashward", level=40, at=1793046600, cls="DRUID", rank="Raider")
    card = milestones.card(m, milestones.DEFAULT_LEVELS, TZ)
    assert card.title == "Vespera Ashward reached level 40"
    assert card.subtitle == "Druid · Raider"
    assert card.colour == 0xFF7C0A
    assert card.body == "**Congratulations!** Next stop: level 50."
    assert card.footer == "Noticed 26 Oct, 20:30"
    top = milestones.card(Milestone(key="t", name="Thorn Gale", level=60, at=1793046600, cls="WARRIOR", nth=3,
                                    top=True, guild="Noctis"), milestones.DEFAULT_LEVELS, TZ)
    assert top.body == "**Congratulations on reaching max level!** The 3rd in Noctis to get there."
    unknown = milestones.card(Milestone(key="x", name="X", level=10, at=0), milestones.DEFAULT_LEVELS, TZ)
    assert unknown.colour == milestones.GOLD and unknown.subtitle == ""


def test_ordinals():
    assert [milestones.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st", "111th"]


# ---- the store -----------------------------------------------------------------------------------

def test_nothing_is_taken_while_off_or_without_a_guild(store, clock):
    now = int(clock())
    assert apply(store, ("Vespera Ashward", 19, 20, now, "DRUID")) == (0, "milestones are off")
    store.set_milestone_settings(on=True, channel_id=MS_CHANNEL)
    assert apply(store, ("Vespera Ashward", 19, 20, now, "DRUID")) == (0, "milestones are off")
    assert store.milestone_counts() == (0, 0, 0)


def test_another_guilds_roster_is_ignored(store, clock):
    turn_on(store)
    clock.t += 60
    now = int(clock())
    assert apply(store, ("Vespera Ashward", 19, 20, now, "DRUID"), guild="Other Guild") == (0, "another guild")
    assert apply(store, ("Vespera Ashward", 19, 20, now, "DRUID"), guild="noctis ") == (1, None)


def test_a_roster_alone_posts_nothing(store, clock):
    turn_on(store)
    queued, _ = apply(store, members=[("Thorn Gale", 60, "WARRIOR", "Officer"), ("Vespera Ashward", 19, "DRUID", "Raider")])
    assert queued == 0
    assert store.milestone_counts() == (2, 0, 0)


def test_each_milestone_is_posted_once_whoever_saw_it(store, clock):
    turn_on(store)
    clock.t += 3600
    now = int(clock())
    apply(store, members=[("Vespera Ashward", 20, "DRUID", "Raider")])
    assert apply(store, ("Vespera Ashward", 19, 20, now - 60, "DRUID")) == (1, None)
    [m] = store.pending_milestones()
    assert (m.name, m.level, m.cls, m.rank, m.top) == ("Vespera Ashward", 20, "DRUID", "Raider", False)
    # Another officer saw it too, later and from further back: nothing new.
    assert apply(store, ("Vespera Ashward", 15, 21, now, "DRUID"), who="Seren") == (0, None)
    # A bigger jump earns the next milestone; a lower one after it never posts.
    clock.t += 600
    assert apply(store, ("Vespera Ashward", 21, 31, int(clock()), "DRUID")) == (1, None)
    assert apply(store, ("Vespera Ashward", 15, 25, int(clock()), "DRUID"), who="Seren") == (0, None)
    assert [p.level for p in store.pending_milestones()] == [20, 30]


def test_old_news_and_news_from_before_it_was_on_are_not_posted(store, clock):
    turn_on(store)
    since = int(clock())
    clock.t += 8 * 86400
    now = int(clock())
    assert apply(store, ("Old News", 9, 10, now - 7 * 86400 - 1, "MAGE")) == (0, None)
    assert apply(store, ("Fresh", 9, 10, now - 3600, "MAGE")) == (1, None)
    # Off and on again: what happened while it was off stays unannounced.
    store.set_milestone_settings(on=False)
    clock.t += 3600
    store.set_milestone_settings(on=True)
    assert store.milestone_settings().since == int(clock()) > since
    assert apply(store, ("While Off", 9, 10, int(clock()) - 60, "MAGE")) == (0, None)


def test_max_level_counts_who_got_there(store, clock):
    turn_on(store)
    clock.t += 60
    apply(store, members=[("Thorn Gale", 60, "WARRIOR", "Officer"), ("Ilsa Marrow", 60, "WARLOCK", "Raider")])
    apply(store, ("Corvin Dusk", 59, 60, int(clock()), "WARLOCK"))
    [m] = store.pending_milestones()
    assert m.top and m.nth == 3 and m.guild == "Noctis"


def test_settings_keep_what_isnt_changed(store):
    s = store.set_milestone_settings(guild="Noctis")
    assert (s.on, s.guild, s.channel_id, s.levels) == (False, "Noctis", None, milestones.DEFAULT_LEVELS)
    s = store.set_milestone_settings(levels=(10, 60), channel_id=5)
    assert (s.guild, s.channel_id, s.levels, s.ready) == ("Noctis", 5, (10, 60), False)
    s = store.set_milestone_settings(on=True)
    assert s.ready


# ---- the API -------------------------------------------------------------------------------------

@pytest.fixture
async def api(aiohttp_client, store):
    calls: list[int] = []
    client = await aiohttp_client(create_app(store, lambda: calls.append(1)))
    client.notified = calls
    client.auth = {"Authorization": f"Bearer {store.issue_token('discord:1', 'Kadmai')}"}
    return client


async def test_the_companion_is_told_whether_to_upload_and_for_which_guild(api, store):
    assert (await api.get("/api/milestones")).status == 401
    r = await api.get("/api/milestones", headers=api.auth)
    assert await r.json() == {"on": False, "guild": None}
    store.set_milestone_settings(guild="Noctis")
    assert await (await api.get("/api/milestones", headers=api.auth)).json() == {"on": False, "guild": None}
    store.set_milestone_settings(on=True)
    assert await (await api.get("/api/milestones", headers=api.auth)).json() == {"on": True, "guild": "Noctis"}


async def test_milestone_uploads(api, store, clock):
    sample = body([("Vespera Ashward", 19, 20, int(clock()) + 10, "DRUID")])
    assert (await api.post("/api/milestones", json=sample)).status == 401
    r = await api.post("/api/milestones", json=sample, headers=api.auth)
    assert await r.json() == {"ok": True, "ignored": "milestones are off", "new_milestones": 0}
    assert api.notified == []
    turn_on(store)
    r = await api.post("/api/milestones", json=sample, headers=api.auth)
    assert await r.json() == {"ok": True, "new_milestones": 1}
    assert api.notified == [1]
    r = await api.post("/api/milestones", json={"guild": "Noctis", "levels": "x"}, headers=api.auth)
    assert r.status == 400


# ---- posting -------------------------------------------------------------------------------------

async def test_milestones_are_posted_once_and_wait_for_their_channel(tmp_path):
    channels: dict = {}
    bot = make_bot(tmp_path, channels)
    bot.store.set_milestone_settings(on=True, guild="Noctis", channel_id=MS_CHANNEL)
    now = bot.store.now()
    bot.store.apply_milestones(parse_milestone_upload(body([("Vespera Ashward", 19, 20, now + 5, "DRUID")])), "Kadmai")
    await bot.post_milestones()  # no channel yet: it waits
    assert bot.store.milestone_counts() == (1, 0, 1)
    channels[MS_CHANNEL] = FakeChannel(MS_CHANNEL)
    await bot.post_milestones()
    await bot.post_milestones()
    ch = channels[MS_CHANNEL]
    assert ch.sends == 1
    assert "### Vespera Ashward reached level 20" in text(next(iter(ch.messages.values())))
    assert bot.store.milestone_counts() == (1, 1, 0)


async def test_nothing_is_posted_while_off(tmp_path):
    channels = {MS_CHANNEL: FakeChannel(MS_CHANNEL)}
    bot = make_bot(tmp_path, channels)
    clock = Clock(1793046600)
    bot.store._clock = clock
    bot.store.set_milestone_settings(on=True, guild="Noctis", channel_id=MS_CHANNEL)
    clock.t += 60
    bot.store.apply_milestones(parse_milestone_upload(body([("Vespera Ashward", 19, 20, int(clock.t), "DRUID")])),
                               "Kadmai")
    bot.store.set_milestone_settings(on=False)
    await bot.post_milestones()
    assert channels[MS_CHANNEL].sends == 0
    # Back on: it happened before, so it's dropped rather than posted late.
    clock.t += 60
    bot.store.set_milestone_settings(on=True)
    await bot.post_milestones()
    assert channels[MS_CHANNEL].sends == 0
    assert bot.store.milestone_counts() == (1, 0, 0)
