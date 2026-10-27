import pytest

from bot.api import create_app

from .conftest import sample_body


@pytest.fixture
async def api(aiohttp_client, store):
    calls: list[int] = []
    client = await aiohttp_client(create_app(store, lambda: calls.append(1)))
    client.notified = calls
    token = store.issue_token("discord:1", "Kadmai")
    client.auth = {"Authorization": f"Bearer {token}"}
    return client


async def test_upload_needs_a_token(api):
    r = await api.post("/api/upload", json=sample_body())
    assert r.status == 401
    r = await api.post("/api/upload", json=sample_body(), headers={"Authorization": "Bearer nope"})
    assert r.status == 401
    r = await api.get("/api/decisions", headers={"Authorization": "Basic abc"})
    assert r.status == 401


async def test_upload_and_dedupe(api):
    r = await api.post("/api/upload", json=sample_body(), headers=api.auth)
    assert r.status == 200
    assert await r.json() == {"ok": True, "new_items": 3, "new_awards": 2}
    assert api.notified == [1]
    r = await api.post("/api/upload", json=sample_body(), headers=api.auth)
    assert await r.json() == {"ok": True, "new_items": 0, "new_awards": 0}


async def test_bad_bodies(api):
    r = await api.post("/api/upload", data=b"{not json", headers={**api.auth, "Content-Type": "application/json"})
    assert r.status == 400
    r = await api.post("/api/upload", json={"items": []}, headers=api.auth)
    assert r.status == 400
    assert (await r.json())["ok"] is False
    assert api.notified == []


async def test_decisions(api, store):
    r = await api.get("/api/decisions", headers=api.auth)
    assert await r.json() == {"at": 0, "items": {}}
    await api.post("/api/upload", json=sample_body(), headers=api.auth)
    for uid in (1, 2, 3):
        store.cast_vote(16805, uid, f"O{uid}", "roll")
    r = await api.get("/api/decisions", headers=api.auth)
    body = await r.json()
    assert body["at"] > 0
    assert body["items"] == {
        "18000": {"handling": "council", "note": "Warlock priority", "name": "Sash of the Unseen"},
        "16805": {"handling": "roll", "name": "Felheart Gloves"},
    }


async def test_health_needs_no_token(api):
    r = await api.get("/api/health")
    assert r.status == 200
