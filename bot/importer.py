"""Items found outside our raids, for /loot import and /loot add: Wowhead links, in-game item links
or item IDs, or another guild's RCLootCouncil CSV export (the format oxm.gg imports, and the one our
addon's /nlc export writes). From a CSV only the items and where they dropped are taken: the winners
are another guild's raiders.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from .upload import name_from_link

# Origins (items.origin): pasted links and IDs are taken as spotted on Wowhead, a CSV as another guild's raid.
WOWHEAD, OTHER_RAID = "wowhead", "other_raid"

_WOWHEAD = re.compile(r"wowhead\.com/(?:[a-z-]+/)*item=(\d+)", re.I)
_GAME = re.compile(r"item:(\d+)")
_ID = re.compile(r"^\d{1,8}$")
MAX_ITEMS = 300


@dataclass(frozen=True)
class Found:
    item_id: int
    name: str | None = None    # from a CSV; Wowhead's is used when it has the item
    source: str | None = None  # 'Molten Core, Lucifron', from a CSV


@dataclass(frozen=True)
class Parsed:
    items: list[Found]
    origin: str
    unread: int  # pieces of text (or CSV rows) that weren't an item


def item_id(text: str) -> int | None:
    """One item: a Wowhead link, an in-game item link or an item ID."""
    text = text.strip()
    m = _WOWHEAD.search(text) or _GAME.search(text)
    if m:
        return int(m[1])
    return int(text) if _ID.match(text) and int(text) > 0 else None


def _links(text: str) -> Parsed:
    items: dict[int, Found] = {}
    unread = 0
    # In-game links have spaces inside their [Name]: take those whole, then split the rest on spaces and commas.
    for link in re.findall(r"\|c[^|]*\|Hitem:[^|]*\|h\[[^\]]*\]\|h\|r", text):
        iid = item_id(link)
        if iid:
            items.setdefault(iid, Found(iid, name_from_link(link)))
        text = text.replace(link, " ")
    for piece in re.split(r"[\s,;]+", text):
        if not piece:
            continue
        iid = item_id(piece)
        if iid:
            items.setdefault(iid, Found(iid))
        else:
            unread += 1
    return Parsed(list(items.values())[:MAX_ITEMS], WOWHEAD, unread)


def _csv(text: str) -> Parsed:
    items: dict[int, Found] = {}
    unread = 0
    for row in csv.DictReader(io.StringIO(text)):
        iid = item_id(row.get("itemID") or "") or item_id(row.get("itemString") or "")
        if not iid:
            unread += 1
            continue
        raw = (row.get("item") or "").strip()
        name = name_from_link(raw) or (raw.strip("[]") if raw and not raw.startswith(("item:", "|")) else None)
        source = ", ".join(p for p in ((row.get("instance") or "").strip(), (row.get("boss") or "").strip()) if p)
        old = items.get(iid)
        if old is None or len(source) > len(old.source or ""):  # a row naming the boss beats one without
            items[iid] = Found(iid, name or (old and old.name), source or None)
    return Parsed(list(items.values())[:MAX_ITEMS], OTHER_RAID, unread)


def parse(text: str) -> Parsed:
    """What was pasted or attached: an RCLootCouncil CSV (its header has itemID) or links and IDs."""
    text = text.lstrip("﻿")
    first = text.lstrip().split("\n", 1)[0]
    if "itemID" in first.split(","):
        return _csv(text.lstrip())
    return _links(text)
