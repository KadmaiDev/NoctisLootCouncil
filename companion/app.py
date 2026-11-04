"""The companion's loop: upload saved files that changed, then fetch decisions and write them for the game."""
from __future__ import annotations

import logging
import re
import sys
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

from . import RELEASES, __version__, client, decisions, savedfile
from .config import Settings
from .luaparse import LuaError

log = logging.getLogger("companion")
DECISIONS = "decisions"  # the key of a failed decisions fetch among the problems
MILESTONES = "milestones"  # the key of a failed milestones-settings fetch
MILESTONES_RECHECK = 600  # seconds the bot's milestones answer (on/off, which guild) is kept


def setup_logging(log_file: Path | None) -> None:
    fmt = logging.Formatter("%(asctime)s  %(message)s", datefmt="%d %b %H:%M:%S")
    root = logging.getLogger("companion")
    root.setLevel(logging.INFO)
    root.handlers.clear()
    if sys.stderr is not None:  # the windowed .exe has none
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)


@dataclass
class Status:
    """What the window shows: how the last talk with the bot went, and what's been uploaded and written."""
    connected: bool | None = None  # None until the bot has answered or failed once
    checked_at: float | None = None
    problem: str | None = None
    token_refused: bool = False
    uploaded_at: float | None = None
    new_awards: int = 0  # in the last upload
    new_items: int = 0
    decisions: tuple[str, int, int] | None = None  # decisions.counts() of the latest the bot sent
    new_milestones: int = 0  # in the last milestones upload
    update: str | None = None  # a newer companion version the bot knows of


def newer_version(named: object, ours: str = __version__) -> str | None:
    """`named` if it's a plain version number ("0.2.3") higher than ours, else None."""
    if not isinstance(named, str) or not re.fullmatch(r"\d{1,4}\.\d{1,4}\.\d{1,4}", named):
        return None
    as_tuple = lambda v: tuple(int(x) for x in v.split("."))  # noqa: E731
    return named if as_tuple(named) > as_tuple(ours) else None


def release_page(version: str) -> str:
    return f"{RELEASES}/tag/companion-v{version}"


def _count(answer: dict, key: str) -> int:
    value = answer.get(key)
    return value if isinstance(value, int) else 0


