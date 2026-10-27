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

ITEM_FIELDS = ("link", "q", "first", "last", "seen", "inst", "handling", "note")
DROP_FIELDS = ("id", "at", "src", "inst", "n")
AWARD_FIELDS = ("id", "link", "who", "class", "at", "how", "roll", "note", "inst", "boss", "nms", "nos")


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
    return {
        "uploader": db.get("me") if isinstance(db.get("me"), str) else None,
        "items": items,
        "encounters": encounters,
        "instances": instances,
        "drops": drops,
        "awards": awards,
    }


def read_saved_file(path: Path) -> dict:
    """Parse a saved file and return its NoctisLootCouncilDB table (raises LuaError or ValueError)."""
    variables = luaparse.load_file(path)
    db = variables.get(DB_VARIABLE)
    if not isinstance(db, dict):
        raise ValueError(f"{path.name} has no {DB_VARIABLE} table")
    return db
