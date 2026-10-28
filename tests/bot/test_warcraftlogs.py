"""Warcraft Logs reports on the loot log: the link, the API, and matching a report to its night."""
import base64

import pytest

from bot import render, warcraftlogs
from bot.upload import parse_upload
from bot.warcraftlogs import Fight, Report, WclError

from .conftest import RAID, sample_body

CODE = "8Td6NXf7AyhbpMWL"
CLASSIC = "classic.warcraftlogs.com"

# What the API answers for a report (shortened from a real one: Majordomo killed twice in a night).
REPORT = {"title": "Molten Core", "startTime": 1792572620683, "endTime": 1792589038177,
          "fights": [{"id": 12, "name": "Majordomo Executus", "endTime": 585128},
                     {"id": 26, "name": "Majordomo Executus", "endTime": 1792147}]}


def test_parse_link():
    assert warcraftlogs.parse_link(f"https://classic.warcraftlogs.com/reports/{CODE}") == (CLASSIC, CODE)
    assert warcraftlogs.parse_link(f" https://classic.warcraftlogs.com/reports/{CODE}#fight=12&type=damage-done ") \
        == (CLASSIC, CODE)
    assert warcraftlogs.parse_link(f"warcraftlogs.com/reports/{CODE}") == ("www.warcraftlogs.com", CODE)
    assert warcraftlogs.parse_link(f"https://FRESH.warcraftlogs.com/reports/{CODE}") == ("fresh.warcraftlogs.com", CODE)
    for bad in ("https://classic.warcraftlogs.com/character/eu/x/y", f"https://evil.example/reports/{CODE}",
                f"https://classic.warcraftlogs.com.evil.example/reports/{CODE}", "https://classic.warcraftlogs.com/reports/short",
                f"https://classic.warcraftlogs.com/reports/{CODE}X"):
        assert warcraftlogs.parse_link(bad) is None, bad


def test_parse_report_turns_times_into_seconds():
    r = warcraftlogs.parse_report(CLASSIC, CODE, REPORT)
    assert (r.start_at, r.end_at, r.title) == (1792572620, 1792589038, "Molten Core")
    assert r.fights == (Fight(12, "Majordomo Executus", 1792573205), Fight(26, "Majordomo Executus", 1792574412))
    assert r.url == f"https://classic.warcraftlogs.com/reports/{CODE}"
    assert warcraftlogs.fight_url(CLASSIC, CODE, 12) == f"https://classic.warcraftlogs.com/reports/{CODE}#fight=12"


class FakeResponse:
    def __init__(self, status, data=None):
        self.status, self.data = status, data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self.data


class FakeSession:
    """Warcraft Logs' token and API endpoints."""

    def __init__(self, token_status=200, reports=None, expire_first=False):
        self.token_status, self.reports, self.expire_first = token_status, reports or {}, expire_first
        self.sign_ins = 0
        self.asked: list[str] = []

    def post(self, url, *, data=None, json=None, headers=None, timeout=None):
        if url == warcraftlogs.TOKEN_URL:
            assert data == {"grant_type": "client_credentials"}
            assert headers["Authorization"] == "Basic " + base64.b64encode(b"id:secret").decode()
            self.sign_ins += 1
            return FakeResponse(self.token_status, {"access_token": f"t{self.sign_ins}"})
        self.asked.append(url)
        if self.expire_first and headers["Authorization"] == "Bearer t1":
            return FakeResponse(401)
        report = self.reports.get(json["variables"]["code"])
        if report is None:
            return FakeResponse(200, {"errors": [{"message": "This report does not exist."}],
                                      "data": {"reportData": {"report": None}}})
        return FakeResponse(200, {"data": {"reportData": {"report": report}}})


async def test_api_signs_in_once_and_asks_the_reports_own_site():
    api, session = warcraftlogs.Api("id", "secret"), FakeSession(reports={CODE: REPORT})
    assert (await api.report(session, CLASSIC, CODE)).code == CODE
    await api.report(session, CLASSIC, CODE)
    assert session.sign_ins == 1 and session.asked == ["https://classic.warcraftlogs.com/api/v2/client"] * 2


