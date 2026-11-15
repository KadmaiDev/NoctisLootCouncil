"""The road to max level: a rough forecast of when each character gets there, from the level-ups
officers' addons noticed (the milestones upload), posted in a channel of its own and edited in
place like the roster. This module is pure: the settings, the sums and the posts' wording. Output
depends only on what's passed in: "now" is the newest roster read, never the clock.

The game shows another player's level, not their experience, so pace is measured between level-ups
and weighed by what each level costs. A level-up is only known to have happened between two roster
reads (`lo` to `hi`), which is a minute apart while an officer is online and hours when none was."""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from . import render, roster
from .milestones import GOLD, name_key
from .roster import Board, Character

# Experience to go from each level to the next, levels 1 to 59 (Classic's; Forever's own table hasn't
# been checked against it. Only the shape matters here: a late level costs many early ones).
XP_TO_NEXT = (
    400, 900, 1400, 2100, 2800, 3600, 4500, 5400, 6500, 7600,
    8800, 10100, 11400, 12900, 14400, 16000, 17700, 19400, 21300, 23200,
    25200, 27300, 29400, 31700, 34000, 36400, 38900, 41400, 44300, 47400,
    50800, 54500, 58600, 62800, 67100, 71600, 76100, 80800, 85700, 90700,
    95800, 101000, 106300, 111800, 117500, 123200, 129100, 135100, 141200, 147500,
    153900, 160400, 167100, 173900, 180800, 187900, 195000, 202300, 209800,
)
DAY = 86400
WINDOW = 14 * DAY          # pace is measured over the level-ups of the last two weeks
LOOKBACK = 2 * WINDOW      # with one level-up in that time, from the one before it, if no older than this
MIN_SPAN = 3600            # two level-ups closer than this say nothing about pace
FAR = 365 * DAY            # a forecast further off than this is no forecast
# People slow down and speed up: the range is never tighter than this around the estimate.
EARLY, LATE = 0.75, 1.5
SOON, MONTH = 7 * DAY, 30 * DAY
RUNNER, SLEEPING, NEW = "\N{RUNNER}", "\N{SLEEPING SYMBOL}", "\N{SQUARED NEW}"
# How much there was to go on, shown before each name.
GOOD, FAIR, THIN = "good", "fair", "thin"
MARKS = {GOOD: "\N{LARGE GREEN CIRCLE}", FAIR: "\N{LARGE YELLOW CIRCLE}", THIN: "\N{LARGE ORANGE CIRCLE}"}
GOOD_LEVELS, GOOD_SPAN, GOOD_SLACK = 4, 3 * DAY, 0.15  # level-ups measured, over how long, how loosely timed
THIN_SPAN, THIN_SLACK = DAY, 0.5
QUIET, UNSEEN = "quiet", "new"  # why there's no forecast


@dataclass(frozen=True)
class Settings:
    """What /roster forecast set. Nothing is posted until it's on with a channel."""
    on: bool = False
    channel_id: int | None = None

    @property
    def ready(self) -> bool:
        return self.on and bool(self.channel_id)


@dataclass(frozen=True)
class Reached:
    """A level reached some time after `lo` (None: not known) and no later than `hi`."""
    level: int
    lo: int | None
    hi: int


@dataclass(frozen=True)
class Forecast:
    eta: int
    early: int
    late: int
    quality: str = FAIR  # GOOD, FAIR or THIN: how much there was to go on


def xp_to_next(level: int) -> int:
    """What the level costs; past the table, as much as its last level."""
    return XP_TO_NEXT[min(max(level, 1), len(XP_TO_NEXT)) - 1]


def xp_at(level: int) -> int:
    """Experience earned by the start of a level."""
    return sum(xp_to_next(lv) for lv in range(1, level))


def _when(p: Reached) -> float:
    return (p.lo + p.hi) / 2 if p.lo is not None and p.lo < p.hi else p.hi


def _eta(l0: int, t0: float, l1: int, t1: float, now: int, target: int) -> float | None:
    """When `target` is reached by someone who got from the start of level l0 (at t0) to the start
    of l1 (at t1). Their pace between the two holds while they could still be within the level at
    that pace; once the level has taken longer, the pace is what it would be had they levelled just
    now, so a forecast slips as a character goes quiet."""
    if t1 - t0 < MIN_SPAN or now <= t0:
        return None
    rate = min((xp_at(l1) - xp_at(l0)) / (t1 - t0), (xp_at(l1 + 1) - xp_at(l0)) / (now - t0))
    if rate <= 0:
        return None
    progress = min(xp_to_next(l1), rate * max(0, now - t1))
    return now + (xp_at(target) - xp_at(l1) - progress) / rate


