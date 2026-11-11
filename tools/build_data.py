"""Build the portable page table (+ asset geometry) from decrypted Artemis .ast scenes."""
from __future__ import annotations

import io
import json
import os
import re

from PIL import Image

from astparse import parse_ast
from pf8 import Pf8

GAME = os.environ.get("GAME_DIR") or ""
if not GAME:
    raise SystemExit("请先设置环境变量 GAME_DIR，指向游戏安装目录（含 hamidashi.pfs）")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT = os.path.join(ROOT, "work", "text")
OUT = os.path.join(ROOT, "build")

SRC_DIRS = ["V/script", "V.020/script", "V.022/script", "V.026/script"]
IMG_VOLS = ["000", "021", "022"]          # 000 = base images, 021 = r18/hd overlay
# base volume first: keep clothed sprites when the r18 patch replaced them
VOL_PREF = {v: i for i, v in enumerate(IMG_VOLS)}

NAME_MAP = {
    "妃愛": "妃爱",
    "華乃": "华乃",
    "錦": "锦",
    "天梨": "天梨",
    "里さん": "里姐",
    "あすみ": "明日美",
}

SKIP_CMDS = {
    "fgact", "quake", "colortone", "flash", "cacheclear", "ntclear", "vostop",
    "user", "line", "selback", "fgf", "trophy", "achievement", "keyskip",
    "staffroll", "brandlogo", "delay", "ex",
}


# ---------------------------------------------------------------- image index
class ImageStore:
    def __init__(self) -> None:
        self.vols: dict[str, Pf8] = {}
        self.index: dict[str, tuple[str, str]] = {}   # lower path -> (vol, real name)
        for v in IMG_VOLS:
            path = os.path.join(GAME, f"hamidashi.pfs.{v}")
            if not os.path.exists(path):
                continue
            p = Pf8(path)
            self.vols[v] = p
            for e in p.entries:
                n = e.name.replace("\\", "/")
                key = n.lower()
                if key not in self.index or VOL_PREF[v] < VOL_PREF[self.index[key][0]]:
                    self.index[key] = (v, n)
        self.cache: dict[str, dict] = {}
        self.raw_cache: dict[str, Image.Image] = {}

    def has(self, path: str) -> bool:
        return path.lower() in self.index

    def real(self, path: str) -> str:
        return self.index[path.lower()][1]

    def raw(self, path: str) -> Image.Image:
        vol, real = self.index[path.lower()]
        p = self.vols[vol]
        e = next(x for x in p.entries if x.name.replace("\\", "/") == real)
        return Image.open(io.BytesIO(p.read(e)))

    def meta(self, path: str, need_bbox: bool = False) -> dict:
        key = (path.lower(), need_bbox)
        if key in self.cache:
            return self.cache[key]
        im = self.raw(path)
        comment = im.info.get("comment") or ""
        pos = (0, 0)
        if comment.startswith("pos"):
            parts = comment.split(",")
            if len(parts) >= 3:
                pos = (int(parts[1]), int(parts[2]))
        bbox = None
        if need_bbox:
            bbox = im.convert("RGBA").getbbox()
        bbox = bbox or (0, 0, im.width, im.height)
        d = {
            "path": self.real(path),
            "pos": pos,
            "w": im.width,
            "h": im.height,
            "bbox": list(bbox),
        }
        self.cache[key] = d
        return d


STORE = ImageStore()


