"""墨色层表情（与身体无关，可跨身体去重）+ 表情内闭嘴提亮

与 build_app12.py 现有"差量烘焙"的区别：
  - 颜色 = 原画墨色（不掺身体颜色） -> 同一 faceId 在不同身体上像素一致 -> 可去重
  - 闭嘴提亮在"表情自身包围盒"内判定，不依赖身体热点
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageFilter
from build_assets import read_img

CW, CCH = 212, 520
GAIN = 16          # 闭嘴线 alpha 提升倍数
CAP = 255
ROW_THR = 12       # 判定"这一行有墨"的 alpha 阈值（唇线中位数只有 11/255，必须很低）

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CH = json.load(open(os.path.join(ROOT, 'app10/src/common/chars.json'), encoding='utf-8'))
ART = json.load(open(os.path.join(ROOT, 'build/assets.json'), encoding='utf-8'))['images']

_bc = {}


def body_canvas(bid):
    if bid in _bc:
        return _bc[bid]
    b = read_img(ART[bid]['src']).convert('RGBA')
    b = b.resize((max(1, round(b.width * CCH / b.height)), CCH), Image.LANCZOS)
    c = Image.new('RGBA', (CW, CCH), (0, 0, 0, 0))
    c.alpha_composite(b, ((CW - b.width) // 2, 0))
    _bc[bid] = c
    return c


def ink_layer(sid):
    """把该 sprite 的表情按真实偏移贴到 212x520 透明画布，返回 RGBA Image"""
    m = CH[sid]
    bid, fid = m[0], m[1]
    ref = Image.open(os.path.join(ROOT, 'app10/src/common/cimg/b/%s.png' % bid))
    kb = CCH / ref.height
    bx = (CW - round(ref.width * kb)) // 2
    cf = Image.open(os.path.join(ROOT, 'app10/src/common/cimg/f/%s.png' % fid))
    tw, th = max(1, round(cf.width * kb)), max(1, round(cf.height * kb))
    f = read_img(ART[fid]['src']).convert('RGBA').resize((tw, th), Image.LANCZOS)
    s = CCH / m[7]
    lay = Image.new('RGBA', (CW, CCH), (0, 0, 0, 0))
    lay.alpha_composite(f, (bx + round(m[2] * s), round(m[3] * s)))
    return lay


def _comps(mask, minpix=5):
    """8 连通分量"""
    H, W = mask.shape
    seen = np.zeros_like(mask, bool)
    out = []
    for sy, sx in zip(*np.nonzero(mask)):
        if seen[sy, sx]:
            continue
        st = [(sy, sx)]; seen[sy, sx] = True; pts = []
        while st:
            cy, cx = st.pop(); pts.append((cy, cx))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True; st.append((ny, nx))
        a = np.array(pts)
        if len(a) < minpix:
            continue
        out.append({'n': len(a),
                    'y0': int(a[:, 0].min()), 'y1': int(a[:, 0].max()),
                    'x0': int(a[:, 1].min()), 'x1': int(a[:, 1].max()),
                    'cy': float(a[:, 0].mean()), 'cx': float(a[:, 1].mean()),
                    'pts': a})
    return out


def locate_mouth(arr):
    """在单张表情里定位嘴：眼睛=最大两个分量；嘴=眼睛下沿以下、最靠下的那个小分量"""
    al = arr[..., 3]
    cs = _comps(al > 5)
    if len(cs) < 3:
        return None
    cs.sort(key=lambda c: -c['n'])
    eyes = cs[:2]
    eye_bottom = max(e['y1'] for e in eyes)
    ex = (eyes[0]['cx'] + eyes[1]['cx']) / 2.0
    cands = [c for c in cs[2:] if c['cy'] > eye_bottom - 3 and c['y1'] - c['y0'] + 1 <= 9]
    if not cands:
        return None
    # 取最靠下、且水平最接近眼距中心的
    cands.sort(key=lambda c: (-c['y1'], abs(c['cx'] - ex)))
    return cands[0]


def classify(arr, comp=None):
    """返回 ('闭嘴'|'张嘴'|'无', 高度)"""
    if comp is None:
        comp = locate_mouth(arr)
    if comp is None:
        return '无', 0
    h = comp['y1'] - comp['y0'] + 1
    return ('闭嘴' if h <= 3 else '张嘴'), h


def boost_alpha(lay, comp, gain=GAIN, cap=CAP):
    """仅闭嘴：把嘴部分量的 alpha 提升（颜色保持原画墨色，不扩像素）"""
    if comp is None:
        return lay, 0
    a = np.array(lay)
    ys, xs = comp['pts'][:, 0], comp['pts'][:, 1]
    sub = a[ys, xs, 3]
    sub = np.clip(sub.astype(np.float32) * gain, 0, cap).astype(np.uint8)
    a[ys, xs, 3] = sub
    return Image.fromarray(a, 'RGBA'), int(len(ys))


def face(sid, do_boost=True):
    """返回 (lay, kind, 墨色高度, changed_px)"""
    lay = ink_layer(sid)
    arr = np.array(lay)
    comp = locate_mouth(arr)
    kind, h = classify(arr, comp)
    changed = 0
    if do_boost and kind == '闭嘴' and comp is not None:
        lay, changed = boost_alpha(lay, comp)
    return lay, kind, h, changed


def delta_face(sid, do_boost=True, thr=8):
    """差量烘焙（v27 口径）：把表情合成到身体上，只保留"与身体差异超过 thr"的像素，
    像素颜色取合成后的最终颜色，alpha 二值化（255/0）。

    代价：含身体色 -> 同一 faceId 在不同身体上哈希不同 -> 不能跨身体去重。
    返回 (layer, kind, mouth_h, changed_px)
    """
    lay, kind, h, changed = face(sid, do_boost=do_boost)
    bid = CH[sid][0]
    body = body_canvas(bid)
    comp = body.copy()
    comp.alpha_composite(lay)
    ac = np.array(comp)
    ab = np.array(body)
    d = np.abs(ac[..., :3].astype(np.int16) - ab[..., :3].astype(np.int16)).max(axis=2)
    keep = (d > thr) & (np.array(lay)[..., 3] > 0)
    out = np.zeros_like(ac)
    out[keep] = ac[keep]
    out[keep, 3] = 255
    return Image.fromarray(out, 'RGBA'), kind, h, changed
