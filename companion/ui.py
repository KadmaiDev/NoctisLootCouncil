"""The window and the tray icon. pywebview shows page.html in Windows' own WebView2; pystray puts the owl by
the clock. The page is built into the app and loaded as text: nothing in the window comes from the internet,
and its Content-Security-Policy refuses anything that tries. The page can call only the methods of Api.
"""
from __future__ import annotations

import base64
import threading
from pathlib import Path

import pystray
import webview
from PIL import Image

from . import autostart, instance
from .config import Settings
from .controller import Controller

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
TITLE = "Noctis Loot"
TRAY_STATUS = {"ok": "Connected", "down": "Can't reach the bot", "checking": "Checking…"}


def page() -> str:
    def inline(name: str) -> str:
        return base64.b64encode((ASSETS / name).read_bytes()).decode("ascii")
    html = (HERE / "page.html").read_text(encoding="utf-8")
    return html.replace("{{OWL}}", inline("owl.png")).replace("{{FONT}}", inline("Philosopher-Bold.ttf"))


class Api:
    """What the page can call. pywebview exposes public methods only, so everything else is underscored."""

    def __init__(self, controller: Controller, ui: "Ui"):
        self._controller = controller
        self._ui = ui

    def state(self) -> dict:
        return self._controller.state()

    def upload_now(self) -> None:
        self._controller.upload_now()

    def check_wow(self, folder: str) -> bool:
        return self._controller.check_wow(folder)

    def save_setup(self, wow: str, url: str, token: str, start_with_windows: bool | None = None) -> dict:
        return self._controller.save_setup(wow, url, token, start_with_windows)

    def reconnect(self, token: str) -> dict:
        return self._controller.reconnect(token)

    def set_autostart(self, on: bool) -> bool:
        return self._controller.set_autostart(bool(on))

    def browse(self, current: str = "") -> str | None:
        start = current if current and Path(current).is_dir() else ""
        picked = self._ui.window.create_file_dialog(webview.FileDialog.FOLDER, directory=start)
        return picked[0] if picked else None


class Ui:
    def __init__(self, controller: Controller):
        self.controller = controller
        self.stopping = threading.Event()
        self.quitting = False
        self.window: webview.Window | None = None
        self.icon: pystray.Icon | None = None

    def show(self) -> None:
        self.window.show()
        self.window.restore()

    def quit(self) -> None:
        self.quitting = True
        self.stopping.set()
        self.controller.stop()
        self.icon.stop()
        self.window.destroy()

    def closing(self) -> bool:
        """Closing the window keeps the app in the tray; Quit in the tray menu ends it."""
        if self.quitting:
            return True
        self.window.hide()
        return False

    def tray_status(self, item=None) -> str:
        state = self.controller.state()
        if state["view"] == "setup":
            return f"{TITLE} · Not set up"
        if state["view"] == "token":
            return f"{TITLE} · Not connected"
        return f"{TITLE} · {TRAY_STATUS.get(state['link']['state'], '')}"

    def toggle_autostart(self) -> None:
        self.controller.set_autostart(not autostart.enabled())

    def changed(self) -> None:
        try:
            self.icon.title = self.tray_status()
            self.icon.update_menu()
        except Exception:  # noqa: BLE001 - the icon may be starting or gone; the next change tries again
            pass

    def notify(self, title: str, text: str) -> None:
        try:
            self.icon.notify(text, title)
        except Exception:  # noqa: BLE001 - a notification is a nicety
            pass

    def make_icon(self) -> pystray.Icon:
        menu = pystray.Menu(
            pystray.MenuItem(self.tray_status, None, enabled=False),
            pystray.MenuItem("Open window", self.show, default=True),
            pystray.MenuItem("Upload now", self.controller.upload_now, enabled=lambda item: self.controller.ready),
            pystray.MenuItem("Start with Windows", self.toggle_autostart,
                             checked=lambda item: autostart.enabled(), visible=autostart.available()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self.quit),
        )
        return pystray.Icon("NoctisLoot", Image.open(ASSETS / "owl.png"), TITLE, menu)


def run(path: Path, settings: Settings | None, start_hidden: bool = False) -> int:
    folder = path.parent
    lock = instance.acquire(folder)
    if lock is None:  # already running: bring that one's window up instead
        instance.ask_to_show(folder)
        return 0
    autostart.follow_moves()
    controller = Controller(path, settings)
    ui = Ui(controller)
    ui.window = webview.create_window(
        TITLE, html=page(), js_api=Api(controller, ui), width=480, height=800, min_size=(420, 560),
        background_color="#0D1017", hidden=start_hidden and controller.ready)
    ui.window.events.closing += ui.closing
    ui.icon = ui.make_icon()
    controller.notify = ui.notify
    controller.changed = ui.changed

    def started() -> None:
        threading.Thread(target=ui.icon.run, name="tray", daemon=True).start()
        instance.watch(folder, ui.show, ui.stopping)
        controller.start()

    try:
        webview.start(started, private_mode=True)
    finally:
        ui.stopping.set()
        controller.stop()
        ui.icon.stop()
        lock.close()
    return 0