class Assets:
    def __init__(self) -> None:
        self.images: dict[str, dict] = {}
        self.by_path: dict[str, str] = {}
        self.sprites: dict[str, dict] = {}
        self.by_sprite: dict[tuple, str] = {}
        self.miss: list[str] = []
        self.kinds = {"bg": "b", "fg": "f", "cg": "c", "sd": "s"}

    def add_image(self, path: str, kind: str) -> str | None:
        if not STORE.has(path):
            self.miss.append(path)
            return None
        key = path.lower()
        if key in self.by_path:
            return self.by_path[key]
        meta = STORE.meta(path, need_bbox=(kind == "fg"))
        aid = f"{kind[0]}{len(self.images)+1:04d}"
        self.images[aid] = {
            "src": meta["path"],
            "kind": kind,
            "w": meta["w"],
            "h": meta["h"],
            "pos": list(meta["pos"]),
            "bbox": meta["bbox"],
        }
        self.by_path[key] = aid
        return aid

    def add(self, kind: str, candidates: list[str]) -> str | None:
        for c in candidates:
            aid = self.add_image(c, kind)
            if aid:
                return aid
        return None

    def add_sprite(self, body: list[str], face: list[str]) -> str | None:
        bid = None
        for c in body:
            bid = self.add_image(c, "fg")
            if bid:
                break
        if not bid:
            return None
        fid = None
        for c in face:
            fid = self.add_image(c, "fg")
            if fid:
                break
        key = (bid, fid)
        if key in self.by_sprite:
            return self.by_sprite[key]
        b = self.images[bid]
        parts = [(bid, b)]
        if fid:
            parts.append((fid, self.images[fid]))
        boxes = []
        for _, m in parts:
            x0, y0, x1, y1 = m["bbox"]
            boxes.append((m["pos"][0] + x0, m["pos"][1] + y0, m["pos"][0] + x1, m["pos"][1] + y1))
        ox = min(b_[0] for b_ in boxes)
        oy = min(b_[1] for b_ in boxes)
        ux = max(b_[2] for b_ in boxes)
        uy = max(b_[3] for b_ in boxes)
        geo = []
        for aid, m in parts:
            x0, y0, x1, y1 = m["bbox"]
            geo.append([aid, m["pos"][0] + x0 - ox, m["pos"][1] + y0 - oy, x1 - x0, y1 - y0])
        sid = f"f{len(self.sprites)+1:05d}"
        self.sprites[sid] = {"parts": geo, "w": ux - ox, "h": uy - oy}
        self.by_sprite[key] = sid
        return sid


# ---------------------------------------------------------------- resolvers
def path_of(attrs: dict) -> str:
    return (attrs.get("path") or "").strip(":").strip("/")


def resolve_kind(c: dict) -> str:
    p = path_of(c).lower()
    if p.startswith(("ev", "cg")):
        return "cg"
    if p.startswith("sd"):
        return "sd"
    return "bg"


def resolve_bg(c: dict) -> list[str]:
    path = path_of(c)
    f = c.get("file") or ""
    cands = [f"image/{path}/{f}.png"] if path else []
    cands += [
        f"image/{f}.png",
        f"image/{f.lstrip('z')}.png",
        f"image/bg/{f}.png",
        f"image/bg/{f.lstrip('z')}.png",
        f"image/ev/{f.lstrip('z')}.png",
        f"image/ev/{path}/{f}.png",
        f"image/ev/{path}/{f.lstrip('z')}.png",
        f"image/sd/{path}/{f}.png",
        f"image/cg/{f}.png",
    ]
    return cands


def resolve_fg_body(c: dict) -> list[str]:
    path = path_of(c)
    f = c.get("file") or ""
    ex = c.get("ex05") or ""
    head = c.get("head") or ""
    face = c.get("face") or ""
    cands = []
    if path and f:
        cands.append(f"image/{path}/{f}.png")
    if path and ex:
        cands.append(f"image/{path}/{ex}.png")
    if path and head:
        pose = face[0] if face else "a"
        for eye in ("0000", "0900", "0010", "0910"):
            cands.append(f"image/{path}/{head}{pose}{eye}.png")
    return cands


def resolve_fg_face(c: dict) -> list[str]:
    path = path_of(c)
    face = c.get("face") or ""
    return [f"image/{path}/{face}.png", f"image/{path}/{face}h.png"] if face and path else []


