"""What the window and the tray drive, with neither imported: the settings, the loop in the background and
what it's done, put the way the page shows it. Tested without a window (tests/companion/test_controller.py)."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

from . import autostart, client, config
from .app import Companion, Status
from .config import Settings

log = logging.getLogger("companion")
ACTIVITY_KEPT = 50
ACTIVITY_SHOWN = 12


class _Activity(logging.Handler):
    """The companion's log lines, newest first, for the window's Activity list."""

    def __init__(self, sink: deque):
        super().__init__(logging.INFO)
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self.sink.appendleft((record.created, record.getMessage()))


def host(url: str) -> str:
    """'loot.example.org' from 'https://loot.example.org/'."""
    return url.split("://", 1)[-1].split("/", 1)[0] or url


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def when(at: float, now: float) -> str:
    """'Today, 23:41', 'Yesterday, 23:41' or '27 Oct, 23:41'."""
    day, today = time.localtime(at), time.localtime(now)
    clock = time.strftime("%H:%M", day)
    if day[:3] == today[:3]:
        return f"Today, {clock}"
    if time.localtime(now - 86400)[:3] == day[:3]:
        return f"Yesterday, {clock}"
    return time.strftime("%d %b, %H:%M", day).lstrip("0")


def ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 10:
        return "just now"
    if seconds < 60:
        return f"{seconds} seconds ago"
    if seconds < 3600:
        return f"{plural(seconds // 60, 'minute')} ago"
    return f"{plural(seconds // 3600, 'hour')} ago"


def news(status: Status) -> str:
    if not status.new_awards and not status.new_items:
        return "nothing new"
    return f"{plural(status.new_awards, 'new award')}, {plural(status.new_items, 'new item')}"


class Controller:
    def __init__(self, path: Path, settings: Settings | None,
                 fetch: Callable[[str, str], dict] = client.get_decisions,
                 make_companion: Callable[[Settings], Companion] = Companion,
                 clock: Callable[[], float] = time.time):
        self.path = path
        self.settings = settings if settings is not None and settings.complete else None
        self._draft = settings  # what the setup form starts from
        self._fetch = fetch
        self._make = make_companion
        self._clock = clock
        self.companion = self._make(self.settings) if self.settings else None
        self.activity: deque = deque(maxlen=ACTIVITY_KEPT)
        self._handler = _Activity(self.activity)
        if log.level == logging.NOTSET or log.level > logging.INFO:
            log.setLevel(logging.INFO)
        log.addHandler(self._handler)
        self.notify: Callable[[str, str], None] = lambda title, text: None
        self.changed: Callable[[], None] = lambda: None
        self._detected: Path | None = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._force = False
        self._thread: threading.Thread | None = None

    @property
    def ready(self) -> bool:
        return self.companion is not None

    # The loop

    def start(self) -> None:
        if self.ready and not (self._thread and self._thread.is_alive()):
            self._thread = threading.Thread(target=self._run, name="companion", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        log.removeHandler(self._handler)

    def _run(self) -> None:
        log.info("Watching %s every %d seconds.", self.settings.wow_dir, self.settings.poll_seconds)
        while not self._stop.is_set():
            companion = self.companion
            self.run_pass()
            if companion.status.token_refused:
                self._wake.wait()  # until a new token, or quitting
            else:
                self._wake.wait(self.settings.poll_seconds)
            self._wake.clear()

    def run_pass(self) -> None:
        """One pass: upload, fetch decisions, tell the tray what's new."""
        companion = self.companion
        force, self._force = self._force, False
        uploaded, wrote = 0, False
        try:
            uploaded = companion.upload_changed(force=force)
            wrote = companion.update_decisions()
        except client.TokenRefused:
            log.error("The bot didn't accept the token. Get a new one with /loot token in Discord.")
            self.notify("Not connected", "The bot didn't accept your token. Open Noctis Loot to paste a new one.")
        except Exception as exc:  # noqa: BLE001 - e.g. a locked file; keep watching rather than die
            log.exception("Unexpected problem: %s. Trying again shortly.", exc)
        status = companion.status
        if uploaded and (status.new_awards or status.new_items):
            self.notify("Uploaded the loot", f"{news(status).capitalize()}. The bot posts them in Discord.")
        if wrote and status.decisions:
            _, council, roll = status.decisions
            self.notify("New decisions for the game",
                        f"{council} council, {roll} roll. In game after your next /reload or login.")
        self.changed()

    def upload_now(self) -> None:
        self._force = True
        self._wake.set()

    # Settings

    def check_wow(self, folder: str) -> bool:
        path = Path(folder.strip().strip('"'))
        return path.is_dir() and config.looks_like_wow(path)

    def _check_bot(self, url: str, token: str) -> tuple[str, str] | None:
        try:
            self._fetch(url, token)
        except client.TokenRefused:
            return "token", "The bot didn't accept that token. Type /loot token in Discord again and paste the new one."
        except client.BotError as exc:
            text = str(exc)
            return "url", f"{text[:1].upper()}{text[1:]}."
        return None

    def save_setup(self, wow: str, url: str, token: str, start_with_windows: bool | None = None) -> dict:
        """Checks the folder, the address and the token with the bot, then saves and starts."""
        wow_dir = Path(wow.strip().strip('"'))
        url = url.strip().rstrip("/")
        token = token.strip() or (self._draft.token if self._draft else "")
        if not str(wow).strip() or not wow_dir.is_dir():
            return {"ok": False, "field": "wow",
                    "error": "Can't find that folder. It's the _forever_ folder inside your World of Warcraft folder."}
        if not url.startswith(("https://", "http://")):
            return {"ok": False, "field": "url", "error": "It should start with https:// (ask whoever runs the bot)."}
        if not token:
            return {"ok": False, "field": "token", "error": "Type /loot token in Discord and paste what it gives you."}
        problem = self._check_bot(url, token)
        if problem:
            return {"ok": False, "field": problem[0], "error": problem[1]}
        poll = self._draft.poll_seconds if self._draft else config.POLL_SECONDS
        settings = Settings(wow_dir=wow_dir, bot_url=url, token=token, poll_seconds=poll)
        config.save(self.path, settings)
        if start_with_windows is not None:
            self.set_autostart(start_with_windows)
        log.info("Connected to %s.", host(url))
        self._use(settings)
        return {"ok": True}

    def reconnect(self, token: str) -> dict:
        if not token.strip():
            return {"ok": False, "field": "token", "error": "Paste the new token from /loot token first."}
        return self.save_setup(str(self.settings.wow_dir), self.settings.bot_url, token)

    def _use(self, settings: Settings) -> None:
        self.settings = self._draft = settings
        self.companion = self._make(settings)
        self.start()
        self._wake.set()
        self.changed()

    def set_autostart(self, on: bool) -> bool:
        try:
            autostart.set_enabled(on)
        except OSError as exc:
            log.warning("Couldn't change Start with Windows: %s", exc)
        else:
            log.info("Start with Windows is %s.", "on" if on else "off")
        return autostart.enabled()

    # What the page shows

    def _setup_state(self) -> dict:
        draft = self._draft
        if draft is not None and str(draft.wow_dir).strip() not in ("", "."):
            wow = str(draft.wow_dir)
        else:
            if self._detected is None:
                self._detected = config.detect_wow_dir() or config.DEFAULT_WOW
            wow = str(self._detected)
        return {
            "wow": wow,
            "wowFound": self.check_wow(wow),
            "url": (draft.bot_url if draft and draft.bot_url else config.GUILD_BOT_URL.rstrip("/")),
            "hasToken": bool(draft and draft.token),
            "canCancel": self.ready,
        }

    def state(self) -> dict:
        auto = {"available": autostart.available(), "on": autostart.enabled()}
        if not self.ready:
            return {"view": "setup", "setup": self._setup_state(), "autostart": auto}
        now = self._clock()
        status = self.companion.status
        address = host(self.settings.bot_url)
        if status.connected is None:
            link = {"state": "checking", "title": "Checking the bot…", "detail": address}
        elif status.connected:
            link = {"state": "ok", "title": "Connected to the loot bot",
                    "detail": f"{address} · checked {ago(now - (status.checked_at or now))}"}
        else:
            link = {"state": "down", "title": "Can't reach the bot", "detail": status.problem or address}
        if status.uploaded_at:
            upload = f"{when(status.uploaded_at, now)} · {news(status)}"
        else:
            upload = "Nothing since the app started"
        if status.decisions:
            from_, council, roll = status.decisions
            decided = f"From {from_} · {council} council, {roll} roll"
        else:
            decided = "Not fetched yet"
        return {
            "view": "token" if status.token_refused else "status",
            "link": link,
            "note": status.problem if status.connected else None,
            "upload": upload,
            "decisions": decided,
            "wow": str(self.settings.wow_dir),
            "pollSeconds": self.settings.poll_seconds,
            "activity": [{"time": time.strftime("%H:%M", time.localtime(at)), "text": text}
                         for at, text in list(self.activity)[:ACTIVITY_SHOWN]],
            "autostart": auto,
            "setup": self._setup_state(),
        }
