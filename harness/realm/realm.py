"""A raid realm: several players, each running the real addon on the fake WoW: Forever client in
their own LuaJIT process (client.lua), and the server between them.

The realm does what the game's servers do for a raid: it delivers raid chat, addon messages
(raid-wide, and whispers to one player) and loot chat, picks the number for every /roll and tells
the whole raid, fires boss kills, opens the loot window for whoever loots, and keeps every
player's clock in step. Players without the addon are simulated here: they only /roll.

    realm = Realm(root)
    lm = realm.add_player("Kadmai", "Moonwhisper", "HUNTER", rank="Officer", leader=True)
    ilsa = realm.add_player("Ilsa", "Marrow", "WARLOCK")
    bran = realm.add_player("Bran", "Holloway", "MAGE", addon=False)
    realm.login()                         # everyone with the addon logs in, with their saved file
    realm.kill(663, "Lucifron")
    realm.loot(lm, [(SASH, 4)], npc=12118)
    lm.type("/nlc start " + SASH)
    realm.wait(30)
    realm.logout()                        # saved files written, ready for the companion app

Each player plays on their own PC: a WoW folder `<root>/<ACCOUNT>` (`player.wow_dir`), with their
saved file in `WTF/Account/<ACCOUNT>/SavedVariables/NoctisLootCouncil.lua` and, if a companion app
runs on that PC, the decisions addon in `Interface/AddOns/NoctisLootDecisions`.
"""
from __future__ import annotations

import collections
import json
import os
import random
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
ADDON = REPO / "addon"
CLIENT = Path(__file__).with_name("client.lua")
PREFIX = "NoctisLC"
START_CLOCK = 1_790_000_000  # unix time when the realm's first night starts


def find_luajit() -> str | None:
    """LUAJIT if set, else luajit on PATH, else the usual Windows install folder."""
    for candidate in (os.environ.get("LUAJIT"), shutil.which("luajit"),
                      os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "LuaJIT", "bin", "luajit.exe")):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _esc(s: Any) -> str:
    return str(s).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def _unesc(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            out.append("\t" if nxt == "t" else "\n" if nxt == "n" else nxt)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _typed(v: Any) -> str:
    if v is None:
        return "z:"
    if isinstance(v, bool):
        return "b:1" if v else "b:0"
    if isinstance(v, (int, float)):
        return f"n:{v}"
    return f"s:{v}"


class GameError(RuntimeError):
    """A Lua error in a player's game (an addon error, or a command the fake couldn't do)."""


@dataclass
class Player:
    first: str
    last: str
    cls: str
    rank: str = "Raider"
    guild: str | None = "Noctis"
    addon: bool = True
    leader: bool = False
    account: str = ""
    realm: "Realm | None" = None
    proc: subprocess.Popen | None = None
    printed: list[str] = field(default_factory=list)
    gear: dict = field(default_factory=dict)  # set before login: equip/stats/gear commands to replay

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}"

    @property
    def key(self) -> str:
        return self.name.lower()

    @property
    def wow_dir(self) -> Path:
        """This player's WoW folder (their own PC), where a companion app would look."""
        assert self.realm is not None
        return self.realm.root / self.account

    @property
    def saved_file(self) -> Path:
        return self.wow_dir / "WTF" / "Account" / self.account / "SavedVariables" / "NoctisLootCouncil.lua"

    @property
    def decisions_file(self) -> Path:
        return self.wow_dir / "Interface" / "AddOns" / "NoctisLootDecisions" / "Decisions.lua"

    # ---- what the player does (players with the addon) -----------------------

    def call(self, *fields: Any) -> Any:
        """Run one command in this player's game, deliver what it sent, return its result."""
        assert self.realm is not None
        return self.realm._call(self, list(fields))

    def type(self, line: str) -> Any:
        return self.call("type", line)

    def click(self, label: str, near: str = "") -> Any:
        return self.call("click", label, near)

    def check(self, label: str) -> Any:
        return self.call("check", label)

    def set_text(self, frame: str, text: str) -> Any:
        return self.call("settext", frame, text)

    def query(self, expr: str) -> Any:
        return self.call("query", expr)

    def screen(self) -> list[str]:
        """Every text visible on the player's screen, newest window first."""
        return self.call("screen")

    def sees(self, text: str) -> bool:
        return any(text in s for s in self.screen())

    def roll(self, high: int = 100) -> None:
        """/roll (or /roll 99) typed in chat; works with or without the addon."""
        assert self.realm is not None
        self.realm._roll(self, 1, high)

    def equip_item(self, item_id: int, item_type: str, subtype: str, loc: str, cls: int = 4, sub: int = 1) -> None:
        self.call("equip", item_id, item_type, subtype, loc, cls, sub)

    def wear(self, slot: int, link: str) -> None:
        self.call("gear", slot, link)

    def item_stats(self, item_id: int, **stats: float) -> None:
        self.call("stats", item_id, *(f"{k}={v}" for k, v in stats.items()))


