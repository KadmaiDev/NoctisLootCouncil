"""A fake Discord: the slice of Discord's HTTP API and gateway that the loot bot uses, served
locally, so the real bot (discord.py and all) runs unchanged against it.

discord.py takes Discord's address from two settings, `discord.http.Route.BASE` and
`discord.gateway.DiscordWebSocket.DEFAULT_GATEWAY`; `FakeDiscord.patched()` points both here.

The fake holds one guild with text channels, roles and members. Tests act as people in it:

    fake = FakeDiscord(); await fake.start()
    seren = fake.add_member("Seren", roles=[fake.officer_role])
    with fake.patched():
        ... start the bot ...
        r = await fake.slash(seren, "loot add", item_id=18000, name="Sash of the Unseen")
        r.text                                   # the bot's (ephemeral) reply
        post = fake.channel("loot-officers").last
        await fake.click(seren, post, "Council")

Payloads follow Discord's documented shapes closely enough for discord.py to parse them; a
request the fake doesn't know is answered 404 and recorded in `fake.unknown_routes`, so a test
can fail on it instead of the bot quietly misbehaving.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import itertools
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import aiohttp
import yarl
from aiohttp import web

log = logging.getLogger("fake_discord")

EPHEMERAL = 64
# Interaction response types (Discord's numbering).
CHANNEL_MESSAGE, DEFERRED_MESSAGE, DEFERRED_UPDATE, UPDATE_MESSAGE, AUTOCOMPLETE, MODAL = 4, 5, 6, 7, 8, 9
ALL_PERMISSIONS = str((1 << 50) - 1)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


@dataclass
class Member:
    id: int
    name: str
    roles: list[int] = field(default_factory=list)
    bot: bool = False

    def user_payload(self) -> dict:
        return {"id": str(self.id), "username": self.name.lower(), "discriminator": "0", "global_name": self.name,
                "avatar": None, "bot": self.bot, "public_flags": 0}

    def member_payload(self, permissions: bool = False) -> dict:
        p = {"user": self.user_payload(), "roles": [str(r) for r in self.roles], "nick": None, "avatar": None,
             "joined_at": _now(), "deaf": False, "mute": False, "flags": 0, "pending": False}
        if permissions:
            p["permissions"] = ALL_PERMISSIONS
        return p


@dataclass
class Message:
    """A message as the fake stores it: the payload discord.py sees, and a few handy views."""
    payload: dict
    deleted: bool = False
    thread: "Channel | None" = None

    @property
    def id(self) -> int:
        return int(self.payload["id"])

    @property
    def content(self) -> str:
        return self.payload.get("content") or ""

    @property
    def embeds(self) -> list[dict]:
        return self.payload.get("embeds") or []

    @property
    def components(self) -> list[dict]:
        """Every component, nested ones too (layout messages put rows and text inside containers)."""
        out, todo = [], list(self.payload.get("components") or [])
        while todo:
            c = todo.pop(0)
            out.append(c)
            todo[:0] = c.get("components") or []
        return out

    @property
    def text(self) -> str:
        """Content, embed and layout text in one string, for asserting on wording."""
        parts = [self.content]
        for e in self.embeds:
            parts += [(e.get("author") or {}).get("name") or "", e.get("title") or "", e.get("description") or ""]
            parts += [f"{f.get('name')}: {f.get('value')}" for f in e.get("fields") or []]
            if e.get("footer"):
                parts.append(e["footer"].get("text") or "")
        parts += [c.get("content") or "" for c in self.components if c.get("type") == 10]
        return "\n".join(p for p in parts if p)

    @property
    def buttons(self) -> list[dict]:
        return [c for c in self.components if c.get("type") == 2]

    @property
    def button_labels(self) -> list[str]:
        return [b.get("label") or "" for b in self.buttons]

    @property
    def ephemeral(self) -> bool:
        return bool(int(self.payload.get("flags") or 0) & EPHEMERAL)


@dataclass
class Channel:
    id: int
    name: str
    type: int = 0  # 0 text, 11 public thread
    parent_id: int | None = None
    owner_id: int | None = None  # threads: who opened it
    messages: dict[int, Message] = field(default_factory=dict)

    def payload(self, guild_id: int) -> dict:
        p = {"id": str(self.id), "type": self.type, "guild_id": str(guild_id), "name": self.name, "position": 0,
             "permission_overwrites": [], "nsfw": False, "parent_id": str(self.parent_id) if self.parent_id else None,
             "topic": None, "last_message_id": None, "rate_limit_per_user": 0, "flags": 0}
        if self.type == 11:
            p.update(owner_id=str(self.owner_id), message_count=0, member_count=1, total_message_sent=0,
                     thread_metadata={"archived": False, "auto_archive_duration": 10080,
                                      "archive_timestamp": _now(), "locked": False})
        return p

    @property
    def posts(self) -> list[Message]:
        """Messages everyone sees (not deleted, not an ephemeral reply), oldest first."""
        return [m for m in self.messages.values() if not m.deleted and not m.ephemeral]

    @property
    def last(self) -> Message | None:
        posts = self.posts
        return posts[-1] if posts else None

    def find(self, text: str) -> Message | None:
        """The newest post whose text contains `text`."""
        for m in reversed(self.posts):
            if text in m.text:
                return m
        return None


@dataclass
class Interaction:
    """One interaction a test started, and everything the bot answered to it."""
    id: int
    token: str
    type: int
    user: Member
    payload: dict
    responses: list[dict] = field(default_factory=list)   # {"type": callback type, "data": ...}
    messages: list[Message] = field(default_factory=list)  # replies and follow-ups, in order
    done: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def modal(self) -> dict | None:
        return next((r["data"] for r in self.responses if r["type"] == MODAL), None)

    @property
    def text(self) -> str:
        return "\n".join(m.text for m in self.messages)

    @property
    def ephemeral(self) -> bool:
        return bool(self.messages) and all(m.ephemeral for m in self.messages)

    @property
    def choices(self) -> list[dict]:
        return next((r["data"].get("choices", []) for r in self.responses if r["type"] == AUTOCOMPLETE), [])


class FakeDiscord:
    def __init__(self, guild_name: str = "Noctis"):
        self._ids = itertools.count(1_300_000_000_000_000_000)
        self.guild_id = self.new_id()
        self.guild_name = guild_name
        self.app_id = self.new_id()
        self.bot_user = Member(self.new_id(), "Noctis Loot", bot=True)
        self.owner = Member(self.new_id(), "Owner")
        self.roles: dict[int, str] = {self.guild_id: "@everyone"}
        self.officer_role = self.add_role("Officer")
        self.members: dict[int, Member] = {self.bot_user.id: self.bot_user}
        self.channels: dict[int, Channel] = {}
        self.commands: list[dict] = []  # as the bot registered them, with ids
        self.interactions: dict[str, Interaction] = {}  # by token
        self.unknown_routes: list[str] = []
        self.requests: list[tuple[str, str]] = []  # (method, path), every REST call
        self.gateway_connections = 0
        self._ws: web.WebSocketResponse | None = None
        self._seq = 0
        self._changed = asyncio.Condition()
        self._runner: web.AppRunner | None = None
        self.url = ""

    # ---- the world ---------------------------------------------------------

    def new_id(self) -> int:
        return next(self._ids)

    def add_role(self, name: str) -> int:
        rid = self.new_id()
        self.roles[rid] = name
        return rid

    def add_member(self, name: str, roles: list[int] | None = None) -> Member:
        m = Member(self.new_id(), name, list(roles or []))
        self.members[m.id] = m
        return m

    def add_channel(self, name: str) -> Channel:
        ch = Channel(self.new_id(), name)
        self.channels[ch.id] = ch
        return ch

    def channel(self, name_or_id: str | int) -> Channel:
        for ch in self.channels.values():
            if ch.id == name_or_id or ch.name == name_or_id:
                return ch
        raise KeyError(name_or_id)

    def message(self, message_id: int) -> Message | None:
        for ch in self.channels.values():
            if message_id in ch.messages:
                return ch.messages[message_id]
        return None

    def delete_message(self, message: Message) -> None:
        """Someone deletes a post (the bot isn't told, as with a moderator's delete it missed)."""
        message.deleted = True

    def guild_payload(self) -> dict:
        return {
            "id": str(self.guild_id), "name": self.guild_name, "icon": None, "splash": None, "discovery_splash": None,
            "owner_id": str(self.owner.id), "afk_channel_id": None, "afk_timeout": 300, "verification_level": 0,
            "default_message_notifications": 0, "explicit_content_filter": 0, "mfa_level": 0, "system_channel_id": None,
            "system_channel_flags": 0, "rules_channel_id": None, "vanity_url_code": None, "description": None,
            "banner": None, "premium_tier": 0, "preferred_locale": "en-US", "public_updates_channel_id": None,
            "nsfw_level": 0, "premium_progress_bar_enabled": False, "features": [], "emojis": [], "stickers": [],
            "roles": [{"id": str(rid), "name": name, "color": 0, "colors": {"primary_color": 0}, "hoist": False,
                       "icon": None, "unicode_emoji": None, "position": 0 if rid == self.guild_id else 1,
                       "permissions": ALL_PERMISSIONS if rid == self.guild_id else "0", "managed": False,
                       "mentionable": False, "flags": 0} for rid, name in self.roles.items()],
            "joined_at": _now(), "large": False, "unavailable": False, "member_count": len(self.members),
            "voice_states": [], "members": [self.bot_user.member_payload()], "presences": [],
            "channels": [ch.payload(self.guild_id) for ch in self.channels.values() if ch.type == 0],
            "threads": [], "stage_instances": [], "guild_scheduled_events": [], "soundboard_sounds": [],
        }

    # ---- running -----------------------------------------------------------

    async def start(self, host: str = "127.0.0.1") -> str:
        app = web.Application()
        app.router.add_get("/gateway", self._gateway)
        app.router.add_route("*", "/api/v10/{path:.*}", self._rest)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        self.url = f"http://{host}:{port}"
        return self.url

    async def stop(self) -> None:
        if self._ws is not None:
            await self._ws.close()
        if self._runner:
            await self._runner.cleanup()

    @contextlib.contextmanager
    def patched(self):
        """Point discord.py at this fake while the block runs."""
        from discord.gateway import DiscordWebSocket
        from discord.http import Route
        old = Route.BASE, DiscordWebSocket.DEFAULT_GATEWAY
        Route.BASE = self.url + "/api/v10"
        DiscordWebSocket.DEFAULT_GATEWAY = yarl.URL(self.url.replace("http", "ws", 1) + "/gateway")
        try:
            yield self
        finally:
            Route.BASE, DiscordWebSocket.DEFAULT_GATEWAY = old

    async def _notify(self) -> None:
        async with self._changed:
            self._changed.notify_all()

    async def wait_until(self, check: Callable[[], Any], timeout: float = 10.0, what: str = "") -> Any:
        """Wait until check() is truthy (re-checked after every request the bot makes)."""
        async def loop():
            async with self._changed:
                while True:
                    result = check()
                    if result:
                        return result
                    await self._changed.wait()
        try:
            return await asyncio.wait_for(loop(), timeout)
        except asyncio.TimeoutError:
            raise AssertionError(f"timed out waiting for {what or check}") from None

    async def ready(self, connections_before: int = 0, timeout: float = 15.0) -> None:
        """Wait until the bot has connected (again, if it had `connections_before` connections) and
        registered its commands."""
        await self.wait_until(lambda: self.gateway_connections > connections_before and self.commands,
                              timeout, "the bot to connect")

    async def quiet(self, seconds: float = 0.3) -> None:
        """Wait until the bot has made no request for `seconds` (its poster has caught up)."""
        while True:
            n = len(self.requests)
            await asyncio.sleep(seconds)
            if len(self.requests) == n:
                return

    # ---- gateway -----------------------------------------------------------

    async def _gateway(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._ws = ws
        await ws.send_json({"op": 10, "d": {"heartbeat_interval": 41250}, "s": None, "t": None})
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            frame = json.loads(msg.data)
            op = frame.get("op")
            if op == 1:  # heartbeat
                await ws.send_json({"op": 11, "d": None, "s": None, "t": None})
            elif op in (2, 6):  # identify, resume: always a fresh session
                await self._dispatch("READY", {
                    "v": 10, "user": self.bot_user.user_payload(), "session_id": "fake-session",
                    "resume_gateway_url": str(self.url.replace("http", "ws", 1) + "/gateway"),
                    "guilds": [{"id": str(self.guild_id), "unavailable": True}], "private_channels": [],
                    "relationships": [], "presences": [], "geo_ordered_rtc_regions": [], "auth": {},
                    "application": {"id": str(self.app_id), "flags": 0}, "shard": [0, 1],
                })
                await self._dispatch("GUILD_CREATE", self.guild_payload())
                self.gateway_connections += 1
                await self._notify()
        if self._ws is ws:
            self._ws = None
        return ws

    async def _dispatch(self, event: str, data: dict) -> None:
        if self._ws is None:
            raise AssertionError("the bot isn't connected")
        self._seq += 1
        await self._ws.send_json({"op": 0, "t": event, "s": self._seq, "d": data})

    # ---- REST --------------------------------------------------------------

    async def _rest(self, request: web.Request) -> web.Response:
        path = "/" + request.match_info["path"]
        self.requests.append((request.method, path))
        body: Any = None
        if request.can_read_body:
            if request.content_type.startswith("multipart/"):
                form = await request.post()
                body = json.loads(form.get("payload_json") or "{}")  # type: ignore[arg-type]
            else:
                raw = await request.read()
                body = json.loads(raw) if raw else None
        try:
            result = await self._route(request.method, path, request.query, body)
        finally:
            await self._notify()
        if result is None:
            self.unknown_routes.append(f"{request.method} {path}")
            log.warning("fake Discord: no route for %s %s", request.method, path)
            result = 404, {"message": "404: Not Found", "code": 0}
        status, data = result
        if status == 204:
            return web.Response(status=204)
        # discord.py parses a body as JSON only if the content type is exactly this (no charset).
        return web.Response(status=status, body=json.dumps(data).encode(), headers={"Content-Type": "application/json"})

    def _error(self, status: int, code: int, message: str) -> tuple[int, dict]:
        return status, {"message": message, "code": code}

    async def _route(self, method: str, path: str, query: Any, body: Any) -> tuple[int, Any] | None:
        parts = path.strip("/").split("/")
        p = parts + [""] * 6
        if method == "GET" and path == "/users/@me":
            return 200, self.bot_user.user_payload()
        if method == "GET" and path == "/oauth2/applications/@me":
            return 200, {"id": str(self.app_id), "name": "Noctis Loot", "icon": None, "description": "",
                         "bot_public": False, "bot_require_code_grant": False, "owner": self.owner.user_payload(),
                         "verify_key": "0" * 64, "flags": 0, "team": None, "summary": "",
                         "interactions_endpoint_url": None, "rpc_origins": []}
        if method == "GET" and path == "/gateway/bot":
            return 200, {"url": self.url.replace("http", "ws", 1) + "/gateway", "shards": 1,
                         "session_start_limit": {"total": 1000, "remaining": 1000, "reset_after": 0,
                                                 "max_concurrency": 1}}
        if p[0] == "applications" and method == "PUT" and p[2] == "commands":  # global commands
            return 200, []
        if p[0] == "applications" and method == "PUT" and p[2] == "guilds" and p[4] == "commands":
            self.commands = [dict(c, id=str(self.new_id()), application_id=str(self.app_id),
                                  guild_id=str(self.guild_id), version=str(self.new_id()), default_member_permissions=None,
                                  type=c.get("type", 1)) for c in body or []]
            return 200, self.commands
        if p[0] == "channels":
            return self._channel_route(method, p, body)
        if p[0] == "interactions" and p[3] == "callback" and method == "POST":
            return self._interaction_callback(p[2], body)
        if p[0] == "webhooks":
            return self._webhook_route(method, p, query, body)
        return None

    def _new_message(self, channel: Channel, body: dict, author: Member | None = None,
                     interaction: Interaction | None = None) -> Message:
        mid = self.new_id()
        payload = {
            "id": str(mid), "channel_id": str(channel.id), "guild_id": str(self.guild_id),
            "author": (author or self.bot_user).user_payload(), "content": body.get("content") or "",
            "timestamp": _now(), "edited_timestamp": None, "tts": False, "mention_everyone": False,
            "mentions": [], "mention_roles": [], "attachments": [], "embeds": body.get("embeds") or [],
            "pinned": False, "type": 0 if interaction is None else 20, "flags": int(body.get("flags") or 0),
            "components": body.get("components") or [],
        }
        if interaction is not None:
            payload["webhook_id"] = str(self.app_id)
            payload["interaction_metadata"] = {"id": str(interaction.id), "type": interaction.type,
                                               "user": interaction.user.user_payload(),
                                               "authorizing_integration_owners": {}}
        msg = Message(payload)
        channel.messages[mid] = msg
        return msg

    def _channel_route(self, method: str, p: list[str], body: Any) -> tuple[int, Any] | None:
        ch = self.channels.get(int(p[1])) if p[1].isdigit() else None
        if ch is None:
            return self._error(404, 10003, "Unknown Channel")
        if p[2] == "" and method == "GET":
            return 200, ch.payload(self.guild_id)
        if p[2] != "messages":
            return None
        if p[3] == "" and method == "POST":
            return 200, self._new_message(ch, body or {}).payload
        msg = ch.messages.get(int(p[3])) if p[3].isdigit() else None
        if msg is None or msg.deleted:
            return self._error(404, 10008, "Unknown Message")
        if p[4] == "" and method == "GET":
            return 200, msg.payload
        if p[4] == "" and method == "PATCH":
            self._edit(msg, body or {})
            return 200, msg.payload
        if p[4] == "" and method == "DELETE":
            msg.deleted = True
            return 204, None
        if p[4] == "threads" and method == "POST":
            thread = Channel(self.new_id(), (body or {}).get("name", "thread"), type=11, parent_id=ch.id,
                             owner_id=self.bot_user.id)
            self.channels[thread.id] = thread
            msg.thread = thread
            return 201, thread.payload(self.guild_id)
        return None

    @staticmethod
    def _edit(msg: Message, body: dict) -> None:
        for key in ("content", "embeds", "components", "flags"):
            if key in body:
                msg.payload[key] = body[key] if body[key] is not None else ([] if key != "content" else "")
        msg.payload["edited_timestamp"] = _now()

    def _interaction_callback(self, token: str, body: dict) -> tuple[int, Any]:
        it = self.interactions.get(token)
        if it is None:
            return self._error(404, 10062, "Unknown interaction")
        if it.responses:
            return self._error(400, 40060, "Interaction has already been acknowledged.")
        kind, data = body.get("type"), body.get("data") or {}
        it.responses.append({"type": kind, "data": data})
        resource: dict = {"type": kind}
        message_id = None
        if kind == CHANNEL_MESSAGE:
            channel = self.channel(int(it.payload["channel_id"]))
            msg = self._new_message(channel, data, self.bot_user, it)
            it.messages.append(msg)
            resource["message"] = msg.payload
            message_id = msg.id
            it.done.set()
        elif kind == UPDATE_MESSAGE:
            target = self.message(int(it.payload["message"]["id"]))
            if target is not None:
                self._edit(target, data)
                resource["message"] = target.payload
            it.done.set()
        elif kind in (MODAL, AUTOCOMPLETE, DEFERRED_UPDATE):
            it.done.set()
        # DEFERRED_MESSAGE ("thinking"): done when the follow-up arrives.
        return 200, {"interaction": {"id": str(it.id), "type": it.type, "response_message_id":
                                     str(message_id) if message_id else None,
                                     "response_message_loading": kind == DEFERRED_MESSAGE,
                                     "response_message_ephemeral": bool(int(data.get("flags") or 0) & EPHEMERAL)},
                     "resource": resource}

    def _webhook_route(self, method: str, p: list[str], query: Any, body: Any) -> tuple[int, Any] | None:
        it = self.interactions.get(p[2])
        if it is None:
            return self._error(404, 10015, "Unknown Webhook")
        channel = self.channel(int(it.payload["channel_id"]))
        if method == "POST" and p[3] == "":
            msg = self._new_message(channel, body or {}, self.bot_user, it)
            it.messages.append(msg)
            it.done.set()
            return 200, msg.payload
        if p[3] == "messages" and p[4] == "@original":
            original = it.messages[0] if it.messages else None
            if method == "PATCH":
                if original is None:  # editing the "thinking" placeholder
                    original = self._new_message(channel, body or {}, self.bot_user, it)
                    it.messages.append(original)
                else:
                    self._edit(original, body or {})
                it.done.set()
                return 200, original.payload
            if method == "GET" and original is not None:
                return 200, original.payload
        return None

    # ---- people acting -----------------------------------------------------

    def _interaction_payload(self, kind: int, user: Member, channel: Channel, data: dict,
                             message: Message | None = None) -> Interaction:
        iid, token = self.new_id(), f"token-{self.new_id()}"
        payload = {
            "id": str(iid), "application_id": str(self.app_id), "type": kind, "data": data,
            "guild_id": str(self.guild_id), "channel_id": str(channel.id), "channel": channel.payload(self.guild_id),
            "member": user.member_payload(permissions=True), "token": token, "version": 1,
            "app_permissions": ALL_PERMISSIONS, "locale": "en-GB", "guild_locale": "en-US", "entitlements": [],
            "authorizing_integration_owners": {"0": str(self.guild_id)}, "context": 0,
            "attachment_size_limit": 10 * 1024 * 1024,
        }
        if message is not None:
            payload["message"] = message.payload
        it = Interaction(iid, token, kind, user, payload)
        self.interactions[token] = it
        return it

    async def _run(self, it: Interaction, timeout: float) -> Interaction:
        await self._dispatch("INTERACTION_CREATE", it.payload)
        try:
            await asyncio.wait_for(it.done.wait(), timeout)
        except asyncio.TimeoutError:
            raise AssertionError(f"the bot didn't answer interaction {it.payload['data']}") from None
        return it

    def _command(self, name: str) -> dict:
        for c in self.commands:
            if c["name"] == name:
                return c
        raise AssertionError(f"no /{name} command registered (have {[c['name'] for c in self.commands]})")

    @staticmethod
    def _options(spec: list[dict], values: dict, focused: str | None = None) -> list[dict]:
        out = []
        for opt in spec:
            if opt["name"] in values:
                o = {"name": opt["name"], "type": opt["type"], "value": values[opt["name"]]}
                if opt["name"] == focused:
                    o["focused"] = True
                out.append(o)
        unknown = set(values) - {o["name"] for o in spec}
        if unknown:
            raise AssertionError(f"unknown options {sorted(unknown)}")
        return out

    def _command_data(self, path: str, values: dict, focused: str | None = None) -> dict:
        names = path.split()
        cmd = self._command(names[0])
        data = {"id": cmd["id"], "name": cmd["name"], "type": 1, "guild_id": str(self.guild_id)}
        spec, target = cmd.get("options") or [], data
        for sub in names[1:]:
            sub_spec = next((o for o in spec if o["name"] == sub), None)
            if sub_spec is None:
                raise AssertionError(f"/{path}: no subcommand {sub}")
            node = {"name": sub, "type": sub_spec["type"], "options": []}
            target["options"] = [node]
            spec, target = sub_spec.get("options") or [], node
        target["options"] = self._options(spec, values, focused)
        return data

    async def slash(self, user: Member, path: str, channel: str | int = "", timeout: float = 10.0,
                    **values: Any) -> Interaction:
        """`/loot add item_id:18000 ...` as `slash(user, "loot add", item_id=18000, ...)`, typed in
        `channel` (default: #general if there is one)."""
        ch = self._typing_channel(channel)
        it = self._interaction_payload(2, user, ch, self._command_data(path, values))
        return await self._run(it, timeout)

    def _typing_channel(self, channel: str | int) -> Channel:
        if channel:
            return self.channel(channel)
        return next((c for c in self.channels.values() if c.name == "general"), next(iter(self.channels.values())))

    async def autocomplete(self, user: Member, path: str, focused: str, **values: Any) -> list[dict]:
        ch = self._typing_channel("")
        it = self._interaction_payload(4, user, ch, self._command_data(path, values, focused))
        await self._run(it, 10.0)
        return it.choices

    async def click(self, user: Member, message: Message, label: str, timeout: float = 10.0) -> Interaction:
        """Press the button with this label (or custom_id) on a message."""
        button = next((b for b in message.buttons if label in (b.get("label"), b.get("custom_id"))), None)
        if button is None:
            raise AssertionError(f"no button {label!r} on the message (has {message.button_labels})")
        if button.get("disabled"):
            raise AssertionError(f"button {label!r} is disabled")
        channel = self.channel(int(message.payload["channel_id"]))
        it = self._interaction_payload(3, user, channel, {"custom_id": button["custom_id"], "component_type": 2},
                                       message)
        return await self._run(it, timeout)

    async def submit(self, user: Member, opened: Interaction, *values: str, timeout: float = 10.0) -> Interaction:
        """Fill in and submit the modal the bot opened in answer to `opened`: one value per text box, in order."""
        modal = opened.modal
        if modal is None:
            raise AssertionError("the bot didn't open a form")
        boxes = iter(values)
        components = []
        for top in modal.get("components") or []:
            if top.get("type") == 1:
                components.append({"type": 1, "components": [
                    {"type": 4, "custom_id": c["custom_id"], "value": next(boxes, "")}
                    for c in top.get("components") or [] if c.get("type") == 4]})
            elif top.get("type") == 18 and (top.get("component") or {}).get("type") == 4:
                components.append({"type": 18, "component": {"type": 4, "custom_id": top["component"]["custom_id"],
                                                             "value": next(boxes, "")}})
        channel = self.channel(int(opened.payload["channel_id"]))
        it = self._interaction_payload(5, user, channel, {"custom_id": modal["custom_id"], "components": components},
                                       None)
        if "message" in opened.payload:
            it.payload["message"] = opened.payload["message"]
        return await self._run(it, timeout)