def _line(level: int, reached: Iterable[Reached], now: int) -> list[Reached]:
    """The level-ups that count, lowest first: up to the level the roster shows, none from after `now`."""
    points: dict[int, Reached] = {}
    for p in reached:
        if 1 < p.level <= level and p.hi <= now:
            points[p.level] = p
    line = [points[lv] for lv in sorted(points)]
    if line and line[-1].level < level:  # the roster shows a level nobody saw them reach: some time since the last one
        line.append(Reached(level, line[-1].hi, now))
    return line


def why_not(level: int, reached: Iterable[Reached], now: int) -> str:
    """For a character without a forecast: UNSEEN when the level-ups on record were noticed at
    fewer than two different times (new to the guild, or never seen levelling), else QUIET."""
    return QUIET if len({p.hi for p in _line(level, reached, now)}) >= 2 else UNSEEN


def _quality(a: Reached, b: Reached) -> str:
    """Good: four or more level-ups over three days or more, timed closely. Thin: one level-up,
    under a day, or timed so loosely that the gaps between roster reads are half the span.
    Without `lo` (older companions) the timing isn't known: fair at best."""
    span, measured = _when(b) - _when(a), b.level - a.level
    slack = ((a.hi - a.lo) + (b.hi - b.lo)) / span if a.lo is not None and b.lo is not None else None
    if measured < 2 or span < THIN_SPAN or (slack is not None and slack > THIN_SLACK):
        return THIN
    if measured >= GOOD_LEVELS and span >= GOOD_SPAN and slack is not None and slack <= GOOD_SLACK:
        return GOOD
    return FAIR


def forecast(level: int, reached: Iterable[Reached], now: int, target: int) -> Forecast | None:
    """When a character at `level` gets to `target`, or None: already there, no level-up in the
    last two weeks, too little to go on, or over a year away."""
    if level >= target:
        return None
    line = _line(level, reached, now)
    if not line:
        return None
    recent = [i for i, p in enumerate(line) if _when(p) >= now - WINDOW]
    if not recent:
        return None
    first = recent[0]
    if first == len(line) - 1:  # one level-up in the window: measure from the one before it
        first -= 1
        if first < 0 or _when(line[first]) < now - LOOKBACK:
            return None
    a, b = line[first], line[-1]
    eta = _eta(a.level, _when(a), b.level, _when(b), now, target)
    if eta is None or eta - now > FAR:
        return None
    # The range: the level-ups as close together and as far apart as the roster reads allow, and
    # never tighter than people's habits are steady.
    fast = _eta(a.level, a.hi, b.level, b.lo if b.lo is not None else _when(b), now, target)
    slow = _eta(a.level, a.lo if a.lo is not None else _when(a), b.level, b.hi, now, target)
    early = min(e for e in (eta, fast, now + EARLY * (eta - now)) if e is not None)
    late = max(e for e in (eta, slow, now + LATE * (eta - now)) if e is not None)
    return Forecast(int(eta), int(early), int(late), _quality(a, b))


# ---- the posts -----------------------------------------------------------------------------------

def _day(t: int, tz: ZoneInfo, year: int) -> str:
    d = dt.datetime.fromtimestamp(t, tz)
    return f"{d.day} {d:%b}" + (f" {d.year}" if d.year != year else "")


def when_text(f: Forecast, now: int, tz: ZoneInfo) -> str:
    """'24 Nov – 2 Dec', or one day when the range is within it; the year only when it isn't now's."""
    year = dt.datetime.fromtimestamp(now, tz).year
    early, late = _day(f.early, tz, year), _day(f.late, tz, year)
    return early if early == late else f"{early} – {late}"


def _lines(rows: list[tuple[Character, Forecast]], now: int, tz: ZoneInfo, width: int) -> list[str]:
    return [f"{MARKS[f.quality]} `{str(c.level).rjust(width)}` **{render.md(c.name)}** · {when_text(f, now, tz)}"
            for c, f in rows]


def _names(chars: list[Character], limit: int) -> str:
    """'Name 34, Name 22 and 5 more', as many as fit."""
    out = ""
    for i, c in enumerate(chars):
        entry = f"{render.md(c.name)} {c.level}"
        more = f" and {len(chars) - i} more"
        candidate = f"{out}, {entry}" if out else entry
        rest = len(chars) - i - 1
        if roster.text_length(candidate) + (roster.text_length(f" and {rest} more") if rest else 0) > limit:
            return out + more if out else roster._cut(entry, limit)
        out = candidate
    return out


