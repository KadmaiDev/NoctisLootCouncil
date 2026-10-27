"""Talking to the bot's API with the standard library only (sync-format.md, sections 2 and 3)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import __version__

USER_AGENT = f"NoctisLootCompanion/{__version__}"


class BotError(Exception):
    """The bot couldn't be reached, or answered with an error."""


class TokenRefused(BotError):
    """401: the token is wrong or was replaced with /loot token."""


def _request(method: str, url: str, token: str, body: dict | None = None, timeout: float = 60) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        **({"Content-Type": "application/json; charset=utf-8"} if data is not None else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise TokenRefused("the bot didn't accept the token") from exc
        detail = ""
        try:
            detail = json.loads(exc.read()).get("error", "")
        except (ValueError, AttributeError, OSError):
            pass
        raise BotError(f"the bot answered {exc.code}{f': {detail}' if detail else ''}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise BotError(f"can't reach the bot ({reason})") from exc
    try:
        result = json.loads(payload)
    except ValueError as exc:
        raise BotError("the bot's answer wasn't JSON (is the address right?)") from exc
    if not isinstance(result, dict):
        raise BotError("the bot's answer wasn't a JSON object")
    return result


def post_upload(base_url: str, token: str, body: dict) -> dict:
    return _request("POST", f"{base_url}/api/upload", token, body)


def get_decisions(base_url: str, token: str) -> dict:
    return _request("GET", f"{base_url}/api/decisions", token, timeout=30)
