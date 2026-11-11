"""The guild roster channel's bot side: the upload's `seen` and `scanned`, who is in the guild now, the
settings, the database added to a live one, and the poster that keeps the channel's posts in step.
(roster.py, the pure wording, is tested in test_roster.py.)"""
from __future__ import annotations

import sqlite3

import discord
import pytest

from bot import roster
from bot.db import connect
from bot.milestones import GOLD, parse_milestone_upload
from bot.model import RosterPost
from bot.upload import BadUpload
from bot.views import board_embed

from .conftest import RAID, Clock
from .test_poster import FakeChannel, FakeWowhead, make_bot, text

ROSTER_CHANNEL, OTHER_CHANNEL = 30, 31


def body(members, scanned=None, levels=(), guild="Noctis") -> dict:
    """members: (name, level, class, rank, seen); seen None is left out, as older companions do."""
    out = {"uploader": "Kadmai Moonwhisper", "guild": guild, "realm": "Forever",
           "members": [{"name": n, "level": lv, "class": c, "rank": r, **({"seen": s} if s is not None else {})}
                       for n, lv, c, r, s in members],
           "levels": [{"name": n, "from": f, "to": t, "at": at, "class": c} for n, f, t, at, c in levels]}
    if scanned is not None:
        out["scanned"] = scanned
    return out


def apply(store, members, scanned=None, **kw):
    return store.apply_milestones(parse_milestone_upload(body(members, scanned, **kw)), "Kadmai")


def names(store) -> list[str]:
    return sorted(c.name for c in store.roster_characters())


def turn_on(store):
    store.set_milestone_settings(on=True, guild="Noctis", channel_id=20)


# ---- the upload ----------------------------------------------------------------------------------

def test_seen_and_scanned_are_read_and_may_be_missing():
    up = parse_milestone_upload(body([("Vespera Ashward", 20, "DRUID", "Raider", 1000)], scanned=1000))
    assert up.scanned == 1000 and up.members[0].seen == 1000
    old = parse_milestone_upload(body([("Vespera Ashward", 20, "DRUID", "Raider", None)]))
    assert old.scanned is None and old.members[0].seen is None
    for bad in ({"scanned": "1000"}, {"scanned": -1}, {"scanned": True}, {"scanned": 1.5}):
        with pytest.raises(BadUpload):
            parse_milestone_upload({**body([]), **bad})
    with pytest.raises(BadUpload):
        parse_milestone_upload(body([("X", 20, None, None, "yesterday")]))


# ---- who is in the guild -------------------------------------------------------------------------

def test_a_roster_read_with_under_half_the_guild_removes_nobody(store, clock):
    turn_on(store)
    t = int(clock()) - 3600
    everyone = [(f"Member {i}", 30, "MAGE", "Raider", t) for i in range(10)]
    apply(store, everyone, t)
    later = t + 1800
    apply(store, [(n, lv, c, r, later if i < 4 else t) for i, (n, lv, c, r, _) in enumerate(everyone)], later)
    assert len(names(store)) == 10 and store.roster_scanned() == t
    # Half or more is a real read: the rest have left.
    apply(store, [(n, lv, c, r, later if i < 5 else t) for i, (n, lv, c, r, _) in enumerate(everyone)], later)
    assert len(names(store)) == 5 and store.roster_scanned() == later


def test_a_member_missing_from_a_later_roster_has_left(store, clock):
    turn_on(store)
    t = int(clock()) - 3600
    apply(store, [("Vespera Ashward", 20, "DRUID", "Raider", t), ("Thorn Gale", 60, "WARRIOR", "Officer", t)], t)
    assert names(store) == ["Thorn Gale", "Vespera Ashward"]
    # The addon keeps those who left, with the time it last saw them.
    later = t + 1800
    apply(store, [("Vespera Ashward", 20, "DRUID", "Raider", t), ("Thorn Gale", 60, "WARRIOR", "Officer", later)], later)
    assert names(store) == ["Thorn Gale"]
    assert store.roster_scanned() == later
    # Back in the guild: back on the roster.
    again = later + 600
    apply(store, [("Vespera Ashward", 21, "DRUID", "Trial", again), ("Thorn Gale", 60, "WARRIOR", "Officer", again)], again)
    assert names(store) == ["Thorn Gale", "Vespera Ashward"]


