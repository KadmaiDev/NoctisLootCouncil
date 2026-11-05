from pathlib import Path

from companion import decisions
from companion.luaparse import load_file, parse_assignments

ROOT = Path(__file__).resolve().parents[2]

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
        "17109": {"handling": "none", "name": "Taken back"},
        "x": {"handling": "roll"},          # not an item ID: left out
        "3": {"handling": "disenchant"},    # not a handling the addon knows: left out
    }}
    parsed = parse_assignments(decisions.render(tricky))["NoctisLootDecisions"]
    assert parsed == {"at": 5, "items": {
        18000: {"h": "council", "note": 'Say "hi"\\now\nnext line\ttab\x01', "name": "Mireíle's Ring"},
        16866: {"h": "roll", "name": "Plain"},
        17109: {"h": "none", "name": "Taken back"},
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
    lines = toc.splitlines()
    assert lines[:4] == [
        "## Interface: 16001",
        "## Title: Noctis Loot Decisions",
        "## Notes: Council and roll decisions from Discord, written by the Noctis Loot companion app. "
        "Don't edit; it's rewritten.",
        "## Version: 1793078967",
    ]
    assert lines[-1] == "Decisions.lua"
    assert decisions.current_at(folder) == 1793078967
    assert load_file(folder / "Decisions.lua")["NoctisLootDecisions"]["items"][18000]["note"] == "Warlock priority"
    # Rewriting replaces the files in place.
    decisions.write_addon(folder, {"at": 1793080000, "items": {}})
    assert decisions.current_at(folder) == 1793080000
    assert len(list(folder.iterdir())) == 3


def test_the_toc_shows_beside_the_main_addon():
    """Same icon and every same category line, or a translated client would list them apart."""
    def beside(text):
        return [line for line in text.splitlines() if line.startswith(("## IconTexture:", "## Category"))]

    main = (ROOT / "addon" / "NoctisLootCouncil.toc").read_text(encoding="utf-8")
    assert len(beside(main)) == 12
    assert beside(decisions.toc(1)) == beside(main)
    assert (ROOT / "addon" / "media" / "icon.tga").is_file()


def test_refresh_tocs_changes_only_what_differs(tmp_path):
    decisions.write_addon(tmp_path, CONTRACT_EXAMPLE)
    old, kept = tmp_path / decisions.TOC_NAMES[0], tmp_path / decisions.TOC_NAMES[1]
    old.write_text("## Title: from an older companion\n", encoding="utf-8")
    before = kept.stat().st_mtime_ns
    decisions.refresh_tocs(tmp_path, 1793078967)
    assert old.read_text(encoding="utf-8") == decisions.toc(1793078967)
    assert kept.stat().st_mtime_ns == before


def test_summary():
    text = decisions.summary(CONTRACT_EXAMPLE)
    assert text.startswith("Decisions from ") and text.endswith(": 1 council, 1 roll.")
    assert decisions.summary({"at": 0, "items": {}}) == "Decisions from never: 0 council, 0 roll."
