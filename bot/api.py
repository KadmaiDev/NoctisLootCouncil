"""The HTTP API the companion app talks to (sync-format.md, sections 2, 3 and 5).

Runs in the bot's own event loop. It only touches the database; Discord posting is done by the
bot's poster, which `on_change` wakes up, so the API works (and is tested) without Discord.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

from aiohttp import web

from .milestones import parse_milestone_upload
from .store import Store
from .upload import BadUpload, parse_upload

log = logging.getLogger("noctis.api")

STORE_KEY: web.AppKey[Store] = web.AppKey("store", Store)
NOTIFY_KEY: web.AppKey[Callable[[], None]] = web.AppKey("notify", Callable)

# A whole season's saved file is well under this; aiohttp's default (1 MB) might not be.
MAX_BODY = 32 * 1024 * 1024


def _error(status: int, message: str) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


def _owner(request: web.Request) -> tuple[str, str] | None:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return request.app[STORE_KEY].token_owner(token.strip())


async def upload(request: web.Request) -> web.Response:
    owner = _owner(request)
    if owner is None:
        return _error(401, "bad token")
    try:
        body = await request.json(loads=json.loads)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error(400, "the body isn't JSON")
    try:
        parsed = parse_upload(body)
    except BadUpload as exc:
        return _error(400, str(exc))
    result = request.app[STORE_KEY].apply_upload(parsed, owner[0], owner[1])
    log.info("Upload from %s (%s): %d new items, %d new awards, %d undone, %d skipped",
             owner[1], parsed.uploader or "?", result.new_items, result.new_awards, result.undone, result.skipped)
    request.app[NOTIFY_KEY]()
    return web.json_response({"ok": True, "new_items": result.new_items, "new_awards": result.new_awards})


async def decisions(request: web.Request) -> web.Response:
    if _owner(request) is None:
        return _error(401, "bad token")
    store = request.app[STORE_KEY]
    answer = store.decisions()
    latest = store.companion_latest()
    if latest:
        answer["companion"] = latest  # the newest companion app, for its update notice (releases.py)
    return web.json_response(answer)


async def milestone_settings(request: web.Request) -> web.Response:
    """Whether to upload milestones, and for which guild: the companion sends nothing else."""
    if _owner(request) is None:
        return _error(401, "bad token")
    s = request.app[STORE_KEY].milestone_settings()
    on = s.on and bool(s.guild)
    return web.json_response({"on": on, "guild": s.guild if on else None})


async def milestones_upload(request: web.Request) -> web.Response:
    owner = _owner(request)
    if owner is None:
        return _error(401, "bad token")
    try:
        body = await request.json(loads=json.loads)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error(400, "the body isn't JSON")
    try:
        parsed = parse_milestone_upload(body)
    except BadUpload as exc:
        return _error(400, str(exc))
    queued, ignored = request.app[STORE_KEY].apply_milestones(parsed, owner[1])
    if ignored:
        log.info("Milestones from %s (%s) ignored: %s", owner[1], parsed.uploader or "?", ignored)
        return web.json_response({"ok": True, "ignored": ignored, "new_milestones": 0})
    log.info("Milestones from %s (%s): %d members, %d level-ups, %d to post", owner[1], parsed.uploader or "?",
             len(parsed.members), len(parsed.levels), queued)
    request.app[NOTIFY_KEY]()
    return web.json_response({"ok": True, "new_milestones": queued})


async def health(_: web.Request) -> web.Response:
    return web.json_response({"ok": True})


def create_app(store: Store, notify: Callable[[], None] = lambda: None) -> web.Application:
    app = web.Application(client_max_size=MAX_BODY)
    app[STORE_KEY] = store
    app[NOTIFY_KEY] = notify
    app.router.add_post("/api/upload", upload)
    app.router.add_get("/api/decisions", decisions)
    app.router.add_get("/api/milestones", milestone_settings)
    app.router.add_post("/api/milestones", milestones_upload)
    app.router.add_get("/api/health", health)
    return app
