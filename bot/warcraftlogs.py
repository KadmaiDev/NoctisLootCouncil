"""Warcraft Logs reports for the loot log. An officer gives the bot a report's link (/loot wcl) and
the bot asks Warcraft Logs' API for the report's boss kills, so that night's #loot-log post links to
the report and each boss heading to that boss's kill in it.

Each game has its own site (classic.warcraftlogs.com, fresh.warcraftlogs.com, ...), and a report is
only on its own site's API, so the link says where to ask. One sign-in (a client ID and secret from
the site's API clients page) works for all of them.
"""
from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass

import aiohttp

log = logging.getLogger("noctis")

TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
API_URL = "https://{host}/api/v2/client"
REPORT_URL = "https://{host}/reports/{code}"
TIMEOUT = aiohttp.ClientTimeout(total=20)

# https://classic.warcraftlogs.com/reports/AbCd1234EfGh5678#fight=12 -> host, code
_LINK = re.compile(r"^(?:https?://)?((?:[a-z]+\.)?warcraftlogs\.com)/reports/([A-Za-z0-9]{16})(?![A-Za-z0-9])", re.I)

QUERY = ("query($code: String) { reportData { report(code: $code) { title startTime endTime "
         "fights(killType: Kills) { id name endTime } } } }")


class WclError(Exception):
    """Why a report couldn't be fetched, worded for the officer who asked."""


@dataclass(frozen=True)
class Fight:
    id: int
    name: str
    end_at: int  # seconds since the epoch, like award times


@dataclass(frozen=True)
class Report:
    host: str
    code: str
    title: str
    start_at: int  # seconds since the epoch
    end_at: int
    fights: tuple[Fight, ...]  # boss kills

    @property
    def url(self) -> str:
        return report_url(self.host, self.code)


def report_url(host: str, code: str) -> str:
    return REPORT_URL.format(host=host, code=code)


def fight_url(host: str, code: str, fight_id: int) -> str:
    return f"{report_url(host, code)}#fight={fight_id}"


def parse_link(text: str) -> tuple[str, str] | None:
    """A report link's site and code, or None if it isn't one."""
    m = _LINK.match(text.strip())
    if m is None:
        return None
    host = m[1].lower()
    return ("www." + host if host == "warcraftlogs.com" else host), m[2]


def parse_report(host: str, code: str, report: dict) -> Report:
    """The API's report (times in milliseconds, fights' relative to the report's start)."""
    start_ms = int(report["startTime"])
    fights = tuple(Fight(id=int(f["id"]), name=str(f["name"]), end_at=(start_ms + int(f["endTime"])) // 1000)
                   for f in report.get("fights") or [] if f.get("name"))
    return Report(host=host, code=code, title=str(report.get("title") or ""), start_at=start_ms // 1000,
                  end_at=int(report["endTime"]) // 1000, fights=fights)


class Api:
    """Warcraft Logs' API, signed in as the bot's client. The token lasts about a year; it's fetched
    again if the API stops taking it."""

    def __init__(self, client_id: str, client_secret: str):
        self._basic = "Basic " + base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self._token: str | None = None

    async def _sign_in(self, session: aiohttp.ClientSession) -> str:
        async with session.post(TOKEN_URL, data={"grant_type": "client_credentials"},
                                headers={"Authorization": self._basic}, timeout=TIMEOUT) as r:
            if r.status in (400, 401):
                raise WclError("Warcraft Logs didn't accept the bot's client ID and secret: "
                               "check WCL_CLIENT_ID and WCL_CLIENT_SECRET in its .env.")
            if r.status != 200:
                raise WclError(f"Warcraft Logs isn't answering (HTTP {r.status}); try again later.")
            return (await r.json(content_type=None))["access_token"]

    async def report(self, session: aiohttp.ClientSession, host: str, code: str) -> Report:
        try:
            for attempt in (1, 2):
                if self._token is None:
                    self._token = await self._sign_in(session)
                async with session.post(API_URL.format(host=host), json={"query": QUERY, "variables": {"code": code}},
                                        headers={"Authorization": f"Bearer {self._token}"}, timeout=TIMEOUT) as r:
                    if r.status == 401 and attempt == 1:
                        self._token = None
                        continue
                    if r.status != 200:
                        raise WclError(f"Warcraft Logs isn't answering (HTTP {r.status}); try again later.")
                    data = await r.json(content_type=None)
                break
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError) as exc:
            log.warning("Warcraft Logs report %s on %s failed: %s", code, host, exc)
            raise WclError("Couldn't reach Warcraft Logs; try again later.") from exc
        report = ((data.get("data") or {}).get("reportData") or {}).get("report")
        if not report:
            raise WclError("Warcraft Logs doesn't have that report, or it's private "
                           "(the bot can only see public and unlisted reports).")
        return parse_report(host, code, report)
