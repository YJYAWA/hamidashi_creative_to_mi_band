"""Convert extracted Artemis art into Mi-Band-sized quick-app assets."""
from __future__ import annotations

import io
import json
import os
import sys

from PIL import Image

from pf8 import Pf8

GAME = os.environ.get("GAME_DIR") or ""
if not GAME:
    raise SystemExit("请先设置环境变量 GAME_DIR，指向游戏安装目录（含 hamidashi.pfs）")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
APP = os.path.join(ROOT, "app", "src")
COMMON = os.environ.get("RAW_DIR") or os.path.join(ROOT, "build", "raw")

W, H = 336, 480
FG_SCALE = 0.235          # 2000px canvas -> ~470px character
BG_Q = int(os.environ.get('BG_Q', 40))
CG_Q = int(os.environ.get('CG_Q', 24))
SD_Q = int(os.environ.get('SD_Q', 28))
FG_COLORS = int(os.environ.get('FG_COLORS', 24))
FG_SCALE = float(os.environ.get('FG_SCALE', FG_SCALE))

VOLS = ["000", "021", "022"]
_pfs: dict[str, Pf8] = {}
_index: dict[str, tuple[str, object]] = {}
for _v in VOLS:
    _path = os.path.join(GAME, f"hamidashi.pfs.{_v}")
    if os.path.exists(_path):
        _p = Pf8(_path)
        _pfs[_v] = _p
        for _e in _p.entries:
            _k = _e.name.replace("\\", "/").lower()
            if _k not in _index:
                _index[_k] = (_v, _e)
BASE = Pf8(os.path.join(GAME, "hamidashi.pfs"))
BASE_INDEX = {e.name.replace("\\", "/").lower(): e for e in BASE.entries}


def read_img(src: str) -> Image.Image:
    key = src.lower()
    if key in _index:
        vol, e = _index[key]
        return Image.open(io.BytesIO(_pfs[vol].read(e)))
    if key in BASE_INDEX:
        return Image.open(io.BytesIO(BASE.read(BASE_INDEX[key])))
    raise KeyError(src)


def cover(im: Image.Image, w: int, h: int) -> Image.Image:
    im = im.convert("RGB")
    s = max(w / im.width, h / im.height)
    nw, nh = max(1, round(im.width * s)), max(1, round(im.height * s))
    im = im.resize((nw, nh), Image.LANCZOS)
    left = (nw - w) // 2
    top = (nh - h) // 2
    return im.crop((left, top, left + w, top + h))


def save_jpg(im: Image.Image, path: str, q: int) -> int:
    im.save(path, "JPEG", quality=q, optimize=True, progressive=False)
    return os.path.getsize(path)


def save_png(im: Image.Image, path: str) -> int:
    im.save(path, "PNG", optimize=True)
    return os.path.getsize(path)


def process(meta: dict) -> None:
    assets = json.load(open(os.path.join(BUILD, "assets.json"), encoding="utf-8"))
    images, sprites = assets["images"], assets["sprites"]
    dirs = {k: os.path.join(COMMON, k) for k in ("bg", "cg", "fg", "sd", "ui")}
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)

    out_img: dict[str, list] = {}
    total = 0
    for i, (aid, m) in enumerate(images.items(), 1):
        kind = m["kind"]
        try:
            im = read_img(m["src"])
        except KeyError:
            print("  ! missing", m["src"])
            continue
        if kind == "fg":
            x0, y0, x1, y1 = m["bbox"]
            part = im.convert("RGBA").crop((x0, y0, x1, y1))
            nw = max(1, round(part.width * FG_SCALE))
            nh = max(1, round(part.height * FG_SCALE))
            part = part.resize((nw, nh), Image.LANCZOS)
            try:
                part = part.quantize(colors=FG_COLORS, method=Image.FASTOCTREE)
            except Exception:
                pass
            p = os.path.join(dirs["fg"], f"{aid}.png")
            total += save_png(part, p)
            out_img[aid] = [nw, nh]
        else:
            sub = "cg" if kind == "cg" else ("sd" if kind == "sd" else "bg")
            art = im.convert("RGB")
            if sub in ("cg", "sd") and art.width > art.height:
                art = art.transpose(Image.ROTATE_270)   # rotate cw: 16:9 art fills the tall screen
            art = cover(art, W, H)
            p = os.path.join(dirs[sub], f"{aid}.jpg")
            total += save_jpg(art, p, BG_Q if sub == "bg" else (SD_Q if sub == "sd" else CG_Q))
            out_img[aid] = [W, H]
        if i % 50 == 0:
            print(f"  images {i}/{len(images)}  {total/1048576:.1f} MB", flush=True)

    s = FG_SCALE
    out_sprite: dict[str, list] = {}
    for sid, sp in sprites.items():
        parts = [[pid, round(dx * s), round(dy * s), out_img[pid][0], out_img[pid][1]]
                 for pid, dx, dy, w, h in sp["parts"] if pid in out_img]
        if not parts:
            continue
        out_sprite[sid] = parts
    geo = {
        "w": W,
        "h": H,
        "images": out_img,
        "sprites": out_sprite,
        "sizes": {sid: [round(sp["w"] * s), round(sp["h"] * s)] for sid, sp in sprites.items() if sid in out_sprite},
    }

    # ui bits taken straight from the game (title art / buttons)
    ui_src = {
        "title_bg": r"pc\cn\title\bg.png",
        "title_logo": r"pc\cn\title\logo.png",
        "title_char": r"pc\cn\title\char_s.png",
        "menu_btn": r"pc\cn\title\menu.png",
    }
    for name, src in ui_src.items():
        key = src.replace("\\", "/").lower()
        e = BASE_INDEX.get(key)
        if e is None:
            print("  ! ui miss", src)
            continue
        im = Image.open(io.BytesIO(BASE.read(e)))
        if im.width > im.height and name == "title_bg":
            im = cover(im, W, H)
        im = im.convert("RGBA")
        if max(im.size) > 700:
            r = 700 / max(im.size)
            im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
        save_png(im, os.path.join(dirs["ui"], f"{name}.png"))

    with open(os.path.join(COMMON, "geo.json"), "w", encoding="utf-8") as f:
        json.dump(geo, f, ensure_ascii=False, separators=(",", ":"))
    print(f"asset bytes: {total/1048576:.1f} MB")
    for d in dirs:
        n = len(os.listdir(dirs[d]))
        sz = sum(os.path.getsize(os.path.join(dirs[d], x)) for x in os.listdir(dirs[d]))
        print(f"  {d:3s} {n:5d} files {sz/1048576:6.2f} MB")


if __name__ == "__main__":
    process({})