def test_two_officers_rosters(store, clock):
    turn_on(store)
    t = int(clock()) - 7200
    # Seren read the roster an hour ago; Kadmai reads it now, and Vespera has left since.
    apply(store, [("Vespera Ashward", 20, "DRUID", "Raider", t), ("Thorn Gale", 60, "WARRIOR", "Officer", t)], t)
    now = t + 3600
    apply(store, [("Vespera Ashward", 20, "DRUID", "Raider", t - 86400),
                  ("Thorn Gale", 60, "WARRIOR", "Officer", now), ("Bran Holloway", 31, "MAGE", "Raider", now)], now)
    assert names(store) == ["Bran Holloway", "Thorn Gale"]
    # Seren's older file again (a re-upload): it can't bring Vespera back, or move the newest read back.
    apply(store, [("Vespera Ashward", 20, "DRUID", "Raider", t), ("Thorn Gale", 60, "WARRIOR", "Officer", t)], t)
    assert names(store) == ["Bran Holloway", "Thorn Gale"] and store.roster_scanned() == now
    # Within the slack, a read a few minutes apart (clocks differ) still counts.
    apply(store, [("Corvin Dusk", 40, "WARLOCK", "Raider", now - 200)], now - 200)
    assert "Corvin Dusk" in names(store)


def test_an_old_companion_without_seen_puts_nobody_on_the_roster(store, clock):
    turn_on(store)
    apply(store, [("Vespera Ashward", 20, "DRUID", "Raider", None)])
    assert store.roster_characters() == [] and store.roster_scanned() is None
    assert store.milestone_counts()[0] == 1  # milestones still know her
    t = int(clock()) - 60
    apply(store, [("Thorn Gale", 60, "WARRIOR", "Officer", t)], t)
    assert names(store) == ["Thorn Gale"]


def test_level_stays_the_highest_and_rank_follows_the_newest_roster(store, clock):
    turn_on(store)
    t = int(clock()) - 3600
    apply(store, [("Vespera Ashward", 22, "DRUID", "Trial", t + 600)], t + 600)
    # An older roster (another officer's file from before): lower level, the old rank. Neither wins.
    apply(store, [("vespera ashward", 20, "DRUID", "Applicant", t)], t)
    [c] = store.roster_characters()
    assert (c.name, c.level, c.rank) == ("Vespera Ashward", 22, "Trial")
    # An old companion's upload (no seen) doesn't change what a newer roster said either.
    apply(store, [("Vespera Ashward", 21, "DRUID", "Applicant", None)])
    assert store.roster_characters()[0].rank == "Trial"
    # A newer roster: promoted.
    apply(store, [("Vespera Ashward", 22, "DRUID", "Raider", t + 1200)], t + 1200)
    assert store.roster_characters()[0].rank == "Raider"


def test_times_from_the_future_are_taken_as_now(store, clock):
    turn_on(store)
    now = int(clock())
    apply(store, [("Vespera Ashward", 20, "DRUID", "Raider", now + 86400)], now + 86400)
    assert store.roster_scanned() == now
    # A read an hour later on a correct clock still sees her as in the guild.
    clock.t += 3600
    apply(store, [("Vespera Ashward", 20, "DRUID", "Raider", now + 3600), ("Thorn Gale", 60, None, None, now + 3600)],
          now + 3600)
    assert names(store) == ["Thorn Gale", "Vespera Ashward"]


def test_nothing_is_taken_while_milestones_are_off_or_for_another_guild(store, clock):
    t = int(clock()) - 60
    apply(store, [("Vespera Ashward", 20, "DRUID", "Raider", t)], t)
    turn_on(store)
    apply(store, [("Secret Alt", 30, "MAGE", None, t)], t, guild="Other Guild")
    assert store.roster_characters() == [] and store.roster_scanned() is None


