"""The guild roster channel: one embed, edited in place, listing the guild's characters by class in
three columns, laid out like Raid-Helper's sign-up posts (more messages only when Discord's limits
force it). The roster comes from the level milestones upload (milestones.py). This module is pure:
the settings, who is listed, and the posts' wording. Output depends only on what's passed in (never
on the clock or the input's order), so the poster's digest skips edits when nothing changed."""
from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass

from . import render
from .milestones import CLASS_COLOURS, GOLD, class_name

DEFAULT_MIN_LEVEL = 10
MAX_RANK_NAME = 64
MAX_RANKS = 20
EVERY_RANK = {"all", "any", "*", "none"}  # words for "hide nothing"
UNKNOWN = "UNKNOWN"
NO_RANK = "No rank"

# Discord's embed limits (characters; counted here in UTF-16 units, which is never fewer).
TITLE_LIMIT = 256
DESCRIPTION_LIMIT = 4096
FIELD_NAME_LIMIT = 256
FIELD_VALUE_LIMIT = 1024
FIELDS_LIMIT = 25
EMBED_LIMIT = 6000  # title + description + every field's name and value + footer
COLUMNS = 3  # inline fields side by side
BLANK = "\N{ZERO WIDTH SPACE}"  # an empty field's name or value (Discord refuses empty ones)
CLASS_TITLE_MAX = 100
PEOPLE, STAR, CLOCK = "\N{BUSTS IN SILHOUETTE}", "\N{WHITE MEDIUM STAR}", "\N{CLOCK FACE TWO OCLOCK}"
GAP = "  ·  "

# Class icons: Wowhead's picture `classicon_warrior` becomes the bot's emoji `class_warrior`.
CLASS_ICON_PREFIX = "classicon_"
CLASS_EMOJI_PREFIX = "class_"


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

Field = tuple[str, str, bool]  # (name, value, inline)


@dataclass(frozen=True)
class Board:
    """One roster message, a classic embed (views.board_embed draws it). The first has the title and
    the counters; further ones, when Discord's limits force them, only carry on the grid."""
    title: str = ""
    description: str = ""
    fields: tuple[Field, ...] = ()
    colour: int = GOLD

    def size(self) -> int:
        """What counts towards Discord's 6000 characters per embed."""
        return text_length(self.title) + text_length(self.description) + sum(
            text_length(n) + text_length(v) for n, v, _ in self.fields)

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

    def text(self) -> str:
        """Everything it says, as markdown: the title, the description, then each field's name and value."""
        parts = [self.title, self.description] + [f"{n}\n{v}" for n, v, _ in self.fields]
        return "\n".join(p for p in parts if p)


def text_length(text: str) -> int:
    """A length as Discord counts it, or more: UTF-16 units (an emoji like the people icon counts two)."""
    return len(text.encode("utf-16-le")) // 2


def _cut(text: str, limit: int) -> str:
    if text_length(text) <= limit:
        return text
    text = text[:limit]
    while text_length(text) > limit - 1:
        text = text[:-1]
    return text + "…"


def _class_key(c: Character) -> str:
    return (c.cls or "").strip().upper() or UNKNOWN


def _class_title(key: str) -> str:
    return "Unknown class" if key == UNKNOWN else class_name(key)


def _class_order(keys: Iterable[str]) -> list[str]:
    """Alphabetical by the name shown, 'Unknown class' last."""
    return sorted(set(keys), key=lambda k: (k == UNKNOWN, _class_title(k).casefold(), k))


def classes(chars: Iterable[Character], s: Settings) -> list[str]:
    """The classes the posts list ('WARRIOR', ...), in the posts' order."""
    return _class_order(_class_key(c) for c in listed(chars, s))


def class_icon(key: str) -> str | None:
    """Wowhead's picture for a class ('WARRIOR' -> 'classicon_warrior'); None for one the game hasn't."""
    return CLASS_ICON_PREFIX + key.lower() if key in CLASS_COLOURS else None


def emoji_name(icon: str) -> str:
    """The bot's emoji for a class picture: 'classicon_warrior' -> 'class_warrior'."""
    return CLASS_EMOJI_PREFIX + icon.removeprefix(CLASS_ICON_PREFIX)


