"""Tolerant parser for Artemis .ast files (Lua table-literal syntax)."""
from __future__ import annotations

import re
from typing import Any


class Parser:
    def __init__(self, src: str):
        self.s = src
        self.i = 0
        self.n = len(src)

    def ws(self) -> None:
        s, n = self.s, self.n
        while self.i < n:
            c = s[self.i]
            if c in " \t\r\n,":
                self.i += 1
            elif c == "-" and s.startswith("--", self.i):
                j = s.find("\n", self.i)
                self.i = n if j < 0 else j + 1
            else:
                break

    def parse(self) -> Any:
        self.ws()
        v = self.value()
        return v

    def value(self) -> Any:
        self.ws()
        c = self.s[self.i]
        if c == "{":
            return self.table()
        if c in "\"'":
            return self.string()
        m = re.compile(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?").match(self.s, self.i)
        if m:
            self.i = m.end()
            t = m.group(0)
            return float(t) if ("." in t or "e" in t.lower()) else int(t)
        m = re.compile(r"[A-Za-z_][A-Za-z_0-9]*").match(self.s, self.i)
        if m:
            self.i = m.end()
            w = m.group(0)
            return {"true": True, "false": False, "nil": None}.get(w, w)
        raise SyntaxError(f"unexpected {c!r} at {self.i}: {self.s[self.i:self.i+40]!r}")

    def string(self) -> str:
        q = self.s[self.i]
        self.i += 1
        out = []
        s = self.s
        while True:
            c = s[self.i]
            if c == "\\":
                nx = s[self.i + 1]
                mp = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "0": "\0"}
                if nx in mp:
                    out.append(mp[nx])
                    self.i += 2
                elif nx == "u":
                    m = re.match(r"u\{([0-9a-fA-F]+)\}", s[self.i + 1:])
                    if m:
                        out.append(chr(int(m.group(1), 16)))
                        self.i += 1 + m.end()
                    else:
                        out.append(nx)
                        self.i += 2
                elif nx == "\n":
                    out.append("\n")
                    self.i += 2
                else:
                    out.append(nx)
                    self.i += 2
                continue
            if c == q:
                self.i += 1
                return "".join(out)
            out.append(c)
            self.i += 1

    def table(self) -> Any:
        assert self.s[self.i] == "{"
        self.i += 1
        arr: list[Any] = []
        dct: dict[Any, Any] = {}
        while True:
            self.ws()
            if self.i >= self.n:
                raise SyntaxError("eof in table")
            if self.s[self.i] == "}":
                self.i += 1
                break
            # key = value  |  [key] = value  |  positional
            save = self.i
            key = None
            if self.s[self.i] == "[":
                self.i += 1
                self.ws()
                key = self.value()
                self.ws()
                assert self.s[self.i] == "]"
                self.i += 1
                self.ws()
                assert self.s[self.i] == "="
                self.i += 1
            else:
                m = re.compile(r"([A-Za-z_][A-Za-z_0-9]*)\s*=(?!=)").match(self.s, self.i)
                if m:
                    key = m.group(1)
                    self.i = m.end()
            val = self.value()
            if key is None:
                arr.append(val)
            else:
                dct[key] = val
            self.ws()
            if self.i < self.n and self.s[self.i] == "}":
                self.i += 1
                break
            if self.i < self.n and self.s[self.i] == ";":
                self.i += 1
                continue
        if arr and not dct:
            return arr
        if not arr:
            return dct
        return {"__arr": arr, **dct}


def parse_ast(text: str) -> dict:
    p = Parser(text)
    p.ws()
    m = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\s*=").match(text, p.i)
    if m:
        p.i = m.end()
    return p.parse()