def test_roster_changes_mark_it_dirty_and_nothing_else_does(store, clock):
    turn_on(store)
    t = int(clock()) - 60
    gen = store.roster_dirty()
    apply(store, [("Vespera Ashward", 20, "DRUID", "Raider", t)], t)
    assert store.roster_dirty() > gen
    store.clear_roster_dirty(store.roster_dirty())
    assert store.roster_dirty() == 0
    apply(store, [("Vespera Ashward", 20, "DRUID", "Raider", t)], t)  # the same roster again
    assert store.roster_dirty() == 0
    store.set_roster_settings(min_level=20)
    assert store.roster_dirty() == 1
    store.clear_roster_dirty(5)  # an older generation: not cleared
    assert store.roster_dirty() == 1


def test_roster_settings_keep_what_isnt_changed(store):
    s = store.roster_settings()
    assert (s.on, s.channel_id, s.min_level, s.hidden_ranks) == (False, None, roster.DEFAULT_MIN_LEVEL, ())
    s = store.set_roster_settings(channel_id=ROSTER_CHANNEL, hidden_ranks=("Trial", "Alt, Main"))
    assert (s.on, s.channel_id, s.hidden_ranks) == (False, ROSTER_CHANNEL, ("Trial", "Alt, Main"))
    s = store.set_roster_settings(on=True, min_level=1)
    assert s.ready and s.min_level == 1 and s.hidden_ranks == ("Trial", "Alt, Main")
    s = store.set_roster_settings(hidden_ranks=())
    assert s.hidden_ranks == ()


def test_the_column_is_added_to_a_database_from_before(tmp_path):
    path = tmp_path / "live.db"
    old = sqlite3.connect(path)
    old.executescript("CREATE TABLE ms_characters (key TEXT PRIMARY KEY, name TEXT NOT NULL, class TEXT, rank TEXT, "
                      "level INTEGER NOT NULL, seen_at INTEGER NOT NULL);"
                      "INSERT INTO ms_characters VALUES ('thorn gale', 'Thorn Gale', 'WARRIOR', 'Officer', 60, 1);")
    old.commit()
    old.close()
    conn = connect(path)
    row = conn.execute("SELECT * FROM ms_characters").fetchone()
    assert row["name"] == "Thorn Gale" and row["roster_seen"] is None
    connect(path).close()  # and again: nothing to add


# ---- the poster ----------------------------------------------------------------------------------

MEMBERS = [("Thorn Gale", 60, "WARRIOR", "Officer"), ("Vespera Ashward", 20, "DRUID", "Raider"),
           ("Bran Holloway", 31, "MAGE", "Raider"), ("Pip Newly", 15, "MAGE", "Trial")]


def roster_bot(tmp_path, channels):
    bot = make_bot(tmp_path, channels)
    bot.store._clock = Clock(RAID)
    bot.store.set_milestone_settings(on=True, guild="Noctis", channel_id=20)
    bot.store.set_roster_settings(on=True, channel_id=ROSTER_CHANNEL, hidden_ranks=("Trial",))
    return bot


def upload(bot, members=MEMBERS, at=None):
    at = at or bot.store.now()
    apply(bot.store, [(*m, at) for m in members], at)


async def sync(bot):
    await bot.sync_pending()


def keys(bot) -> list[str]:
    return [p.key for p in bot.store.roster_posts()]


def big_guild(n: int) -> list[tuple]:
    """Enough warriors with long names that the roster needs more than one message."""
    return MEMBERS + [(f"Warrior{i:03d} Withaverylongsurname", 20 + i % 40, "WARRIOR", "Raider") for i in range(n)]