def _counts_row(chars: list[Character], scanned: int | None) -> str:
    """The icon row under the title, as Raid-Helper's: how many, how many at the top level, and
    when the roster was read (Discord shows the time relative to the reader's clock)."""
    if scanned is not None:
        clock = f"{CLOCK} <t:{int(scanned)}:R>"
    else:
        clock = f"{CLOCK} waiting for an officer's roster"
    n = len(chars)
    if not n:
        return GAP.join((f"{PEOPLE} Nobody is listed yet", clock))
    top = chars[0].level  # listed() puts the highest first
    at_top = sum(1 for c in chars if c.level == top)
    people = f"{PEOPLE} **{n}** {'member' if n == 1 else 'members'}"
    if n == 1:
        star = f"{STAR} level **{top}**"
    elif at_top == n:
        star = f"{STAR} all at level **{top}**"
    else:
        star = f"{STAR} **{at_top}** at level {top}"
    return GAP.join((people, star, clock))


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


def _who_line(s: Settings) -> str:
    parts = []
    if s.min_level > 1:
        parts.append(f"Level {s.min_level} and up")
    if s.hidden_ranks:
        parts.append("not shown: " + ", ".join(render.md(r) for r in s.hidden_ranks))
    text = " · ".join(parts)
    return text[:1].upper() + text[1:]


def _pack(lines: list[str], limit: int) -> list[str]:
    """Lines into as few field values as fit, never splitting a line."""
    out: list[str] = []
    cur = ""
    for line in lines:
        line = _cut(line, limit)
        candidate = f"{cur}\n{line}" if cur else line
        if cur and text_length(candidate) > limit:
            out.append(cur)
            candidate = line
        cur = candidate
    if cur:
        out.append(cur)
    return out


def _grid(shown: list[Character], icons: Mapping[str, str]) -> list[tuple[tuple[Field, ...], tuple[Field, ...]]]:
    """The classes three to a row. A class too long for one field carries on in the field below it,
    in a row of three (blank where a class has nothing more), so the columns stay in line. Each row
    comes twice: as it goes under the row above, and as the first row of a further message (where a
    continued class is named again)."""
    groups: dict[str, list[Character]] = defaultdict(list)
    for c in shown:  # already in order
        groups[_class_key(c)].append(c)
    width = max(len(str(c.level)) for c in shown)
    order = _class_order(groups)
    rows = []
    for i in range(0, len(order), COLUMNS):
        cells: list[tuple[str | None, int, list[str]]] = []  # (heading, count, values)
        for key in order[i:i + COLUMNS]:
            members = groups[key]
            heading = render.with_emoji(icons.get(key), _cut(render.md(_class_title(key)), CLASS_TITLE_MAX))
            lines = [f"`{str(c.level).rjust(width)}` **{render.md(c.name)}**" for c in members]
            cells.append((heading, len(members), _pack(lines, FIELD_VALUE_LIMIT)))
        height = max(len(values) for _, _, values in cells)
        if height > 1:
            cells += [(None, 0, [])] * (COLUMNS - len(cells))
        for r in range(height):
            under, fresh = [], []
            for heading, count, values in cells:
                value = values[r] if r < len(values) else BLANK
                if heading is None:
                    name = again = BLANK
                elif r == 0:
                    name = again = _cut(f"{heading} ({count})", FIELD_NAME_LIMIT)
                else:
                    name = BLANK
                    again = _cut(f"{heading} (continued)", FIELD_NAME_LIMIT) if r < len(values) else BLANK
                under.append((name, value, True))
                fresh.append((again, value, True))
            rows.append((tuple(under), tuple(fresh)))
    return rows


def boards(chars: Iterable[Character], s: Settings, guild: str, scanned: int | None,
           icons: Mapping[str, str] | None = None) -> list[tuple[str, Board]]:
    """The roster channel's messages, in order, as (key, board): 'roster', then 'roster#2'... only
    when Discord's limits for one embed (25 fields, 6000 characters) force more. `chars` is the
    whole guild; `icons` maps a class ('WARRIOR') to its emoji's markup, for the classes that have one."""
    icons = icons or {}
    shown = listed(chars, s)
    who = _who_line(s)
    lines = (_counts_row(shown, scanned), _ranks_line(shown) if shown else "", render.small(who))
    out = [Board(title=_cut(f"{render.md(guild)} · Guild roster", TITLE_LIMIT),
                 description=_cut("\n".join(p for p in lines if p), DESCRIPTION_LIMIT), colour=GOLD)]
    if shown:
        for under, fresh in _grid(shown, icons):
            cur = out[-1]
            size = sum(text_length(n) + text_length(v) for n, v, _ in under)
            if len(cur.fields) + len(under) > FIELDS_LIMIT or cur.size() + size > EMBED_LIMIT:
                out.append(Board(fields=fresh, colour=GOLD))  # a row never splits between messages
            else:
                out[-1] = dataclasses.replace(cur, fields=cur.fields + under)
    return [("roster" if i == 0 else f"roster#{i + 1}", b) for i, b in enumerate(out)]


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
