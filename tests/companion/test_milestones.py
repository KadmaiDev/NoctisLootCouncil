"""The companion and the Noctis Milestones addon's saved file: nothing at all without the addon, nothing
while the bot has milestones off, and only the bot's guild's roster when it's on."""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from bot.api import create_app
from bot.db import connect
from bot.store import Store
from companion import app, client, savedfile
from companion.app import Companion
from companion.config import Settings

from .test_savedfile import make_wow


def write_milestones(wow: Path, at: int, account: str = "ACCOUNT1", vespera: int = 20) -> Path:
    """A saved file as the game writes it: Noctis, and an alt's other guild."""
    path = wow / "WTF" / "Account" / account / "SavedVariables" / savedfile.MILESTONES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""
NoctisMilestonesDB = {{
["me"] = "Kadmai Moonwhisper",
["v"] = 1,
["guilds"] = {{
["Noctis|Forever"] = {{
["name"] = "Noctis",
["realm"] = "Forever",
["scanned"] = {at},
["members"] = {{
["vespera ashward"] = {{
["name"] = "Vespera Ashward",
["class"] = "DRUID",
["level"] = {vespera},
["rank"] = "Raider",
["seen"] = {at},
}},
["thorn gale"] = {{
["name"] = "Thorn Gale",
["class"] = "WARRIOR",
["level"] = 60,
["rank"] = "Officer",
["seen"] = {at},
}},
}},
["levels"] = {{
{{
["name"] = "Vespera Ashward",
["class"] = "DRUID",
["from"] = 19,
["to"] = {vespera},
["at"] = {at},
["since"] = {at - 600},
}}, -- [1]
}},
}},
["Other Guild|Forever"] = {{
["name"] = "Other Guild",
["realm"] = "Forever",
["members"] = {{
["secret alt"] = {{
["name"] = "Secret Alt",
["level"] = 30,
["seen"] = {at},
}},
}},
["levels"] = {{
{{
["name"] = "Secret Alt",
["from"] = 29,
["to"] = 30,
["at"] = {at},
}}, -- [1]
}},
}},
}},
}}
""", encoding="utf-8")
    return path


class FakeBot:
    def __init__(self, on=True, guild="Noctis"):
        self.answer = {"on": on, "guild": guild if on else None}
        self.asked = 0
        self.sent: list[dict] = []

    def settings(self, url, token):
        self.asked += 1
        return self.answer

    def upload(self, url, token, body):
        self.sent.append(body)
        return {"ok": True, "new_milestones": 1}


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def companion(wow: Path, bot: FakeBot, clock=None) -> Companion:
    return Companion(Settings(wow_dir=wow, bot_url="https://bot", token="t"), clock=clock or time.time,
                     milestone_settings=bot.settings, upload_milestones=bot.upload)


def test_without_the_addon_it_does_nothing_and_asks_nothing(tmp_path):
    bot = FakeBot()
    comp = companion(make_wow(tmp_path), bot)
    assert comp.upload_milestones() == 0
    assert comp.upload_milestones(force=True) == 0
    assert bot.asked == 0 and bot.sent == []


def test_only_the_bots_guild_is_sent(tmp_path):
    wow = make_wow(tmp_path)
    write_milestones(wow, 1_800_000_000)
    bot = FakeBot(guild="noctis")
    comp = companion(wow, bot)
    assert comp.upload_milestones() == 1
    [body] = bot.sent
    assert body["guild"] == "Noctis" and body["realm"] == "Forever" and body["uploader"] == "Kadmai Moonwhisper"
    assert [m["name"] for m in body["members"]] == ["Thorn Gale", "Vespera Ashward"]
    assert body["levels"] == [{"name": "Vespera Ashward", "class": "DRUID", "from": 19, "to": 20, "at": 1_800_000_000}]
    assert "Secret Alt" not in repr(body) and "Other Guild" not in repr(body)
    assert comp.status.new_milestones == 1
    # Unchanged: not again. Changed: again.
    assert comp.upload_milestones() == 0
    path = write_milestones(wow, 1_800_000_000, vespera=21)
    os.utime(path, ns=(time.time_ns(), time.time_ns() + 10**9))
    assert comp.upload_milestones() == 1 and len(bot.sent) == 2


def test_nothing_is_sent_while_the_bot_has_milestones_off(tmp_path):
    wow = make_wow(tmp_path)
    write_milestones(wow, 1_800_000_000)
    bot, clock = FakeBot(on=False), Clock()
    comp = companion(wow, bot, clock)
    assert comp.upload_milestones() == 0
    assert comp.upload_milestones() == 0
    assert bot.asked == 1 and bot.sent == []  # the answer is kept a while
    # Turned on in Discord: picked up at the next check, and the waiting file goes up.
    bot.answer = {"on": True, "guild": "Noctis"}
    clock.t += app.MILESTONES_RECHECK
    assert comp.upload_milestones() == 1
    assert bot.asked == 2


def test_an_alts_file_with_no_character_in_the_guild_sends_nothing(tmp_path):
    wow = make_wow(tmp_path)
    write_milestones(wow, 1_800_000_000)
    bot = FakeBot(guild="Somebody Else")
    comp = companion(wow, bot)
    assert comp.upload_milestones() == 1  # read, and nothing in it for the bot
    assert bot.sent == []


def test_a_bot_that_cant_be_reached_is_a_problem_until_it_answers(tmp_path):
    wow = make_wow(tmp_path)
    write_milestones(wow, 1_800_000_000)
    bot = FakeBot()

    def down(url, token):
        raise client.BotError("can't reach the bot (refused)")

    comp = Companion(Settings(wow_dir=wow, bot_url="https://bot", token="t"), milestone_settings=down,
                     upload_milestones=bot.upload, upload=lambda url, token, body: {"ok": True})
    assert comp.upload_milestones() == 0
    assert "milestones" in comp.status.problem and comp.status.connected is False
    assert comp.upload_changed() == 1  # the loot upload working doesn't hide it
    assert comp.status.problem and "milestones" in comp.status.problem
    comp._ms_settings = bot.settings
    assert comp.upload_milestones() == 1
    assert comp.status.problem is None


def test_a_refused_token_stops_it(tmp_path):
    wow = make_wow(tmp_path)
    write_milestones(wow, 1_800_000_000)

    def refused(url, token):
        raise client.TokenRefused("the bot didn't accept the token")

    comp = Companion(Settings(wow_dir=wow, bot_url="https://bot", token="t"), milestone_settings=refused)
    with pytest.raises(client.TokenRefused):
        comp.upload_milestones()
    assert comp.status.token_refused


async def test_round_trip_with_the_real_api(tmp_path, aiohttp_server):
    store = Store(connect(tmp_path / "bot.db"), ZoneInfo("Europe/London"), 3)
    server = await aiohttp_server(create_app(store))
    token = store.issue_token("discord:1", "Kadmai")
    wow = make_wow(tmp_path)
    settings = Settings(wow_dir=wow, bot_url=str(server.make_url("")).rstrip("/"), token=token)
    store.set_milestone_settings(on=True, guild="Noctis", channel_id=5)
    write_milestones(wow, int(time.time()) + 5)
    comp = Companion(settings)
    await asyncio.to_thread(comp.run_once)
    [m] = store.pending_milestones()
    assert (m.name, m.level, m.rank) == ("Vespera Ashward", 20, "Raider")
    assert store.milestone_counts() == (2, 0, 1)  # Noctis's two; the alt's guild never reached the bot
