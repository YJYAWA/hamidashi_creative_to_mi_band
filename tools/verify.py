"""Sanity-check the generated port data."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
COMMON = os.path.join(ROOT, "app", "src", "common")


def main() -> None:
    scenes = json.load(open(os.path.join(BUILD, "scenes.json"), encoding="utf-8"))
    geo = json.load(open(os.path.join(COMMON, "geo.json"), encoding="utf-8"))
    images, sprites = geo["images"], geo["sprites"]

    errors = []
    pages = 0
    choices = 0
    cg = set()
    used_imgs = set()

    for sid, sc in scenes.items():
        for op in sc["ops"]:
            c = op[0]
            if c == "t":
                pages += 1
            elif c in ("b",):
                used_imgs.add(("bg", op[1]))
            elif c in ("c", "s"):
                used_imgs.add(("cg" if c == "c" else "sd", op[1]))
                if c == "c":
                    cg.add(op[1])
            elif c == "g":
                if op[2] not in sprites:
                    errors.append(f"{sid}: 缺少立绘 {op[2]}")
                for p in sprites.get(op[2], []):
                    used_imgs.add(("fg", p[0]))
            elif c == "j":
                if op[1] not in scenes:
                    errors.append(f"{sid}: 跳转场景不存在 {op[1]}")
            elif c == "o":
                choices += 1
                for o in op[1]:
                    dest = o[1]
                    if isinstance(dest, int):
                        continue
                    if "#" in dest:
                        d = dest.split("#")[0]
                        if d not in scenes:
                            errors.append(f"{sid}: 选项场景不存在 {d}")
                    elif dest and dest not in scenes:
                        errors.append(f"{sid}: 选项场景不存在 {dest}")
            elif c == "i":
                t = op[2]
                if isinstance(t, str) and "#" not in t and t not in scenes:
                    errors.append(f"{sid}: 条件跳转场景不存在 {t}")

    # 资源文件存在性
    missing = []
    for kind, aid in sorted(used_imgs):
        ext = ".jpg" if kind in ("bg", "cg", "sd") else ".png"
        p = os.path.join(COMMON, kind, aid + ext)
        if not os.path.exists(p):
            missing.append(f"{kind}/{aid}{ext}")

    # 模拟通关（总是选第一项）
    visited = set()
    states = set()
    trace = 0
    cur, ip, flags = "gamestart", 0, {}
    while trace < 200000:
        trace += 1
        sc = scenes.get(cur)
        if not sc or ip >= len(sc["ops"]):
            break
        visited.add(cur)
        if (cur, ip) in states:
            break
        states.add((cur, ip))
        op = sc["ops"][ip]
        c = op[0]
        if c == "j":
            cur, ip = op[1], 0
        elif c == "o":
            dest = op[1][0][1]
            if isinstance(dest, int):
                ip = dest
            elif "#" in dest:
                cur, ip = dest.split("#")[0], 0
            else:
                cur, ip = dest, 0
        elif c == "i":
            t = op[2]
            if isinstance(t, str) and "#" not in t:
                cur, ip = t, 0   # 假设条件成立
            else:
                ip += 1
        elif c == "k":
            ip = op[1] if isinstance(op[1], int) else ip + 1
        else:
            ip += 1

    print(f"场景 {len(scenes)} · 文本页 {pages} · 选项组 {choices} · CG {len(cg)}")
    print(f"图片 {len(images)} · 立绘组合 {len(sprites)} · 被引用资源 {len(used_imgs)}")
    print(f"线性通关：经过 {len(visited)} 个场景，步数 {trace}")
    if missing:
        print(f"缺失文件 {len(missing)}：", missing[:8])
    if errors:
        print(f"数据错误 {len(errors)}：")
        for e in errors[:12]:
            print("  ", e)
    if not errors and not missing:
        print("校验通过")


if __name__ == "__main__":
    main()
