"""One copy at a time: a second start (say, a double-click while it's in the tray) asks the first to show
its window and exits. Two files beside companion.ini: a lock held while the app runs, and the request."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, IO

LOCK_NAME = "companion.lock"
SHOW_NAME = "companion.show"

try:
    import msvcrt
except ImportError:  # not Windows: no guard
    msvcrt = None


def acquire(folder: Path) -> IO | None:
    """The open lock file (keep it open while running), or None if another copy holds it."""
    folder.mkdir(parents=True, exist_ok=True)
    f = open(folder / LOCK_NAME, "a+")
    if msvcrt is None:
        return f
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    (folder / SHOW_NAME).unlink(missing_ok=True)  # a request left from before isn't for us
    return f


def ask_to_show(folder: Path) -> None:
    (folder / SHOW_NAME).write_text("")


def watch(folder: Path, show: Callable[[], None], stop: threading.Event, every: float = 1.0) -> threading.Thread:
    """Calls show() whenever another start asks; runs until stop is set."""
    request = folder / SHOW_NAME

    def loop() -> None:
        while not stop.wait(every):
            if request.exists():
                try:
                    request.unlink()
                except OSError:
                    continue
                show()

    thread = threading.Thread(target=loop, name="show-requests", daemon=True)
    thread.start()
    return thread
