"""Level milestones: the addon (for officers who turn it on) notes guild members' level-ups, the
companion uploads them (POST /api/milestones, sync-format.md section 5) and the bot congratulates
in its milestones channel. This module is pure: the upload's shape, the settings, which milestone
a level-up earns, and the post's wording. The database side is in store.py."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from . import render
from .upload import BadUpload

DEFAULT_LEVELS = (10, 20, 30, 40, 50, 60)
# A level-up noticed longer ago than this isn't announced: an officer's first upload, or one after
# weeks away, would otherwise post a month of old news.
STALE_SECONDS = 7 * 86400
MAX_NAME = 64
MAX_MEMBERS = 5000
MAX_LEVELS = 5000
MAX_LEVEL = 200

CLASS_COLOURS = {  # the game's class colours
    "DRUID": 0xFF7C0A, "HUNTER": 0xAAD372, "MAGE": 0x3FC7EB, "PALADIN": 0xF48CBA, "PRIEST": 0xFFFFFF,
    "ROGUE": 0xFFF468, "SHAMAN": 0x0070DD, "WARLOCK": 0x8788EE, "WARRIOR": 0xC69B6D,
    "DEATHKNIGHT": 0xC41E3A, "MONK": 0x00FF98, "DEMONHUNTER": 0xA330C9, "EVOKER": 0x33937F,
}
GOLD = 0xFFD100
CLASS_NAMES = {"DEATHKNIGHT": "Death Knight", "DEMONHUNTER": "Demon Hunter"}


@dataclass(frozen=True)
class Settings:
    """What /milestones settings set. Nothing is accepted or posted until it's on with a guild and channel."""
    on: bool = False
    guild: str | None = None
    channel_id: int | None = None
    levels: tuple[int, ...] = DEFAULT_LEVELS
    since: int = 0  # when it was last turned on: level-ups from before aren't announced

    @property
    def ready(self) -> bool:
        return self.on and bool(self.guild) and bool(self.channel_id)


def parse_levels(text: str) -> tuple[int, ...]:
    """'10, 20, 30' -> (10, 20, 30). Raises ValueError with a message for the officer."""
    parts = [p for p in text.replace(";", ",").replace(" ", ",").split(",") if p]
    if not parts or not all(p.isdigit() for p in parts):
        raise ValueError("Levels are whole numbers separated by commas, like `10, 20, 30, 40, 50, 60`.")
    levels = sorted({int(p) for p in parts})
    if levels[0] < 2 or levels[-1] > MAX_LEVEL:
        raise ValueError(f"Levels go from 2 to {MAX_LEVEL}.")
    return tuple(levels)


