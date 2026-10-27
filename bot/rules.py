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

# Drops seen by several officers are the same sighting if they fall in the same half hour
# (sync-format.md, section 2).
DROP_BUCKET_SECONDS = 1800

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


def drop_key(item_id: int, src: str | None, at: int) -> tuple[int, str, int]:
    """The de-duplication key of a drop: (item, source or "", half-hour bucket)."""
    return item_id, src or "", at // DROP_BUCKET_SECONDS


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