# ---------------------------------------------------------------- text
def texts_of(entry: dict) -> tuple[str, list[str]]:
    if not isinstance(entry, dict):
        return "", []
    name = ""
    nm = entry.get("name")
    if isinstance(nm, dict):
        name = nm.get("name") or ""
    content = entry.get("cn") or entry.get("ja") or []
    screens: list[str] = []
    if isinstance(content, list):
        for screen in content:
            if isinstance(screen, list):
                parts: list[str] = []
                for x in screen:
                    if isinstance(x, (dict, list)):
                        continue                    # ruby 读音等内联标记，丢弃
                    t = re.sub(r"\[/?ruby[^\]]*\]", "", str(x))
                    if t:
                        parts.append(t)
                screens.append("\n".join(parts))
            else:
                screens.append(str(screen))
    return name, screens


def load_scenes() -> dict[str, dict]:
    scenes: dict[str, dict] = {}
    for d in SRC_DIRS:
        p = os.path.join(TEXT, d)
        if not os.path.isdir(p):
            continue
        for fn in sorted(os.listdir(p)):
            if fn.endswith(".ast"):
                try:
                    with open(os.path.join(p, fn), encoding="utf-8-sig") as f:
                        scenes[fn[:-4]] = parse_ast(f.read())
                except Exception as ex:  # noqa: BLE001
                    print("  ! parse fail", d, fn, ex)
    return scenes


def scene_title(doc: dict) -> str:
    for blk in (doc.get("__arr") or [])[:3]:
        cmds = blk.get("__arr", []) if isinstance(blk, dict) else blk
        for c in cmds:
            if isinstance(c, dict) and c.get("__arr") and c["__arr"][0] == "savetitle":
                return c.get("cn") or c.get("text") or ""
    return ""


