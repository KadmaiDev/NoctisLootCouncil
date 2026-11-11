"""The guild roster channel's pure side: settings parsing, who is listed, and the posts."""
from __future__ import annotations

import random
import re

import pytest

from bot import render
from bot.milestones import CLASS_COLOURS, GOLD
from bot.roster import Character, Settings, cards, listed, parse_ranks, settings_text

ON = Settings(on=True, channel_id=5)
GUILD = [
    Character("Thorgar Ironvale", 60, "WARRIOR", "Officer"),
    Character("Brannoch Steel", 60, "WARRIOR", "Raider"),
    Character("Aelwyn Dusk", 44, "DRUID", "Raider"),
    Character("Kadmai Moonwhisper", 60, "HUNTER", "Guild Master"),
    Character("Pip", 12, "MAGE", "Trial"),
    Character("Tiny", 5, "ROGUE", "Raider"),
    Character("Shade", 30, None, None),
]


def bodies(result):
    return {key: card.body for key, card in result}


# ---- parse_ranks ---------------------------------------------------------------------------------

def test_ranks_are_parsed_trimmed_and_deduplicated():
    assert parse_ranks("Trial, Alt") == ("Trial", "Alt")
    assert parse_ranks("  Trial ;alt;  Alt , TRIAL,, Social  Member ") == ("Trial", "alt", "Social Member")
    for every in ("none", "All", " any ", "*"):
        assert parse_ranks(every) == ()


def test_bad_ranks_are_refused_with_a_message():
    for bad in ("", " , ; ", "x" * 65, ",".join(f"R{i}" for i in range(21))):
        with pytest.raises(ValueError) as e:
            parse_ranks(bad)
        assert str(e.value)
    assert len(parse_ranks(",".join(f"R{i}" for i in range(20)))) == 20


# ---- listed --------------------------------------------------------------------------------------

def test_listed_drops_low_levels_and_hidden_ranks():
    names = [c.name for c in listed(GUILD, ON)]
    assert "Tiny" not in names and "Pip" in names and "Shade" in names
    hidden = Settings(on=True, channel_id=5, min_level=30, hidden_ranks=(" trial ", "RAIDER"))
    assert [c.name for c in listed(GUILD, hidden)] == ["Kadmai Moonwhisper", "Thorgar Ironvale", "Shade"]
    assert len(listed(GUILD, Settings(min_level=1))) == len(GUILD)


# ---- the posts -----------------------------------------------------------------------------------

def test_output_does_not_depend_on_input_order():
    first = cards(GUILD, ON, "Noctis", 1_700_000_000)
    for seed in range(10):
        shuffled = GUILD[:]
        random.Random(seed).shuffle(shuffled)
        again = cards(shuffled, ON, "Noctis", 1_700_000_000)
        assert [(k, c.digest()) for k, c in again] == [(k, c.digest()) for k, c in first]


def test_header_totals_rank_order_and_who_is_listed():
    s = Settings(on=True, channel_id=5, hidden_ranks=("Trial",))
    header = cards(GUILD, s, "Noctis", 1_700_000_000)[0]
    assert header[0] == "header"
    card = header[1]
    assert card.title == "Noctis · Guild roster" and card.colour == GOLD
    lines = card.body.splitlines()
    # Thorgar, Brannoch, Kadmai at 60, Aelwyn 44, Shade 30: average 50.8
    assert lines[0] == "5 members · 3 at level 60 · average level 51"
    assert lines[1] == "Warrior 2 · Druid 1 · Hunter 1 · Unknown class 1"
    assert lines[2] == "Raider 2 · Guild Master 1 · No rank 1 · Officer 1"
    assert lines[3] == "-# Level 10 and up · not shown: Trial"
    assert card.footer == "Roster read <t:1700000000:R>"


def test_header_wording_for_one_and_for_everyone_at_one_level():
    one = cards([Character("Solo", 60, "MAGE", "Raider")], ON, "Noctis", None)[0][1]
    assert one.body.splitlines()[0] == "1 member · level 60"
    assert one.footer == "Waiting for an officer's roster"
    same = cards([Character("A", 60, "MAGE"), Character("B", 60, "MAGE")], Settings(min_level=1), "Noctis", None)[0][1]
    assert same.body.splitlines()[0] == "2 members · all at level 60"
    assert "-#" not in same.body  # level 1 and every rank: nothing to say about who's listed


def test_nobody_listed_is_just_the_header():
    result = cards([Character("Tiny", 5, "ROGUE")], ON, "Noctis", None)
    assert len(result) == 1
    assert result[0][1].body.startswith("Nobody is listed yet.")
    assert cards([], ON, "Noctis", None)[0][1].body.startswith("Nobody is listed yet.")


