"""Finding the addon's saved files and turning one into the upload body (sync-format.md, sections 1 and 2)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from . import luaparse

SAVED_FILE = "NoctisLootCouncil.lua"
DB_VARIABLE = "NoctisLootCouncilDB"
FORMAT_VERSION = 1

_LINK_NAME = re.compile(r"\|h\[(.*?)\]\|h")

ITEM_FIELDS = ("link", "q", "first", "last", "seen", "inst", "handling", "note", "slot", "sub")
DROP_FIELDS = ("id", "at", "src", "inst", "n")
AWARD_FIELDS = ("id", "link", "who", "class", "at", "how", "roll", "note", "inst", "boss", "nms", "nos", "tags")
UNDONE_FIELDS = ("id", "who", "at")  # an award taken back with /nlc undo: which one it was


def find_saved_files(wow_dir: Path) -> list[Path]:
    """Every account's saved file. The client's `.bak` copy doesn't match the name, so it's skipped."""
    return sorted(p for p in (wow_dir / "WTF" / "Account").glob(f"*/SavedVariables/{SAVED_FILE}") if p.is_file())


def name_from_link(link: Any) -> str | None:
    if not isinstance(link, str):
        return None
    m = _LINK_NAME.search(link)
    return m.group(1) if m and m.group(1) else None


def _pairs(table: Any) -> Iterable[tuple[Any, Any]]:
    """Key/value pairs of a parsed Lua table, whether it came out as a dict or a list."""
    if isinstance(table, dict):
        return table.items()
    if isinstance(table, list):
        return enumerate(table, start=1)
    return ()


def _entries(table: Any) -> list[Any]:
    return [v for _, v in sorted(_pairs(table), key=lambda kv: kv[0] if isinstance(kv[0], int) else 0)]


def _pick(src: dict, fields: tuple[str, ...]) -> dict:
    return {k: src[k] for k in fields if k in src and src[k] is not None}


def build_upload(db: dict) -> dict:
    """The JSON body for POST /api/upload from the parsed NoctisLootCouncilDB."""
    items: dict[str, dict] = {}
    for item_id, it in _pairs(db.get("items")):
        if not isinstance(it, dict):
            continue
        out = _pick(it, ITEM_FIELDS)
        name = name_from_link(it.get("link"))
        if name:
            out["name"] = name
        out["from"] = {str(k): v for k, v in _pairs(it.get("from"))}
        items[str(item_id)] = out

    encounters = {str(k): _pick(v, ("name", "inst")) for k, v in _pairs(db.get("encounters")) if isinstance(v, dict)}
    instances = {str(k): v for k, v in _pairs(db.get("instances")) if isinstance(v, str)}
    drops = [_pick(d, DROP_FIELDS) for d in _entries(db.get("drops")) if isinstance(d, dict)]
    awards = [_pick(a, AWARD_FIELDS) for a in _entries(db.get("log")) if isinstance(a, dict)]
    undone = [_pick(u, UNDONE_FIELDS) for u in _entries(db.get("undone")) if isinstance(u, dict)]
    return {
        "uploader": db.get("me") if isinstance(db.get("me"), str) else None,
        "items": items,
        "encounters": encounters,
        "instances": instances,
        "drops": drops,
        "awards": awards,
        "undone": undone,
        "decisions_at": db.get("decisionsAt") if isinstance(db.get("decisionsAt"), int) else None,
    }


def read_saved_file(path: Path, variable: str = DB_VARIABLE) -> dict:
    """Parse a saved file and return its NoctisLootCouncilDB table (raises LuaError or ValueError)."""
    variables = luaparse.load_file(path)
    db = variables.get(variable)
    if not isinstance(db, dict):
        raise ValueError(f"{path.name} has no {variable} table")
    return db


# ---- Level milestones (sync-format.md, section 5) ---------------------------------------------------
# Officers who turn milestones on in game (/nlc milestones on) have a `milestones` section in the same
# saved file. Without it, or while it's off, the companion does nothing about milestones (it doesn't even
# ask the bot).

MEMBER_FIELDS = ("name", "class", "level", "rank")
LEVEL_FIELDS = ("name", "class", "from", "to", "at")


def milestones_on(db: dict) -> bool:
    """True if this file's milestones are turned on (/nlc milestones on) and hold a guild."""
    ms = db.get("milestones")
    return isinstance(ms, dict) and ms.get("on") is True and any(True for _ in _pairs(ms.get("guilds")))


def build_milestone_uploads(db: dict, guild: str) -> list[dict]:
    """The bodies for POST /api/milestones from a parsed NoctisLootCouncilDB: one per guild in its
    milestones section with the bot's guild's name (one, unless characters on two realms are in guilds of
    that name). Every other guild's roster stays here, and nothing is sent while milestones are off."""
    if not milestones_on(db):
        return []
    want = guild.strip().casefold()
    me = db.get("me") if isinstance(db.get("me"), str) else None
    bodies = []
    for _, g in sorted(_pairs(db["milestones"].get("guilds")), key=lambda kv: str(kv[0])):
        if not isinstance(g, dict) or not isinstance(g.get("name"), str) or g["name"].strip().casefold() != want:
            continue
        members = [_pick(m, MEMBER_FIELDS) for _, m in sorted(_pairs(g.get("members")), key=lambda kv: str(kv[0]))
                   if isinstance(m, dict)]
        levels = [_pick(e, LEVEL_FIELDS) for e in _entries(g.get("levels")) if isinstance(e, dict)]
        bodies.append({"uploader": me, "guild": g["name"], "realm": g.get("realm") if isinstance(g.get("realm"), str) else None,
                       "members": members, "levels": levels})
    return bodies
