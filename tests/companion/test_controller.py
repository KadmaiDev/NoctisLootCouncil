"""The controller the window drives, without a window: setup, the pass, notifications and what the page shows."""
from __future__ import annotations

import time

import pytest

from companion import client, config
from companion.app import Companion
from companion.config import Settings
from companion.controller import Controller, ago, when

from .test_savedfile import make_wow

URL = "https://loot.example.org"
DECISIONS = {"at": 1793000000, "items": {"18000": {"handling": "council"}, "19000": {"handling": "roll"},
                                         "19001": {"handling": "roll"}}}


class FakeBot:
    def __init__(self, token="good"):
        self.token = token
        self.down = False
        self.rejects = None  # an upload error the bot answers while fetching decisions still works
        self.uploads = 0

    def _check(self, token):
        if self.down:
            raise client.BotError("can't reach the bot (connection refused)")
        if token != self.token:
            raise client.TokenRefused("the bot didn't accept the token")

    def upload(self, url, token, body):
        self._check(token)
        if self.rejects:
            raise client.BotError(self.rejects)
        self.uploads += 1
        return {"new_awards": 3, "new_items": 1} if self.uploads == 1 else {"new_awards": 0, "new_items": 0}

    def fetch(self, url, token):
        self._check(token)
        return DECISIONS


@pytest.fixture
def bot():
    return FakeBot()


def make(tmp_path, bot, settings=None):
    controller = Controller(tmp_path / "companion.ini", settings, fetch=bot.fetch,
                            make_companion=lambda s: Companion(s, upload=bot.upload, fetch=bot.fetch))
    told = []
    controller.notify = lambda title, text: told.append((title, text))
    return controller, told


def test_first_run_shows_setup_with_the_folder_it_found(tmp_path, bot):
    controller, _ = make(tmp_path, bot)
    state = controller.state()
    assert state["view"] == "setup"
    assert state["setup"]["hasToken"] is False and state["setup"]["canCancel"] is False
    wow = make_wow(tmp_path)
    assert controller.check_wow(str(wow)) is True
    assert controller.check_wow(str(tmp_path / "nowhere")) is False
    controller.stop()


def test_setup_checks_each_field_and_the_token_with_the_bot(tmp_path, bot):
    controller, _ = make(tmp_path, bot)
    wow = str(make_wow(tmp_path))
    assert controller.save_setup(str(tmp_path / "nowhere"), URL, "good")["field"] == "wow"
    assert controller.save_setup(wow, "loot.example.org", "good")["field"] == "url"
    assert controller.save_setup(wow, URL, " ")["field"] == "token"
    refused = controller.save_setup(wow, URL, "old")
    assert refused["field"] == "token" and "didn't accept" in refused["error"]
    bot.down = True
    assert controller.save_setup(wow, URL, "good") == {
        "ok": False, "field": "url", "error": "Can't reach the bot (connection refused)."}
    assert not (tmp_path / "companion.ini").exists()
    bot.down = False
    controller.start = lambda: None  # no background thread: the test drives the passes
    assert controller.save_setup(wow, URL + "/", "good") == {"ok": True}
    saved = config.load(tmp_path / "companion.ini")
    assert (saved.bot_url, saved.token) == (URL, "good")
    assert controller.state()["view"] == "status"
    controller.stop()


def test_a_pass_uploads_writes_and_tells_the_tray(tmp_path, bot):
    settings = Settings(wow_dir=make_wow(tmp_path), bot_url=URL, token="good")
    controller, told = make(tmp_path, bot, settings)
    assert controller.state()["link"]["state"] == "checking"
    controller.run_pass()
    assert [title for title, _ in told] == ["Uploaded the loot", "New decisions for the game"]
    assert told[0][1] == "3 new awards, 1 new item. The bot posts them in Discord."
    assert told[1][1].startswith("1 council, 2 roll.")
    state = controller.state()
    assert state["link"]["title"] == "Connected to the loot bot"
    assert state["link"]["detail"] == "loot.example.org · checked just now"
    assert state["upload"].endswith("· 3 new awards, 1 new item")
    assert state["decisions"].endswith("· 1 council, 2 roll")
    assert any(a["text"].startswith("Uploaded ACCOUNT1") for a in state["activity"])

    told.clear()
    controller.run_pass()  # nothing changed: no upload, no new decisions, nothing to tell
    assert told == [] and bot.uploads == 1
    controller.upload_now()
    controller.run_pass()  # Upload now sends it again even though it hasn't changed
    assert bot.uploads == 2 and told == []
    controller.stop()


def test_bot_down_shows_on_the_status(tmp_path, bot):
    controller, told = make(tmp_path, bot, Settings(wow_dir=make_wow(tmp_path), bot_url=URL, token="good"))
    bot.down = True
    controller.run_pass()
    link = controller.state()["link"]
    assert link["state"] == "down" and "connection refused" in link["detail"]
    assert told == []
    controller.stop()


def test_a_failing_upload_stays_on_the_status_while_decisions_arrive(tmp_path, bot):
    controller, told = make(tmp_path, bot, Settings(wow_dir=make_wow(tmp_path), bot_url=URL, token="good"))
    bot.rejects = "the bot answered 400: bad upload"
    controller.run_pass()
    state = controller.state()
    assert state["link"]["state"] == "ok"  # the bot answers; only the upload is refused
    assert "Upload of ACCOUNT1/NoctisLootCouncil.lua failed: the bot answered 400" in state["note"]
    assert [t for t, _ in told] == ["New decisions for the game"]
    warned = [a for a in controller.activity if "failed" in a[1]]
    controller.run_pass()  # still refused: still shown, and not logged again every pass
    assert "failed" in controller.state()["note"]
    assert [a for a in controller.activity if "failed" in a[1]] == warned and len(warned) == 1
    bot.rejects = None
    controller.run_pass()
    assert controller.state()["note"] is None and bot.uploads == 1
    controller.stop()


def test_a_replaced_token_asks_for_a_new_one(tmp_path, bot):
    controller, told = make(tmp_path, bot, Settings(wow_dir=make_wow(tmp_path), bot_url=URL, token="good"))
    bot.token = "new"
    controller.run_pass()
    assert controller.state()["view"] == "token"
    assert told == [("Not connected", "The bot didn't accept your token. Open Noctis Loot to paste a new one.")]
    assert controller.reconnect("")["field"] == "token"
    assert controller.reconnect("good")["field"] == "token"
    controller.start = lambda: None
    assert controller.reconnect("new") == {"ok": True}
    assert config.load(tmp_path / "companion.ini").token == "new"
    controller.run_pass()
    assert controller.state()["view"] == "status"
    controller.stop()


def test_the_background_loop_runs_and_stops(tmp_path, bot):
    controller, _ = make(tmp_path, bot, Settings(wow_dir=make_wow(tmp_path), bot_url=URL, token="good"))
    controller.start()
    deadline = time.time() + 5
    while bot.uploads == 0 and time.time() < deadline:
        time.sleep(0.02)
    controller.stop()
    controller._thread.join(5)
    assert bot.uploads == 1 and not controller._thread.is_alive()


def test_times_read_naturally():
    now = time.mktime((2026, 10, 28, 23, 50, 0, 0, 0, -1))
    assert when(now - 600, now) == "Today, 23:40"
    assert when(now - 86400, now) == "Yesterday, 23:50"
    assert when(now - 3 * 86400, now) == "25 Oct, 23:50"
    assert [ago(s) for s in (3, 42, 60, 150, 7200)] == [
        "just now", "42 seconds ago", "1 minute ago", "2 minutes ago", "2 hours ago"]
