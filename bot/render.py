"""What every Discord post says, as plain data (no discord import), so wording can be tested.

The wording follows the mockups (DiscordVote, DiscordItems, DiscordPosts). Every post is a Card:
views.py draws it as a Discord layout (a container in the item's quality colour with the title
as a heading, grey lines under it, a divider, the body, and the buttons under the card). Output
must depend only on the state passed in, never on the current time: the poster compares a digest
of the rendered card with what it last sent, and a clock in here would make it edit posts forever.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from zoneinfo import ZoneInfo

from . import iteminfo, rules
from .model import AwardInfo, ItemState, LogGroup
from .rules import COUNCIL, ROLL

# A layout message holds at most 4000 characters of text; the rest is for the title and footer.
MESSAGE_LIMIT = 3500

# The game's item quality colours, so posts match the item's colour in game.
QUALITY_COLOURS = {0: 0x9D9D9D, 1: 0xFFFFFF, 2: 0x1EFF00, 3: 0x0070DD, 4: 0xA335EE, 5: 0xFF8000}
QUALITY_NAMES = {0: "Poor", 1: "Common", 2: "Uncommon", 3: "Rare", 4: "Epic", 5: "Legendary"}
DEFAULT_COLOUR = 0x4A55C9

ROLL_ORDER_TEXT = "Main spec, then second main spec, then off spec."
SUGGESTERS_SHOWN = 15  # names on the officer post; the rest are "and N more"
EVERYTHING_ELSE = ("Everything else is rolled: main spec, then second main spec (already won one that night), "
                   "then off spec. Items we haven't seen before are rolled.")
LOG_FOOTER = ("Questions about a decision: message the raid leader. "
              "Decisions on the night stand unless there was a clear mistake.")


@dataclass(frozen=True)
class Button:
    action: str  # council, roll, priority, suggest
    label: str
    style: str  # success, secondary, primary


@dataclass(frozen=True)
class Card:
    """One post: kicker (small capitals above the title), title (a heading, after the item's icon
    `emoji` and linked to `url`), subtitle (grey, under it), then below a divider the body
    (markdown) and footer (grey), then the buttons."""
    title: str
    colour: int
    subtitle: str = ""
    body: str = ""
    footer: str = ""
    kicker: str = ""
    buttons: list[Button] = field(default_factory=list)
    url: str = ""
    emoji: str = ""

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

    def head(self) -> str:
        # The icon as a small emoji before the name, like an item link in game: Discord draws a
        # Section thumbnail at a fixed, much larger size.
        title = with_emoji(self.emoji, f"[{self.title}]({self.url})" if self.url else self.title)
        return "\n".join(p for p in (small(self.kicker), f"### {title}", small(self.subtitle)) if p)

    def tail(self) -> str:
        return "\n".join(p for p in (self.body, small(self.footer)) if p)

    def text(self) -> str:
        """Everything the post says, as Discord markdown (views.py splits it into its parts)."""
        return "\n".join(p for p in (self.head(), self.tail()) if p)


def small(text: str) -> str:
    """Discord's small grey text, line by line."""
    return "\n".join(f"-# {line}" for line in text.splitlines() if line.strip())


_MD = re.compile(r"([\\*_~`|>])")


def md(text: str) -> str:
    """Escape Discord markdown in text that came from players (names, notes)."""
    return _MD.sub(r"\\\1", text)


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def colour(state: ItemState) -> int:
    return QUALITY_COLOURS.get(state.quality, DEFAULT_COLOUR) if state.quality is not None else DEFAULT_COLOUR


def subtitle(state: ItemState) -> str:
    """'Epic · Waist · Cloth · Molten Core, Gehennas'."""
    return " · ".join(p for p in (QUALITY_NAMES.get(state.quality), state.slot, state.source_text) if p)


def item_links(state: ItemState) -> dict[str, str]:
    """The card's link to Wowhead and its icon, when Wowhead knows the item."""
    return {"url": iteminfo.page_url(state.id, state.wowhead[1], state.wowhead[0]) if state.wowhead else "",
            "emoji": state.emoji or ""}


