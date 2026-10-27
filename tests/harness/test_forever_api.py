"""The fakes mustn't invent the game: every function the fake client gives the addon, every C_
function the addon calls, and every event either of them uses exists in the Forever client
(harness/forever_api.json)."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from harness.realm import find_luajit

ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / "addon"
FOREVER = json.loads((ROOT / "harness" / "forever_api.json").read_text(encoding="utf-8"))
GLOBALS = set(FOREVER["globals"])
EVENTS = set(FOREVER["events"])


def addon_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(ADDON.glob("*.lua")))


def has(namespace: str, name: str) -> bool:
    return name in FOREVER["namespaces"].get(namespace, [])


@pytest.fixture(scope="module")
def fake():
    luajit = find_luajit()
    if luajit is None:
        pytest.skip("LuaJIT not found (set LUAJIT)")
    out = subprocess.run([luajit, str(ROOT / "harness" / "fake_api_names.lua")], cwd=ADDON,
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_the_fake_client_only_has_functions_forever_has(fake):
    assert fake["globals"], "the fake client defined no functions"
    assert [g for g in fake["globals"] if g not in GLOBALS] == []
    missing = [f"{ns}.{name}" for ns, names in fake["namespaces"].items()
               for name in names if not has(ns, name)]
    assert missing == []


def test_the_fake_client_only_fires_events_forever_has(fake):
    assert fake["events"] and [e for e in fake["events"] if e not in EVENTS] == []


def test_the_addon_only_calls_c_functions_forever_has():
    calls = set(re.findall(r"\b(C_\w+)\.(\w+)", addon_source()))
    assert calls
    assert sorted(f"{ns}.{name}" for ns, name in calls if not has(ns, name)) == []


def test_the_addon_only_listens_for_events_forever_has():
    events = set(re.findall(r"(?:ns\.On|RegisterEvent)\(\"(\w+)\"", addon_source()))
    assert events
    assert sorted(events - EVENTS) == []