class Companion:
    def __init__(self, settings: Settings,
                 upload: Callable[[str, str, dict], dict] = client.post_upload,
                 fetch: Callable[[str, str], dict] = client.get_decisions,
                 clock: Callable[[], float] = time.time,
                 milestone_settings: Callable[[str, str], dict] = client.get_milestone_settings,
                 upload_milestones: Callable[[str, str, dict], dict] = client.post_milestones):
        self.settings = settings
        self._upload = upload
        self._fetch = fetch
        self._clock = clock
        self._ms_settings = milestone_settings
        self._ms_upload = upload_milestones
        self._uploaded: dict[Path, tuple[int, int]] = {}  # file -> (mtime_ns, size) last uploaded
        self._ms_uploaded: dict[Path, tuple[int, int]] = {}  # the same for milestones files
        self._ms_guild: str | None = None  # the guild the bot takes milestones for (None: off)
        self._ms_checked_at: float | None = None
        # Standing problems by what failed (a saved file, or "decisions"): each is cleared only when
        # that same thing next works, so fetching decisions doesn't hide an upload that keeps failing.
        self._problems: dict[str, str] = {}
        self.status = Status()

    def _problem(self, what: str, message: str) -> None:
        # A bot that's down would otherwise log the same line every 30 seconds.
        if self._problems.pop(what, None) != message:
            log.warning(message)
        self._problems[what] = message
        self.status.problem = message

    def _cleared(self, *what: str) -> None:
        for key in what:
            self._problems.pop(key, None)
        self.status.problem = next(reversed(self._problems.values()), None)  # the newest left

    def _answered(self, ok: bool) -> None:
        self.status.connected = ok
        self.status.checked_at = self._clock()

    def _refused(self) -> None:
        self._answered(False)
        self.status.token_refused = True

    def _label(self, path: Path) -> str:
        return f"{path.parent.parent.name}/{path.name}"  # the account folder, not the whole path

    def upload_changed(self, force: bool = False) -> int:
        """Upload every saved file whose modification time or size changed (every one, with `force`;
        the bot ignores what it already has). Returns how many went up."""
        done = 0
        paths = savedfile.find_saved_files(self.settings.wow_dir)
        self._cleared(*(k for k in self._problems  # loot files gone
                        if k not in (DECISIONS, MILESTONES) and not k.startswith("ms:") and Path(k) not in paths))
        for path in paths:
            try:
                st = path.stat()
            except OSError:
                continue
            signature = (st.st_mtime_ns, st.st_size)
            if self._uploaded.get(path) == signature and not force:
                continue
            try:
                body = savedfile.build_upload(savedfile.read_saved_file(path))
            except (LuaError, ValueError, OSError) as exc:
                # Usually the game is still writing it; the next pass reads it again.
                self._problem(str(path), f"Couldn't read {self._label(path)} yet ({exc}); trying again shortly.")
                continue
            try:
                answer = self._upload(self.settings.bot_url, self.settings.token, body)
            except client.TokenRefused:
                self._refused()
                raise
            except client.BotError as exc:
                self._answered(False)
                self._problem(str(path), f"Upload of {self._label(path)} failed: {exc}. Trying again shortly.")
                continue
            self._uploaded[path] = signature
            self._answered(True)
            self._cleared(str(path))
            self.status.uploaded_at = self._clock()
            self.status.new_awards = _count(answer, "new_awards")
            self.status.new_items = _count(answer, "new_items")
            log.info("Uploaded %s (%s): %s new items, %s new awards.", self._label(path),
                     body.get("uploader") or "unknown character", answer.get("new_items", "?"),
                     answer.get("new_awards", "?"))
            done += 1
        return done

    def _signature(self, path: Path) -> tuple[int, int] | None:
        try:
            st = path.stat()
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    def _milestones_guild(self) -> str | None:
        """The guild the bot takes milestones for, or None (off, or the bot can't be asked); asked again
        after MILESTONES_RECHECK seconds."""
        now = self._clock()
        if self._ms_checked_at is not None and now - self._ms_checked_at < MILESTONES_RECHECK:
            return self._ms_guild
        try:
            answer = self._ms_settings(self.settings.bot_url, self.settings.token)
        except client.TokenRefused:
            self._refused()
            raise
        except client.BotError as exc:
            self._answered(False)
            self._problem(MILESTONES, f"Couldn't ask the bot about milestones: {exc}. Trying again shortly.")
            return None
        self._answered(True)
        self._cleared(MILESTONES)
        guild = answer.get("guild")
        self._ms_guild = guild if answer.get("on") is True and isinstance(guild, str) and guild.strip() else None
        self._ms_checked_at = now
        return self._ms_guild

    def upload_milestones(self, force: bool = False) -> int:
        """Send the bot's guild's roster and level-ups from each changed saved file that has milestones on
        (/nlc milestones on in game). Without that this does nothing at all, not even ask the bot; while
        the bot has milestones off, nothing is sent. Other guilds' rosters never leave the PC. Returns how
        many files went up."""
        paths = savedfile.find_saved_files(self.settings.wow_dir)
        self._cleared(*(k for k in self._problems if k.startswith("ms:") and Path(k[3:]) not in paths))
        changed = [(p, sig) for p in paths
                   if (sig := self._signature(p)) is not None and (force or self._ms_uploaded.get(p) != sig)]
        files = []
        for path, signature in changed:
            try:
                db = savedfile.read_saved_file(path)
            except (LuaError, ValueError, OSError):
                continue  # the loot upload says so; tried again at the next change
            if savedfile.milestones_on(db):
                files.append((path, signature, db))
            else:
                self._ms_uploaded[path] = signature
                self._cleared(f"ms:{path}")
        if not files:
            return 0
        guild = self._milestones_guild()
        if guild is None:
            return 0  # the files stay changed: they go up once the bot takes them
        done = 0
        for path, signature, db in files:
            what = f"ms:{path}"
            bodies = savedfile.build_milestone_uploads(db, guild)
            try:
                for body in bodies:
                    answer = self._ms_upload(self.settings.bot_url, self.settings.token, body)
                    self.status.new_milestones = _count(answer, "new_milestones")
                    log.info("Sent %s's level-ups from %s (%s): %d members, %d level-ups, %s new milestones.",
                             body["guild"], self._label(path), body.get("uploader") or "unknown character",
                             len(body["members"]), len(body["levels"]), answer.get("new_milestones", "?"))
            except client.TokenRefused:
                self._refused()
                raise
            except client.BotError as exc:
                self._answered(False)
                self._problem(what, f"Sending level-ups from {self._label(path)} failed: {exc}. Trying again shortly.")
                continue
            self._ms_uploaded[path] = signature
            self._answered(True)
            self._cleared(what)
            done += 1
        return done

    def update_decisions(self) -> bool:
        """Fetch the decisions and rewrite the addon folder if `at` changed. Returns True if it wrote."""
        try:
            answer = self._fetch(self.settings.bot_url, self.settings.token)
        except client.TokenRefused:
            self._refused()
            raise
        except client.BotError as exc:
            self._answered(False)
            self._problem(DECISIONS, f"Couldn't fetch decisions: {exc}. Trying again shortly.")
            return False
        self._answered(True)
        update = newer_version(answer.get("companion"))
        if update and update != self.status.update:
            log.info("Companion %s is out (this is %s): download it from %s", update, __version__, release_page(update))
        self.status.update = update
        at = answer.get("at")
        if not isinstance(at, int) or not isinstance(answer.get("items"), dict):
            self._problem(DECISIONS, "The bot's decisions answer didn't look right; trying again shortly.")
            return False
        self.status.decisions = decisions.counts(answer)
        folder = decisions.addon_dir(self.settings.wow_dir)
        if decisions.current_at(folder) == at and all((folder / n).is_file() for n in decisions.TOC_NAMES):
            self._cleared(DECISIONS)
            return False
        decisions.write_addon(folder, answer)
        self._cleared(DECISIONS)
        log.info("Wrote %s In game after the next /reload or login.", decisions.summary(answer))
        return True

    def run_once(self) -> None:
        self.upload_changed()
        self.upload_milestones()
        self.update_decisions()

    def run_forever(self, sleep: Callable[[float], None] = time.sleep) -> None:
        log.info("Companion %s. Watching %s every %d seconds. Ctrl+C stops.", __version__, self.settings.wow_dir,
                 self.settings.poll_seconds)
        while True:
            try:
                self.run_once()
            except client.TokenRefused:
                raise
            except Exception as exc:  # noqa: BLE001 - e.g. a locked file; keep watching rather than die
                log.exception("Unexpected problem: %s. Trying again shortly.", exc)
            sleep(self.settings.poll_seconds)
