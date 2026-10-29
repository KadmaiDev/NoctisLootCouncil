"""Reading the companion app's upload body (sync-format.md, section 2) into typed records.

The structure is checked strictly (a wrong container type is a 400), but a single malformed
entry is skipped rather than rejecting the whole upload: the companion sends the whole saved
file every time, so one bad entry would otherwise block every later upload from that officer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .rules import HANDLINGS

LINK_NAME = re.compile(r"\|h\[(.*?)\]\|h")


class BadUpload(ValueError):
    """The body isn't the shape the contract describes."""


@dataclass
class UploadItem:
    id: int
    name: str | None = None
    link: str | None = None
    quality: int | None = None
    first: int | None = None
    last: int | None = None
    seen: int = 0
    sources: dict[str, int] = field(default_factory=dict)
    inst: int | None = None
    handling: str | None = None
    note: str | None = None
    slot: str | None = None  # the game's equip slot, INVTYPE_WAIST
    sub: str | None = None   # armour or weapon type, Cloth


@dataclass
class UploadDrop:
    id: int
    at: int
    src: str | None
    inst: int | None
    n: int


@dataclass
class UploadAward:
    id: int
    who: str
    at: int
    how: str
    link: str | None = None
    cls: str | None = None
    roll: int | None = None
    note: str | None = None
    inst: str | None = None
    boss: str | None = None
    nms: int | None = None
    nos: int | None = None
    tags: str | None = None


@dataclass
class UploadUndone:
    """An award taken back in game (/nlc undo): the identity of the award it was."""
    id: int
    who: str
    at: int


@dataclass
class Upload:
    uploader: str | None
    items: list[UploadItem]
    encounters: dict[int, tuple[str, int | None]]
    instances: dict[int, str]
    drops: list[UploadDrop]
    awards: list[UploadAward]
    decisions_at: int | None = None  # the newest decisions the uploader's game had applied
    undone: list[UploadUndone] = field(default_factory=list)  # awards taken back (missing from older companions)
    skipped: int = 0  # malformed entries left out


def name_from_link(link: str | None) -> str | None:
    if not link:
        return None
    m = LINK_NAME.search(link)
    return m.group(1) if m and m.group(1) else None


def _int(v: Any) -> int | None:
    # JSON has one number type; the client writes whole numbers, but accept 3.0 as 3.
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
        return int(v)
    return None


def _str(v: Any) -> str | None:
    return v if isinstance(v, str) and v != "" else None


def _container(body: dict, key: str, kind: type) -> Any:
    v = body.get(key)
    if v is None:
        return kind()
    # The client writes an empty Lua table for an empty list, which the companion may send as {}.
    if kind is list and v == {}:
        return []
    if not isinstance(v, kind):
        raise BadUpload(f"`{key}` must be a JSON {'object' if kind is dict else 'array'}")
    return v


def parse_upload(body: Any) -> Upload:
    if not isinstance(body, dict):
        raise BadUpload("the body must be a JSON object")
    skipped = 0

    items: list[UploadItem] = []
    for key, raw in _container(body, "items", dict).items():
        iid = _int(key)
        if iid is None or iid <= 0 or not isinstance(raw, dict):
            skipped += 1
            continue
        link = _str(raw.get("link"))
        sources: dict[str, int] = {}
        if isinstance(raw.get("from"), dict):
            for src, n in raw["from"].items():
                n = _int(n)
                if isinstance(src, str) and src and n is not None:
                    sources[src] = n
        handling = raw.get("handling")
        items.append(UploadItem(
            id=iid,
            name=_str(raw.get("name")) or name_from_link(link),
            link=link,
            quality=_int(raw.get("q")),
            first=_int(raw.get("first")),
            last=_int(raw.get("last")),
            seen=max(_int(raw.get("seen")) or 0, 0),
            sources=sources,
            inst=_int(raw.get("inst")),
            handling=handling if handling in HANDLINGS else None,
            note=_str(raw.get("note")),
            slot=_str(raw.get("slot")),
            sub=_str(raw.get("sub")),
        ))

    encounters: dict[int, tuple[str, int | None]] = {}
    for key, raw in _container(body, "encounters", dict).items():
        eid = _int(key)
        if eid is None or not isinstance(raw, dict) or not _str(raw.get("name")):
            skipped += 1
            continue
        encounters[eid] = (raw["name"], _int(raw.get("inst")))

    instances: dict[int, str] = {}
    for key, raw in _container(body, "instances", dict).items():
        iid = _int(key)
        if iid is None or not _str(raw):
            skipped += 1
            continue
        instances[iid] = raw

    drops: list[UploadDrop] = []
    for raw in _container(body, "drops", list):
        if not isinstance(raw, dict):
            skipped += 1
            continue
        iid, at = _int(raw.get("id")), _int(raw.get("at"))
        if iid is None or at is None:
            skipped += 1
            continue
        drops.append(UploadDrop(id=iid, at=at, src=_str(raw.get("src")), inst=_int(raw.get("inst")),
                                n=max(_int(raw.get("n")) or 1, 1)))

    awards: list[UploadAward] = []
    for raw in _container(body, "awards", list):
        if not isinstance(raw, dict):
            skipped += 1
            continue
        iid, at, who, how = _int(raw.get("id")), _int(raw.get("at")), _str(raw.get("who")), _str(raw.get("how"))
        if iid is None or at is None or who is None or how is None:
            skipped += 1
            continue
        awards.append(UploadAward(
            id=iid, who=who, at=at, how=how, link=_str(raw.get("link")), cls=_str(raw.get("class")),
            roll=_int(raw.get("roll")), note=_str(raw.get("note")), inst=_str(raw.get("inst")),
            boss=_str(raw.get("boss")), nms=_int(raw.get("nms")), nos=_int(raw.get("nos")),
            tags=_str(raw.get("tags")),
        ))

    undone: list[UploadUndone] = []
    for raw in _container(body, "undone", list):
        if not isinstance(raw, dict):
            skipped += 1
            continue
        iid, at, who = _int(raw.get("id")), _int(raw.get("at")), _str(raw.get("who"))
        if iid is None or at is None or who is None:
            skipped += 1
            continue
        undone.append(UploadUndone(id=iid, who=who, at=at))

    return Upload(uploader=_str(body.get("uploader")), items=items, encounters=encounters,
                  instances=instances, drops=drops, awards=awards, decisions_at=_int(body.get("decisions_at")),
                  undone=undone, skipped=skipped)
