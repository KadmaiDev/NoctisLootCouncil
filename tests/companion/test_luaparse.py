from pathlib import Path

import pytest

from companion.luaparse import LuaError, load_file, parse_assignments, parse_value

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("text, expected", [
    (r'"plain"', "plain"),
    (r'"say \"hi\""', 'say "hi"'),
    (r'"back\\slash"', "back\\slash"),
    (r'"two\nlines"', "two\nlines"),
    (r'"tab\there"', "tab\there"),
    (r"'single \' quote'", "single ' quote"),
    (r'"\65\066\0671"', "ABC1"),             # decimal escapes take at most three digits
    (r'"caf\195\169"', "café"),               # UTF-8 written as byte escapes
    (r'"\x41\u{48}"', "AH"),
    ('"a\\z   \n   b"', "ab"),
    ('"line\\\nbreak"', "line\nbreak"),       # backslash-newline
    ('"Mireíle"', "Mireíle"),                 # UTF-8 in the file as it is
    ("[[long\nstring]]", "long\nstring"),
    ("[==[with ]] inside]==]", "with ]] inside"),
])
def test_strings(text, expected):
    assert parse_value(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("0", 0), ("42", 42), ("-7", -7), ("1.5", 1.5), ("-0.25", -0.25), (".5", 0.5), ("1e3", 1000.0),
    ("-2.5E-2", -0.025), ("0x1F", 31), ("1793078967", 1793078967),
])
def test_numbers(text, expected):
    v = parse_value(text)
    assert v == expected and type(v) is type(expected)


def test_booleans_and_nil():
    assert parse_value("{ true, false }") == [True, False]
    assert parse_value("{ a = nil, b = 1 }") == {"b": 1}


def test_tables_lists_and_comments():
    text = """{
        {
            ["id"] = 1,
        }, -- [1]
        {
            ["id"] = 2,
        }, -- [2]
    }"""
    assert parse_value(text) == [{"id": 1}, {"id": 2}]


def test_mixed_and_keyed_tables():
    assert parse_value('{ [1] = "a", [2] = "b" }') == ["a", "b"]
    assert parse_value('{ [2] = "b", [3] = "c" }') == {2: "b", 3: "c"}  # not 1..n: stays a map
    assert parse_value('{ "a", x = 1; "b" }') == {1: "a", "x": 1, 2: "b"}
    assert parse_value('{ [18000] = { h = "council" } }') == {18000: {"h": "council"}}
    assert parse_value('{ ["with space"] = 1, [-3] = 2, [1.5] = 3 }') == {"with space": 1, -3: 2, 1.5: 3}
    assert parse_value("{}") == {}
    assert parse_value("{ --[[ block\ncomment ]] 5 }") == [5]


@pytest.mark.parametrize("bad", ['"unfinished', "{ 1, 2", "{ [1] 2 }", "{ 1 2 }", "@", '"bad \\q escape"', ""])
def test_errors(bad):
    with pytest.raises(LuaError):
        parse_value(bad)


def test_error_names_the_line():
    with pytest.raises(LuaError, match="line 3"):
        parse_assignments("A = {\n  x = 1,\n  y = @,\n}")


def test_assignments():
    assert parse_assignments("﻿A = 1\nB = { 2 }\nC = nil\n") == {"A": 1, "B": [2], "C": None}


def test_saved_file_fixture():
    variables = load_file(FIXTURES / "NoctisLootCouncil.lua")
    db = variables["NoctisLootCouncilDB"]
    assert variables["NoctisLootCouncilCharDB"] is None
    assert db["v"] == 1 and db["me"] == "Kadmai Moonwhisper"
    assert db["window"] == {"point": "CENTER", "x": -12.5, "y": 140.25, "scale": 0.85, "shown": False}
    assert db["trials"] == ["Trial", "Initiate"]
    assert set(db["items"]) == {18000, 16805, 17069}
    assert db["items"][17069]["from"] == {}
    assert db["items"][16805]["from"] == {"e663": 1, "e664": 1}
    assert len(db["drops"]) == 3 and "src" not in db["drops"][2]
    log = db["log"]
    assert [a["who"] for a in log] == ["Ilsa Marrow", "Mireíle Duskbane", "Corvin Dusk"]
    assert log[0]["note"] == 'Warlock priority; "biggest" upgrade\\sidegrade for the rest\nsecond line'


def test_crlf_file(tmp_path):
    p = tmp_path / "x.lua"
    p.write_bytes(b'X = {\r\n\t["a"] = "b", -- [1]\r\n}\r\n')
    assert load_file(p) == {"X": {"a": "b"}}
