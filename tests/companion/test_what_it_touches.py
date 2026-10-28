"""Keeps the README's "What it reads, writes and sends" true, so officers can check the app by reading a few files.

- Python's standard library only, except the window: ui.py alone may use pywebview, pystray and Pillow.
- Only client.py imports anything that can reach the network.
- Nothing starts other programs, loads native code or runs code it's given.
- The window's page can't load anything from the internet.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCES = sorted((ROOT / "companion").rglob("*.py")) + [ROOT / "packaging" / "companion_entry.py"]
NETWORK_FILE = ROOT / "companion" / "client.py"
UI_FILE = ROOT / "companion" / "ui.py"
UI_LIBRARIES = {"webview", "pystray", "PIL"}
PAGE = ROOT / "companion" / "page.html"

NETWORK = {"urllib", "http", "socket", "socketserver", "ssl", "asyncio", "ftplib", "smtplib", "poplib",
           "imaplib", "xmlrpc", "webbrowser"}
FORBIDDEN = {"subprocess", "multiprocessing", "ctypes", "importlib", "runpy", "code", "pickle", "marshal", "shelve"}
FORBIDDEN_OS = {"system", "popen", "startfile", "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp",
                "execvpe", "spawnl", "spawnle", "spawnv", "spawnve", "posix_spawn", "posix_spawnp", "add_dll_directory"}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__"}


def tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported(module: ast.Module) -> set[str]:
    """Top-level names of everything imported, leaving out the companion's own modules."""
    names = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names - {"companion", "__future__"}


def label(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


@pytest.mark.parametrize("path", SOURCES, ids=label)
def test_standard_library_only(path):
    outside = imported(tree(path)) - set(sys.stdlib_module_names)
    if path == UI_FILE:
        assert outside == UI_LIBRARIES
    else:
        assert outside == set()


def test_the_page_loads_nothing_from_the_internet():
    html = PAGE.read_text(encoding="utf-8")
    policy = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
    rules = dict(rule.strip().split(" ", 1) for rule in policy.split(";"))
    assert rules["default-src"] == "'none'"
    assert rules["img-src"] == rules["font-src"] == "data:"
    assert rules["style-src"] == rules["script-src"] == "'unsafe-inline'"
    assert set(rules) == {"default-src", "img-src", "font-src", "style-src", "script-src"}
    assert not re.search(r"(src|href)\s*=\s*[\"']?(https?:)?//", html)
    assert "connect-src" not in policy and "fetch(" not in html and "XMLHttpRequest" not in html


@pytest.mark.parametrize("path", SOURCES, ids=label)
def test_only_the_client_reaches_the_network(path):
    network = imported(tree(path)) & NETWORK
    if path == NETWORK_FILE:
        assert network == {"urllib"}
    else:
        assert network == set()


@pytest.mark.parametrize("path", SOURCES, ids=label)
def test_starts_no_programs_and_runs_no_code(path):
    module = tree(path)
    assert imported(module) & FORBIDDEN == set()
    for node in ast.walk(module):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
            assert node.attr not in FORBIDDEN_OS, f"{label(path)}:{node.lineno} uses os.{node.attr}"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in FORBIDDEN_CALLS, f"{label(path)}:{node.lineno} calls {node.func.id}()"


def test_it_checks_every_file_in_the_app():
    assert NETWORK_FILE in SOURCES and len(SOURCES) >= 8
