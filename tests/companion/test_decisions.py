from companion import decisions
from companion.luaparse import load_file, parse_assignments

CONTRACT_EXAMPLE = {
    "at": 1793078967,
    "items": {
        "18000": {"handling": "council", "note": "Warlock priority", "name": "Sash of the Unseen"},
        "16866": {"handling": "roll"},
    },
}


def test_render_matches_the_contract():
    assert decisions.render(CONTRACT_EXAMPLE) == (
        "-- Written by the Noctis Loot companion app. Don't edit; it's rewritten.\n"
        "NoctisLootDecisions = {\n"
        "  at = 1793078967,\n"
        "  items = {\n"
        "    [16866] = { h = \"roll\" },\n"
        "    [18000] = { h = \"council\", note = \"Warlock priority\", name = \"Sash of the Unseen\" },\n"
        "  },\n"
        "}\n"
    )


def test_render_round_trips_through_the_parser():
    tricky = {"at": 5, "items": {
        "18000": {"handling": "council", "note": 'Say "hi"\\now\nnext line\ttab\x01', "name": "Mireíle's Ring"},
        "16866": {"handling": "roll", "name": "Plain"},
        "x": {"handling": "roll"},          # not an item ID: left out
        "3": {"handling": "disenchant"},    # not a handling the addon knows: left out
    }}
    parsed = parse_assignments(decisions.render(tricky))["NoctisLootDecisions"]
    assert parsed == {"at": 5, "items": {
        18000: {"h": "council", "note": 'Say "hi"\\now\nnext line\ttab\x01', "name": "Mireíle's Ring"},
        16866: {"h": "roll", "name": "Plain"},
    }}


def test_lua_string_escapes():
    assert decisions.lua_string('a"b\\c\nd') == '"a\\"b\\\\c\\nd"'
    assert decisions.lua_string("\x01" + "2") == '"\\0012"'  # three digits: the 2 stays a 2
    assert decisions.lua_string("é") == '"é"'


def test_empty_decisions():
    parsed = parse_assignments(decisions.render({"at": 0, "items": {}}))["NoctisLootDecisions"]
    assert parsed == {"at": 0, "items": {}}


def test_write_addon(tmp_path):
    folder = tmp_path / "Interface" / "AddOns" / "NoctisLootDecisions"
    assert decisions.current_at(folder) is None
    decisions.write_addon(folder, CONTRACT_EXAMPLE)
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["Decisions.lua", "NoctisLootDecisions.toc", "NoctisLootDecisions_Camelot.toc"]  # no .tmp left
    toc = (folder / "NoctisLootDecisions.toc").read_text(encoding="utf-8")
    assert toc == (folder / "NoctisLootDecisions_Camelot.toc").read_text(encoding="utf-8")
    assert toc.splitlines() == [
        "## Interface: 16001",
        "## Title: Noctis Loot Decisions",
        "## Notes: Council and roll decisions from Discord, written by the Noctis Loot companion app. "
        "Don't edit; it's rewritten.",
        "## Version: 1793078967",
        "Decisions.lua",
    ]
    assert decisions.current_at(folder) == 1793078967
    assert load_file(folder / "Decisions.lua")["NoctisLootDecisions"]["items"][18000]["note"] == "Warlock priority"
    # Rewriting replaces the files in place.
    decisions.write_addon(folder, {"at": 1793080000, "items": {}})
    assert decisions.current_at(folder) == 1793080000
    assert len(list(folder.iterdir())) == 3


def test_summary():
    text = decisions.summary(CONTRACT_EXAMPLE)
    assert text.startswith("Decisions from ") and text.endswith(": 1 council, 1 roll.")
    assert decisions.summary({"at": 0, "items": {}}) == "Decisions from never: 0 council, 0 roll."