async def test_the_roster_is_one_embed_edited_in_place(tmp_path):
    channels = {ROSTER_CHANNEL: FakeChannel(ROSTER_CHANNEL)}
    bot = roster_bot(tmp_path, channels)
    upload(bot)
    await sync(bot)
    ch = channels[ROSTER_CHANNEL]
    assert keys(bot) == ["roster"] and ch.sends == 1
    [msg] = ch.messages.values()
    embed = msg["embed"]
    assert isinstance(embed, discord.Embed) and "view" not in msg
    assert embed.title == "Noctis · Guild roster" and embed.colour.value == GOLD
    assert [(f.name, f.inline) for f in embed.fields] == [("Druid (1)", True), ("Mage (1)", True), ("Warrior (1)", True)]
    assert "Pip Newly" not in text(msg)  # a trial: hidden

    # Nothing changed: nothing sent or edited, even after a restart.
    await sync(bot)
    bot2 = make_bot(tmp_path, channels)
    bot2.store.mark_all_dirty()
    await sync(bot2)
    assert ch.sends == 1 and ch.edits == 0

    # A mage levels: the one post is edited, with the embed only.
    upload(bot2, [("Bran Holloway", 32, "MAGE", "Raider") if m[0] == "Bran Holloway" else m for m in MEMBERS],
           at=bot2.store.roster_scanned())
    await sync(bot2)
    assert ch.sends == 1 and ch.edits == 1
    assert "`32` **Bran Holloway**" in text(ch.messages[bot2.store.roster_posts()[0].message_id])
    assert "view" not in msg and "attachments" not in msg


def test_a_board_becomes_an_embed():
    chars = [roster.Character(f"Warrior{i:03d} Withaverylongsurname", 60, "WARRIOR") for i in range(200)]
    result = roster.boards(chars, roster.Settings(on=True, channel_id=1), "Noctis", 1, {"WARRIOR": "<:class_warrior:9>"})
    first, second = (board_embed(b) for _, b in result[:2])
    assert first.title == "Noctis · Guild roster" and first.description.startswith("\N{BUSTS IN SILHOUETTE} **200**")
    assert first.fields[0].name == "<:class_warrior:9> Warrior (200)" and first.fields[0].inline
    assert second.title is None and second.description is None and second.colour == first.colour
    assert [(f.name, f.value, f.inline) for f in second.fields] == list(result[1][1].fields)
    assert second.fields[0].name == "<:class_warrior:9> Warrior (continued)"
    for e, (_, b) in zip((first, second), result):
        # discord.py's own count of an embed's characters (code points: ours, in UTF-16 units, is never less)
        assert len(e) <= b.size() <= 6000


async def test_a_roster_grown_into_more_messages_is_posted_again_in_order(tmp_path):
    channels = {ROSTER_CHANNEL: FakeChannel(ROSTER_CHANNEL)}
    bot = roster_bot(tmp_path, channels)
    upload(bot)
    await sync(bot)
    ch = channels[ROSTER_CHANNEL]
    first = set(ch.messages)
    # A hundred and fifty warriors join: too many for one message; the post is deleted and they're posted in order.
    bot.store._clock.t += 600
    upload(bot, big_guild(150))
    await sync(bot)
    assert keys(bot)[:2] == ["roster", "roster#2"] and len(keys(bot)) == len(ch.messages)
    assert not first & set(ch.messages)
    assert [p.message_id for p in bot.store.roster_posts()] == sorted(ch.messages)
    assert ch.messages[min(ch.messages)]["embed"].title == "Noctis · Guild roster"
    # Level 60 and up only: back to one message.
    bot.store.set_roster_settings(min_level=60)
    await sync(bot)
    assert keys(bot) == ["roster"] and len(ch.messages) == 1
    assert [f.name for f in next(iter(ch.messages.values()))["embed"].fields] == ["Warrior (1)"]


async def test_cards_from_before_are_replaced_by_the_embed(tmp_path):
    """A database from the card version holds posts keyed header, DRUID...: they're deleted and the
    embed is posted (a layout post can't be edited into an embed)."""
    channels = {ROSTER_CHANNEL: FakeChannel(ROSTER_CHANNEL)}
    bot = roster_bot(tmp_path, channels)
    ch = channels[ROSTER_CHANNEL]
    for position, key in enumerate(("header", "DRUID", "MAGE", "WARRIOR")):
        msg = await ch.send(view=object())
        bot.store.save_roster_post(RosterPost(key, position, ROSTER_CHANNEL, msg.id, "old"))
    upload(bot)
    await sync(bot)
    assert keys(bot) == ["roster"] and len(ch.messages) == 1 and ch.edits == 0
    assert isinstance(next(iter(ch.messages.values()))["embed"], discord.Embed)


