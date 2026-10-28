"""Start with Windows, against the real registry under a test name (removed afterwards). Windows only."""
from __future__ import annotations

import sys

import pytest

from companion import autostart

pytestmark = pytest.mark.skipif(autostart.winreg is None, reason="Windows only")


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Games\Noctis\NoctisLootCompanion.exe")
    monkeypatch.setattr(autostart, "NAME", "Noctis Loot companion (test)")
    yield
    autostart.set_enabled(False)


def test_only_the_exe_offers_it(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert autostart.available() is False and autostart.enabled() is False
    autostart.set_enabled(True)  # does nothing from the code
    assert autostart.enabled() is False


def test_turns_on_and_off_and_follows_a_moved_exe(frozen, monkeypatch):
    assert autostart.enabled() is False
    autostart.set_enabled(True)
    assert autostart.enabled() and autostart._value() == r'"C:\Games\Noctis\NoctisLootCompanion.exe" --tray'
    monkeypatch.setattr(sys, "executable", r"D:\Noctis\NoctisLootCompanion.exe")
    autostart.follow_moves()
    assert autostart._value() == r'"D:\Noctis\NoctisLootCompanion.exe" --tray'
    autostart.set_enabled(False)
    autostart.set_enabled(False)  # already off: no error
    assert autostart.enabled() is False
