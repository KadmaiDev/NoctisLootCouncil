"""The guild roster channel end to end: an officer turns milestones and the roster on in Discord, the
addon reads the guild roster, the real companion sends it with the milestones, and the bot keeps one
embed in the roster channel (a field per class, three to a row, as Raid-Helper's sign-ups), edited in
place as people level and leave, through a restart and a change of channel."""
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


def fields(message) -> dict[str, str]:
    """The embed's fields, name to value."""
    [embed] = message.embeds
    return {f["name"]: f["value"] for f in embed.get("fields") or []}


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
    [post] = await guild.wait_until(lambda: channel.posts, what="the roster's post")
    await guild.quiet()
    assert len(channel.posts) == 1 and not post.components  # a classic embed, not a layout
    [embed] = post.embeds
    assert embed["title"] == "Noctis · Guild roster"
    assert "**5** members" in embed["description"] and "**2** at level 60" in embed["description"]
    # Alphabetical, three to a row; no class emojis (lookups are off in the harness).
    assert list(fields(post)) == ["Hunter (1)", "Mage (1)", "Warlock (2)", "Warrior (1)"]
    assert all(f["inline"] for f in embed["fields"])
    assert fields(post)["Warlock (2)"] == "`60` **Ilsa Marrow**\n`20` **Vespera Ashward**"
    assert "Pip Newly" not in post.text and "Priest" not in post.text  # a trial: hidden
    assert "Tiny Alt" not in post.text  # below level 10
    r = await guild.slash(kadmai, "roster settings")
    assert "Characters in the guild: 7; listed: 5." in r.text

    # Bran levels: the one post is edited.
    stamp = edited(post)
    realm.skip(600)
    await read_and_send(realm, [("Bran Holloway", 32, *m[2:]) if m[0] == "Bran Holloway" else m for m in MEMBERS],
                        running.api_url, token)
    await guild.wait_until(lambda: "`32` **Bran Holloway**" in channel.posts[0].text, what="Bran's new level")
    await guild.quiet()
    assert [p.id for p in channel.posts] == [post.id] and edited(channel.posts[0]) != stamp

    # Vespera leaves the guild: gone from the warlocks, still the same post.
    realm.skip(600)
    await read_and_send(realm, [m for m in MEMBERS if m[0] != "Vespera Ashward" and m[0] != "Bran Holloway"]
                        + [("Bran Holloway", 32, "MAGE", "Raider")], running.api_url, token)
    await guild.wait_until(lambda: "Vespera" not in channel.posts[0].text, what="Vespera gone from the roster")
    assert "Warlock (1)" in fields(channel.posts[0]) and [p.id for p in channel.posts] == [post.id]

    # A restart posts nothing and edits nothing.
    await guild.quiet()
    stamp = edited(channel.posts[0])
    await stop_bot(running)
    again = await start_bot(guild.fake, tmp_path / "bot.db")
    try:
        await guild.quiet(1.0)
        assert [p.id for p in channel.posts] == [post.id] and edited(channel.posts[0]) == stamp

        # Another channel: the post moves.
        r = await guild.slash(kadmai, "roster settings", channel=moved_to)
        assert f"<#{moved_to.id}>" in r.text
        [moved] = await guild.wait_until(lambda: len(moved_to.posts) == 1 and not channel.posts and moved_to.posts,
                                         what="the roster in its new channel")
        assert moved.embeds[0]["title"] == "Noctis · Guild roster" and "Warrior (1)" in fields(moved)

        # Off: the post stays as it is, and the reply says so.
        r = await guild.slash(kadmai, "roster settings", show=False)
        assert "Guild roster: **Off**" in r.text and "stay as they are" in r.text
        assert len(moved_to.posts) == 1
    finally:
        await stop_bot(again)
    assert guild.unknown_routes == [], guild.unknown_routes