async def test_a_deleted_post_or_a_new_channel_moves_the_posts(tmp_path):
    channels = {ROSTER_CHANNEL: FakeChannel(ROSTER_CHANNEL), OTHER_CHANNEL: FakeChannel(OTHER_CHANNEL)}
    bot = roster_bot(tmp_path, channels)
    upload(bot, big_guild(150))
    await sync(bot)
    ch, other = channels[ROSTER_CHANNEL], channels[OTHER_CHANNEL]
    count = len(keys(bot))
    assert count > 1 and ch.sends == count
    # Someone deletes the first post; the next change to it finds it gone and reposts them all.
    ch.messages.pop(bot.store.roster_posts()[0].message_id)
    upload(bot, [("Bran Holloway", 33, "MAGE", "Raider") if m[0] == "Bran Holloway" else m for m in big_guild(150)],
           at=bot.store.roster_scanned())
    await sync(bot)
    assert len(ch.messages) == count and ch.sends == 2 * count
    # The channel changes: gone from the old one, posted in the new one.
    bot.store.set_roster_settings(channel_id=OTHER_CHANNEL)
    await sync(bot)
    assert ch.messages == {} and len(other.messages) == count
    assert {p.channel_id for p in bot.store.roster_posts()} == {OTHER_CHANNEL}


async def test_off_leaves_the_posts_as_they_are(tmp_path):
    channels = {ROSTER_CHANNEL: FakeChannel(ROSTER_CHANNEL)}
    bot = roster_bot(tmp_path, channels)
    upload(bot)
    await sync(bot)
    ch = channels[ROSTER_CHANNEL]
    bot.store.set_roster_settings(on=False)
    bot.store._clock.t += 600
    upload(bot, MEMBERS[:2])  # the mage and the trial have left
    await sync(bot)
    assert ch.sends == 1 and ch.edits == 0 and "Bran Holloway" in text(next(iter(ch.messages.values())))
    # Milestones off stops it too (the roster comes with their upload).
    bot.store.set_roster_settings(on=True)
    bot.store.set_milestone_settings(on=False)
    await sync(bot)
    assert ch.sends == 1 and ch.edits == 0
    bot.store.set_milestone_settings(on=True)
    await sync(bot)
    [msg] = ch.messages.values()
    assert ch.edits == 1 and [f.name for f in msg["embed"].fields] == ["Druid (1)", "Warrior (1)"]


async def test_on_again_brings_back_posts_deleted_while_off(tmp_path):
    channels = {ROSTER_CHANNEL: FakeChannel(ROSTER_CHANNEL)}
    bot = roster_bot(tmp_path, channels)
    upload(bot)
    await sync(bot)
    ch = channels[ROSTER_CHANNEL]
    bot.store.set_roster_settings(on=False)
    await sync(bot)
    ch.messages.clear()
    bot.store.set_roster_settings(on=True)
    await sync(bot)
    assert len(ch.messages) == 1 and ch.sends == 2
    assert [p.message_id for p in bot.store.roster_posts()] == sorted(ch.messages)


async def test_no_channel_waits_and_retries(tmp_path):
    channels: dict = {}
    bot = roster_bot(tmp_path, channels)
    upload(bot)
    await sync(bot)
    assert bot.store.roster_dirty() > 0 and keys(bot) == []
    channels[ROSTER_CHANNEL] = FakeChannel(ROSTER_CHANNEL)
    await sync(bot)
    assert bot.store.roster_dirty() == 0 and keys(bot) == ["roster"]


# ---- class emojis --------------------------------------------------------------------------------

