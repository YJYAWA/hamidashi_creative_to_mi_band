"""Dedupe identical image files, remap references in scenes.json / geo.json."""
from __future__ import annotations

import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
COMMON = os.path.join(ROOT, "app", "src", "common")
DIRS = {"b": "bg", "c": "cg", "s": "sd", "f": "fg"}


def digest(path: str) -> str:
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    scenes = json.load(open(os.path.join(BUILD, "scenes.json"), encoding="utf-8"))
    geo = json.load(open(os.path.join(COMMON, "geo.json"), encoding="utf-8"))

    # id -> canonical id
    canon: dict[str, str] = {}
    removed = 0
    saved = 0
    for prefix, sub in DIRS.items():
        d = os.path.join(COMMON, sub)
        if not os.path.isdir(d):
            continue
        seen: dict[str, str] = {}
        for fn in sorted(os.listdir(d)):
            aid = os.path.splitext(fn)[0]
            p = os.path.join(d, fn)
            h = digest(p)
            if h in seen:
                canon[aid] = seen[h]
                saved += os.path.getsize(p)
                trash = os.path.join(ROOT, "_dedup_trash", sub)
                os.makedirs(trash, exist_ok=True)
                os.replace(p, os.path.join(trash, fn))
                removed += 1
            else:
                seen[h] = aid
                canon[aid] = aid

    def remap(aid):
        return canon.get(aid, aid)

    n_ops = 0
    for sc in scenes.values():
        for op in sc["ops"]:
            if op[0] in ("b", "c", "s") and isinstance(op[1], str):
                new = remap(op[1])
                if new != op[1]:
                    op[1] = new
                    n_ops += 1
            elif op[0] == "g" and isinstance(op[2], str):
                new = remap(op[2])
                if new != op[2]:
                    op[2] = new
                    n_ops += 1

    sprites = {}
    for sid, parts in geo["sprites"].items():
        sprites[sid] = [[remap(p[0]), p[1], p[2], p[3], p[4]] for p in parts]
    geo["sprites"] = sprites
    geo["sizes"] = {sid: v for sid, v in geo["sizes"].items() if sid in sprites}
    geo.pop("images", None)

    with open(os.path.join(BUILD, "scenes.json"), "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(COMMON, "geo.json"), "w", encoding="utf-8") as f:
        json.dump(geo, f, ensure_ascii=False, separators=(",", ":"))

    # 一致性检查：所有被引用的 id 必须存在
    missing = []
    have = set()
    for sub in DIRS.values():
        d = os.path.join(COMMON, sub)
        if os.path.isdir(d):
            have |= {os.path.splitext(x)[0] for x in os.listdir(d)}
    for sid, sc in scenes.items():
        for op in sc["ops"]:
            if op[0] in ("b", "c", "s") and isinstance(op[1], str) and op[1] not in have:
                missing.append((sid, op[1]))
            if op[0] == "g" and op[2] not in sprites:
                missing.append((sid, op[2]))
    if missing:
        print(f"!! 引用缺失 {len(missing)} 处，例如 {missing[:5]}")

    total = 0
    for sub in DIRS.values():
        d = os.path.join(COMMON, sub)
        if os.path.isdir(d):
            total += sum(os.path.getsize(os.path.join(d, x)) for x in os.listdir(d))
    print(f"去重删除 {removed} 个文件，省 {saved/1048576:.2f} MB；重映射 {n_ops} 处引用")
    print(f"图片总计 {total/1048576:.2f} MB")


if __name__ == "__main__":
    main()
