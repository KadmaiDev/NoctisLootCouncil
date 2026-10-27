from bot import render
from bot.model import AwardInfo, ItemState, LogGroup
from bot.rules import COUNCIL, ROLL, Vote, tally

from .conftest import RAID, TZ


def state(**kw) -> ItemState:
    base = dict(id=18000, name="Sash of the Unseen", quality=4, slot="Waist · Cloth",
                source_text="Molten Core, Gehennas", raid="Molten Core", created_at=RAID + 4 * 3600)
    base.update(kw)
    return ItemState(**base)


def votes(*pairs) -> list[Vote]:
    return [Vote(i, name, choice, i) for i, (name, choice) in enumerate(pairs)]


MOCKUP_VOTES = votes(("Seren", COUNCIL), ("Doran", COUNCIL), ("Lyra", ROLL), ("Kadmai", COUNCIL))


def test_officer_card_matches_mockup():
    s = state(tally=tally(MOCKUP_VOTES, 3), decision=COUNCIL, priority="Warlock priority", priority_by="Seren",
              suggestions=6)
    card = render.officer_card(s, TZ)
    assert card.title == "Sash of the Unseen"
    assert card.description == "Waist · Cloth · Molten Core, Gehennas · not dropped for us yet"
    assert card.colour == 0xA335EE
    fields = {f.name: f.value for f in card.fields}
    assert fields["Votes"] == "**Council 3** · Roll 1\nSeren, Doran, Kadmai · Lyra"
    assert fields["Priority"] == "Warlock priority\nset by Seren"
    assert fields["Raiders suggesting council"] == "6, from #loot-items"
    assert fields["In our raids"] == "No drops yet"
    assert fields["Decision"] == ("✅ Decided: **council item**, 3 of 4. "
                                  "Shown in #loot-items; in the addon after the next /reload.")
    assert [b.label for b in card.buttons] == ["Council", "Roll", "Set priority"]


def test_officer_card_new_in_raid():
    award = AwardInfo(item_id=16805, item_name="Felheart Gloves", who="Corvin Dusk", how="ms", at=RAID + 1000,
                      roll=77, nms=4, nos=1)
    s = state(id=16805, name="Felheart Gloves", slot="Hands · Cloth", source_text="Molten Core, Lucifron",
              new_in_raid=True, drops=1, first_drop_at=RAID + 900, last_drop_at=RAID + 900, first_award=award,
              suggestions=2)
    card = render.officer_card(s, TZ)
    assert card.author == "NEW IN OUR RAID LAST NIGHT"
    assert card.description == ("Hands · Cloth · Molten Core, Lucifron · rolled, won by Corvin Dusk (main spec, 77)\n"
                                "Wanted it: **4** main spec, **1** off spec")
    fields = {f.name: f.value for f in card.fields}
    assert fields["Votes"] == "None yet"
    assert fields["In our raids"] == "Dropped once, last Mon 26 Oct"
    assert "Decision" not in fields


def test_new_in_raid_posted_days_later_names_the_day():
    s = state(new_in_raid=True, drops=1, first_drop_at=RAID, last_drop_at=RAID, created_at=RAID + 3 * 86400)
    assert render.officer_card(s, TZ).author == "NEW IN OUR RAID ON MONDAY 26 OCT"


def test_officer_card_in_game_decision():
    s = state(game_handling=ROLL, game_note="tanks first", game_by="Kadmai Moonwhisper")
    fields = {f.name: f.value for f in render.officer_card(s, TZ).fields}
    assert fields["Decision"] == "Set in game by Kadmai Moonwhisper: **roll item**. A vote here replaces it."
    assert fields["Priority"] == "tanks first\nset in game by Kadmai Moonwhisper"


def test_items_card_council():
    s = state(tally=tally(MOCKUP_VOTES, 3), decision=COUNCIL, priority="Warlock priority")
    card = render.items_card(s, TZ)
    assert card.description == ("Waist · Cloth · Molten Core, Gehennas\n**Council item**\n"
                                "Priority: **Warlock priority**\n*Decided by the officers, 3 of 4.*")
    assert card.buttons == []  # council items show no button


def test_items_card_undecided_new_item():
    s = state(id=16805, name="Felheart Gloves", slot="Hands · Cloth", source_text="Molten Core, Lucifron",
              new_in_raid=True, drops=1, first_drop_at=RAID + 900, suggestions=2)
    card = render.items_card(s, TZ)
    assert card.description == ("Hands · Cloth · Molten Core, Lucifron · first seen last night\n"
                                "**Undecided · rolled**\nRolled until the officers decide.")
    assert [b.label for b in card.buttons] == ["Suggest for council · 2"]


def test_items_card_roll_item():
    s = state(name="Robe of Volatile Power", quality=3, tally=tally(votes(("A", ROLL), ("B", ROLL), ("C", ROLL)), 3),
              decision=ROLL)
    card = render.items_card(s, TZ)
    assert "**Roll item**" in card.description
    assert card.description.endswith("Main spec, then second main spec, then off spec.")
    assert card.colour == 0x0070DD
    assert [b.label for b in card.buttons] == ["Suggest for council · 0"]


