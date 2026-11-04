"""The update notice: the version the bot names in its decisions answer, shown with a link to the
guild's GitHub releases (built here, never taken from the bot), told once per version and hidden by
"Not now" until a newer one. Nothing is downloaded or opened."""
from __future__ import annotations

from companion import RELEASES, __version__, config
from companion.app import Companion, newer_version, release_page
from companion.config import Settings
from companion.controller import Controller

from .test_savedfile import make_wow

URL = "https://loot.example.org"


def bump(version: str, by: int = 1) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    return f"{major}.{minor}.{patch + by}"


class Bot:
    def __init__(self, latest=None):
        self.latest = latest

    def fetch(self, url, token):
        answer = {"at": 1, "items": {}}
        if self.latest is not None:
            answer["companion"] = self.latest
        return answer

    def upload(self, url, token, body):
        return {"new_awards": 0, "new_items": 0}


def make(tmp_path, bot, skip=""):
    wow = tmp_path / "_forever_"
    settings = Settings(wow_dir=wow if wow.is_dir() else make_wow(tmp_path), bot_url=URL, token="good",
                        skip_update=skip)
    controller = Controller(tmp_path / "companion.ini", settings, fetch=bot.fetch,
                            make_companion=lambda s: Companion(s, upload=bot.upload, fetch=bot.fetch))
    controller.start = lambda: None
    told = []  # update notices only (a first pass also tells of new decisions)
    controller.notify = lambda title, text: told.append((title, text)) if title == "Companion update" else None
    return controller, told


def test_only_a_plain_higher_version_counts():
    assert newer_version(bump(__version__)) == bump(__version__)
    assert newer_version("99.0.0") == "99.0.0"
    assert newer_version(__version__) is None
    assert newer_version("0.0.1") is None
    for odd in ("1.2", "1.2.3.4", "v9.9.9", "9.9.9/../../evil", "9.9.9 ", "", None, 3, ["9.9.9"]):
        assert newer_version(odd) is None, odd
    assert release_page("1.2.3") == RELEASES + "/tag/companion-v1.2.3"
    assert RELEASES == "https://github.com/KadmaiDev/NoctisLootCouncil/releases"


def test_the_version_is_shown_and_an_update_told_once(tmp_path):
    bot = Bot()
    controller, told = make(tmp_path, bot)
    assert controller.state()["version"] == __version__
    controller.run_pass()
    assert controller.state()["update"] is None and told == []

    later = bump(__version__)
    bot.latest = later
    controller.run_pass()
    state = controller.state()
    assert state["update"] == {"version": later, "url": f"{RELEASES}/tag/companion-v{later}"}
    assert told == [("Companion update", f"Version {later} is out. Open Noctis Loot for the download link.")]
    controller.run_pass()
    assert len(told) == 1  # told once, still shown
    assert controller.state()["update"]["version"] == later
    controller.stop()


def test_not_now_hides_it_until_a_newer_version_and_is_remembered(tmp_path):
    later = bump(__version__)
    bot = Bot(later)
    controller, told = make(tmp_path, bot)
    controller.run_pass()
    controller.dismiss_update()
    assert controller.state()["update"] is None
    assert config.load(tmp_path / "companion.ini").skip_update == later
    controller.stop()

    # After a restart: still hidden, not told again.
    controller, told = make(tmp_path, bot, skip=config.load(tmp_path / "companion.ini").skip_update)
    controller.run_pass()
    assert controller.state()["update"] is None and told == []
    # A newer one shows again.
    bot.latest = bump(__version__, 2)
    controller.run_pass()
    assert controller.state()["update"]["version"] == bump(__version__, 2) and len(told) == 1
    controller.stop()


def test_a_bot_that_names_nothing_odd_shows_nothing(tmp_path):
    bot = Bot("https://example.com/evil.exe")
    controller, told = make(tmp_path, bot)
    controller.run_pass()
    assert controller.state()["update"] is None and told == []
    controller.stop()


def test_settings_keep_the_skipped_version_when_saved_again(tmp_path):
    later = bump(__version__)
    controller, _ = make(tmp_path, Bot(later), skip=later)
    assert controller.save_setup(str(controller.settings.wow_dir), URL, "good")["ok"]
    assert config.load(tmp_path / "companion.ini").skip_update == later
    controller.stop()