def _rows(name: str, lines: list[str]) -> list[tuple[tuple, tuple]]:
    """A full-width field, carried on in unnamed ones below when it's over Discord's limit."""
    rows = []
    for i, value in enumerate(roster._pack(lines, roster.FIELD_VALUE_LIMIT)):
        rows.append((((name if i == 0 else roster.BLANK, value, False),), ((f"{name} (continued)" if i else name, value, False),)))
    return rows


def _board(key: str, title: str, colour: int, chars: list[Character], history: Mapping[str, list[Reached]],
           now: int | None, target: int, tz: ZoneInfo, note: str) -> list[tuple[str, Board]]:
    there = [c for c in chars if c.level >= target]
    going = [c for c in chars if c.level < target]
    rows: list[tuple[Character, Forecast]] = []
    quiet: list[Character] = []
    unseen: list[Character] = []
    for c in going:
        reached = history.get(name_key(c.name), ())
        f = forecast(c.level, reached, now, target) if now is not None else None
        if f:
            rows.append((c, f))
        elif now is not None and why_not(c.level, reached, now) == QUIET:
            quiet.append(c)
        else:
            unseen.append(c)
    rows.sort(key=lambda r: (r[1].eta, r[0].name.casefold(), r[0].name))
    clock = f"{roster.CLOCK} <t:{int(now)}:R>" if now is not None else f"{roster.CLOCK} waiting for an officer's roster"
    counts = roster.GAP.join((f"{roster.STAR} **{len(there)}** at level {target}", f"{RUNNER} **{len(rows)}** on the way",
                              f"{SLEEPING} **{len(quiet)}** quiet", f"{NEW} **{len(unseen)}** no history yet", clock))
    first = Board(title=roster._cut(title, roster.TITLE_LIMIT), colour=colour,
                  description=roster._cut("\n".join(p for p in (counts, render.small(note) if note else "") if p),
                                          roster.DESCRIPTION_LIMIT))
    fields = []
    if rows and now is not None:
        width = max(len(str(c.level)) for c, _ in rows)
        for name, group in (("Within a week", [r for r in rows if r[1].eta - now <= SOON]),
                            ("Within a month", [r for r in rows if SOON < r[1].eta - now <= MONTH]),
                            ("Later", [r for r in rows if r[1].eta - now > MONTH])):
            if group:
                fields += _rows(f"{name} ({len(group)})", _lines(group, now, tz, width))
    for name, group in ((f"{SLEEPING} Quiet", quiet), (f"{NEW} No history yet", unseen)):
        if group:
            group.sort(key=roster._order)
            fields.append((((f"{name} ({len(group)})", _names(group, roster.FIELD_VALUE_LIMIT), False),),) * 2)
    return roster._section(key, first, fields)


NOTE = ("Rough: from the level-ups officers' addons noticed in the last two weeks, weighed by what each level costs.\n"
        f"{MARKS[GOOD]} good data: four or more level-ups over three days, closely timed · {MARKS[FAIR]} less to go on · "
        f"{MARKS[THIN]} thin: one level-up, under a day, or noticed long after\n"
        "Quiet: no level-up in two weeks, or over a year away at this pace. "
        "No history yet: joined lately, or not seen levelling.")


def boards(chars: Iterable[Character], s: roster.Settings, guild: str, scanned: int | None,
           history: Mapping[str, list[Reached]], target: int, tz: ZoneInfo) -> list[tuple[str, Board]]:
    """The forecast channel's messages, in order, as (key, board): 'road', then 'road#2'... only
    when Discord's limits force more. Who is listed follows the roster's settings (minimum level,
    hidden ranks), without its alt ranks: the forecast is for mains (the owner's choice)."""
    alt_ranks = {roster._key(r) for r in s.alt_ranks}
    mains = [c for c in roster.listed(chars, s) if not (c.rank and roster._key(c.rank) in alt_ranks)]
    return _board("road", f"{render.md(guild)} · Road to {target}", GOLD, mains, history, scanned, target, tz, NOTE)


def settings_text(s: Settings, channel_mention: str | None, known: int, milestones_ready: bool) -> str:
    """/roster forecast's answer."""
    waiting = []
    if not s.channel_id:
        waiting.append("the channel is set")
    if not milestones_ready:
        waiting.append("level milestones are on with a guild (the level-ups come from their upload: `/milestones settings`)")
    state = "**Off**" if not s.on else "**On**, but not posting until " + " and ".join(waiting) if waiting else "**On**"
    lines = [
        f"Road to max level: {state}.",
        f"Channel: {channel_mention or 'not set'}.",
        f"Characters with level-ups on record: {known}.",
        "It lists who the guild roster lists (`/roster settings`: minimum level, hidden ranks), without its alt ranks.",
    ]
    if not s.on:
        lines.append("Nothing is posted while it's off.")
    return "\n".join(lines)
