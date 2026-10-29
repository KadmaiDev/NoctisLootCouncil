import shutil
from pathlib import Path

from bot.upload import parse_upload
from companion import savedfile

FIXTURES = Path(__file__).parent / "fixtures"


def make_wow(tmp_path: Path, accounts=("ACCOUNT1",)) -> Path:
    wow = tmp_path / "_forever_"
    for account in accounts:
        sv = wow / "WTF" / "Account" / account / "SavedVariables"
        sv.mkdir(parents=True)
        shutil.copy(FIXTURES / "NoctisLootCouncil.lua", sv / "NoctisLootCouncil.lua")
        shutil.copy(FIXTURES / "NoctisLootCouncil.lua", sv / "NoctisLootCouncil.lua.bak")
    (wow / "Interface" / "AddOns").mkdir(parents=True)
    return wow


def test_finds_every_account_and_skips_bak(tmp_path):
    wow = make_wow(tmp_path, ("ACCOUNT1", "ACCOUNT2"))
    (wow / "WTF" / "Account" / "SavedVariables").mkdir()  # account-wide folder without a file
    files = savedfile.find_saved_files(wow)
    assert [f.parent.parent.name for f in files] == ["ACCOUNT1", "ACCOUNT2"]
    assert all(f.name == "NoctisLootCouncil.lua" for f in files)
    assert savedfile.find_saved_files(tmp_path / "nowhere") == []


def test_build_upload_from_fixture():
    body = savedfile.build_upload(savedfile.read_saved_file(FIXTURES / "NoctisLootCouncil.lua"))
    assert body["uploader"] == "Kadmai Moonwhisper"
    assert body["items"]["18000"] == {
        "link": "|cffa335ee|Hitem:18000::::::::60:::::::|h[Sash of the Unseen]|h|r", "name": "Sash of the Unseen",
        "q": 4, "first": 1792700000, "last": 1793047200, "seen": 1, "from": {"e663": 1}, "inst": 409,
        "handling": "council", "note": "Warlock priority",
    }
    # Not loaded by the game yet: no name to take.
    assert "name" not in body["items"]["17069"] and body["items"]["17069"]["from"] == {}
    assert body["encounters"] == {"663": {"name": "Lucifron", "inst": 409}, "664": {"name": "Magmadar", "inst": 409}}
    assert body["instances"] == {"409": "Molten Core"}
    assert body["drops"][2] == {"id": 16805, "at": 1793049000, "inst": 409, "n": 1}
    assert [a["who"] for a in body["awards"]] == ["Ilsa Marrow", "Mireíle Duskbane", "Corvin Dusk"]
    assert body["awards"][1]["class"] == "WARLOCK" and "class" not in body["awards"][2]
    # Fields the companion doesn't use stay home.
    assert "window" not in body and "decisionsAt" not in body


def test_upload_is_what_the_bot_reads():
    body = savedfile.build_upload(savedfile.read_saved_file(FIXTURES / "NoctisLootCouncil.lua"))
    up = parse_upload(body)
    assert up.skipped == 0
    assert len(up.items) == 3 and len(up.drops) == 3 and len(up.awards) == 3
    assert up.awards[0].note.endswith("\nsecond line")


def test_awards_taken_back_go_up_for_the_bot_to_remove():
    db = savedfile.read_saved_file(FIXTURES / "NoctisLootCouncil.lua")
    assert savedfile.build_upload(db)["undone"] == []  # a file from before /nlc undo was remembered
    db["undone"] = [{"id": 16805, "who": "Corvin Dusk", "at": 1793049100, "how": "ms"}, "junk"]
    body = savedfile.build_upload(db)
    assert body["undone"] == [{"id": 16805, "who": "Corvin Dusk", "at": 1793049100}]
    assert [(u.id, u.who, u.at) for u in parse_upload(body).undone] == [(16805, "Corvin Dusk", 1793049100)]


def test_missing_db_variable(tmp_path):
    p = tmp_path / "NoctisLootCouncil.lua"
    p.write_text("SomethingElse = {}\n")
    try:
        savedfile.read_saved_file(p)
    except ValueError as exc:
        assert "NoctisLootCouncilDB" in str(exc)
    else:
        raise AssertionError("expected ValueError")
