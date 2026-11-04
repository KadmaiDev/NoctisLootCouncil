"""The newest companion app on GitHub, so the companion can tell officers there's an update.

The bot asks GitHub (about once an hour) and adds the version to GET /api/decisions; the companion never
talks to GitHub itself, and builds the download link from the version alone. Only full releases tagged
`companion-v<major>.<minor>.<patch>` count: not drafts, not pre-releases, not the addon's `addon-v` ones.
"""
from __future__ import annotations

import logging
import re

import aiohttp

log = logging.getLogger("noctis.releases")

REPO = "KadmaiDev/NoctisLootCouncil"
CHECK_SECONDS = 3600
_TAG = re.compile(r"companion-v(\d{1,4})\.(\d{1,4})\.(\d{1,4})")


def newest_companion(releases: object) -> str | None:
    """The highest companion version in GitHub's list of releases (its JSON), or None."""
    best: tuple[int, int, int] | None = None
    if not isinstance(releases, list):
        return None
    for r in releases:
        if not isinstance(r, dict) or r.get("draft") or r.get("prerelease"):
            continue
        m = _TAG.fullmatch(str(r.get("tag_name", "")))
        if m:
            version = (int(m[1]), int(m[2]), int(m[3]))
            best = version if best is None or version > best else best
    return ".".join(map(str, best)) if best else None


async def fetch_newest(session: aiohttp.ClientSession, repo: str = REPO) -> str | None:
    """Asks GitHub; None if it can't be reached or has no companion release."""
    url = f"https://api.github.com/repos/{repo}/releases?per_page=50"
    try:
        async with session.get(url, headers={"Accept": "application/vnd.github+json"},
                               timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                log.warning("GitHub's releases answered %d", resp.status)
                return None
            return newest_companion(await resp.json())
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        log.warning("Couldn't ask GitHub for releases: %s", exc)
        return None
