"""The newest companion release, from GitHub's list, and how the API passes it on."""
from __future__ import annotations

import asyncio

import pytest

from bot.api import create_app
from bot.client import LootBot
from bot.releases import newest_companion


def release(tag, draft=False, prerelease=False):
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease}


def test_the_highest_full_companion_release_counts():
    releases = [release("addon-v0.9.0", prerelease=True), release("companion-v0.2.1"),
                release("companion-v0.10.0"), release("companion-v0.9.9"), release("companion-v1.0.0", draft=True),
                release("companion-v2.0.0", prerelease=True), release("companion-v3.0"), release("companion-v4.0.0-rc1")]
    assert newest_companion(releases) == "0.10.0"
    assert newest_companion([release("addon-v0.1.3")]) is None
    assert newest_companion({"message": "API rate limit exceeded"}) is None
    assert newest_companion([None, "x", {}]) is None


@pytest.fixture
async def api(aiohttp_client, store):
    client = await aiohttp_client(create_app(store))
    client.auth = {"Authorization": "Bearer " + store.issue_token("discord:1", "Kadmai")}
    return client


async def test_decisions_name_the_newest_companion_once_known(api, store):
    r = await api.get("/api/decisions", headers=api.auth)
    assert "companion" not in await r.json()
    store.set_companion_latest("0.3.0")
    r = await api.get("/api/decisions", headers=api.auth)
    assert (await r.json())["companion"] == "0.3.0"


async def test_the_bot_keeps_the_newest_it_hears_of(tmp_path):
    from tests.bot.test_poster import make_bot
    bot = make_bot(tmp_path, {})
    answers = ["0.2.2", None]

    async def fetch(session):
        return answers.pop(0) if answers else None

    bot.fetch_newest_companion = fetch
    task = asyncio.create_task(bot._watch_releases())
    for _ in range(50):
        if bot.store.companion_latest():
            break
        await asyncio.sleep(0.01)
    task.cancel()
    assert bot.store.companion_latest() == "0.2.2"
    if bot._http:
        await bot._http.close()
