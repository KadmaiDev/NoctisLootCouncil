"""The companion app against the real bot API (aiohttp test server, temp database)."""
from __future__ import annotations

import asyncio
import os
from zoneinfo import ZoneInfo

import pytest

from bot.api import create_app
from bot.db import connect
from bot.rules import COUNCIL
from bot.store import Store
from companion import client, config, decisions
from companion.__main__ import main
from companion.app import Companion
from companion.config import Settings
from companion.luaparse import load_file

from .test_savedfile import make_wow


@pytest.fixture
async def setup(tmp_path, aiohttp_server):
    store = Store(connect(tmp_path / "bot.db"), ZoneInfo("Europe/London"), 3)
    server = await aiohttp_server(create_app(store))
    wow = make_wow(tmp_path)
    token = store.issue_token("discord:1", "Kadmai")
    settings = Settings(wow_dir=wow, bot_url=str(server.make_url("")).rstrip("/"), token=token)
    return store, settings


def decisions_file(settings: Settings):
    return decisions.addon_dir(settings.wow_dir) / "Decisions.lua"


async def test_full_round_trip(setup):
    store, settings = setup
    uploads: list[dict] = []

    def counting_upload(url, token, body):
        uploads.append(body)
        return client.post_upload(url, token, body)

    comp = Companion(settings, upload=counting_upload)
    await asyncio.to_thread(comp.run_once)

    # The bot has the night.
    assert len(uploads) == 1
    assert {s.name for s in store.item_states()} == {"Sash of the Unseen", "Felheart Gloves", "Item 17069"}
    group = store.log_group("Molten Core", "2026-10-26")
    assert [a.who for a in group.awards] == ["Ilsa Marrow", "Mireíle Duskbane", "Corvin Dusk"]
    assert store.item_state(16805).drops == 2

    # The game gets the decisions set in game back (they're the only ones so far).
    written = load_file(decisions_file(settings))["NoctisLootDecisions"]
    assert written["at"] == store.decisions()["at"]
    assert written["items"] == {18000: {"h": "council", "note": "Warlock priority", "name": "Sash of the Unseen"},
                                17069: {"h": "roll", "name": "Item 17069"}}

    # Nothing changed: no upload, no rewrite.
    before = os.stat(decisions_file(settings)).st_mtime_ns
    await asyncio.to_thread(comp.run_once)
    assert len(uploads) == 1
    assert os.stat(decisions_file(settings)).st_mtime_ns == before

    # The officers decide in Discord: the next pass rewrites the addon.
    for uid in (1, 2, 3):
        store.cast_vote(16805, uid, f"O{uid}", COUNCIL)
    store.set_priority(16805, "Warlocks first", "Seren")
    await asyncio.to_thread(comp.run_once)
    written = load_file(decisions_file(settings))["NoctisLootDecisions"]
    assert written["items"][16805] == {"h": "council", "note": "Warlocks first", "name": "Felheart Gloves"}
    assert written["at"] == store.decisions()["at"]
    toc = (decisions.addon_dir(settings.wow_dir) / "NoctisLootDecisions.toc").read_text(encoding="utf-8")
    assert f"## Version: {written['at']}" in toc

    # The game rewrites the saved file (a /reload): it's uploaded again, and nothing is doubled.
    saved = next(settings.wow_dir.glob("WTF/Account/*/SavedVariables/NoctisLootCouncil.lua"))
    st = saved.stat()
    os.utime(saved, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    await asyncio.to_thread(comp.run_once)
    assert len(uploads) == 2
    assert len(store.log_group("Molten Core", "2026-10-26").awards) == 3


async def test_half_written_file_is_retried(setup):
    store, settings = setup
    saved = next(settings.wow_dir.glob("WTF/Account/*/SavedVariables/NoctisLootCouncil.lua"))
    good = saved.read_bytes()
    saved.write_bytes(good[: len(good) // 2])
    comp = Companion(settings)
    await asyncio.to_thread(comp.upload_changed)
    assert store.item_states() == []
    saved.write_bytes(good)
    assert await asyncio.to_thread(comp.upload_changed) == 1
    assert len(store.item_states()) == 3


async def test_bot_down_is_retried(setup, tmp_path):
    store, settings = setup
    settings.bot_url = "http://127.0.0.1:9"  # nothing listens there
    comp = Companion(settings)
    assert await asyncio.to_thread(comp.upload_changed) == 0
    assert await asyncio.to_thread(comp.update_decisions) is False


async def test_wrong_token_stops_the_app(setup):
    _, settings = setup
    settings.token = "nlc_wrong"
    with pytest.raises(client.TokenRefused):
        await asyncio.to_thread(Companion(settings).run_once)


async def test_command_line_once(setup, tmp_path, monkeypatch):
    store, settings = setup
    ini = tmp_path / "cfg" / "companion.ini"
    config.save(ini, settings)
    assert await asyncio.to_thread(main, ["--once", "--config", str(ini)]) == 0
    assert len(store.item_states()) == 3
    assert decisions_file(settings).is_file()
    log_text = (ini.parent / "companion.log").read_text(encoding="utf-8")
    assert "Uploaded ACCOUNT1/NoctisLootCouncil.lua (Kadmai Moonwhisper): 3 new items, 3 new awards." in log_text
    assert "Wrote Decisions from" in log_text

    settings.token = "nlc_wrong"
    config.save(ini, settings)
    assert await asyncio.to_thread(main, ["--once", "--config", str(ini)]) == 3