class Realm:
    def __init__(self, root: Path, luajit: str | None = None, seed: int = 1):
        self.root = Path(root)
        self.luajit = luajit or find_luajit()
        if not self.luajit:
            raise RuntimeError("LuaJIT not found: set LUAJIT to luajit's path")
        self.players: list[Player] = []
        self.clock = START_CLOCK
        self.rng = random.Random(seed)
        self.next_rolls: dict[str, collections.deque] = collections.defaultdict(collections.deque)
        self.chat: list[tuple[str, str, str]] = []      # (who, chat type, text): raid chat everyone saw
        self.system: list[str] = []                       # system lines: rolls
        self.addon_traffic: list[tuple[str, str, str, str]] = []  # (from, channel, target, text)
        self._spawn = 0
        self._queue: collections.deque = collections.deque()
        self._busy = 0  # player commands running (nested while one's output is being read)

    # ---- the raid ------------------------------------------------------------

    def add_player(self, first: str, last: str, cls: str, rank: str = "Raider", guild: str | None = "Noctis",
                   addon: bool = True, leader: bool = False, account: str | None = None) -> Player:
        p = Player(first, last, cls.upper(), rank, guild, addon, leader,
                   account or f"{first}{last}".upper(), self)
        self.players.append(p)
        return p

    def player(self, name: str) -> Player:
        return next(p for p in self.players if p.name == name or p.first == name)

    @property
    def clients(self) -> list[Player]:
        return [p for p in self.players if p.addon and p.proc is not None]

    def login(self) -> None:
        """Everyone with the addon starts their game (reading their saved file and the decisions
        addon), and the raid forms."""
        for p in self.players:
            if p.addon and p.proc is None:
                p.proc = subprocess.Popen([self.luajit, str(CLIENT)], cwd=str(ADDON), stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                          encoding="utf-8", bufsize=1)
                saved = p.saved_file if p.saved_file.exists() else ""
                decisions = p.decisions_file if p.decisions_file.exists() else ""
                p.call("load", p.first, p.last, p.cls, p.rank, p.guild or "", self.clock, saved, decisions)
        for p in self.clients:
            others = [f"{o.first},{o.last},{o.cls},{o.rank},{o.guild or ''}" for o in self.players if o is not p]
            p.call("raid", *others)
            if p.leader:
                p.call("leader", "1")

    def logout(self) -> None:
        """Everyone logs out: the game writes each player's saved file."""
        for p in self.clients:
            p.saved_file.parent.mkdir(parents=True, exist_ok=True)
            p.call("save", str(p.saved_file))
            self._stop(p)

    def close(self) -> None:
        for p in self.players:
            if p.proc is not None:
                self._stop(p)

    def _stop(self, p: Player) -> None:
        assert p.proc is not None
        try:
            p.proc.stdin.close()  # type: ignore[union-attr]
            p.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            p.proc.kill()
        p.proc = None

    # ---- time ------------------------------------------------------------------

    def wait(self, seconds: float, step: float = 1.0) -> None:
        """Time passes for everyone, in steps, with everything sent along the way delivered."""
        left = seconds
        while left > 0:
            dt = min(step, left)
            for p in self.clients:
                p.call("wait", dt)
            left -= dt
        self.clock += int(seconds)

    def skip(self, seconds: int) -> None:
        """Time passes while everyone is logged out (between raid nights)."""
        assert not self.clients, "log out first"
        self.clock += int(seconds)

    # ---- the world ---------------------------------------------------------------

    def fire_all(self, event: str, *args: Any) -> None:
        for p in self.clients:
            p.call("fire", event, *(_typed(a) for a in args))

    def kill(self, encounter_id: int, name: str) -> None:
        self.fire_all("ENCOUNTER_END", encounter_id, name, 9, 40, 1)

    def guid(self, npc_id: int) -> str:
        self._spawn += 1
        return f"Creature-0-4170-409-12345-{npc_id}-{self._spawn:010X}"

    def loot(self, looter: Player, items: list[tuple[str, int]], npc: int = 12118) -> str:
        """The looter opens a corpse with these items ((link, quality)). Returns the corpse GUID."""
        guid = self.guid(npc)
        fields: list[Any] = []
        for link, quality in items:
            fields += [link, quality, guid]
        looter.call("open", *fields)
        return guid

    def give(self, link: str, to: Player) -> None:
        """The item is handed to a player: everyone sees "X receives loot: [item]." in chat."""
        self.fire_all("CHAT_MSG_LOOT", f"{to.name} receives loot: {link}.", "", "", "", to.name, "", 0, 0, "", 0,
                      1, None, 0, False, False)

    def set_rolls(self, player: Player, *values: int) -> None:
        """What the player's next /rolls come up as (otherwise random, from the realm's seed)."""
        self.next_rolls[player.key].extend(values)

    def _roll(self, who: Player, low: int, high: int) -> None:
        """A /roll: the realm picks the number and the whole raid sees the line."""
        queued = self.next_rolls[who.key]
        value = queued.popleft() if queued else self.rng.randint(low, high)
        line = f"{who.name} rolls {value} ({low}-{high})"
        self.system.append(line)
        for p in self.clients:
            self._deliver(p, "CHAT_MSG_SYSTEM", line, "", "", "", "", "", 0, 0, "", 0, 1, None, 0)
        self._drain()

    # ---- the wire ------------------------------------------------------------------

    def _call(self, p: Player, fields: list[Any]) -> Any:
        """Send one command to a player's game; route everything it sends until all is quiet."""
        result = self._raw(p, fields)
        self._drain()
        return result

    def _drain(self) -> None:
        """Deliver what's queued. Only from the top: while any player's command is still running,
        a delivery to that player would interleave with its answer."""
        if self._busy:
            return
        while self._queue:
            target, cmd = self._queue.popleft()
            if target.proc is not None:
                self._raw(target, cmd)

    def _raw(self, p: Player, fields: list[Any]) -> Any:
        if p.proc is None:
            raise GameError(f"{p.name} isn't logged in")
        self._busy += 1
        try:
            return self._exchange(p, fields)
        finally:
            self._busy -= 1

    def _exchange(self, p: Player, fields: list[Any]) -> Any:
        assert p.proc is not None
        p.proc.stdin.write("\t".join(_esc(f) for f in fields) + "\n")  # type: ignore[union-attr]
        p.proc.stdin.flush()  # type: ignore[union-attr]
        while True:
            line = p.proc.stdout.readline()  # type: ignore[union-attr]
            if not line:
                err = p.proc.stderr.read() if p.proc.stderr else ""  # type: ignore[union-attr]
                raise GameError(f"{p.name}'s game stopped: {err}")
            line = line.rstrip("\n")
            kind, _, rest = line.partition("\t")
            if kind == "ok":
                return json.loads(rest)
            if kind == "err":
                raise GameError(f"{p.name}: {_unesc(rest)}")
            if kind == "out":
                self._outgoing(p, [_unesc(f) for f in rest.split("\t")])

    def _deliver(self, to: Player, event: str, *args: Any) -> None:
        self._queue.append((to, ["fire", event, *(_typed(a) for a in args)]))

    def _outgoing(self, sender: Player, out: list[str]) -> None:
        kind = out[0]
        if kind == "print":
            sender.printed.append(out[1])
        elif kind == "chat":
            chat_type, text = out[1], out[2]
            self.chat.append((sender.name, chat_type, text))
        elif kind == "roll":
            self._roll(sender, int(out[1]), int(out[2]))
        elif kind == "addon":
            prefix, text, channel, target = out[1], out[2], out[3], out[4]
            self.addon_traffic.append((sender.name, channel, target, text))
            if channel in ("RAID", "PARTY", "INSTANCE_CHAT"):
                recipients = self.clients
            elif channel == "WHISPER":
                recipients = [p for p in self.clients if p.key == target.lower()]
            else:
                recipients = []
            for p in recipients:
                self._deliver(p, "CHAT_MSG_ADDON", prefix, text, channel, sender.name, "", 0, 0, "", 0)

    # ---- reading ----------------------------------------------------------------------

    def said(self) -> str:
        """Raid chat so far, one line each."""
        return "\n".join(text for _, _, text in self.chat)

    def addon_messages(self, kind: str | None = None) -> list[tuple[str, str, str, str]]:
        """Addon traffic so far: (from, channel, target, text), optionally only one kind (S, B, V...)."""
        return [m for m in self.addon_traffic if kind is None or m[3].split("\t", 1)[0] == kind]
