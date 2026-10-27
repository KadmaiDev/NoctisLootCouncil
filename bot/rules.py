"""The loot rules the bot applies, as plain functions (no Discord, no database).

Kept separate so they can be tested on their own and read in one place.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

COUNCIL = "council"
ROLL = "roll"
HANDLINGS = (COUNCIL, ROLL)

# Drops seen by several officers are the same sighting if they are within 15 minutes of each
# other (sync-format.md, section 2). A boss drops once per kill, so this can't merge two kills.
DROP_WINDOW_SECONDS = 900

# A raid night runs past midnight: anything before 06:00 local time belongs to the evening before.
NIGHT_CUTOFF_HOURS = 6


@dataclass(frozen=True)
class Vote:
    user_id: int
    user_name: str
    choice: str  # COUNCIL or ROLL
    at: int = 0


@dataclass(frozen=True)
class Tally:
    council: list[str] = field(default_factory=list)  # voter names, in voting order
    roll: list[str] = field(default_factory=list)
    needed: int = 3
    decided: str | None = None

    @property
    def total(self) -> int:
        return len(self.council) + len(self.roll)

    def count(self, choice: str) -> int:
        return len(self.council) if choice == COUNCIL else len(self.roll)

    @property
    def tied_at_threshold(self) -> bool:
        return self.decided is None and len(self.council) == len(self.roll) >= self.needed


def tally(votes: list[Vote], needed: int) -> Tally:
    """Count one vote per officer. An option decides once it has `needed` votes and more than the other.

    Votes are changeable, so a decision can also be undone when someone switches: the result is
    always recomputed from the current votes, never remembered.
    """
    latest: dict[int, Vote] = {}
    for v in sorted(votes, key=lambda v: v.at):
        latest[v.user_id] = v
    ordered = sorted(latest.values(), key=lambda v: v.at)
    council = [v.user_name for v in ordered if v.choice == COUNCIL]
    roll = [v.user_name for v in ordered if v.choice == ROLL]
    decided = None
    if len(council) >= needed and len(council) > len(roll):
        decided = COUNCIL
    elif len(roll) >= needed and len(roll) > len(council):
        decided = ROLL
    return Tally(council=council, roll=roll, needed=needed, decided=decided)


def same_drop(at: int, other_at: int) -> bool:
    """Two reports of a drop with the same item and source are one drop if close enough in time."""
    return abs(at - other_at) <= DROP_WINDOW_SECONDS


# The game's equip slots, as the posts name them.
SLOT_NAMES = {
    "INVTYPE_HEAD": "Head", "INVTYPE_NECK": "Neck", "INVTYPE_SHOULDER": "Shoulder", "INVTYPE_BODY": "Shirt",
    "INVTYPE_CHEST": "Chest", "INVTYPE_ROBE": "Chest", "INVTYPE_WAIST": "Waist", "INVTYPE_LEGS": "Legs",
    "INVTYPE_FEET": "Feet", "INVTYPE_WRIST": "Wrist", "INVTYPE_HAND": "Hands", "INVTYPE_FINGER": "Finger",
    "INVTYPE_TRINKET": "Trinket", "INVTYPE_CLOAK": "Back", "INVTYPE_WEAPON": "One-hand",
    "INVTYPE_SHIELD": "Shield", "INVTYPE_2HWEAPON": "Two-hand", "INVTYPE_WEAPONMAINHAND": "Main hand",
    "INVTYPE_WEAPONOFFHAND": "Off hand", "INVTYPE_HOLDABLE": "Held in off hand", "INVTYPE_RANGED": "Ranged",
    "INVTYPE_RANGEDRIGHT": "Ranged", "INVTYPE_THROWN": "Thrown", "INVTYPE_RELIC": "Relic",
    "INVTYPE_TABARD": "Tabard", "INVTYPE_BAG": "Bag",
}

# Armour and weapon types that add nothing after the slot name.
_PLAIN_SUBTYPES = {"Miscellaneous", "Junk", "Other"}


def slot_text(slot: str | None, sub: str | None) -> str | None:
    """'Waist · Cloth' from the addon's slot and armour type; None if it knows neither."""
    name = SLOT_NAMES.get(slot or "")
    if name is None and slot and slot.startswith("INVTYPE_"):
        name = slot[len("INVTYPE_"):].replace("_", " ").title()
    sub = sub if sub and sub not in _PLAIN_SUBTYPES and sub != name else None
    return " · ".join(p for p in (name, sub) if p) or None


def award_key(who: str, item_id: int, at: int) -> tuple[str, int, int]:
    """Awards are the same award if winner (any case), item and time match."""
    return who.strip().lower(), item_id, at


def merge_sources(old: dict[str, int], new: dict[str, int]) -> dict[str, int]:
    """Union of drop sources. Counts take the largest report, because officers upload the same raids."""
    out = dict(old)
    for src, n in new.items():
        out[src] = max(out.get(src, 0), n)
    return out


def better_link(old: str | None, new: str | None) -> str | None:
    """Prefer a full game link over the bare `item:18000` the addon writes before the game loads an item."""
    if not new:
        return old
    if not old:
        return new
    if "|Hitem:" in new or "|Hitem:" not in old:
        return new
    return old


def night_of(ts: int, tz: ZoneInfo) -> dt.date:
    """The raid night a unix time belongs to, in the guild's time zone."""
    local = dt.datetime.fromtimestamp(ts, tz) - dt.timedelta(hours=NIGHT_CUTOFF_HOURS)
    return local.date()


def day_label(day: dt.date) -> str:
    """'Monday 27 Oct', as in the mockups."""
    return f"{day:%A} {day.day} {day:%b}"


def short_day_label(day: dt.date) -> str:
    """'Mon 27 Oct'."""
    return f"{day:%a} {day.day} {day:%b}"


HOW_ROLL_TEXT = {
    "ms": "main-spec roll",
    "ms2": "second main-spec roll",
    "os": "off-spec roll",
}

HOW_SPEC_TEXT = {
    "ms": "main spec",
    "ms2": "second main spec",
    "os": "off spec",
}