def test_card_digest_changes_with_content():
    a = render.items_card(state(), TZ)
    assert a.digest() == render.items_card(state(), TZ).digest()
    assert a.digest() != render.items_card(state(suggestions=1), TZ).digest()


def test_suggestion_replies():
    assert render.suggestion_reply(True, 3) == "Thanks, that's 3 suggestions. The officers see the count when they decide."
    assert render.suggestion_reply(False, 1) == "Taken back. That leaves 1 suggestion."


def aw(name, who, how, roll=None, note=None, nms=None, nos=None, new=False) -> AwardInfo:
    return AwardInfo(item_id=1, item_name=name, who=who, how=how, at=RAID, roll=roll, note=note, nms=nms, nos=nos,
                     new_item=new)


def test_log_post_matches_mockup():
    group = LogGroup("Molten Core", "2026-10-26", [
        aw("Choker of Enlightenment", "Vespera Ashward", "ms", 91, nms=3, nos=0),
        aw("Sash of the Unseen", "Ilsa Marrow", "council",
           note="Warlock priority; biggest upgrade over raid gear; one item in two weeks"),
        aw("Felheart Gloves", "Corvin Dusk", "ms", 77, nms=4, nos=1, new=True),
        aw("Helm of Might", "Tarnia Moonwhisper", "ms", 90),
        aw("Robe of Volatile Power", "Bran Holloway", "os", 64),
        aw("Onslaught Girdle", "Doran Pike", "ms2", 58, nms=1, nos=0),
    ])
    [msg] = render.log_messages(group)
    assert msg.splitlines() == [
        "**Molten Core · Monday 26 Oct · 6 items**",
        "Choker of Enlightenment → **Vespera Ashward** · main-spec roll, 91",
        "Sash of the Unseen → **Ilsa Marrow** · council",
        '> "Warlock priority; biggest upgrade over raid gear; one item in two weeks"',
        "Felheart Gloves → **Corvin Dusk** · main-spec roll, 77 · new item",
        "Helm of Might → **Tarnia Moonwhisper** · main-spec roll, 90",
        "Robe of Volatile Power → **Bran Holloway** · off-spec roll, 64",
        "Onslaught Girdle → **Doran Pike** · second main-spec roll, 58 (nobody else wanted it)",
        "-# " + render.LOG_FOOTER,
    ]


def test_long_log_is_split_without_breaking_lines():
    group = LogGroup("Molten Core", "2026-10-26", [aw(f"Item number {i:03}", "Somebody Longname", "ms", 50)
                                                   for i in range(80)])
    parts = render.log_messages(group)
    assert len(parts) > 1
    assert all(len(p) <= 2000 for p in parts)
    assert parts[0].startswith("**Molten Core · Monday 26 Oct · 80 items**")
    assert parts[-1].endswith(render.LOG_FOOTER)
    assert sum(p.count(" → ") for p in parts) == 80


def test_markdown_in_player_text_is_escaped():
    line = render.award_line(aw("Sash", "Ilsa", "council", note="*best* upgrade"))
    assert '"\\*best\\* upgrade"' in line


def test_priorities_post_for_one_raid():
    states = [
        state(name="Sash of the Unseen", decision=COUNCIL, priority="Warlock priority"),
        state(id=2, name="Onslaught Girdle", decision=COUNCIL, priority="tanks first"),
        state(id=3, name="Robe of Volatile Power", decision=ROLL),
        state(id=4, name="Head of Onyxia", decision=COUNCIL, raid="Onyxia's Lair"),
    ]
    [msg] = render.priorities_messages(states, "Thursday 29 Oct", "Molten Core")
    assert msg.splitlines() == [
        "**Molten Core · Thursday 29 Oct · council items**",
        "Onslaught Girdle · tanks first",
        "Sash of the Unseen · Warlock priority",
        "",
        render.EVERYTHING_ELSE,
        "-# Think something should be a council item? Press Suggest for council on its post in #loot-items.",
    ]


def test_priorities_post_all_raids_grouped():
    states = [state(name="Sash", decision=COUNCIL), state(id=4, name="Head of Onyxia", game_handling=COUNCIL,
                                                          raid="Onyxia's Lair"),
              state(id=5, name="Mystery", decision=COUNCIL, raid=None)]
    [msg] = render.priorities_messages(states, "Thursday 29 Oct")
    lines = msg.splitlines()
    assert lines[:7] == ["**Thursday 29 Oct · council items**", "__Molten Core__", "Sash", "__Onyxia's Lair__",
                         "Head of Onyxia", "__Other__", "Mystery"]


def test_status_text():
    states = [state(decision=COUNCIL, priority="Warlock priority"), state(id=2, name="Robe", decision=ROLL),
              state(id=3, name="Gloves")]
    text = render.status_text(states)
    assert "• Sash of the Unseen (Molten Core) · Warlock priority" in text
    assert "**Roll items:** 1" in text
    assert "**Undecided:** 1" in text
    assert render.item_status(states[2]) == "**Gloves**: undecided, rolled until the officers decide."
    assert render.item_status(state(game_handling=ROLL, game_by="Kadmai", suggestions=2)) == (
        "**Sash of the Unseen**: roll item (set in game by Kadmai). 2 raiders suggest council.")
