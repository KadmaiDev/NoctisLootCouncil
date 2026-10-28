"""The real bot, connected to a fake Discord, with its API on a free local port."""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

import pytest

from bot.client import LootBot
from bot.config import Config
from harness.fake_discord import FakeDiscord, Member
from harness.realm import Realm


@dataclass
class Guild:
    """The fake Discord as the guild sees it: channels, officers and raiders."""
    fake: FakeDiscord
    officers: list[Member]
    raiders: list[Member]

    def __getattr__(self, name):
        return getattr(self.fake, name)


@dataclass
class RunningBot:
    bot: LootBot
    task: asyncio.Task
    api_url: str


def make_config(fake: FakeDiscord, db_path) -> Config:
    return Config(token="fake-token", guild_id=fake.guild_id, officer_role_id=fake.officer_role,
                  ch_officers=fake.channel("loot-officers").id, ch_items=fake.channel("loot-items").id,
                  ch_priorities=fake.channel("loot-priorities").id, ch_log=fake.channel("loot-log").id,
                  api_host="127.0.0.1", api_port=0, votes_to_decide=3, db_path=db_path, timezone="Europe/London",
                  wowhead=False)


async def start_bot(fake: FakeDiscord, db_path) -> RunningBot:
    bot = LootBot(make_config(fake, db_path))
    before = fake.gateway_connections
    task = asyncio.create_task(bot.start("fake-token"))
    try:
        await fake.ready(before)
    except AssertionError:
        if task.done() and task.exception():
            raise task.exception() from None
        raise
    host, port = bot._runner.addresses[0][:2]
    return RunningBot(bot, task, f"http://{host}:{port}")


async def stop_bot(running: RunningBot) -> None:
    await running.bot.close()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await asyncio.wait_for(running.task, 5)


@pytest.fixture
async def guild():
    fake = FakeDiscord()
    for name in ("loot-officers", "loot-items", "loot-priorities", "loot-log", "general"):
        fake.add_channel(name)
    officers = [fake.add_member(n, roles=[fake.officer_role]) for n in ("Seren", "Doran", "Kadmai")]
    raiders = [fake.add_member(n) for n in ("Ilsa", "Vespera")]
    await fake.start()
    with fake.patched():
        yield Guild(fake, officers, raiders)
    await fake.stop()


@pytest.fixture
async def running(guild, tmp_path):
    rb = await start_bot(guild.fake, tmp_path / "bot.db")
    yield rb
    await stop_bot(rb)
    assert guild.unknown_routes == [], guild.unknown_routes


@pytest.fixture
def realm(tmp_path):
    """Three officers (Kadmai is the loot master), two raiders with the addon, one without."""
    r = Realm(tmp_path / "pcs")
    r.lm = r.add_player("Kadmai", "Moonwhisper", "HUNTER", rank="Officer", leader=True)
    r.seren = r.add_player("Seren", "Vale", "PRIEST", rank="Officer")
    r.doran = r.add_player("Doran", "Pike", "WARRIOR", rank="Officer")
    r.ilsa = r.add_player("Ilsa", "Marrow", "WARLOCK")
    r.vespera = r.add_player("Vespera", "Ashward", "WARLOCK")
    r.bran = r.add_player("Bran", "Holloway", "MAGE", addon=False)
    yield r
    r.close()
