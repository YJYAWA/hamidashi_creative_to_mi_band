"""按小米手环10 画布（212x490）重建资源，立绘保持「身体 + 表情」分层，不做任何合成。

产出（写入 build/prep）：
  bcgi/<id>.jpg        背景 212x490
  evig/<id>.jpg        CG   212x490
  cimg/b/<id>.png      身体（缩放后）
  cimg/f/<id>.png      表情（缩放后）
  chars.json           spriteId -> [body, face, fx, fy, fw, fh]（目标像素）
"""
from __future__ import annotations

import io
import json
import os
import sys

from PIL import Image, ImageStat

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_assets as B          # 复用 PFS 读取器

ROOT = B.ROOT
BUILD = os.path.join(ROOT, "build")
SRC = os.environ.get("RAW_DIR") or os.path.join(ROOT, "build", "raw")
DST = os.environ.get("PREP_DIR") or os.path.join(ROOT, "build", "prep")

W, H = 212, 490
REF_W, REF_H = 400, 720           # 原版画布（由立绘坐标反推：x=±0.44 对应左右站位）
S = H / REF_H                     # 0.6806
FG_K = 0.279
SS = float(os.environ.get("SS", 1.6))   # 存储超采样倍数：按显示尺寸的倍数存，显示时缩小更锐                      # 游戏空间 -> 屏幕：普通体高 1144 -> 319px（约 65% 屏高）
FG_PRE = 0.235                    # app/src/common/fg 里那批图已被缩到 0.235，坐标换算要除掉它

BG_Q = int(os.environ.get("BG_Q", 14))
CG_Q_HIGH = int(os.environ.get("CG_Q_HIGH", 18))
CG_Q_LOW = int(os.environ.get("CG_Q_LOW", 12))
FORCE = os.environ.get("FORCE") == "1"
REVIEW = os.path.join(ROOT, "work", "cg_review")
TAGGED = {f.split("__p")[0] for f in os.listdir(REVIEW) if "__p" in f} if os.path.isdir(REVIEW) else set()
FG_COLORS = int(os.environ.get("FG_COLORS", 32))


def ensure(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p


def cover_portrait(im: Image.Image) -> Image.Image:
    """仅背景：居中裁切铺满 212x490。"""
    return B.cover(im.convert("RGB"), W, H)


CG_W, CG_H = 336, 480   # 参考项目同款：真机 JPEG 解码宽度上限，竖裁剪+横向滚动


def fit_height(im: Image.Image) -> Image.Image:
    """教程同款：CG 向右旋转 90° 后 fit 裁切 336x480；背景/SD 直接裁 7:10。"""
    return B.cover(im.convert("RGB"), CG_W, CG_H)


def fit_cg(im: Image.Image) -> Image.Image:
    im = im.convert("RGB").transpose(Image.ROTATE_270)   # 向右旋转 90°
    return B.cover(im, CG_W, CG_H)




def save_jpg(im: Image.Image, path: str, q: int) -> int:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q, optimize=True, progressive=False, subsampling=2)
    data = buf.getvalue()
    with open(path, "wb") as f:
        f.write(data)
    return len(data)

