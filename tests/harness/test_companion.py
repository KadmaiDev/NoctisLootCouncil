"""The companion app as officers get it: tokens from Discord, and the built .exe doing a night."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from companion import client, config
from companion.app import Companion
from companion.config import Settings
from harness.realm import find_luajit

from .helpers import SASH, companion_pass, decide, token_for

pytestmark = pytest.mark.skipif(find_luajit() is None, reason="LuaJIT not found (set LUAJIT)")

EXE = Path(__file__).resolve().parents[2] / "dist" / "NoctisLootCompanion.exe"


async def test_a_new_token_from_discord_stops_the_old_one(guild, running, realm):
    officer = guild.officers[2]
    old = await token_for(guild, officer)
    await companion_pass(realm.lm, running.api_url, old)
    new = await token_for(guild, officer)
    comp = Companion(Settings(wow_dir=realm.lm.wow_dir, bot_url=running.api_url, token=old))
    with pytest.raises(client.TokenRefused):
        await asyncio.to_thread(comp.run_once)
    await companion_pass(realm.lm, running.api_url, new)


async def run_exe(ini: Path, *args: str) -> int:
    proc = await asyncio.create_subprocess_exec(str(EXE), "--config", str(ini), *args,
                                                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    return await asyncio.wait_for(proc.wait(), 60)


@pytest.mark.skipif(not EXE.exists(), reason="build it first: python tools/package.py companion")
async def test_the_built_exe_brings_decisions_in_and_uploads_the_night(guild, running, realm, tmp_path):
    r = realm
    officer = guild.officers[2]
    token = await token_for(guild, officer)
    await guild.slash(officer, "loot add", item="18000", name="Sash of the Unseen")
    await decide(guild, 18000, "Roll")
    r.lm.wow_dir.mkdir(parents=True, exist_ok=True)
    ini = tmp_path / "companion.ini"
    config.save(ini, Settings(wow_dir=r.lm.wow_dir, bot_url=running.api_url, token=token))

    assert await run_exe(ini, "--once") == 0
    r.login()
    assert r.lm.query("ns.db.items[18000].handling") == "roll"
    r.kill(663, "Lucifron")
    r.loot(r.lm, [(SASH, 4)])
    r.set_rolls(r.ilsa, 77)
    r.lm.type("/nlc start " + SASH)
    r.ilsa.click("Main spec")
    r.wait(31)
    r.logout()

    assert await run_exe(ini, "--once") == 0
    await guild.wait_until(lambda: guild.channel("loot-log").find("Ilsa Marrow"), what="the loot log")
    # A token replaced in Discord: the app stops and says so (exit code 3).
    await token_for(guild, officer)
    assert await run_exe(ini, "--once") == 3