def with_emoji(emoji: str | None, text: str) -> str:
    return f"{emoji} {text}" if emoji else text


def _night(ts: int, tz: ZoneInfo) -> dt.date:
    return rules.night_of(ts, tz)


def seen_phrase(first_drop_at: int, posted_at: int, tz: ZoneInfo) -> str:
    """'last night' when the post went up the day after the raid (as in the mockup), else the date.

    Relative to when the item was first posted, not to now, so the post doesn't go stale.
    """
    gap = (_night(posted_at, tz) - _night(first_drop_at, tz)).days
    return "last night" if gap <= 1 else f"on {rules.day_label(_night(first_drop_at, tz))}"


def drops_text(state: ItemState, tz: ZoneInfo) -> str:
    if state.drops <= 0:
        return "No drops yet"
    times = "once" if state.drops == 1 else f"{state.drops} times"
    if state.last_drop_at is None:
        return f"Dropped {times}"
    return f"Dropped {times}, last {rules.short_day_label(_night(state.last_drop_at, tz))}"


def award_summary(a: AwardInfo) -> str:
    """'rolled, won by Corvin Dusk (main spec, 77)'."""
    if a.how == COUNCIL:
        return f"council award to {md(a.who)}"
    spec = rules.HOW_SPEC_TEXT.get(a.how, a.how)
    detail = f"{spec}, {a.roll}" if a.roll is not None else spec
    return f"rolled, won by {md(a.who)} ({detail})"


def wanted_text(a: AwardInfo) -> str | None:
    """'Wanted it: 4 main spec, 1 off spec'."""
    if a.nms is None and a.nos is None:
        return None
    return f"Wanted it: {a.nms or 0} main spec, {a.nos or 0} off spec"


def votes_lines(t: rules.Tally) -> list[str]:
    """'**Votes:** Council 3 · Roll 1', then who voted which way in small text."""
    if t.total == 0:
        return ["**Votes:** none yet"]
    names = " · ".join(f"{label}: {', '.join(md(n) for n in group)}"
                       for label, group in (("Council", t.council), ("Roll", t.roll)) if group)
    return [f"**Votes:** Council {len(t.council)} · Roll {len(t.roll)}", small(names)]


def handling_name(h: str) -> str:
    return "council item" if h == COUNCIL else "roll item"


def decision_line(state: ItemState) -> str | None:
    t = state.tally
    if state.decision:
        return (f"✅ **{handling_name(state.decision).capitalize()}**, decided {t.count(state.decision)} of "
                f"{t.total}. In game after the next /reload.")
    if state.game_handling:
        return (f"Set in game by {md(state.game_by or 'an officer')}: **{handling_name(state.game_handling)}**. "
                f"A vote here replaces it.")
    if t.tied_at_threshold:
        return f"Tied, {len(t.council)} each: not decided yet."
    return None


def suggesters_text(state: ItemState, items_channel: str) -> str | None:
    """Who pressed Suggest for council: names for the officers (the public post shows only the count)."""
    if not state.suggestions:
        return None
    names = [md(n) for n in state.suggested_by[:SUGGESTERS_SHOWN]]
    if not names:  # all from before names were kept
        return f"{plural(state.suggestions, 'raider suggests', 'raiders suggest')} council in {items_channel}"
    more = state.suggestions - len(names)
    return f"Suggested for council by {', '.join(names)}{f' and {more} more' if more else ''}"


