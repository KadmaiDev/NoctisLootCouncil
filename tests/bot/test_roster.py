"""The guild roster channel's pure side: settings parsing, who is listed, and the posts."""
from __future__ import annotations

import random
import re

import pytest

from bot import roster
from bot.milestones import CLASS_COLOURS, GOLD
from bot.roster import BLANK, Character, Settings, boards, listed, parse_ranks, settings_text

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

def u16(text: str) -> int:
    """A length as Discord counts it (UTF-16 units), worked out here independently of roster.py."""
    return sum(2 if ord(ch) > 0xFFFF else 1 for ch in text)


def assert_within_discord_limits(result) -> None:
    for _, b in result:
        assert u16(b.title) <= 256 and u16(b.description) <= 4096
        assert len(b.fields) <= 25
        for name, value, inline in b.fields:
            assert name and value and inline  # Discord refuses an empty name or value
            assert u16(name) <= 256 and u16(value) <= 1024
        total = u16(b.title) + u16(b.description) + sum(u16(n) + u16(v) for n, v, _ in b.fields)
        assert total <= 6000 and total == b.size()


def rows(board) -> list[tuple]:
    return [board.fields[i:i + 3] for i in range(0, len(board.fields), 3)]


def columns(result) -> dict[str, list[str]]:
    """Each class's lines, read column by column as a reader sees the grid: a field with no name
    carries on the class headed above it in the same column (or named '(continued)' at the top
    of a further message)."""
    out: dict[str, list[str]] = {}
    for _, b in result:
        above = [None, None, None]
        for row in rows(b):
            for col, (name, value, _) in enumerate(row):
                if name != BLANK:
                    above[col] = re.sub(r" \((\d+|continued)\)$", "", re.sub(r"^<:\w+:\d+> ", "", name))
                if value != BLANK:
                    assert above[col], f"a value with no class above it: {value[:40]}"
                    out.setdefault(above[col], []).extend(value.split("\n"))
    return out


def names_in(lines: list[str]) -> list[str]:
    return [re.fullmatch(r"` *\d+` \*\*(.+)\*\*", line)[1] for line in lines]


def test_output_does_not_depend_on_input_order():
    first = boards(GUILD, ON, "Noctis", 1_700_000_000)
    for seed in range(10):
        shuffled = GUILD[:]
        random.Random(seed).shuffle(shuffled)
        again = boards(shuffled, ON, "Noctis", 1_700_000_000)
        assert [(k, b.digest()) for k, b in again] == [(k, b.digest()) for k, b in first]


def test_the_title_and_the_counters():
    s = Settings(on=True, channel_id=5, hidden_ranks=("Trial",))
    [(key, board)] = boards(GUILD, s, "Noctis", 1_700_000_000)
    assert key == "roster"
    assert board.title == "Noctis · Guild roster" and board.colour == GOLD
    lines = board.description.splitlines()
    # Thorgar, Brannoch, Kadmai at 60, Aelwyn 44, Shade 30.
    assert lines[0] == "\N{BUSTS IN SILHOUETTE} **5** members  ·  \N{WHITE MEDIUM STAR} **3** at level 60  ·  " \
                       "\N{CLOCK FACE TWO OCLOCK} <t:1700000000:R>"
    assert lines[1] == "Raider 2 · Guild Master 1 · No rank 1 · Officer 1"
    assert lines[2] == "-# Level 10 and up · not shown: Trial"
    assert len(lines) == 3


def test_counter_wording_for_one_and_for_everyone_at_one_level():
    [(_, one)] = boards([Character("Solo", 60, "MAGE", "Raider")], ON, "Noctis", None)
    assert one.description.splitlines()[0] == ("\N{BUSTS IN SILHOUETTE} **1** member  ·  \N{WHITE MEDIUM STAR} "
                                               "level **60**  ·  \N{CLOCK FACE TWO OCLOCK} waiting for an officer's roster")
    [(_, same)] = boards([Character("A", 60, "MAGE"), Character("B", 60, "MAGE")], Settings(min_level=1), "Noctis", None)
    assert "**2** members  ·  \N{WHITE MEDIUM STAR} all at level **60**  ·  " in same.description
    assert "-#" not in same.description  # level 1 and every rank: nothing to say about who's listed


def test_nobody_listed_is_just_the_title_and_description():
    for chars in ([Character("Tiny", 5, "ROGUE")], []):
        [(key, board)] = boards(chars, ON, "Noctis", None)
        assert key == "roster" and board.fields == () and board.title == "Noctis · Guild roster"
        assert board.description.startswith("\N{BUSTS IN SILHOUETTE} Nobody is listed yet  ·  ")
        assert board.description.endswith("\n-# Level 10 and up")


