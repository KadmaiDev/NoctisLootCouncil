from pathlib import Path

from companion import config
from companion.config import Settings


def test_save_and_load(tmp_path):
    path = tmp_path / "sub" / "companion.ini"
    s = Settings(wow_dir=tmp_path / "_forever_", bot_url="https://loot.example.org", token="nlc_abc%def")
    config.save(path, s)
    assert config.load(path) == s
    assert config.load(tmp_path / "missing.ini") is None


def test_incomplete_settings(tmp_path):
    path = tmp_path / "companion.ini"
    path.write_text("[companion]\nwow_folder = C:\\WoW\nbot_url = https://x/\n")
    s = config.load(path)
    assert s.bot_url == "https://x" and s.token == "" and not s.complete


def test_explicit_config_path_wins(tmp_path):
    assert config.config_path(tmp_path / "mine.ini") == tmp_path / "mine.ini"


def test_detect_prefers_a_folder_that_looks_like_wow(tmp_path):
    empty = tmp_path / "a" / "_forever_"
    real = tmp_path / "b" / "_forever_"
    empty.mkdir(parents=True)
    (real / "WTF").mkdir(parents=True)
    assert config.detect_wow_dir([tmp_path / "missing", empty, real]) == real
    assert config.detect_wow_dir([tmp_path / "missing", empty]) == empty
    assert config.detect_wow_dir([tmp_path / "missing"]) is None


def test_candidates_include_the_default():
    cands = config.wow_candidates()
    assert cands[0] == config.DEFAULT_WOW
    assert len({str(c).lower() for c in cands}) == len(cands)


def test_first_run_prompt(tmp_path, capsys):
    wow = tmp_path / "_forever_"
    wow.mkdir()
    answers = iter([str(tmp_path / "nope"), "", "loot.example.org", "https://loot.example.org/"])
    s = config.prompt(None, ask=lambda _: next(answers), ask_secret=lambda _: "  nlc_token  ", detected=wow)
    assert s == Settings(wow_dir=wow, bot_url="https://loot.example.org", token="nlc_token")
    out = capsys.readouterr().out
    assert "Can't find" in out and "https://" in out


def test_prompt_keeps_existing_values(tmp_path):
    wow = tmp_path / "_forever_"
    wow.mkdir()
    old = Settings(wow_dir=wow, bot_url="https://loot.example.org", token="nlc_old", poll_seconds=60)
    s = config.prompt(old, ask=lambda _: "", ask_secret=lambda _: "")
    assert s == old