def officer_card(state: ItemState, tz: ZoneInfo, items_channel: str = "#loot-items") -> Card:
    """The private #loot-officers post: decision, votes, priority, and the vote buttons."""
    kicker = ""
    lines: list[str] = []
    line = decision_line(state)
    if line:
        lines.append(line)
    if state.new_in_raid and state.first_drop_at is not None:
        kicker = f"NEW IN OUR RAID {seen_phrase(state.first_drop_at, state.created_at, tz).upper()}"
        if state.first_award:
            summary = award_summary(state.first_award)
            lines.append(summary[:1].upper() + summary[1:])
            lines.append(small(wanted_text(state.first_award) or ""))
    lines += votes_lines(state.tally)
    if state.priority:
        lines += [f"**Priority:** {md(state.priority)}", small(f"Set by {md(state.priority_by or 'an officer')}")]
    elif state.decided_in_game and state.game_note:
        lines += [f"**Priority:** {md(state.game_note)}",
                  small(f"Set in game by {md(state.game_by or 'an officer')}")]
    footer = [drops_text(state, tz), suggesters_text(state, items_channel)]
    buttons = [Button("council", "Council", "success"), Button("roll", "Roll", "secondary"),
               Button("priority", "Set priority", "secondary")]
    return Card(title=state.name, colour=colour(state), subtitle=subtitle(state), kicker=kicker,
                body="\n".join(p for p in lines if p), footer="\n".join(p for p in footer if p), buttons=buttons,
                **item_links(state))


def status_badge(state: ItemState) -> str:
    if state.handling == COUNCIL:
        return "Council item"
    if state.handling == ROLL:
        return "Roll item"
    return "Undecided"


def items_card(state: ItemState, tz: ZoneInfo) -> Card:
    """The public #loot-items post: status, priority, and Suggest for council (not on council items)."""
    lines = [f"**{status_badge(state)}**"]
    if state.note:
        lines.append(f"Priority: **{md(state.note)}**")
    footer: list[str] = []
    if state.new_in_raid and state.first_drop_at is not None:
        footer.append(f"First seen {seen_phrase(state.first_drop_at, state.created_at, tz)}.")
    if state.handling == ROLL:
        footer.append(ROLL_ORDER_TEXT)
    elif state.handling is None:
        footer.append("Rolled until the officers decide.")
    if state.decision:
        t = state.tally
        footer.append(f"Decided by the officers, {t.count(state.decision)} of {t.total}.")
    elif state.game_handling:
        footer.append(f"Set in game by {md(state.game_by or 'an officer')}.")
    buttons = [] if state.handling == COUNCIL else [
        Button("suggest", f"Suggest for council · {state.suggestions}", "primary")]
    return Card(title=state.name, colour=colour(state), subtitle=subtitle(state), body="\n".join(lines),
                footer="\n".join(footer), buttons=buttons, **item_links(state))


def suggestion_reply(on: bool, count: int) -> str:
    if on:
        return f"Thanks, that's {plural(count, 'suggestion')}. The officers see who suggested it when they decide."
    return f"Taken back. That leaves {plural(count, 'suggestion')}."


# ---- #loot-log -------------------------------------------------------------

def award_line(a: AwardInfo) -> str:
    """'Felheart Gloves → **Corvin Dusk** · main-spec roll, 77 · new item'."""
    item = with_emoji(a.emoji, md(a.item_name))
    if a.how == COUNCIL:
        line = f"{item} → **{md(a.who)}** · council"
        if a.note:
            line += f'\n> "{md(a.note)}"'
        return line
    how = rules.HOW_ROLL_TEXT.get(a.how, md(a.how))
    if a.roll is not None:
        how += f", {a.roll}"
    if a.nms is not None and (a.nms or 0) + (a.nos or 0) <= 1:
        how += " (nobody else wanted it)"
    if a.new_item:
        how += " · new item"
    return f"{item} → **{md(a.who)}** · {how}"


def chunk(lines: list[str], limit: int = MESSAGE_LIMIT) -> list[str]:
    """Pack lines into as few messages as fit Discord's length limit, never splitting a line."""
    out: list[str] = []
    cur = ""
    for line in lines:
        if len(line) > limit:
            line = line[: limit - 1] + "…"
        candidate = f"{cur}\n{line}" if cur else line
        if len(candidate) > limit:
            out.append(cur)
            cur = line
        else:
            cur = candidate
    if cur:
        out.append(cur)
    return out