def test_one_field_per_class_three_to_a_row_alphabetical_with_unknown_last():
    [(_, board)] = boards(GUILD, ON, "Noctis", 1)
    assert [n for n, _, _ in board.fields] == ["Druid (1)", "Hunter (1)", "Mage (1)", "Warrior (2)", "Unknown class (1)"]
    assert all(inline for _, _, inline in board.fields)
    fields = dict((n, v) for n, v, _ in board.fields)
    assert fields["Warrior (2)"] == "`60` **Brannoch Steel**\n`60` **Thorgar Ironvale**"
    assert fields["Unknown class (1)"] == "`30` **Shade**"
    assert fields["Mage (1)"] == "`12` **Pip**"


def test_class_names_levels_in_order_and_levels_lined_up():
    chars = [Character("zed", 40, "deathknight"), Character("Amy", 58, "DEATHKNIGHT"), Character("bob", 40, "DEATHKNIGHT"),
             Character("Kit", 9, "MAGE")]
    [(_, board)] = boards(chars, Settings(min_level=1), "Noctis", 1)
    (dk_name, dk, _), (mage_name, mage, _) = board.fields
    assert dk_name == "Death Knight (3)" and dk == "`58` **Amy**\n`40` **bob**\n`40` **zed**"
    # Right-aligned to the widest level in the roster, the space inside the code span.
    assert mage_name == "Mage (1)" and mage == "` 9` **Kit**"


def test_class_emojis_head_their_fields():
    icons = {"WARRIOR": "<:class_warrior:111>", "ROGUE": "<:class_rogue:222>"}  # nobody listed is a rogue
    [(_, board)] = boards(GUILD, ON, "Noctis", 1, icons)
    assert [n for n, _, _ in board.fields] == ["Druid (1)", "Hunter (1)", "Mage (1)", "<:class_warrior:111> Warrior (2)",
                                              "Unknown class (1)"]
    assert board.digest() != boards(GUILD, ON, "Noctis", 1)[0][1].digest()


def test_class_icons_only_for_the_games_classes():
    assert roster.class_icon("WARRIOR") == "classicon_warrior"
    assert roster.class_icon("DEATHKNIGHT") == "classicon_deathknight"
    assert roster.class_icon("UNKNOWN") is None and roster.class_icon("BARD") is None
    assert roster.emoji_name("classicon_deathknight") == "class_deathknight"
    assert roster.classes(GUILD, ON) == ["DRUID", "HUNTER", "MAGE", "WARRIOR", "UNKNOWN"]


def test_markdown_in_names_is_escaped():
    chars = [Character("*Star*_x", 60, "MAGE", "Rank|One")]
    [(_, board)] = boards(chars, ON, "No_ctis", 1)
    assert board.title == "No\\_ctis · Guild roster"
    assert "Rank\\|One 1" in board.description
    assert board.fields == (("Mage (1)", "`60` **\\*Star\\*\\_x**", True),)


def test_big_classes_carry_on_below_in_their_column_across_messages():
    rng = random.Random(1)
    chars = [Character(f"Warrior{i:03d} Longsurname{i:03d}", rng.randint(10, 60), "WARRIOR") for i in range(400)]
    chars += [Character(f"Character{i:03d} Withaverylongsurname", 60, "PRIEST") for i in range(200)]
    chars += [Character(f"Druid{i}", 30 + i, "DRUID") for i in range(3)]
    chars += [Character(f"Nobody{i}", 20, None) for i in range(2)]
    result = boards(chars, ON, "Noctis", 1)
    assert_within_discord_limits(result)
    assert len(result) > 1
    assert [k for k, _ in result] == ["roster"] + [f"roster#{i}" for i in range(2, len(result) + 1)]
    assert result[0][1].title and all(not b.title and not b.description for _, b in result[1:])
    assert all(b.colour == GOLD for _, b in result)

    # Druid, Priest, Warrior in the first row; their rows are padded to three, so the columns stay
    # in line; Unknown class alone in a last, short row.
    all_rows = [row for _, b in result for row in rows(b)]
    assert [n for n, _, _ in all_rows[0]] == ["Druid (3)", "Priest (200)", "Warrior (400)"]
    assert all(len(row) == 3 for row in all_rows[:-1])
    assert [n for n, _, _ in all_rows[-1]] == ["Unknown class (2)"]
    assert all(row[0][1] == BLANK for row in all_rows[1:-1])  # the druids fit in one field
    # Priests run out before the warriors: blank cells under them.
    assert any(row[1] == (BLANK, BLANK, True) and row[2][1] != BLANK for row in all_rows[1:-1])
    # A further message starts by naming the classes it carries on.
    for _, b in result[1:]:
        first = [n for n, _, _ in b.fields[:3]]
        assert first[0] == BLANK and first[2] == "Warrior (continued)"
        assert first[1] in ("Priest (continued)", BLANK)

    # Nobody lost, nobody twice, everyone in their class's column, in order.
    by_class = columns(result)
    assert sorted(by_class) == ["Druid", "Priest", "Unknown class", "Warrior"]
    for title, cls in (("Druid", "DRUID"), ("Priest", "PRIEST"), ("Warrior", "WARRIOR"), ("Unknown class", None)):
        expected = [c.name for c in listed(chars, ON) if c.cls == cls]
        assert names_in(by_class[title]) == expected
    # 200 at one level: one name per line, by name.
    assert names_in(by_class["Priest"]) == sorted(c.name for c in chars if c.cls == "PRIEST")


