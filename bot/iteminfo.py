"""Item icons, slots and Wowhead links, looked up once per item in Wowhead's Classic database.

Only what Forever shares with Classic is taken: the icon and the slot. Wowhead's Classic pages show
Season of Discovery's version of some items, so quality and stats keep coming from the game.
Items Wowhead doesn't know (Forever's own) simply go without, and are asked about again a day later.
"""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass

import aiohttp

log = logging.getLogger("noctis")

TOOLTIP_URL = "https://nether.wowhead.com/classic/tooltip/item/{id}"
ICON_URL = "https://wow.zamimg.com/images/wow/icons/large/{icon}.jpg"
PAGE_URL = "https://www.wowhead.com/classic/item={id}"
RETRY_SECONDS = 86400
TIMEOUT = aiohttp.ClientTimeout(total=15)

# '<table width="100%"><tr><td>Two-Hand</td><th>...Staff...</th>': the slot and the armour or weapon type.
_SLOT = re.compile(r'<table width="100%"><tr><td>(.*?)</td><th>(.*?)</th>', re.S)
_TAG = re.compile(r"<[^>]+>")
_ICON = re.compile(r"^[a-z0-9_]{1,64}$")


@dataclass(frozen=True)
class ItemInfo:
    found: bool
    icon: str | None = None
    slot: str | None = None  # 'Two-Hand · Staff', as /loot add writes it


def icon_url(icon: str) -> str:
    return ICON_URL.format(icon=icon)


def page_url(item_id: int) -> str:
    return PAGE_URL.format(id=item_id)


def _text(fragment: str) -> str:
    return html.unescape(_TAG.sub("", fragment)).strip()


def parse(data: dict) -> ItemInfo:
    icon = str(data.get("icon") or "").lower()
    m = _SLOT.search(str(data.get("tooltip") or ""))
    slot = " · ".join(p for p in (_text(m[1]), _text(m[2])) if p) if m else ""
    return ItemInfo(found=True, icon=icon if _ICON.match(icon) else None, slot=slot or None)


async def fetch(session: aiohttp.ClientSession, item_id: int) -> ItemInfo | None:
    """What Wowhead knows about an item; ItemInfo(found=False) if nothing, None if it couldn't be asked."""
    try:
        async with session.get(TOOLTIP_URL.format(id=item_id), timeout=TIMEOUT) as r:
            if r.status == 404:
                return ItemInfo(found=False)
            if r.status != 200:
                log.warning("Wowhead lookup for item %s: HTTP %s", item_id, r.status)
                return None
            data = await r.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        log.warning("Wowhead lookup for item %s failed: %s", item_id, exc)
        return None
    return parse(data) if isinstance(data, dict) and data.get("name") else ItemInfo(found=False)


async def fetch_icon(session: aiohttp.ClientSession, icon: str) -> bytes | None:
    try:
        async with session.get(icon_url(icon), timeout=TIMEOUT) as r:
            return await r.read() if r.status == 200 else None
    except (aiohttp.ClientError, TimeoutError) as exc:
        log.warning("Icon %s failed: %s", icon, exc)
        return None
