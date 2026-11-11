"""pf8 (Artemis Engine) archive reader/writer.

layout:
  "pf8"
  u32 count
  entries: u32 name_len, name(utf8, '\\' separated), u32 unk(orig_size when compressed else 0),
           u32 offset, u32 size
"""
from __future__ import annotations

import hashlib
import os
import struct
import zlib
from dataclasses import dataclass, field
from typing import BinaryIO

UNENCRYPTED_EXT = {".mp4", ".flv", ".webm", ".mpg", ".mpeg", ".wmv", ".avi"}


def xor_key(data: bytes, key: bytes) -> bytes:
    """XOR data with a repeating 20-byte key (fast int path)."""
    n = len(data)
    if not n:
        return data
    ks = (key * (n // len(key) + 1))[:n]
    return (int.from_bytes(data, "big") ^ int.from_bytes(ks, "big")).to_bytes(n, "big")


@dataclass
class Entry:
    name: str
    offset: int
    size: int
    extra: int = 0


@dataclass
class Pf8:
    path: str
    entries: list[Entry] = field(default_factory=list)
    data_start: int = 0
    key: bytes = b"\x00" * 20

    def __post_init__(self):
        with open(self.path, "rb") as f:
            head = f.read(3)
            assert head == b"pf8", f"not pf8: {head!r}"
            (index_size,) = struct.unpack("<I", f.read(4))
            (count,) = struct.unpack("<I", f.read(4))
            self.data_start = 7 + index_size
            # pf8: XOR key = sha1(index block), 20 bytes, repeated, per-file reset
            f.seek(7)
            self.key = hashlib.sha1(f.read(index_size)).digest()
            pos = 11
            for _ in range(count):
                f.seek(pos)
                (nlen,) = struct.unpack("<I", f.read(4))
                raw = f.read(nlen)
                name = raw.decode("utf-8", "replace")
                extra, off, size = struct.unpack("<III", f.read(12))
                self.entries.append(Entry(name, off, size, extra))
                pos += 4 + nlen + 12
        # sanity
        for e in self.entries:
            if e.offset + e.size > os.path.getsize(self.path):
                raise ValueError(f"entry out of range: {e}")

    def read(self, e: Entry) -> bytes:
        with open(self.path, "rb") as f:
            f.seek(e.offset)
            blob = f.read(e.size)
        ext = os.path.splitext(e.name)[1].lower()
        if ext not in UNENCRYPTED_EXT and self.key != b"\x00" * 20:
            blob = xor_key(blob, self.key)
        if e.extra:
            try:
                return zlib.decompress(blob)
            except zlib.error:
                return blob
        return blob


class Pf8Set:
    """Multiple volumes; larger numeric suffix wins (overlay rule)."""

    def __init__(self, base_path: str):
        d = os.path.dirname(base_path)
        base = os.path.basename(base_path)
        vols = []
        for fn in os.listdir(d):
            if fn == base or fn.startswith(base + "."):
                suf = fn[len(base) + 1:] if fn != base else ""
                try:
                    prio = int(suf) if suf else 0
                except ValueError:
                    continue
                vols.append((prio, os.path.join(d, fn)))
        vols.sort()
        self.volumes = [(p, Pf8(path)) for p, path in vols]
        self.index: dict[str, Entry] = {}
        self.owner: dict[str, Pf8] = {}
        for prio, pf in self.volumes:  # low -> high, later overrides
            for e in pf.entries:
                key = e.name.replace("\\", "/").lower()
                self.index[key] = e
                self.owner[key] = pf

    def names(self) -> list[str]:
        return sorted(self.index)

    def read(self, name: str) -> bytes:
        key = name.replace("\\", "/").lower()
        return self.owner[key].read(self.index[key])

    def find(self, prefix: str) -> list[str]:
        prefix = prefix.replace("\\", "/").lower()
        return [n for n in self.names() if n.startswith(prefix)]
