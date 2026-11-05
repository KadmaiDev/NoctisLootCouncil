"""Writing the NoctisLootDecisions addon the game loads at login (sync-format.md, section 4).

It's a separate addon folder so updating the main addon never deletes it. Every file is written
to a temporary file and renamed over the old one, so the game never loads half a file.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from . import luaparse

ADDON = "NoctisLootDecisions"
TOC_NAMES = (f"{ADDON}.toc", f"{ADDON}_Camelot.toc")
LUA_NAME = "Decisions.lua"
HEADER = "-- Written by the Noctis Loot companion app. Don't edit; it's rewritten."

# The icon is the main addon's file, so this folder stays just these files. The category lines match
# its .toc (test_decisions.py checks), so the two sit together in the AddOns list in every language.
TOC = r"""## Interface: 16001
## Title: Noctis Loot Decisions
## Notes: Council and roll decisions from Discord, written by the Noctis Loot companion app. Don't edit; it's rewritten.
## Version: {at}
## IconTexture: Interface\AddOns\NoctisLootCouncil\media\icon.tga
## Category: Loot
## Category-deDE: Beute
## Category-esES: Botín
## Category-esMX: Botín
## Category-frFR: Butin
## Category-itIT: Bottino
## Category-koKR: 전리품
## Category-ptBR: Saque
## Category-ruRU: Добыча
## Category-zhCN: 战利品
## Category-zhTW: 戰利品
Decisions.lua
"""


def addon_dir(wow_dir: Path) -> Path:
    return wow_dir / "Interface" / "AddOns" / ADDON


def lua_string(s: str) -> str:
    """A Lua string literal: `\\`, `"` and line breaks escaped, other control characters as `\\ddd`,
    and everything else (accented names included) left as UTF-8."""
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append(f"\\{ord(ch):03d}")  # three digits, so a following digit can't join the escape
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def render(decisions: dict) -> str:
    """Decisions.lua for the bot's GET /api/decisions answer."""
    at = int(decisions.get("at") or 0)
    lines = [HEADER, f"{ADDON} = {{", f"  at = {at},", "  items = {"]
    entries: list[tuple[int, str]] = []
    for key, d in (decisions.get("items") or {}).items():
        if not str(key).isdigit() or not isinstance(d, dict) or d.get("handling") not in ("council", "roll", "none"):
            continue
        fields = [f"h = {lua_string(d['handling'])}"]
        for name in ("note", "name"):
            if isinstance(d.get(name), str) and d[name]:
                fields.append(f"{name} = {lua_string(d[name])}")
        entries.append((int(key), f"    [{int(key)}] = {{ {', '.join(fields)} }},"))
    lines.extend(line for _, line in sorted(entries))
    lines += ["  },", "}", ""]
    return "\n".join(lines)


def toc(at: int) -> str:
    return TOC.format(at=at)


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(text.encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    # Windows refuses the rename for a moment if something (an antivirus, the game) has the file open.
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2 * (attempt + 1))


def write_addon(folder: Path, decisions: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    at = int(decisions.get("at") or 0)
    # Decisions.lua first: a .toc with the new version never points at old data for long.
    _write_atomic(folder / LUA_NAME, render(decisions))
    refresh_tocs(folder, at)


def refresh_tocs(folder: Path, at: int) -> None:
    """Writes any .toc that's missing or differs: a new version of this app can change them while
    the decisions stay the same."""
    text = toc(at)
    for name in TOC_NAMES:
        try:
            same = (folder / name).read_bytes() == text.encode("utf-8")
        except OSError:
            same = False
        if not same:
            _write_atomic(folder / name, text)


def current_at(folder: Path) -> int | None:
    """The `at` of the decisions already written there, read back with the parser (None if none)."""
    try:
        table = luaparse.load_file(folder / LUA_NAME).get(ADDON)
    except (OSError, luaparse.LuaError):
        return None
    if isinstance(table, dict) and isinstance(table.get("at"), int):
        return table["at"]
    return None


def counts(decisions: dict) -> tuple[str, int, int]:
    """(when they're from, e.g. '27 Oct, 18:40', how many council items, how many roll items)."""
    items = (decisions.get("items") or {}).values()
    council = sum(1 for d in items if isinstance(d, dict) and d.get("handling") == "council")
    roll = sum(1 for d in items if isinstance(d, dict) and d.get("handling") == "roll")
    at = int(decisions.get("at") or 0)
    when = time.strftime("%d %b, %H:%M", time.localtime(at)).lstrip("0") if at else "never"
    return when, council, roll


def summary(decisions: dict) -> str:
    """'Decisions from 27 Oct, 18:40: 34 council, 112 roll.', as the addon says it."""
    when, council, roll = counts(decisions)
    return f"Decisions from {when}: {council} council, {roll} roll."
