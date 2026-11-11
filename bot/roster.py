"""The guild roster channel: a few posts, edited in place, listing the guild's characters by class.
The roster comes from the level milestones upload (milestones.py). This module is pure: the
settings, who is listed, and the posts' wording. Output depends only on what's passed in (never on
the clock or the input's order), so the poster's digest skips edits when nothing changed."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from . import render
from .milestones import CLASS_COLOURS, GOLD, class_name

DEFAULT_MIN_LEVEL = 10
MAX_RANK_NAME = 64
MAX_RANKS = 20
EVERY_RANK = {"all", "any", "*", "none"}  # words for "hide nothing"
UNKNOWN = "UNKNOWN"
NO_RANK = "No rank"


@dataclass(frozen=True)
class Settings:
    """What /roster settings set. Nothing is posted until it's on with a channel."""
    on: bool = False
    channel_id: int | None = None
    min_level: int = DEFAULT_MIN_LEVEL       # characters at this level and above are listed
    hidden_ranks: tuple[str, ...] = ()       # rank names not listed; empty = every rank is listed

    @property
    def ready(self) -> bool:
        return self.on and bool(self.channel_id)


@dataclass(frozen=True)
class Character:
    name: str
    level: int
    cls: str | None = None
    rank: str | None = None


def _key(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def parse_ranks(text: str) -> tuple[str, ...]:
    """'Trial, Alt' -> ('Trial', 'Alt'): the ranks to hide. 'none', 'all', 'any' or '*' hide
    nothing. Raises ValueError with a message for the officer."""
    if _key(text) in EVERY_RANK:
        return ()
    names: list[str] = []
    seen: set[str] = set()
    for part in text.replace(";", ",").split(","):
        name = " ".join(part.split())
        if not name or _key(name) in seen:
            continue
        if len(name) > MAX_RANK_NAME:
            raise ValueError(f"A rank name is at most {MAX_RANK_NAME} characters.")
        seen.add(_key(name))
        names.append(name)
    if not names:
        raise ValueError("Ranks are names separated by commas, like `Trial, Alt`, or `none` to show every rank.")
    if len(names) > MAX_RANKS:
        raise ValueError(f"At most {MAX_RANKS} ranks.")
    return tuple(names)


def _order(c: Character) -> tuple:
    return (-c.level, c.name.casefold(), c.name, c.rank or "", c.cls or "")


def listed(chars: Iterable[Character], s: Settings) -> list[Character]:
    """The characters the posts list: at the minimum level or above, and not in a hidden rank (a
    character with no rank is listed). Ordered by level, highest first, then name."""
    hidden = {_key(r) for r in s.hidden_ranks}
    return sorted((c for c in chars if c.level >= s.min_level and not (c.rank and _key(c.rank) in hidden)), key=_order)


# ---- the posts -----------------------------------------------------------------------------------

def _class_key(c: Character) -> str:
    return (c.cls or "").strip().upper() or UNKNOWN


def _class_title(key: str) -> str:
    return "Unknown class" if key == UNKNOWN else class_name(key)


def _totals(chars: list[Character]) -> str:
    n = len(chars)
    first = render.plural(n, "member")
    if n == 1:
        return f"{first} · level {chars[0].level}"
    top = chars[0].level  # listed() puts the highest first
    at_top = sum(1 for c in chars if c.level == top)
    if at_top == n:
        return f"{first} · all at level {top}"
    average = int(sum(c.level for c in chars) / n + 0.5)
    return f"{first} · {at_top} at level {top} · average level {average}"


def _ranks_line(chars: list[Character]) -> str:
    counts: dict[str, int] = defaultdict(int)
    spellings: dict[str, set[str]] = defaultdict(set)
    for c in chars:
        name = " ".join((c.rank or "").split()) or NO_RANK
        counts[_key(name)] += 1
        spellings[_key(name)].add(name)
    shown = sorted((min(spellings[k]), n) for k, n in counts.items())
    shown.sort(key=lambda p: (-p[1], p[0].casefold()))
    return " · ".join(f"{render.md(name)} {n}" for name, n in shown)


def _classes_line(chars: list[Character]) -> str:
    """'Warrior 9 · Druid 7': the counters above the lists, as raid sign-up bots have them."""
    counts: dict[str, int] = defaultdict(int)
    for c in chars:
        counts[_class_key(c)] += 1
    shown = sorted(counts.items(), key=lambda p: (-p[1], p[0] == UNKNOWN, _class_title(p[0]).casefold()))
    return " · ".join(f"{_class_title(k)} {n}" for k, n in shown)


def _who_line(s: Settings) -> str:
    parts = []
    if s.min_level > 1:
        parts.append(f"Level {s.min_level} and up")
    if s.hidden_ranks:
        parts.append("not shown: " + ", ".join(render.md(r) for r in s.hidden_ranks))
    text = " · ".join(parts)
    return text[:1].upper() + text[1:]


def _level_lines(chars: list[Character], limit: int) -> list[str]:
    """'**60** Thorgar · Brannoch', one line per level; a level too long for one post goes on
    several lines, split between names."""
    by_level: dict[int, list[str]] = defaultdict(list)
    for c in chars:  # already in order
        by_level[c.level].append(render.md(c.name))
    lines = []
    for level in sorted(by_level, reverse=True):
        head = f"**{level}** "
        cur = ""
        for name in by_level[level]:
            candidate = f"{cur} · {name}" if cur else head + name
            if cur and len(candidate) > limit:
                lines.append(cur)
                candidate = head + name
            cur = candidate
        lines.append(cur)
    return lines


def cards(chars: Iterable[Character], s: Settings, guild: str, scanned: int | None) -> list[tuple[str, render.Card]]:
    """The roster channel's posts, in order, as (key, card): the header, then one card per class
    (more when a class is too long for one post: 'WARRIOR#2'...). `chars` is the whole guild."""
    shown = listed(chars, s)
    who = _who_line(s)
    if shown:
        body = "\n".join(p for p in (_totals(shown), _classes_line(shown), _ranks_line(shown), render.small(who)) if p)
    else:
        body = "\n".join(p for p in ("Nobody is listed yet.", render.small(who)) if p)
    footer = f"Roster read <t:{int(scanned)}:R>" if scanned is not None else "Waiting for an officer's roster"
    out = [("header", render.Card(title=f"{render.md(guild)} · Guild roster", colour=GOLD, body=body, footer=footer))]

    classes: dict[str, list[Character]] = defaultdict(list)
    for c in shown:
        classes[_class_key(c)].append(c)
    order = sorted(classes, key=lambda k: (k == UNKNOWN, _class_title(k).casefold(), k))
    for key in order:
        members = classes[key]
        title = _class_title(key)
        colour = CLASS_COLOURS.get(key, GOLD)
        for i, part in enumerate(render.chunk(_level_lines(members, render.MESSAGE_LIMIT))):
            out.append((key if i == 0 else f"{key}#{i + 1}", render.Card(
                title=f"{title} ({len(members)})" if i == 0 else f"{title} (continued)", colour=colour, body=part)))
    return out


def settings_text(s: Settings, channel_mention: str | None, counts: tuple[int, int], milestones_ready: bool) -> str:
    """/roster settings' answer: what's set, and how many characters are listed."""
    in_guild, shown = counts
    waiting = []
    if not s.channel_id:
        waiting.append("the channel is set")
    if not milestones_ready:
        waiting.append("level milestones are on with a guild (the roster comes from their upload: `/milestones settings`)")
    if not s.on:
        state = "**Off**"
    elif waiting:
        state = "**On**, but not posting until " + " and ".join(waiting)
    else:
        state = "**On**"
    lines = [
        f"Guild roster: {state}.",
        f"Channel: {channel_mention or 'not set'}.",
        f"Minimum level: {s.min_level}.",
        "Hidden ranks: " + (", ".join(render.md(r) for r in s.hidden_ranks) if s.hidden_ranks else "none") + ".",
        f"Characters in the guild: {in_guild}; listed: {shown}.",
    ]
    if not s.on:
        lines.append("Nothing is posted while it's off.")
    return "\n".join(lines)