def test_one_card_per_class_alphabetical_with_unknown_last():
    result = cards(GUILD, ON, "Noctis", 1)
    assert [k for k, _ in result] == ["header", "DRUID", "HUNTER", "MAGE", "WARRIOR", "UNKNOWN"]
    by_key = dict(result)
    warrior = by_key["WARRIOR"]
    assert warrior.title == "Warrior (2)" and warrior.colour == CLASS_COLOURS["WARRIOR"]
    assert warrior.body == "**60** Brannoch Steel · Thorgar Ironvale"
    unknown = by_key["UNKNOWN"]
    assert unknown.title == "Unknown class (1)" and unknown.body == "**30** Shade"
    assert unknown.colour == GOLD
    assert not any(c.buttons for _, c in result)


def test_class_names_and_levels_in_order():
    chars = [Character("zed", 40, "deathknight"), Character("Amy", 58, "DEATHKNIGHT"), Character("bob", 40, "DEATHKNIGHT")]
    (_, card), = cards(chars, ON, "Noctis", 1)[1:]
    assert card.title == "Death Knight (3)"
    assert card.body == "**58** Amy\n**40** bob · zed"


def test_markdown_in_names_is_escaped():
    chars = [Character("*Star*_x", 60, "MAGE", "Rank|One")]
    result = cards(chars, ON, "No_ctis", 1)
    assert result[0][1].title == "No\\_ctis · Guild roster"
    assert "Rank\\|One 1" in result[0][1].body
    assert result[1][1].body == "**60** \\*Star\\*\\_x"


def test_a_big_class_splits_without_losing_anyone():
    rng = random.Random(1)
    chars = [Character(f"Warrior{i:03d} Longsurname{i:03d}", rng.randint(10, 60), "WARRIOR") for i in range(400)]
    chars += [Character(f"Mage{i}", 60, "MAGE") for i in range(3)]
    result = cards(chars, ON, "Noctis", 1)
    keys = [k for k, _ in result]
    warrior = [(k, c) for k, c in result if k.startswith("WARRIOR")]
    assert len(warrior) > 1
    assert [k for k, _ in warrior] == ["WARRIOR"] + [f"WARRIOR#{i}" for i in range(2, len(warrior) + 1)]
    assert warrior[0][1].title == "Warrior (400)"
    assert all(c.title == "Warrior (continued)" for _, c in warrior[1:])
    assert keys.index("MAGE") < keys.index("WARRIOR")
    for _, c in result:
        assert len(c.body) <= render.MESSAGE_LIMIT
    names = [n for _, c in warrior for line in c.body.splitlines() for n in re.sub(r"^\*\*\d+\*\* ", "", line).split(" · ")]
    assert sorted(names) == sorted(c.name for c in chars if c.cls == "WARRIOR")


def test_one_level_too_long_for_a_post_splits_between_names():
    chars = [Character(f"Character{i:03d} Withaverylongsurname", 60, "PRIEST") for i in range(200)]
    result = cards(chars, ON, "Noctis", 1)[1:]
    assert len(result) > 1
    for _, c in result:
        assert len(c.body) <= render.MESSAGE_LIMIT
        assert all(line.startswith("**60** ") for line in c.body.splitlines())
    names = [n for _, c in result for line in c.body.splitlines() for n in line[len("**60** "):].split(" · ")]
    assert names == sorted(c.name for c in chars)


def test_nothing_clock_derived_in_the_posts():
    for scanned in (None, 1_700_000_000):
        result = cards(GUILD, ON, "Noctis", scanned)
        assert all(not c.footer for _, c in result[1:])
        footer = result[0][1].footer
        assert footer == (f"Roster read <t:{scanned}:R>" if scanned else "Waiting for an officer's roster")
        assert not re.search(r"\d", footer.replace(str(scanned), ""))
        assert all(not re.search(r"<t:", c.body) for _, c in result)


# ---- settings ------------------------------------------------------------------------------------

def test_settings_text_says_what_is_missing():
    off = settings_text(Settings(), None, (0, 0), False)
    assert "Guild roster: **Off**." in off and "Channel: not set." in off and "Hidden ranks: none." in off
    assert "Minimum level: 10." in off
    no_ms = settings_text(Settings(on=True, channel_id=5), "<#5>", (87, 80), False)
    assert "not posting until level milestones are on" in no_ms and "Channel: <#5>." in no_ms
    assert "Characters in the guild: 87; listed: 80." in no_ms
    no_channel = settings_text(Settings(on=True), None, (1, 1), True)
    assert "not posting until the channel is set." in no_channel
    ready = settings_text(Settings(on=True, channel_id=5, min_level=20, hidden_ranks=("Trial", "Alt")), "<#5>", (3, 2), True)
    assert "Guild roster: **On**." in ready and "Hidden ranks: Trial, Alt." in ready and "Minimum level: 20." in ready
    assert Settings(on=True, channel_id=5).ready and not Settings(on=True).ready and not Settings(channel_id=5).ready
