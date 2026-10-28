"""Start with Windows: one value under the user's Run key, which starts the .exe in the tray at sign-in.

Only the .exe offers it: `python -m companion` would need the project folder as its working folder.
"""
from __future__ import annotations

import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "Noctis Loot companion"

try:
    import winreg
except ImportError:  # not Windows
    winreg = None


def available() -> bool:
    return winreg is not None and bool(getattr(sys, "frozen", False))


def command() -> str:
    return f'"{sys.executable}" --tray'


def _value() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, NAME)[0]
    except OSError:
        return None


def enabled() -> bool:
    return available() and _value() is not None


def set_enabled(on: bool) -> None:
    if not available():
        return
    if on:  # a new Windows profile may not have the Run key yet
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command())
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, NAME)
    except FileNotFoundError:  # no key or no value: already off
        pass


def follow_moves() -> None:
    """If the .exe was moved since Start with Windows was turned on, point the value at where it is now."""
    value = _value() if available() else None
    if value is not None and value != command():
        set_enabled(True)