def same_guild(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and a.strip().casefold() == b.strip().casefold()


def name_key(name: str) -> str:
    return " ".join(name.split()).casefold()


# ---- the upload ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Member:
    name: str
    level: int
    cls: str | None = None
    rank: str | None = None


@dataclass(frozen=True)
class LevelUp:
    name: str
    frm: int
    to: int
    at: int
    cls: str | None = None


@dataclass(frozen=True)
class MilestoneUpload:
    guild: str
    realm: str | None
    uploader: str | None
    members: list[Member]
    levels: list[LevelUp]


def _text(v: Any, what: str, required: bool = False) -> str | None:
    if v is None and not required:
        return None
    if not isinstance(v, str) or not v.strip() or len(v) > MAX_NAME:
        raise BadUpload(f"{what} should be a short text")
    return v.strip()


def _int(v: Any, what: str) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise BadUpload(f"{what} should be a whole number")
    return v


def _level(v: Any, what: str) -> int:
    n = _int(v, what)
    if not 1 <= n <= MAX_LEVEL:
        raise BadUpload(f"{what} should be a level")
    return n


def parse_milestone_upload(body: Any) -> MilestoneUpload:
    if not isinstance(body, dict):
        raise BadUpload("the body should be a JSON object")
    members_in, levels_in = body.get("members", []), body.get("levels", [])
    if not isinstance(members_in, list) or not isinstance(levels_in, list):
        raise BadUpload("members and levels should be lists")
    if len(members_in) > MAX_MEMBERS or len(levels_in) > MAX_LEVELS:
        raise BadUpload("too many members or level-ups")
    members, levels = [], []
    for i, m in enumerate(members_in):
        if not isinstance(m, dict):
            raise BadUpload(f"members[{i}] should be an object")
        members.append(Member(_text(m.get("name"), f"members[{i}].name", True), _level(m.get("level"), f"members[{i}].level"),
                              _text(m.get("class"), f"members[{i}].class"), _text(m.get("rank"), f"members[{i}].rank")))
    for i, e in enumerate(levels_in):
        if not isinstance(e, dict):
            raise BadUpload(f"levels[{i}] should be an object")
        frm, to = _level(e.get("from"), f"levels[{i}].from"), _level(e.get("to"), f"levels[{i}].to")
        if to <= frm:
            raise BadUpload(f"levels[{i}] should go up")
        levels.append(LevelUp(_text(e.get("name"), f"levels[{i}].name", True), frm, to, _int(e.get("at"), f"levels[{i}].at"),
                              _text(e.get("class"), f"levels[{i}].class")))
    return MilestoneUpload(guild=_text(body.get("guild"), "guild", True), realm=_text(body.get("realm") or None, "realm"),
                           uploader=_text(body.get("uploader"), "uploader"), members=members, levels=levels)


# ---- which milestone -----------------------------------------------------------------------------

def milestone_for(frm: int, to: int, levels: tuple[int, ...]) -> int | None:
    """The milestone a level-up from `frm` to `to` earns: the highest one it passed (someone who went
    from 18 to 31 between two roster reads gets 30, not 20 and 30)."""
    passed = [m for m in levels if frm < m <= to]
    return max(passed) if passed else None


# ---- the post ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Milestone:
    """A milestone to post (or posted): who, which level, and when it was noticed."""
    key: str
    name: str
    level: int
    at: int
    cls: str | None = None
    rank: str | None = None
    nth: int | None = None  # set for the top milestone: how many in the guild had reached it by then
    top: bool = False       # the highest level in the settings (max level)
    guild: str = ""


def class_name(cls: str | None) -> str:
    if not cls:
        return ""
    return CLASS_NAMES.get(cls.upper(), cls.capitalize())


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def card(m: Milestone, levels: tuple[int, ...], tz: ZoneInfo) -> render.Card:
    nxt = next((lv for lv in levels if lv > m.level), None)
    if m.top:
        body = "**Congratulations on reaching max level!**"
        if m.nth:
            body += f" The {ordinal(m.nth)} in {render.md(m.guild)} to get there." if m.guild else ""
    else:
        body = "**Congratulations!**" + (f" Next stop: level {nxt}." if nxt else "")
    noticed = dt.datetime.fromtimestamp(m.at, tz)
    return render.Card(
        kicker=f"Level {m.level}",
        title=f"{render.md(m.name)} reached level {m.level}",
        subtitle=" · ".join(p for p in (class_name(m.cls), render.md(m.rank or "")) if p),
        body=body,
        footer=f"Noticed {noticed.day} {noticed:%b, %H:%M}",
        colour=CLASS_COLOURS.get((m.cls or "").upper(), GOLD),
    )


def settings_text(s: Settings, channel_mention: str | None, counts: tuple[int, int, int]) -> str:
    """/milestones settings' answer: what's set, and what the bot has."""
    characters, posted, waiting = counts
    state = "**On**" if s.ready else ("**On**, but not posting until " + (
        "the guild and channel are set" if not s.guild and not s.channel_id else
        "the guild is set" if not s.guild else "the channel is set") if s.on else "**Off**")
    lines = [
        f"Level milestones: {state}.",
        f"Guild: {render.md(s.guild) if s.guild else 'not set'} (uploads from characters in any other guild are ignored).",
        f"Channel: {channel_mention or 'not set'}.",
        f"Levels: {', '.join(str(lv) for lv in s.levels)}.",
        f"Characters known: {characters}; milestones posted: {posted}" + (f"; waiting to post: {waiting}" if waiting else "") + ".",
    ]
    if not s.on:
        lines.append("Uploads are ignored while it's off, and turning it on announces nothing from before.")
    return "\n".join(lines)
