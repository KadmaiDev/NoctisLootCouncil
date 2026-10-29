"""The whole system for a week: officers decide in (fake) Discord, the companion app brings the
decisions into the game, a raid night runs in the realm, the companion uploads it, the bot posts
it, the officers vote on what's new, and the next night the game knows."""
from __future__ import annotations

import pytest

from harness.realm import find_luajit

from .helpers import CLOAK, COUNCIL, HELM, SASH, companion_pass, decide, token_for

pytestmark = pytest.mark.skipif(find_luajit() is None, reason="LuaJIT not found (set LUAJIT)")

WEEK = 7 * 24 * 3600


async def test_week_one(guild, running, realm):
    r = realm
    seren_d, doran_d, kadmai_d = guild.officers
    lm_token = await token_for(guild, kadmai_d)
    seren_token = await token_for(guild, seren_d)

    # Between raids, in Discord: the sash is a council item (Warlock priority), the helm is rolled.
    await guild.slash(seren_d, "loot add", item="18000", name="Sash of the Unseen", slot="Waist · Cloth")
    await guild.slash(seren_d, "loot add", item="16866", name="Helm of Might", slot="Head · Plate")
    await decide(guild, 18000, "Council", "Warlock priority")
    await decide(guild, 16866, "Roll")

    # The companion apps on the loot master's and Seren's PCs write the decisions addon.
    await companion_pass(r.lm, running.api_url, lm_token)
    await companion_pass(r.seren, running.api_url, seren_token)
    assert r.lm.decisions_file.exists()

    # Raid night. The loot master's game reads the decisions at login.
    r.login()
    assert any("Decisions from" in line and "1 council, 1 roll." in line for line in r.lm.printed), r.lm.printed
    r.lm.equip_item(17109, "Armor", "Cloth", "INVTYPE_CLOAK")
    r.lm.type("/nlc councillors " + COUNCIL)
    r.kill(663, "Lucifron")
    r.loot(r.lm, [(SASH, 4), (HELM, 4), (CLOAK, 4)])
    assert any("First time seen" in line for line in r.lm.printed)

    # The sash goes to the council, as Discord decided.
    r.lm.type("/nlc start " + SASH)
    assert "Council item:" in r.said()
    r.ilsa.check("BIS")
    r.ilsa.click("Main spec")
    r.vespera.click("Main spec")
    r.wait(31)
    r.seren.check("Biggest upgrade")
    r.seren.click("Vote", near="Ilsa Marrow")
    r.doran.check("Biggest upgrade")
    r.doran.click("Vote", near="Ilsa Marrow")
    r.lm.check("Biggest upgrade")
    r.lm.click("Vote", near="Ilsa Marrow")
    r.wait(2)
    assert f"Ilsa Marrow wins {SASH}" in r.said()
    r.give(SASH, r.ilsa)

    # The helm is rolled; the new cloak too (nobody has decided it).
    r.set_rolls(r.doran, 71)
    r.set_rolls(r.bran, 30)
    r.lm.type("/nlc start " + HELM)
    assert "Roll for" in r.said().splitlines()[-1]
    r.doran.click("Main spec")
    r.bran.roll()
    r.wait(31)
    r.give(HELM, r.doran)
    r.set_rolls(r.vespera, 64)
    r.lm.type("/nlc start " + CLOAK)
    r.vespera.click("Main spec")
    r.wait(31)
    r.give(CLOAK, r.vespera)
    assert [a["who"] for a in r.lm.query("ns.db.log")] == ["Ilsa Marrow", "Doran Pike", "Vespera Ashward"]
    r.logout()

    # After the raid: both officers' companions upload. The bot posts the night once, with every
    # drop counted once, and puts the new cloak up for a vote.
    await companion_pass(r.lm, running.api_url, lm_token)
    await companion_pass(r.seren, running.api_url, seren_token)
    log_post = await guild.wait_until(lambda: guild.channel("loot-log").find("Vespera Ashward"),
                                      what="the loot log")
    assert "Ilsa Marrow" in log_post.text and "Doran Pike" in log_post.text
    assert len(guild.channel("loot-log").posts) == 1
    store = running.bot.store
    assert store.item_state(18000).drops == 1 and store.item_state(17109).drops == 1
    cloak_post = await guild.wait_until(lambda: guild.channel("loot-officers").find("NEW IN OUR RAID"),
                                        what="the new item's post")
    assert "Cloak of the Shrouded Mists" in cloak_post.text and "Back · Cloth" in cloak_post.text
    assert store.item_state(18000).first_award.tags == "BIS"

    # The officers make the cloak a council item; the companion brings it into the game.
    await decide(guild, 17109, "Council", "Tanks first")
    await companion_pass(r.lm, running.api_url, lm_token)

    # Next week: the loot master's game knows, and the cloak goes to the council.
    r.skip(WEEK)
    r.login()
    assert any("2 council, 1 roll." in line for line in r.lm.printed), r.lm.printed
    cloak = r.lm.query("ns.db.items[17109]")
    assert (cloak["handling"], cloak["note"]) == ("council", "Tanks first")
    r.kill(663, "Lucifron")
    r.loot(r.lm, [(CLOAK, 4)])
    r.lm.type("/nlc start " + CLOAK)
    assert "Council item:" in r.said().splitlines()[-1]


async def test_a_decision_taken_back_in_discord_is_forgotten_in_game(guild, running, realm):
    r = realm
    kadmai_d = guild.officers[2]
    token = await token_for(guild, kadmai_d)
    await guild.slash(kadmai_d, "loot add", item="18000", name="Sash of the Unseen")
    await decide(guild, 18000, "Council", "Warlock priority")
    await companion_pass(r.lm, running.api_url, token)
    r.login()
    assert r.lm.query("ns.db.items[18000].handling") == "council"
    r.logout()
    await companion_pass(r.lm, running.api_url, token)  # uploads the game's copy of the decision

    post = guild.channel("loot-officers").find("Sash of the Unseen")
    clicked = await guild.click(kadmai_d, post, "Roll")  # 2 council, 1 roll: no longer decided
    assert "Decided" not in clicked.text
    # The companion uploads the game's old copy again before writing the new decisions; the
    # bot mustn't take it for a decision made in game (it did, when both fell in one second).
    await companion_pass(r.lm, running.api_url, token)
    r.skip(3600)
    r.login()
    sash = r.lm.query("ns.db.items[18000]")
    assert sash.get("handling") is None and sash.get("note") is None
    r.logout()
    # The game's next upload doesn't bring the old decision back.
    await companion_pass(r.lm, running.api_url, token)
    assert running.bot.store.decisions()["items"]["18000"]["handling"] == "none"