def split_cards(title: str, subtitle: str, lines: list[str], footer: str, colour: int = DEFAULT_COLOUR) -> list[Card]:
    """As many cards as the lines need: the subtitle on the first, the footer on the last."""
    parts = chunk(lines) or [""]
    return [Card(title=title if i == 0 else f"{title} (continued)", colour=colour,
                 subtitle=subtitle if i == 0 else "", body=part, footer=footer if i == len(parts) - 1 else "")
            for i, part in enumerate(parts)]


def log_cards(group: LogGroup) -> list[Card]:
    """One raid night in one instance: 'Molten Core · Monday 27 Oct', '6 items', then a line per award."""
    day = rules.day_label(dt.date.fromisoformat(group.night))
    return split_cards(f"{md(group.inst or 'Raid')} · {day}", plural(len(group.awards), "item"),
                       [award_line(a) for a in group.awards], LOG_FOOTER)


# ---- #loot-priorities -------------------------------------------------------

def priorities_cards(states: list[ItemState], day: str, raid: str | None = None,
                     items_channel: str = "#loot-items") -> list[Card]:
    """Council items and their priorities, then the fixed paragraph about everything else."""
    council = [s for s in states if s.handling == COUNCIL]
    if raid:
        council = [s for s in council if (s.raid or "").lower() == raid.lower()]
    lines: list[str] = []

    def item_line(s: ItemState) -> str:
        name = with_emoji(s.emoji, f"**{md(s.name)}**")
        return f"- {name} · {md(s.note)}" if s.note else f"- {name}"

    if not council:
        lines.append("No council items yet.")
    elif raid:
        lines.extend(item_line(s) for s in sorted(council, key=lambda s: s.name.lower()))
    else:
        by_raid: dict[str, list[ItemState]] = {}
        for s in council:
            by_raid.setdefault(s.raid or "Other", []).append(s)
        for name in sorted(by_raid, key=lambda n: (n == "Other", n.lower())):
            lines.append(f"__{md(name)}__")
            lines.extend(item_line(s) for s in sorted(by_raid[name], key=lambda s: s.name.lower()))
    lines += ["", EVERYTHING_ELSE]
    title = f"{md(raid)} · {day}" if raid else day
    return split_cards(title, "Council items", lines,
                       f"Think something should be a council item? Press Suggest for council on its post in "
                       f"{items_channel}.")


# ---- /loot status -----------------------------------------------------------

def item_status(state: ItemState) -> str:
    """One item, for /loot status <item>."""
    if state.handling is None:
        text = f"**{md(state.name)}**: undecided, rolled until the officers decide"
    else:
        text = f"**{md(state.name)}**: {handling_name(state.handling)}"
        if state.note:
            text += f" · {md(state.note)}"
        if state.decision:
            t = state.tally
            text += f" (decided by the officers, {t.count(state.decision)} of {t.total})"
        else:
            text += f" (set in game by {md(state.game_by or 'an officer')})"
    if state.suggestions:
        text += f". {plural(state.suggestions, 'raider suggests', 'raiders suggest')} council"
    return text + "."


def status_text(states: list[ItemState], limit: int = 4000) -> str:
    """Everything that's decided, for /loot status."""
    council = sorted((s for s in states if s.handling == COUNCIL), key=lambda s: ((s.raid or "~"), s.name.lower()))
    rolls = sum(1 for s in states if s.handling == ROLL)
    undecided = sum(1 for s in states if s.handling is None)
    lines = [f"**Council items ({len(council)})**"]
    if not council:
        lines.append("None yet.")
    for s in council:
        where = f" ({md(s.raid)})" if s.raid else ""
        lines.append(f"• {md(s.name)}{where}" + (f" · {md(s.note)}" if s.note else ""))
    lines.append("")
    lines.append(f"**Roll items:** {rolls}")
    lines.append(f"**Undecided:** {undecided} (rolled until the officers decide)")
    text = "\n".join(lines)
    if len(text) > limit:
        text = text[: limit - 40].rsplit("\n", 1)[0] + "\n… and more: see #loot-items."
    return text
