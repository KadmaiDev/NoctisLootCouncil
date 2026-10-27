"""Raid nights in the realm: every player with the addon runs the real addon on the fake client,
in their own process; the realm delivers chat, addon messages and rolls between them."""
from __future__ import annotations

import pytest

from harness.realm import Realm, find_luajit

from .helpers import COUNCIL, HELM, SASH

pytestmark = pytest.mark.skipif(find_luajit() is None, reason="LuaJIT not found (set LUAJIT)")


@pytest.fixture
def realm(tmp_path):
    r = Realm(tmp_path / "pcs")
    r.lm = r.add_player("Kadmai", "Moonwhisper", "HUNTER", rank="Officer", leader=True)
    r.seren = r.add_player("Seren", "Vale", "PRIEST", rank="Officer")
    r.doran = r.add_player("Doran", "Pike", "WARRIOR", rank="Officer")
    r.ilsa = r.add_player("Ilsa", "Marrow", "WARLOCK")
    r.vespera = r.add_player("Vespera", "Ashward", "WARLOCK")
    r.odo = r.add_player("Odo", "Fenwick", "MAGE", rank="Trial")
    r.bran = r.add_player("Bran", "Holloway", "MAGE", addon=False)  # rolls in chat
    yield r
    r.close()


def test_a_roll_from_the_pop_up_and_from_chat(realm):
    r = realm
    r.login()
    r.kill(663, "Lucifron")
    r.loot(r.lm, [(SASH, 4)])
    r.lm.type("/nlc start " + SASH)
    assert r.ilsa.sees("Main spec") and r.odo.sees("Main spec")
    r.set_rolls(r.ilsa, 40)
    r.set_rolls(r.vespera, 88)
    r.set_rolls(r.odo, 99)
    r.set_rolls(r.bran, 95)
    r.ilsa.click("Main spec")
    r.vespera.click("Off spec")
    r.odo.click("Main spec")  # a trial: loses to any member's main-spec roll
    r.bran.roll(100)
    r.wait(31)
    assert "10 seconds left to roll" in r.said()
    assert f"Bran Holloway wins {SASH} (main spec, 95)." in r.said()
    [award] = r.lm.query("ns.db.log")
    assert (award["who"], award["how"], award["boss"], award["nms"], award["nos"]) == \
        ("Bran Holloway", "ms", "Lucifron", 3, 1)
    assert not r.ilsa.sees("Main spec")  # the pop-up closed for everyone


def test_main_spec_winners_drop_to_the_second_tier_for_the_night(realm):
    r = realm
    r.login()
    r.kill(663, "Lucifron")
    r.loot(r.lm, [(SASH, 4), (HELM, 4)])
    r.set_rolls(r.ilsa, 90, 99)
    r.set_rolls(r.vespera, 10, 5)
    r.lm.type("/nlc start " + SASH)
    r.ilsa.click("Main spec")
    r.vespera.click("Main spec")
    r.wait(31)
    r.lm.type("/nlc start " + HELM)
    r.ilsa.click("Main spec")
    r.vespera.click("Main spec")
    r.wait(31)
    log = r.lm.query("ns.db.log")
    assert [(a["who"], a["how"]) for a in log] == [("Ilsa Marrow", "ms"), ("Vespera Ashward", "ms")]


def council_night(r):
    r.login()
    r.lm.type("/nlc councillors " + COUNCIL)
    r.lm.type(f"/nlc council {SASH} Warlock priority")
    r.kill(663, "Lucifron")
    r.loot(r.lm, [(SASH, 4)])
    r.lm.type("/nlc start " + SASH)


def test_council_bids_go_only_to_the_council_and_a_clear_vote_awards(realm):
    r = realm
    council_night(r)
    # Raiders bid from the pop-up: tags and a note for council items.
    r.ilsa.check("BIS")
    r.ilsa.set_text("NoctisLootCouncilPopupNote", "first upgrade in weeks")
    r.ilsa.click("Main spec")
    r.vespera.click("Main spec")
    r.wait(31)  # bids close; the vote starts
    bids = r.addon_messages("B")
    assert bids and all(channel == "WHISPER" for _, channel, _, _ in bids)
    assert {target for _, _, target, _ in bids} <= {"Seren Vale", "Doran Pike", "Kadmai Moonwhisper"}
    # The council sees the candidates; raiders don't.
    assert r.seren.sees("Ilsa Marrow") and r.seren.sees("first upgrade in weeks")
    assert not r.vespera.sees("first upgrade in weeks")
    r.seren.click("Vote", near="Ilsa Marrow")
    r.doran.click("Vote", near="Ilsa Marrow")
    r.lm.click("Vote", near="Vespera Ashward")
    r.wait(2)
    assert f"Ilsa Marrow wins {SASH}" in r.said()
    [award] = r.lm.query("ns.db.log")
    assert (award["who"], award["how"], award["tags"]) == ("Ilsa Marrow", "council", "BIS")
    assert "first upgrade in weeks" in award["note"]
    # The councillors' windows show the result too.
    assert r.seren.sees("Awarded to Ilsa Marrow.")


def test_a_split_vote_goes_to_a_roll_off_between_the_tied(realm):
    r = realm
    council_night(r)
    r.ilsa.click("Main spec")
    r.vespera.click("Main spec")
    r.wait(31)
    r.seren.click("Vote", near="Ilsa Marrow")
    r.doran.click("Vote", near="Vespera Ashward")
    r.wait(301)  # Kadmai never votes: the time runs out, 1-1
    assert "Roll-off for" in r.said()
    r.set_rolls(r.ilsa, 12)
    r.set_rolls(r.vespera, 70)
    r.ilsa.roll()
    r.vespera.roll()
    r.wait(31)
    assert f"Vespera Ashward wins {SASH} (council: roll-off after a split vote, 70)." in r.said()
    assert r.lm.query("ns.db.log")[0]["who"] == "Vespera Ashward"