async def test_class_emojis_are_made_once_and_the_roster_edited_when_they_arrive(tmp_path):
    channels = {ROSTER_CHANNEL: FakeChannel(ROSTER_CHANNEL)}
    bot = roster_bot(tmp_path, channels)
    wowhead = FakeWowhead({})
    wowhead.install(bot)
    asked: list[str] = []

    async def fetch_icon(session, icon):
        asked.append(icon)
        return b"jpeg"
    bot.fetch_icon = fetch_icon
    upload(bot, MEMBERS + [("Odd One", 30, "BARD", "Raider")])  # not a class the game has: no icon asked for
    await sync(bot)
    ch = channels[ROSTER_CHANNEL]
    # The trial's priest is hidden, so no priest icon either.
    assert sorted(asked) == ["classicon_druid", "classicon_mage", "classicon_warrior"]
    assert sorted(wowhead.emojis) == ["class_druid", "class_mage", "class_warrior"]
    [msg] = ch.messages.values()
    names = [f.name for f in msg["embed"].fields]
    assert names[0] == "Bard (1)" and names[1].startswith("<:class_druid:") and names[1].endswith("> Druid (1)")
    assert ch.sends == 1

    # Nothing more to make: nothing asked, nothing edited.
    bot.store.mark_all_dirty()
    await sync(bot)
    assert len(asked) == 3 and len(wowhead.emojis) == 3 and ch.edits == 0

    # A priest joins: one more icon, and the roster is edited with it.
    upload(bot, MEMBERS + [("Odd One", 30, "BARD", "Raider"), ("Lia Dawn", 25, "PRIEST", "Raider")],
           at=bot.store.roster_scanned())
    await sync(bot)
    assert asked[-1] == "classicon_priest" and wowhead.emojis[-1] == "class_priest"
    assert any(f.name.endswith("> Priest (1)") for f in msg["embed"].fields)
    assert ch.sends == 1


async def test_a_class_emoji_that_arrives_later_edits_the_roster(tmp_path):
    channels = {ROSTER_CHANNEL: FakeChannel(ROSTER_CHANNEL)}
    bot = roster_bot(tmp_path, channels)
    wowhead = FakeWowhead({})
    wowhead.install(bot)
    up = False

    async def fetch_icon(session, icon):
        return b"jpeg" if up else None  # Wowhead's pictures are down at first
    bot.fetch_icon = fetch_icon
    upload(bot)
    await sync(bot)
    ch = channels[ROSTER_CHANNEL]
    [msg] = ch.messages.values()
    assert [f.name for f in msg["embed"].fields] == ["Druid (1)", "Mage (1)", "Warrior (1)"]  # posted without
    assert wowhead.emojis == [] and bot.store.roster_dirty() == 0
    # Back up, and the pause over: the emojis are made and the roster edited once.
    up = True
    bot._lookup_paused_until = 0
    bot.notify()
    await sync(bot)
    assert len(wowhead.emojis) == 3 and ch.sends == 1 and ch.edits == 1
    assert all(f.name.startswith("<:class_") for f in msg["embed"].fields)


async def test_without_lookups_no_icons_are_asked_for(tmp_path):
    channels = {ROSTER_CHANNEL: FakeChannel(ROSTER_CHANNEL)}
    bot = roster_bot(tmp_path, channels)  # wowhead=False, as in the tests and the harness

    async def fetch_icon(session, icon):
        raise AssertionError("asked for an icon with lookups off")
    bot.fetch_icon = fetch_icon
    upload(bot)
    await sync(bot)
    assert keys(bot) == ["roster"]


def test_alt_ranks_are_kept_and_shown_in_the_settings(store):
    s = store.set_roster_settings(alt_ranks=("Alt", "Officer Alt"), hidden_ranks=("Trial",))
    assert s.alt_ranks == ("Alt", "Officer Alt") and s.hidden_ranks == ("Trial",)
    assert store.set_roster_settings(min_level=20).alt_ranks == ("Alt", "Officer Alt")
    assert "Alt ranks: Alt, Officer Alt" in roster.settings_text(s, None, (0, 0), True)
    assert store.set_roster_settings(alt_ranks=()).alt_ranks == ()
