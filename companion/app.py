"""The companion's loop: upload saved files that changed, then fetch decisions and write them for the game."""
from __future__ import annotations

import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

from . import client, decisions, savedfile
from .config import Settings
from .luaparse import LuaError

log = logging.getLogger("companion")


def setup_logging(log_file: Path | None) -> None:
    fmt = logging.Formatter("%(asctime)s  %(message)s", datefmt="%d %b %H:%M:%S")
    root = logging.getLogger("companion")
    root.setLevel(logging.INFO)
    root.handlers.clear()
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)


class Companion:
    def __init__(self, settings: Settings,
                 upload: Callable[[str, str, dict], dict] = client.post_upload,
                 fetch: Callable[[str, str], dict] = client.get_decisions):
        self.settings = settings
        self._upload = upload
        self._fetch = fetch
        self._uploaded: dict[Path, tuple[int, int]] = {}  # file -> (mtime_ns, size) last uploaded
        self._last_problem: str | None = None

    def _problem(self, message: str) -> None:
        # A bot that's down would otherwise log the same line every 30 seconds.
        if message != self._last_problem:
            log.warning(message)
        self._last_problem = message

    def _label(self, path: Path) -> str:
        return f"{path.parent.parent.name}/{path.name}"  # the account folder, not the whole path

    def upload_changed(self) -> int:
        """Upload every saved file whose modification time or size changed. Returns how many went up."""
        done = 0
        for path in savedfile.find_saved_files(self.settings.wow_dir):
            try:
                st = path.stat()
            except OSError:
                continue
            signature = (st.st_mtime_ns, st.st_size)
            if self._uploaded.get(path) == signature:
                continue
            try:
                body = savedfile.build_upload(savedfile.read_saved_file(path))
            except (LuaError, ValueError, OSError) as exc:
                # Usually the game is still writing it; the next pass reads it again.
                self._problem(f"Couldn't read {self._label(path)} yet ({exc}); trying again shortly.")
                continue
            try:
                answer = self._upload(self.settings.bot_url, self.settings.token, body)
            except client.TokenRefused:
                raise
            except client.BotError as exc:
                self._problem(f"Upload of {self._label(path)} failed: {exc}. Trying again shortly.")
                continue
            self._uploaded[path] = signature
            self._last_problem = None
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
            raise
        except client.BotError as exc:
            self._problem(f"Couldn't fetch decisions: {exc}. Trying again shortly.")
            return False
        at = answer.get("at")
        if not isinstance(at, int) or not isinstance(answer.get("items"), dict):
            self._problem("The bot's decisions answer didn't look right; trying again shortly.")
            return False
        folder = decisions.addon_dir(self.settings.wow_dir)
        if decisions.current_at(folder) == at and all((folder / n).is_file() for n in decisions.TOC_NAMES):
            return False
        decisions.write_addon(folder, answer)
        self._last_problem = None
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
