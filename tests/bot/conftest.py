from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from bot.db import connect
from bot.store import Store

TZ = ZoneInfo("Europe/London")

# Monday 26 Oct 2026, 20:30 in London: a raid night.
RAID = 1793046600


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock(RAID + 4 * 3600)  # just after midnight, when the loot master logs out


@pytest.fixture
def store(tmp_path, clock) -> Store:
    return Store(connect(tmp_path / "loot.db"), TZ, votes_to_decide=3, clock=clock)


def link(item_id: int, name: str, colour: str = "a335ee") -> str:
    return f"|cff{colour}|Hitem:{item_id}::::::::60:::::|h[{name}]|h|r"


def sample_body(uploader: str = "Kadmai Moonwhisper") -> dict:
    """An upload like the contract's example: one raid night in Molten Core."""
    return {
        "uploader": uploader,
        "items": {
            "18000": {"link": link(18000, "Sash of the Unseen"), "q": 4, "first": RAID - 86400 * 3,
                      "last": RAID + 600, "seen": 1, "from": {"e663": 1}, "inst": 409,
                      "handling": "council", "note": "Warlock priority"},
            "16805": {"link": link(16805, "Felheart Gloves"), "q": 4, "first": RAID + 900, "last": RAID + 900,
                      "seen": 1, "from": {"e663": 1}, "inst": 409},
            "17069": {"link": "item:17069", "q": 4, "first": RAID - 3600, "last": RAID - 3600, "seen": 0},
        },
        "encounters": {"663": {"name": "Lucifron", "inst": 409}},
        "instances": {"409": "Molten Core"},
        "drops": [
            {"id": 18000, "at": RAID + 600, "src": "e663", "inst": 409, "n": 1},
            {"id": 16805, "at": RAID + 900, "src": "e663", "inst": 409, "n": 1},
        ],
        "awards": [
            {"id": 18000, "link": link(18000, "Sash of the Unseen"), "who": "Ilsa Marrow", "class": "WARLOCK",
             "at": RAID + 700, "how": "council", "note": "Warlock priority; biggest upgrade",
             "inst": "Molten Core", "boss": "Lucifron", "nms": 4, "nos": 1},
            {"id": 16805, "link": link(16805, "Felheart Gloves"), "who": "Corvin Dusk", "class": "WARLOCK",
             "at": RAID + 1000, "how": "ms", "roll": 77, "inst": "Molten Core", "boss": "Lucifron",
             "nms": 4, "nos": 1},
        ],
    }
