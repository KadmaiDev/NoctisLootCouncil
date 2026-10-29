"""What one officer's game records differently from another's, or takes back, reaching the bot right:
copies of a drop seen in the loot window and in chat, and an award undone after it was uploaded."""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from bot.db import connect
from bot.store import Store
from bot.upload import parse_upload
from companion import savedfile
from harness.realm import find_luajit

from .helpers import HELM, SASH, companion_pass, token_for

pytestmark = pytest.mark.skipif(find_luajit() is None, reason="LuaJIT not found (set LUAJIT)")


def body_of(player) -> dict:
    """What the companion app on this player's PC uploads."""
    return savedfile.build_upload(savedfile.read_saved_file(player.saved_file))


def test_two_copies_seen_in_the_window_and_in_chat_count_twice_in_either_upload_order(realm, tmp_path):
    r = realm
    r.login()
    r.kill(663, "Lucifron")
    r.loot(r.lm, [(SASH, 4), (SASH, 4)])  # two copies in the loot master's window
    r.wait(60)
    r.give(SASH, r.ilsa)  # everyone sees each copy handed out, a minute apart
    r.wait(60)
    r.give(SASH, r.vespera)
    r.logout()
    lm, seren = body_of(r.lm), body_of(r.seren)
    # The two addons' own records of the same two copies: one entry of two, two entries of one.
    assert [(d["src"], d["n"]) for d in lm["drops"]] == [("e663", 2)]
    assert [(d["src"], d["n"]) for d in seren["drops"]] == [("e663", 1), ("e663", 1)]

    for name, order in (("window first", (lm, seren)), ("chat first", (seren, lm))):
        store = Store(connect(tmp_path / f"{name}.db"), ZoneInfo("Europe/London"))
        for body in (*order, *order):  # and each uploaded again
            store.apply_upload(parse_upload(body), "discord:1", body["uploader"])
            assert store.item_state(18000).drops == 2, name
        store.conn.close()


async def test_an_award_undone_after_its_upload_leaves_the_loot_log(guild, running, realm):
    r = realm
    token = await token_for(guild, guild.officers[2])
    r.login()
    r.kill(663, "Lucifron")
    r.loot(r.lm, [(HELM, 4)])
    r.set_rolls(r.doran, 71)
    r.lm.type("/nlc start " + HELM)
    r.doran.roll()
    r.wait(31)
    assert f"Doran Pike wins {HELM}" in r.said()
    r.logout()  # a /reload: the companion uploads the award and the bot posts it
    await companion_pass(r.lm, running.api_url, token)
    log = guild.channel("loot-log")
    await guild.wait_until(lambda: log.find("Doran Pike"), what="the award in the loot log")

    # It was the wrong winner: the loot master takes it back and rolls the helm again.
    r.login()
    r.lm.type("/nlc undo")
    r.set_rolls(r.bran, 50)
    r.lm.type("/nlc start " + HELM)
    r.bran.roll()
    r.wait(31)
    assert [a["who"] for a in r.lm.query("ns.db.log")] == ["Bran Holloway"]
    r.logout()
    await companion_pass(r.lm, running.api_url, token)
    post = await guild.wait_until(lambda: log.find("Bran Holloway"), what="the corrected award")
    await guild.wait_until(lambda: "Doran Pike" not in log.find("Bran Holloway").text, what="the undone award gone")
    assert len(log.posts) == 1 and log.posts[0].id == post.id
    assert [row["who"] for row in running.bot.store.conn.execute("SELECT who FROM awards")] == ["Bran Holloway"]
