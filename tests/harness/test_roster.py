"""The guild roster channel end to end: an officer turns milestones and the roster on in Discord, the
addon reads the guild roster, the real companion sends it with the milestones, and the bot keeps a post
per class in the roster channel, edited in place as people level and leave, through a restart and a
change of channel."""
from __future__ import annotations

import time

from .conftest import start_bot, stop_bot
from .helpers import companion_pass, token_for

MEMBERS = [("Vespera Ashward", 20, "WARLOCK", "Raider"), ("Ilsa Marrow", 60, "WARLOCK", "Raider"),
           ("Bran Holloway", 31, "MAGE", "Raider"), ("Thorn Gale", 60, "WARRIOR", "Officer"),
           ("Kadmai Moonwhisper", 41, "HUNTER", "Officer"), ("Pip Newly", 25, "PRIEST", "Trial"),
           ("Tiny Alt", 5, "ROGUE", "Raider")]


def edited(message) -> str | None:
    return message.payload.get("edited_timestamp")


async def read_and_send(realm, members, api_url, token) -> None:
    """Kadmai logs in, the addon reads the roster, Kadmai logs out and the companion sends it."""
    realm.login()
    realm.roster(members)
    realm.logout()
    await companion_pass(realm.lm, api_url, token)


async def test_the_roster_channel_follows_the_guild(guild, running, realm, tmp_path):
    kadmai = guild.officers[2]
    channel, moved_to = guild.channel("guild-roster"), guild.channel("officers-roster")

    # Officers only; not on without a channel.
    r = await guild.slash(guild.raiders[0], "roster settings", show=True)
    assert "That's for officers." in r.text
    r = await guild.slash(kadmai, "roster settings", show=True)
    assert "Set the channel first" in r.text
    r = await guild.slash(kadmai, "roster settings", channel=channel, hide_ranks="Trial", show=True)
    assert "Guild roster: **On**, but not posting until level milestones are on" in r.text
    assert "Hidden ranks: Trial." in r.text and f"<#{channel.id}>" in r.text
    r = await guild.slash(kadmai, "milestones settings", guild="Noctis", channel=guild.channel("milestones"),
                          announce=True)
    assert "Turned on" in r.text

    # The roster is read in the past (the bot takes no time from its future), with gaps between reads
    # longer than the slack, so a read without someone means they left.
    realm.clock = int(time.time()) - 7200
    realm.lm.milestones = True
    token = await token_for(guild, kadmai)
    await read_and_send(realm, MEMBERS, running.api_url, token)
    posts = await guild.wait_until(lambda: len(channel.posts) == 5 and channel.posts, what="the roster's five posts")
    texts = [p.text for p in posts]
    assert "Noctis · Guild roster" in texts[0]
    assert "Hunter (1)" in texts[1] and "Mage (1)" in texts[2] and "Warlock (2)" in texts[3] and "Warrior (1)" in texts[4]
    assert "**60** Ilsa Marrow" in texts[3] and "**20** Vespera Ashward" in texts[3]
    everything = "\n".join(texts)
    assert "Pip Newly" not in everything and "Priest" not in everything  # a trial: hidden
    assert "Tiny Alt" not in everything  # below level 10
    r = await guild.slash(kadmai, "roster settings")
    assert "Characters in the guild: 7; listed: 5." in r.text

    # Bran levels: the mages' post is edited (and the header, which says when the roster was read);
    # the other classes' posts aren't touched.
    ids = [p.id for p in posts]
    before = {p.id: edited(p) for p in posts}
    realm.skip(600)
    await read_and_send(realm, [("Bran Holloway", 32, *m[2:]) if m[0] == "Bran Holloway" else m for m in MEMBERS],
                        running.api_url, token)
    await guild.wait_until(lambda: "**32** Bran Holloway" in channel.posts[2].text, what="Bran's new level")
    await guild.quiet()
    assert [p.id for p in channel.posts] == ids
    assert [edited(p) == before[p.id] for p in channel.posts] == [False, True, False, True, True]

    # Vespera leaves the guild: gone from the warlocks' post, still the same posts.
    realm.skip(600)
    await read_and_send(realm, [m for m in MEMBERS if m[0] != "Vespera Ashward" and m[0] != "Bran Holloway"]
                        + [("Bran Holloway", 32, "MAGE", "Raider")], running.api_url, token)
    await guild.wait_until(lambda: "Vespera" not in channel.posts[3].text, what="Vespera gone from the roster")
    assert "Warlock (1)" in channel.posts[3].text and [p.id for p in channel.posts] == ids

    # A restart posts nothing and edits nothing.
    await guild.quiet()
    stamps = [edited(p) for p in channel.posts]
    await stop_bot(running)
    again = await start_bot(guild.fake, tmp_path / "bot.db")
    try:
        await guild.quiet(1.0)
        assert [p.id for p in channel.posts] == ids and [edited(p) for p in channel.posts] == stamps

        # Another channel: the posts move, in order.
        r = await guild.slash(kadmai, "roster settings", channel=moved_to)
        assert f"<#{moved_to.id}>" in r.text
        moved = await guild.wait_until(lambda: len(moved_to.posts) == 5 and not channel.posts and moved_to.posts,
                                       what="the roster in its new channel")
        assert "Guild roster" in moved[0].text and "Warrior (1)" in moved[4].text

        # Off: the posts stay as they are, and the reply says so.
        r = await guild.slash(kadmai, "roster settings", show=False)
        assert "Guild roster: **Off**" in r.text and "stay as they are" in r.text
        assert len(moved_to.posts) == 5
    finally:
        await stop_bot(again)
    assert guild.unknown_routes == [], guild.unknown_routes
