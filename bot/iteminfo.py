"""Item icons, slots, quality and Wowhead links, looked up on Wowhead: its Forever database first,
then Classic's.

Wowhead's Forever data has Forever's own version of an item, so its quality is used until the game
reports one. Not every item is in it yet: for those, Classic's database gives the icon and slot only,
since its pages show Season of Discovery's version of some items. An item not in Forever's data is
asked about again a day later (Wowhead keeps adding them); one in neither simply goes without.
"""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass

import aiohttp

log = logging.getLogger("noctis")

FOREVER, CLASSIC = "forever", "classic"
TOOLTIP_URL = "https://nether.wowhead.com/{env}/tooltip/item/{id}"
ICON_URL = "https://wow.zamimg.com/images/wow/icons/large/{icon}.jpg"
PAGE_URL = "https://www.wowhead.com/{env}/item={id}/{slug}"
RETRY_SECONDS = 86400
TIMEOUT = aiohttp.ClientTimeout(total=15)

# '<table width="100%"><tr><td>Two-Hand</td><th>...Staff...</th>': the slot and the armour or weapon type.
_SLOT = re.compile(r'<table width="100%"><tr><td>(.*?)</td><th>(.*?)</th>', re.S)
_TAG = re.compile(r"<[^>]+>")
_ICON = re.compile(r"^[a-z0-9_]{1,64}$")


@dataclass(frozen=True)
class ItemInfo:
    found: bool
    env: str | None = None   # forever or classic: which of Wowhead's databases has it
    name: str | None = None
    quality: int | None = None  # Forever's only
    icon: str | None = None
    slot: str | None = None  # 'Two-Hand · Staff', as /loot add writes it


def icon_url(icon: str) -> str:
    return ICON_URL.format(icon=icon)


def slug(name: str) -> str:
    """'Staff of Jordan' -> 'staff-of-jordan', as Wowhead's page addresses end."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "")).strip("-")


def page_url(item_id: int, name: str, env: str = FOREVER) -> str:
    return PAGE_URL.format(env=env, id=item_id, slug=slug(name)).rstrip("/")


def _text(fragment: str) -> str:
    return html.unescape(_TAG.sub("", fragment)).strip()


def parse(data: dict, env: str) -> ItemInfo:
    icon = str(data.get("icon") or "").lower()
    m = _SLOT.search(str(data.get("tooltip") or ""))
    slot = " · ".join(p for p in (_text(m[1]), _text(m[2])) if p) if m else ""
    quality = data.get("quality") if env == FOREVER and isinstance(data.get("quality"), int) else None
    return ItemInfo(found=True, env=env, name=str(data.get("name") or "") or None, quality=quality,
                    icon=icon if _ICON.match(icon) else None, slot=slot or None)


async def _fetch_env(session: aiohttp.ClientSession, item_id: int, env: str) -> ItemInfo | None:
    async with session.get(TOOLTIP_URL.format(env=env, id=item_id), timeout=TIMEOUT) as r:
        if r.status == 404:
            return ItemInfo(found=False)
        if r.status != 200:
            log.warning("Wowhead lookup for item %s (%s): HTTP %s", item_id, env, r.status)
            return None
        data = await r.json(content_type=None)
    return parse(data, env) if isinstance(data, dict) and data.get("name") else ItemInfo(found=False)


async def fetch(session: aiohttp.ClientSession, item_id: int) -> ItemInfo | None:
    """What Wowhead knows about an item; ItemInfo(found=False) if nothing, None if it couldn't be asked."""
    try:
        info = await _fetch_env(session, item_id, FOREVER)
        if info is not None and not info.found:
            info = await _fetch_env(session, item_id, CLASSIC)
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        log.warning("Wowhead lookup for item %s failed: %s", item_id, exc)
        return None
    return info


async def fetch_icon(session: aiohttp.ClientSession, icon: str) -> bytes | None:
    try:
        async with session.get(icon_url(icon), timeout=TIMEOUT) as r:
            return await r.read() if r.status == 200 else None
    except (aiohttp.ClientError, TimeoutError) as exc:
        log.warning("Icon %s failed: %s", icon, exc)
        return None