async def test_api_signs_in_again_when_the_token_stops_working():
    api, session = warcraftlogs.Api("id", "secret"), FakeSession(reports={CODE: REPORT}, expire_first=True)
    assert (await api.report(session, CLASSIC, CODE)).code == CODE
    assert session.sign_ins == 2


async def test_api_errors_are_worded_for_the_officer():
    with pytest.raises(WclError, match="private"):
        await warcraftlogs.Api("id", "secret").report(FakeSession(), CLASSIC, CODE)
    with pytest.raises(WclError, match="WCL_CLIENT_ID"):
        await warcraftlogs.Api("id", "secret").report(FakeSession(token_status=401), CLASSIC, CODE)


def report(code=CODE, start=RAID - 600, end=RAID + 3 * 3600, fights=()):
    return Report(host=CLASSIC, code=code, title="MC", start_at=start, end_at=end, fights=tuple(fights))


def test_report_links_the_nights_post_and_each_boss_to_its_kill(store):
    # sample_body: Sash at RAID+700 and Felheart Gloves at RAID+1000, both from Lucifron.
    store.apply_upload(parse_upload(sample_body()), "discord:1", "Kadmai")
    store.clear_log_dirty("Molten Core", "2026-10-26", store.dirty_log_groups()[0][2])
    kills = [Fight(2, "Lucifron", RAID + 200), Fight(5, "Lucifron", RAID + 650), Fight(9, "Lucifron", RAID + 5000)]
    assert store.save_report(report(fights=kills), "Seren") == [("Molten Core", "2026-10-26")]
    assert [g[:2] for g in store.dirty_log_groups()] == [("Molten Core", "2026-10-26")]  # the post gets edited
    group = store.log_group("Molten Core", "2026-10-26")
    assert group.report_url == f"https://classic.warcraftlogs.com/reports/{CODE}"
    assert group.fight_urls == {"Lucifron": f"https://classic.warcraftlogs.com/reports/{CODE}#fight=5"}
    [card] = render.log_cards(group)
    assert card.subtitle == f"2 items · [Warcraft Logs](https://classic.warcraftlogs.com/reports/{CODE})"
    assert card.body.splitlines()[0] == f"__[Lucifron](https://classic.warcraftlogs.com/reports/{CODE}#fight=5)__"


def test_the_report_that_holds_the_loot_wins(store):
    store.apply_upload(parse_upload(sample_body()), "discord:1", "Kadmai")
    # Onyxia later the same night, logged separately: it holds none of MC's loot.
    assert store.save_report(report(code="OnyxiaOnyxia1234", start=RAID + 4 * 3600, end=RAID + 5 * 3600)) == []
    assert store.save_report(report()) == [("Molten Core", "2026-10-26")]
    assert CODE in store.log_group("Molten Core", "2026-10-26").report_url
    # An officer linking another report that holds the loot just as well: the newer one is taken.
    store.now = lambda: 2_000_000_000
    assert store.save_report(report(code="CorrectedReport1")) == [("Molten Core", "2026-10-26")]
    assert "CorrectedReport1" in store.log_group("Molten Core", "2026-10-26").report_url


def test_a_report_linked_before_the_upload_is_used_once_the_loot_comes(store):
    assert store.save_report(report(fights=[Fight(5, "Lucifron", RAID + 650)])) == []
    store.apply_upload(parse_upload(sample_body()), "discord:1", "Kadmai")
    assert store.log_group("Molten Core", "2026-10-26").fight_urls["Lucifron"].endswith("#fight=5")


def test_another_nights_report_is_not_used(store):
    store.apply_upload(parse_upload(sample_body()), "discord:1", "Kadmai")
    assert store.save_report(report(start=RAID + 7 * 86400, end=RAID + 7 * 86400 + 3600)) == []
    assert store.log_group("Molten Core", "2026-10-26").report_url is None
