"""The companion's loop: upload saved files that changed, then fetch decisions and write them for the game."""
from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

from . import client, decisions, savedfile
from .config import Settings
from .luaparse import LuaError

log = logging.getLogger("companion")
DECISIONS = "decisions"  # the key of a failed decisions fetch among the problems


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


def _count(answer: dict, key: str) -> int:
    value = answer.get(key)
    return value if isinstance(value, int) else 0


class Companion:
    def __init__(self, settings: Settings,
                 upload: Callable[[str, str, dict], dict] = client.post_upload,
                 fetch: Callable[[str, str], dict] = client.get_decisions,
                 clock: Callable[[], float] = time.time):
        self.settings = settings
        self._upload = upload
        self._fetch = fetch
        self._clock = clock
        self._uploaded: dict[Path, tuple[int, int]] = {}  # file -> (mtime_ns, size) last uploaded
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
        self._cleared(*(k for k in self._problems if k != DECISIONS and Path(k) not in paths))  # files gone
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
        self.update_decisions()

    def run_forever(self, sleep: Callable[[float], None] = time.sleep) -> None:
        log.info("Watching %s every %d seconds. Ctrl+C stops.", self.settings.wow_dir, self.settings.poll_seconds)
        while True:
            try:
                self.run_once()
            except client.TokenRefused:
                raise
            except Exception as exc:  # noqa: BLE001 - e.g. a locked file; keep watching rather than die
                log.exception("Unexpected problem: %s. Trying again shortly.", exc)
            sleep(self.settings.poll_seconds)