def test_many_classes_fill_messages_by_whole_rows():
    # Every class at its limit of one field: 13 classes, 5 rows; a message holds 8 rows of fields at
    # most (25 fields) and 6000 characters, so rows go on to the next message whole.
    classes = sorted(CLASS_COLOURS)
    chars = [Character(f"{cls.title()}{i:02d} Withaverylongsurname", 60, cls) for cls in classes for i in range(25)]
    result = boards(chars, ON, "Noctis", 1)
    assert_within_discord_limits(result)
    for _, b in result[:-1]:
        assert len(b.fields) % 3 == 0
    by_class = columns(result)
    assert sum(len(v) for v in by_class.values()) == len(chars)
    assert len({n for v in by_class.values() for n in names_in(v)}) == len(chars)


def test_at_most_25_fields_a_message():
    # Short classes (whatever the game calls them): it's the 25 fields, not the characters, that
    # start another message, after eight whole rows.
    chars = [Character(f"P{i}{j}", 60, f"CLASS{i:02d}") for i in range(40) for j in range(2)]
    result = boards(chars, ON, "Noctis", 1)
    assert_within_discord_limits(result)
    assert [len(b.fields) for _, b in result] == [24, 16]
    assert [n for n, _, _ in result[1][1].fields[:2]] == ["Class24 (2)", "Class25 (2)"]
    assert sum(len(v) for v in columns(result).values()) == 80


def test_nothing_clock_derived_in_the_posts():
    for scanned in (None, 1_700_000_000):
        [(_, board)] = boards(GUILD, ON, "Noctis", scanned)
        first = board.description.splitlines()[0]
        clock = first.split("  ·  ")[-1]
        assert clock == ("\N{CLOCK FACE TWO OCLOCK} " + (f"<t:{scanned}:R>" if scanned else "waiting for an officer's roster"))
        assert all("<t:" not in n + v for n, v, _ in board.fields)
        assert board.description.count("<t:") == (1 if scanned else 0)


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


def test_alt_ranks_get_a_post_of_their_own():
    chars = [Character("Thorn Gale", 60, "WARRIOR", "Officer"), Character("Vespera Ashward", 44, "DRUID", "Member"),
             Character("Thornlet", 30, "MAGE", "Officer Alt"), Character("Vesper Two", 12, "ROGUE", "alt"),
             Character("Tiny Alt", 5, "ROGUE", "Alt")]
    s = Settings(on=True, channel_id=5, alt_ranks=("Alt", "Officer Alt"))
    out = boards(chars, s, "Noctis", 1_700_000_000)
    assert [k for k, _ in out] == ["roster", "alts"]
    mains, alts = out[0][1], out[1][1]
    assert mains.title == "Noctis · Guild roster · Mains" and alts.title == "Noctis · Guild roster · Alts"
    assert "**2** members" in mains.description and "alts are listed below" in mains.description
    assert "Thornlet" not in mains.text() and "Thorn Gale" in mains.text()
    assert "**2** alts" in alts.description and "alt 1 · Officer Alt 1" in alts.description  # ranks match whatever the case
    assert "Thornlet" in alts.text() and "Vesper Two" in alts.text() and "Tiny Alt" not in alts.text()
    assert alts.colour != mains.colour
    # No alt listed: one roster, titled as without the setting.
    one = boards(chars[:2] + chars[4:], s, "Noctis", 1_700_000_000)
    assert [k for k, _ in one] == ["roster"] and one[0][1].title == "Noctis · Guild roster"
    assert boards(chars, Settings(on=True, channel_id=5), "Noctis", 1)[0][1].digest() != mains.digest()
