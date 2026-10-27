"""Items, and what officers do, shared by the harness scenarios."""
from __future__ import annotations

import asyncio
import re

from companion.app import Companion
from companion.config import Settings


def link(item_id: int, name: str, quality: int = 4) -> str:
    colour = {3: "0070dd", 4: "a335ee", 5: "ff8000"}[quality]
    return f"|cff{colour}|Hitem:{item_id}::::::::60:::::::::|h[{name}]|h|r"


SASH = link(18000, "Sash of the Unseen")
HELM = link(16866, "Helm of Might")
CLOAK = link(17109, "Cloak of the Shrouded Mists")
COUNCIL = "Seren Vale, Doran Pike, Kadmai Moonwhisper"


async def token_for(guild, officer) -> str:
    """/loot token in Discord: the token for the officer's companion app."""
    r = await guild.slash(officer, "loot token")
    return re.search(r"nlc_[\w-]+", r.text).group(0)


async def companion_pass(player, api_url: str, token: str) -> None:
    """One pass of the companion app on this player's PC: upload what changed, write the decisions."""
    comp = Companion(Settings(wow_dir=player.wow_dir, bot_url=api_url, token=token))
    await asyncio.to_thread(comp.run_once)


async def decide(guild, item_id: int, choice: str, priority: str = "") -> None:
    """Every officer presses Council or Roll on the item's #loot-officers post (and one sets a priority)."""
    post = await guild.wait_until(lambda: next((m for m in guild.channel("loot-officers").posts
                                                if f"nlc:vote:council:{item_id}" in
                                                [b.get("custom_id") for b in m.buttons]), None),
                                  what=f"the officer post for {item_id}")
    for officer in guild.officers:
        await guild.click(officer, post, choice)
    if priority:
        opened = await guild.click(guild.officers[0], post, "Set priority")
        await guild.submit(guild.officers[0], opened, priority)