def save_png(im: Image.Image, path: str, colors: int) -> int:
    """立绘：32 色 + 10% 色散。做法：透明区填平均色，分别做「无抖动」与
    「Floyd-Steinberg 全抖动」量化，再按 1:9 混合（抖动占 10%），最后连同
    二值 alpha 一起八叉树量化。既打破色阶断层，又不产生黑边。"""
    im = im.convert("RGBA")
    alpha = im.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    mask = alpha.point(lambda v: 255 if v > 0 else 0)

    rgb = im.convert("RGB")
    try:
        mean = tuple(int(c) for c in ImageStat.Stat(rgb, mask).mean)
    except Exception:
        mean = (128, 128, 128)
    filled = Image.composite(rgb, Image.new("RGB", im.size, mean), mask)

    base = filled.quantize(colors=colors, method=Image.MEDIANCUT, dither=Image.Dither.NONE).convert("RGB")
    dith = filled.quantize(colors=colors, method=Image.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")
    final = Image.blend(base, dith, 0.10).convert("RGBA")
    final.putalpha(alpha)

    q = final.quantize(colors=colors, method=Image.FASTOCTREE)
    buf = io.BytesIO()
    q.save(buf, "PNG", optimize=True)
    data = buf.getvalue()
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


def main() -> None:
    assets = json.load(open(os.path.join(BUILD, "assets.json"), encoding="utf-8"))
    geo = json.load(open(os.path.join(SRC, "geo.json"), encoding="utf-8"))
    imgs = assets["images"]

    ensure(os.path.join(DST, "bcgi"))
    ensure(os.path.join(DST, "evig"))
    ensure(os.path.join(DST, "cimg", "b"))
    ensure(os.path.join(DST, "cimg", "f"))

    # ---- 背景 / CG ----
    stat = {"bg": 0, "cg": 0, "sd": 0}
    for aid, m in imgs.items():
        kind = m["kind"]
        if kind not in ("bg", "cg", "sd"):
            continue
        im = B.read_img(m["src"])
        art = fit_cg(im) if kind == "cg" else fit_height(im)
        q = BG_Q
        if kind != "bg":
            q = CG_Q_HIGH if aid in TAGGED else CG_Q_LOW
        outp = os.path.join(DST, "evig" if kind == "cg" else "bcgi", f"{aid}.jpg")
        if os.path.exists(outp) and not FORCE:
            stat[kind] += os.path.getsize(outp)
            continue
        stat[kind] += save_jpg(art, outp, q)

    # ---- 立绘：按 geo 拆成 身体 / 表情（直接读游戏原始 PNG，按 FG_K 缩放） ----
    bodies: dict[str, tuple[int, int]] = {}
    faces: dict[str, tuple[int, int]] = {}
    chars: dict[str, list] = {}
    ratio = FG_K / FG_PRE

    for sid, parts in geo["sprites"].items():
        body = None
        face = None
        fx = fy = 0
        for pid, px, py, pw, ph in parts:
            if px == 0 and py == 0:
                body = pid
            else:
                face = pid
                fx, fy = px, py
        if not body:
            continue
        bw, bh = assets["images"][body]["w"], assets["images"][body]["h"]
        tw, th = max(1, round(bw * FG_K)), max(1, round(bh * FG_K))
        bodies[body] = (max(1, round(tw * SS)), max(1, round(th * SS)))
        if face:
            fw_g = assets["images"][face]["w"]
            fh_g = assets["images"][face]["h"]
            fw, fh = max(1, round(fw_g * FG_K)), max(1, round(fh_g * FG_K))
            faces[face] = (max(1, round(fw * SS)), max(1, round(fh * SS)))
            chars[sid] = [body, face, round(fx * ratio), round(fy * ratio),
                          max(1, round(fw_g * FG_K)), max(1, round(fh_g * FG_K)), tw, th]
        else:
            chars[sid] = [body, "", 0, 0, 0, 0, tw, th]

    fstat = {"b": 0, "f": 0}
    for pid, (tw, th) in bodies.items():
        im = B.read_img(assets["images"][pid]["src"]).convert("RGBA")
        im = im.resize((tw, th), Image.LANCZOS)
        fstat["b"] += save_png(im, os.path.join(DST, "cimg", "b", f"{pid}.png"), FG_COLORS)
    for pid, (fw, fh) in faces.items():
        im = B.read_img(assets["images"][pid]["src"]).convert("RGBA")
        im = im.resize((fw, fh), Image.LANCZOS)
        fstat["f"] += save_png(im, os.path.join(DST, "cimg", "f", f"{pid}.png"), FG_COLORS)

    json.dump(chars, open(os.path.join(DST, "chars.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    print(f"bg {stat['bg'] / 1048576:.2f}MB  cg {stat['cg'] / 1048576:.2f}MB  sd {stat['sd'] / 1048576:.2f}MB")
    print(f"body {len(bodies)}/{fstat['b'] / 1048576:.2f}MB  face {len(faces)}/{fstat['f'] / 1048576:.2f}MB  sprites {len(chars)}")


if __name__ == "__main__":
    main()
