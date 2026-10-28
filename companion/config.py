"""companion.ini: where WoW is, where the bot is, and the officer's token. Plus the first-run prompt."""
from __future__ import annotations

import configparser
import getpass
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CONFIG_NAME = "companion.ini"
SECTION = "companion"
DEFAULT_WOW = Path(r"C:\Program Files (x86)\World of Warcraft\_forever_")
POLL_SECONDS = 30

try:  # a guild's own build prefills its bot address: a git-ignored companion/_guild.py with BOT_URL = "https://..."
    from ._guild import BOT_URL as GUILD_BOT_URL
except ImportError:
    GUILD_BOT_URL = ""


@dataclass
class Settings:
    wow_dir: Path
    bot_url: str
    token: str
    poll_seconds: int = POLL_SECONDS

    @property
    def complete(self) -> bool:
        return bool(str(self.wow_dir).strip() and self.bot_url and self.token)


def app_dir() -> Path:
    """The folder the app runs from: next to the .exe, or the project folder for `python -m companion`."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def appdata_config() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "NoctisLoot" / CONFIG_NAME


def _writable(folder: Path) -> bool:
    try:
        probe = folder / ".write-test"
        probe.write_text("")
        probe.unlink()
        return True
    except OSError:
        return False


def config_path(explicit: Path | None = None) -> Path:
    """An existing companion.ini next to the app wins, then the one in %APPDATA%. A new one goes next
    to the app when that folder is writable (easy to find), else to %APPDATA%."""
    if explicit:
        return explicit
    local, roaming = app_dir() / CONFIG_NAME, appdata_config()
    for candidate in (local, roaming):
        if candidate.is_file():
            return candidate
    return local if _writable(local.parent) else roaming


def load(path: Path) -> Settings | None:
    if not path.is_file():
        return None
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path, encoding="utf-8")
    if not cp.has_section(SECTION):
        return None
    s = cp[SECTION]
    try:
        poll = max(5, int(s.get("poll_seconds", str(POLL_SECONDS))))
    except ValueError:
        poll = POLL_SECONDS
    return Settings(wow_dir=Path(s.get("wow_folder", "").strip()), bot_url=s.get("bot_url", "").strip().rstrip("/"),
                    token=s.get("token", "").strip(), poll_seconds=poll)


def save(path: Path, settings: Settings) -> None:
    cp = configparser.ConfigParser(interpolation=None)
    cp[SECTION] = {
        "wow_folder": str(settings.wow_dir),
        "bot_url": settings.bot_url,
        "token": settings.token,
        "poll_seconds": str(settings.poll_seconds),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Noctis Loot companion app. Get a token with /loot token in Discord.\n")
        cp.write(f)


def _registry_wow() -> list[Path]:
    """The Battle.net install, if the registry knows it (it points at another flavour's folder)."""
    try:
        import winreg
    except ImportError:
        return []
    found = []
    for key in (r"SOFTWARE\WOW6432Node\Blizzard Entertainment\World of Warcraft",
                r"SOFTWARE\Blizzard Entertainment\World of Warcraft"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                install = Path(winreg.QueryValueEx(k, "InstallPath")[0].rstrip("\\/"))
        except OSError:
            continue
        # InstallPath is usually ...\World of Warcraft\_retail_ (or _classic_): _forever_ sits beside it.
        base = install.parent if install.name.startswith("_") else install
        found.append(base / "_forever_")
    return found


def wow_candidates() -> list[Path]:
    paths = [DEFAULT_WOW, *_registry_wow()]
    for drive in "CDEFGH":
        for base in (r"Program Files (x86)\World of Warcraft", r"Program Files\World of Warcraft",
                     "World of Warcraft", r"Games\World of Warcraft", r"Blizzard\World of Warcraft",
                     r"Battle.net\World of Warcraft"):
            paths.append(Path(f"{drive}:\\") / base / "_forever_")
    seen: set[str] = set()
    out = []
    for p in paths:
        if str(p).lower() not in seen:
            seen.add(str(p).lower())
            out.append(p)
    return out


def detect_wow_dir(candidates: list[Path] | None = None) -> Path | None:
    """The first candidate that looks like a WoW: Forever folder (has WTF or Interface), else any that exists."""
    candidates = wow_candidates() if candidates is None else candidates
    existing = [p for p in candidates if p.is_dir()]
    for p in existing:
        if (p / "WTF").is_dir() or (p / "Interface").is_dir():
            return p
    return existing[0] if existing else None


def prompt(existing: Settings | None, ask: Callable[[str], str] = input,
           ask_secret: Callable[[str], str] = getpass.getpass, detected: Path | None = None,
           default_url: str = GUILD_BOT_URL) -> Settings:
    """Ask for anything missing, in the console. Enter keeps the value shown in brackets."""
    print("Noctis Loot companion: setup. Press Enter to keep the value in brackets.")
    wow_default = existing.wow_dir if existing and str(existing.wow_dir).strip() else (detected or DEFAULT_WOW)
    while True:
        wow = ask(f"WoW: Forever folder [{wow_default}]: ").strip().strip('"') or str(wow_default)
        if Path(wow).is_dir():
            break
        print(f"  Can't find {wow}. It's the _forever_ folder inside your World of Warcraft folder.")
    url_default = (existing.bot_url if existing else "") or default_url.rstrip("/")
    while True:
        url = ask(f"Bot address [{url_default}]: " if url_default else "Bot address, e.g. https://loot.example.org: ").strip()
        url = (url or url_default).rstrip("/")
        if url.startswith(("http://", "https://")):
            break
        print("  It should start with https:// (ask whoever runs the bot).")
    has_token = bool(existing and existing.token)
    while True:
        token = ask_secret("Token from /loot token in Discord (not shown as you paste)"
                           f"{' [keep the current one]' if has_token else ''}: ").strip()
        token = token or (existing.token if existing else "")
        if token:
            break
        print("  Type /loot token in Discord to get one.")
    return Settings(wow_dir=Path(wow), bot_url=url, token=token,
                    poll_seconds=existing.poll_seconds if existing else POLL_SECONDS)