def build() -> None:
    raw = load_scenes()
    print(f"scenes loaded: {len(raw)}")
    A = Assets()
    out: dict[str, dict] = {}
    missing: set[str] = set()
    pages = choices = 0

    for sid, doc in raw.items():
        ast = doc.get("__arr") or []
        tbl = doc.get("text") or {}
        lbl = doc.get("label") or {}
        ops: list = []
        block_op: dict[int, int] = {}
        title = ""

        for bi, blk in enumerate(ast, start=1):
            block_op[bi] = len(ops)
            cmds = blk.get("__arr", []) if isinstance(blk, dict) else blk
            lang = blk.get("lang") if isinstance(blk, dict) else None
            sel: list = []

            for c in cmds:
                if not isinstance(c, dict) or not c.get("__arr"):
                    continue
                n = c["__arr"][0]
                if n == "bg" and c.get("file"):
                    kind = resolve_kind(c)
                    aid = A.add(kind, resolve_bg(c))
                    if aid:
                        ops.append(["c" if kind == "cg" else ("s" if kind == "sd" else "b"), aid])
                elif n == "fg":
                    mode = c.get("mode", 3)
                    ch = c.get("ch") or ""
                    if mode is not None and mode < 0:
                        ops.append(["x", ch])
                    elif c.get("head") or c.get("ex05") or c.get("file"):
                        sid2 = A.add_sprite(resolve_fg_body(c), resolve_fg_face(c))
                        if sid2:
                            lv = float(c.get("lv") or 2.4)
                            x = float(c.get("x") or 0)
                            ops.append(["g", ch, sid2, round(x / 640.0, 2), round(lv / 2.4, 2)])
                elif n == "cgdel":
                    ops.append(["d"])
                elif n == "msgoff":
                    ops.append(["m", 0])
                elif n == "msgon":
                    ops.append(["m", 1])
                elif n == "extrans":
                    ops.append(["w", int(c.get("time") or 300)])
                elif n == "bgm":
                    if c.get("stop"):
                        ops.append(["u", "", 0])
                    elif c.get("file"):
                        ops.append(["u", c["file"], int(c.get("loop") if c.get("loop") is not None else 1)])
                elif n == "se" and c.get("file"):
                    ops.append(["q", c["file"]])
                elif n == "eval" and c.get("exp"):
                    ops.append(["f", c["exp"]])
                elif n == "savetitle":
                    t = c.get("cn") or c.get("text") or ""
                    if t:
                        title = t
                        ops.append(["h", t])
                elif n == "select":
                    sel.append(c)
                elif n == "excall":
                    tgt, lab, cond = c.get("file"), c.get("label"), c.get("cond")
                    if tgt and tgt not in raw:
                        missing.add(tgt)
                    if cond:
                        ops.append(["i", cond, tgt or f"@{sid}:{lab}"])
                    elif tgt:
                        ops.append(["j", tgt])
                    elif lab:
                        ops.append(["k", f"@{sid}:{lab}"])
                elif n == "sceneend":
                    ops.append(["z"])
                elif n == "タイトル":
                    ops.append(["y"])
                elif n == "movie":
                    ops.append(["v", c.get("file") or ""])
                elif n in SKIP_CMDS:
                    continue

            if sel:
                labels = None
                if lang:
                    for probe in (lang,):
                        try:
                            ent = tbl.get(int(probe.split("_")[1]))
                        except (IndexError, ValueError):
                            ent = None
                        if isinstance(ent, dict) and "select" in ent:
                            s = ent["select"] or {}
                            labels = s.get("cn") or s.get("ja")
                    if labels is None:
                        try:
                            ent = tbl.get(int(lang.split("_")[1]) + 1)
                        except (IndexError, ValueError):
                            ent = None
                        if isinstance(ent, dict) and "select" in ent:
                            s = ent["select"] or {}
                            labels = s.get("cn") or s.get("ja")
                opts = []
                for i, c in enumerate(sel):
                    tgt, lab, exp = c.get("file"), c.get("label"), c.get("exp")
                    dest = tgt or (f"@{sid}:{lab}" if lab else "")
                    if tgt and tgt not in raw:
                        missing.add(tgt)
                    text = ""
                    if labels and i < len(labels) and labels[i]:
                        text = labels[i]
                    elif tgt in raw:
                        text = scene_title(raw[tgt]) or tgt
                    opts.append([text or f"选项{i+1}", dest, exp or ""])
                choices += 1
                ops.append(["o", opts])

            if lang:
                try:
                    idx = int(lang.split("_")[1])
                except (IndexError, ValueError):
                    idx = None
                if idx is not None:
                    name, screens = texts_of(tbl.get(idx))
                    name = NAME_MAP.get(name, name)
                    for s in screens:
                        if s.strip():
                            ops.append(["t", name, s])
                            pages += 1

        if ops:
            out[sid] = {"t": title, "ops": ops}
        if len(out) % 20 == 0:
            print(f"  scene {len(out)}/{len(raw)}  imgs={len(A.images)} sprites={len(A.sprites)}", flush=True)

    # label refs -> op index inside scene
    def resolve_ref(sid: str, lbl: dict, ref: str):
        body = ref[1:]
        s2, _, lab = body.partition(":")
        if s2 == sid:
            ent = lbl.get(lab) or lbl.get(f'"{lab}"')
            bi = ent.get("block") if isinstance(ent, dict) else None
            return bi or 0
        return f"{s2}#{lab}"

    for sid, sc in out.items():
        lbl = (raw[sid].get("label") or {})
        for op in sc["ops"]:
            if op[0] in ("k", "i") and isinstance(op[-1], str) and op[-1].startswith("@"):
                op[-1] = resolve_ref(sid, lbl, op[-1])
            elif op[0] == "o":
                for opt in op[1]:
                    if isinstance(opt[1], str) and opt[1].startswith("@"):
                        opt[1] = resolve_ref(sid, lbl, opt[1])

    print(f"scenes: {len(out)}  pages: {pages}  choices: {choices}")
    print(f"images: {len(A.images)}  sprites: {len(A.sprites)}  unresolved: {len(A.miss)}")
    for m in A.miss[:8]:
        print("   miss", m)
    if missing:
        print("missing scene targets:", sorted(missing)[:15])

    os.makedirs(OUT, exist_ok=True)
    dump(os.path.join(OUT, "scenes.json"), out)
    dump(os.path.join(OUT, "assets.json"), {"images": A.images, "sprites": A.sprites})


def dump(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  {os.path.basename(path)}: {os.path.getsize(path)/1024:.0f} KB")


if __name__ == "__main__":
    build()
