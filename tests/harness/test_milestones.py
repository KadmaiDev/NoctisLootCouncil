"""Level milestones end to end: officers with milestones on in the addon see the guild roster, log out, their
companion apps send the level-ups, and the bot congratulates each milestone once in #milestones. An
officer's alt in another guild runs the addon too, and none of that guild reaches the bot."""
from __future__ import annotations

import time

from .helpers import companion_pass, token_for

LEVELS_BEFORE = [("Vespera Ashward", 19, "WARLOCK", "Raider"), ("Ilsa Marrow", 59, "WARLOCK", "Raider"),
                 ("Bran Holloway", 18, "MAGE", "Raider"), ("Thorn Gale", 60, "WARRIOR", "Officer"),
                 ("Kadmai Moonwhisper", 41, "HUNTER", "Officer")]


def roster(**levels: int) -> list[tuple[str, int, str, str]]:
    """LEVELS_BEFORE with some members' levels changed (by first name)."""
    return [(n, levels.get(n.split()[0].lower(), lv), c, r) for n, lv, c, r in LEVELS_BEFORE]


async def test_level_ups_are_congratulated_once_for_the_guild_only(guild, running, realm):
    kadmai, seren = guild.officers[2], guild.officers[0]
    milestones = guild.channel("milestones")

    # Setting up: officers only, and not on without a guild and channel.
    r = await guild.slash(guild.raiders[0], "milestones settings", announce=True)
    assert "That's for officers." in r.text
    r = await guild.slash(kadmai, "milestones settings", announce=True)
    assert "Set the guild and the channel first" in r.text
    r = await guild.slash(kadmai, "milestones settings", guild="Noctis", channel=milestones, announce=True)
    assert "Turned on" in r.text and "Guild: Noctis" in r.text and f"<#{milestones.id}>" in r.text

    # Two officers run the addon; so does an alt of Doran's in another guild.
    realm.clock = int(time.time())
    realm.lm.milestones = realm.seren.milestones = True
    alt = realm.add_player("Secret", "Alt", "MAGE", rank="Officer", guild="Other Guild", milestones=True)
    realm.login()
    realm.roster(LEVELS_BEFORE)  # first read: nothing to announce
    realm.wait(600)
    realm.roster(roster(vespera=20, ilsa=60, bran=31))
    realm.logout()

    tokens = {o.name: await token_for(guild, o) for o in guild.officers}
    await companion_pass(realm.lm, running.api_url, tokens["Kadmai"])
    posts = await guild.wait_until(lambda: len(milestones.posts) == 3 and milestones.posts,
                                   what="three milestone posts")
    text = "\n".join(p.text for p in posts)
    assert "Vespera Ashward reached level 20" in text
    assert "Bran Holloway reached level 30" in text  # 18 to 31: one post, for 30
    assert "Bran Holloway reached level 20" not in text
    assert "Ilsa Marrow reached level 60" in text
    assert "The 2nd in Noctis to get there." in text  # after Thorn Gale, already 60
    assert "Warlock · Raider" in text

    # Seren's roster saw the same: nothing new. The alt's guild never leaves Doran's PC.
    await companion_pass(realm.seren, running.api_url, tokens["Seren"])
    await companion_pass(alt, running.api_url, tokens["Doran"])
    await guild.wait_until(lambda: not running.bot.store.pending_milestones(), what="the poster to finish")
    assert len(milestones.posts) == 3
    assert running.bot.store.milestone_counts() == (5, 3, 0)

    # Off: uploads are ignored. /milestones settings shows where it stands.
    r = await guild.slash(seren, "milestones settings", announce=False)
    assert "Level milestones: **Off**" in r.text and "milestones posted: 3" in r.text
