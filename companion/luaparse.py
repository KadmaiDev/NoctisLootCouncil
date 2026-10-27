"""A small parser for the Lua the WoW client writes into SavedVariables files.

It reads data, not code: `Name = value` statements whose values are strings, numbers, booleans,
nil and tables (`[key] = value`, `name = value` and list-style entries), with `--` comments.
That's everything the client writes. Tables whose keys are exactly 1..n become Python lists,
everything else a dict (an empty table is an empty dict).
"""
from __future__ import annotations

import re
from typing import Any

_NUMBER = re.compile(
    r"-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LONG_OPEN = re.compile(r"\[(=*)\[")
_DEC_ESCAPE = re.compile(r"\d{1,3}")
_HEX_ESCAPE = re.compile(r"[0-9a-fA-F]{2}")
_UTF8_ESCAPE = re.compile(r"\{([0-9a-fA-F]+)\}")

_SIMPLE_ESCAPES = {"n": b"\n", "t": b"\t", "r": b"\r", "a": b"\a", "b": b"\b", "f": b"\f", "v": b"\v",
                   "\\": b"\\", '"': b'"', "'": b"'", "\n": b"\n"}


class LuaError(ValueError):
    pass


class _Parser:
    def __init__(self, text: str):
        self.s = text
        self.i = 0
        self.n = len(text)

    # ---- helpers -----------------------------------------------------------

    def error(self, message: str) -> LuaError:
        line = self.s.count("\n", 0, self.i) + 1
        return LuaError(f"line {line}: {message}")

    def peek(self, k: int = 0) -> str:
        j = self.i + k
        return self.s[j] if j < self.n else ""

    def skip(self) -> None:
        """Skip whitespace and comments (`-- [1]` after list entries, and block comments)."""
        while self.i < self.n:
            c = self.s[self.i]
            if c in " \t\r\n\f\v":
                self.i += 1
            elif c == "-" and self.peek(1) == "-":
                self.i += 2
                m = _LONG_OPEN.match(self.s, self.i)
                if m:
                    self._long_bracket(m)
                else:
                    end = self.s.find("\n", self.i)
                    self.i = self.n if end < 0 else end + 1
            else:
                break

    def expect(self, ch: str) -> None:
        self.skip()
        if self.peek() != ch:
            raise self.error(f"expected {ch!r}, found {self.peek() or 'end of file'!r}")
        self.i += 1

    def _long_bracket(self, m: re.Match[str]) -> str:
        close = "]" + m.group(1) + "]"
        start = m.end()
        end = self.s.find(close, start)
        if end < 0:
            raise self.error("unfinished long string or comment")
        self.i = end + len(close)
        body = self.s[start:end]
        # Lua drops a newline straight after the opening bracket.
        if body.startswith("\r\n"):
            body = body[2:]
        elif body.startswith("\n"):
            body = body[1:]
        return body

    # ---- values ------------------------------------------------------------

    def value(self) -> Any:
        self.skip()
        c = self.peek()
        if not c:
            raise self.error("unexpected end of file")
        if c == "{":
            return self.table()
        if c in "\"'":
            return self.string()
        if c == "[":
            m = _LONG_OPEN.match(self.s, self.i)
            if m:
                return self._long_bracket(m)
        if c.isdigit() or c in "-.":
            return self.number()
        m = _NAME.match(self.s, self.i)
        if m:
            word = m.group()
            if word in ("true", "false", "nil"):
                self.i = m.end()
                return {"true": True, "false": False, "nil": None}[word]
        raise self.error(f"unexpected {c or 'end of file'!r}")

    def number(self) -> int | float:
        m = _NUMBER.match(self.s, self.i)
        if not m:
            raise self.error("bad number")
        self.i = m.end()
        text = m.group()
        neg = text.startswith("-")
        body = text[1:] if neg else text
        if body[:2] in ("0x", "0X"):
            v: int | float = int(body, 16)
        elif any(ch in body for ch in ".eE"):
            v = float(body)
        else:
            v = int(body)
        return -v if neg else v

    def string(self) -> str:
        quote = self.s[self.i]
        self.i += 1
        out = bytearray()
        while True:
            if self.i >= self.n:
                raise self.error("unfinished string")
            c = self.s[self.i]
            if c == quote:
                self.i += 1
                break
            if c == "\n":
                raise self.error("line break inside a string")
            if c != "\\":
                # Strings are bytes in Lua; keep the file's UTF-8 as it is.
                out += c.encode("utf-8", "surrogateescape")
                self.i += 1
                continue
            self.i += 1
            e = self.peek()
            if e in _SIMPLE_ESCAPES:
                out += _SIMPLE_ESCAPES[e]
                self.i += 1
            elif e == "\r":
                out += b"\n"
                self.i += 2 if self.peek(1) == "\n" else 1
            elif e.isdigit():
                m = _DEC_ESCAPE.match(self.s, self.i)
                code = int(m.group())
                if code > 255:
                    raise self.error("escape too large")
                out.append(code)
                self.i = m.end()
            elif e == "x":
                m = _HEX_ESCAPE.match(self.s, self.i + 1)
                if not m:
                    raise self.error("bad \\x escape")
                out.append(int(m.group(), 16))
                self.i = m.end()
            elif e == "z":
                self.i += 1
                while self.i < self.n and self.s[self.i] in " \t\r\n\f\v":
                    self.i += 1
            elif e == "u":
                m = _UTF8_ESCAPE.match(self.s, self.i + 1)
                if not m:
                    raise self.error("bad \\u escape")
                out += chr(int(m.group(1), 16)).encode("utf-8", "surrogatepass")
                self.i = m.end()
            else:
                raise self.error(f"bad escape \\{e}")
        return out.decode("utf-8", "replace")

    def table(self) -> dict | list:
        self.expect("{")
        d: dict[Any, Any] = {}
        index = 1
        while True:
            self.skip()
            if self.peek() == "}":
                self.i += 1
                break
            if self.peek() == "[" and not _LONG_OPEN.match(self.s, self.i):
                self.i += 1
                key = self.value()
                self.expect("]")
                self.expect("=")
                val = self.value()
            else:
                m = _NAME.match(self.s, self.i)
                after = m and self.s[m.end():].lstrip(" \t")
                if m and m.group() not in ("true", "false", "nil") and after.startswith("=") and not after.startswith("=="):
                    key = m.group()
                    self.i = m.end()
                    self.expect("=")
                    val = self.value()
                else:
                    key = index
                    index += 1
                    val = self.value()
            if key is None:
                raise self.error("nil table key")
            if val is not None:  # Lua tables don't hold nil
                d[key] = val
            self.skip()
            if self.peek() and self.peek() in ",;":
                self.i += 1
            elif self.peek() != "}":
                raise self.error(f"expected ',' or '}}', found {self.peek() or 'end of file'!r}")
        if d and all(isinstance(k, int) and not isinstance(k, bool) for k in d) and sorted(d) == list(range(1, len(d) + 1)):
            return [d[k] for k in range(1, len(d) + 1)]
        return d


def parse_value(text: str) -> Any:
    p = _Parser(text)
    v = p.value()
    p.skip()
    if p.i != p.n:
        raise p.error("unexpected text after the value")
    return v


def parse_assignments(text: str) -> dict[str, Any]:
    """Parse a SavedVariables file: a series of `Name = value` statements."""
    text = text.lstrip("﻿")
    p = _Parser(text)
    out: dict[str, Any] = {}
    while True:
        p.skip()
        if p.i >= p.n:
            return out
        m = _NAME.match(p.s, p.i)
        if not m:
            raise p.error("expected a variable name")
        p.i = m.end()
        p.expect("=")
        out[m.group()] = p.value()
        p.skip()
        if p.peek() == ";":
            p.i += 1


def load_file(path) -> dict[str, Any]:
    with open(path, "rb") as f:
        raw = f.read()
    # surrogateescape keeps any byte that isn't valid UTF-8, so strings round-trip exactly.
    return parse_assignments(raw.decode("utf-8", "surrogateescape"))
