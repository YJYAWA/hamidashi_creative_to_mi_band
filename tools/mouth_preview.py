"""闭嘴唇线预览生成器（只读素材，输出 PNG 到桌面）

用法: python tools/mouth_preview.py <gain> <cap> <output_name>
做法:
 1) 每个身体取 8 个不同表情，逐像素求 alpha 标准差 -> 热点
 2) 两个最大热点=眼睛，眼睛下沿以下、水平居中的小热点=嘴框
 3) 框内墨色像素高度 <=3 行 => 闭嘴；否则张嘴（不动）
 4) 闭嘴：颜色取原画墨色，alpha = min(cap, 原alpha*gain)
"""
import sys, json, os, collections
sys.path.insert(0, 'tools')
import numpy as np
from PIL import Image, ImageFilter, ImageDraw, ImageFont
from build_assets import read_img

CW, CCH = 212, 520
AMP, BLUR, AL = 2.0, 0.9, 3
GAIN = int(sys.argv[1]) if len(sys.argv) > 1 else 16
CAP = int(sys.argv[2]) if len(sys.argv) > 2 else 255
NAME = sys.argv[3] if len(sys.argv) > 3 else 'mouth_preview.png'

CH = json.load(open('app10/src/common/chars.json', encoding='utf-8'))
ART = json.load(open('build/assets.json', encoding='utf-8'))['images']
SC = json.load(open('build/scenes.json', encoding='utf-8'))
use = collections.Counter()
for sc in SC.values():
    for op in sc['ops']:
        if op[0] == 'g' and op[2]:
            use[op[2]] += 1
by_body = collections.defaultdict(list)
for sid, m in CH.items():
    if m[1] and use.get(sid):
        by_body[m[0]].append(sid)


def font(sz):
    for p in [r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\simhei.ttf']:
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


FS, FT = font(15), font(20)


def ink(sid):
    m = CH[sid]; bid, fid = m[0], m[1]
    ref = Image.open('app10/src/common/cimg/b/%s.png' % bid); kb = CCH / ref.height
    cf = Image.open('app10/src/common/cimg/f/%s.png' % fid)
    f = read_img(ART[fid]['src']).convert('RGBA').resize(
        (max(1, round(cf.width * kb)), max(1, round(cf.height * kb))), Image.LANCZOS)
    s = CCH / m[7]
    lay = Image.new('RGBA', (CW, CCH), (0, 0, 0, 0))
    lay.alpha_composite(f, ((CW - round(ref.width * kb)) // 2 + round(m[2] * s), round(m[3] * s)))
    return lay


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


def comps_of(mask, minpix=12):
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
        out.append({'n': len(a), 'y0': int(a[:, 0].min()), 'y1': int(a[:, 0].max()),
                    'x0': int(a[:, 1].min()), 'x1': int(a[:, 1].max()),
                    'cy': float(a[:, 0].mean()), 'cx': float(a[:, 1].mean())})
    return out


def mouth_box(bid, k=8):
    sids = []; seen = set()
    for sid in sorted(by_body[bid], key=lambda s: -use[s]):
        fid = CH[sid][1]
        if fid in seen:
            continue
        seen.add(fid); sids.append(sid)
        if len(sids) >= k:
            break
    arr = np.stack([np.array(ink(s))[..., 3].astype(np.float32) for s in sids])
    std = arr.std(axis=0)
    std = np.array(Image.fromarray(np.clip(std, 0, 255).astype(np.uint8))
                   .filter(ImageFilter.GaussianBlur(1.2))).astype(np.float32)
    comps = comps_of(std > 45)
    comps.sort(key=lambda c: -c['n'])
    eyes = comps[:2]
    ex = (eyes[0]['cx'] + eyes[1]['cx']) / 2 if len(eyes) >= 2 else 106
    eb = max(c['y1'] for c in eyes) if eyes else 60
    mouth = None
    for c in comps[2:]:
        if c['cy'] > eb and abs(c['cx'] - ex) < 14:
            if mouth is None or c['cy'] > mouth['cy']:
                mouth = c
    return (mouth['x0'] - 1, mouth['y0'] - 1, mouth['x1'] + 2, mouth['y1'] + 2)


def baseline(bid, sid):
    base = body_canvas(bid); lay = ink(sid); comp = Image.alpha_composite(base, lay)
    ba = np.array(base).astype(np.float32); fa = np.array(lay); ca = np.array(comp).astype(np.float32)
    d = ca[..., :3] - ba[..., :3]; ad = np.abs(d).max(axis=2)
    mask = (fa[..., 3] > 0) & (ad > 4)
    w = np.clip((40.0 - ad) / 40.0, 0, 1)
    rgb = np.clip(ba[..., :3] + d * (1.0 + (AMP - 1.0) * w)[..., None], 0, 255)
    da = np.zeros((CCH, CW, 4), np.uint8)
    da[..., :3] = rgb.astype(np.uint8)
    am = mask.astype(np.float32) * 255.0
    am = np.array(Image.fromarray(am.astype(np.uint8), 'L')
                  .filter(ImageFilter.GaussianBlur(BLUR))).astype(np.float32)
    step = 255.0 / max(1, AL - 1)
    aq = np.clip(np.round(am / step) * step, 0, 255)
    da[..., 3] = np.where(aq > 70, aq, 0).astype(np.uint8)
    return base, fa, da


def classify(fa, box):
    x0, y0, x1, y1 = box
    al = np.array(fa)[..., 3][y0:y1, x0:x1]
    rows = np.nonzero((al > 30).any(axis=1))[0]
    h = int(rows.max() - rows.min() + 1) if len(rows) else 0
    return ('闭嘴' if 0 < h <= 3 else '张嘴'), h


def boost(da, fa, box):
    out = da.copy()
    x0, y0, x1, y1 = box
    reg = out[y0:y1, x0:x1].copy()
    ia = np.array(fa)[y0:y1, x0:x1]
    m = ia[..., 3] > 0
    if not m.any():
        return out
    rgb = reg[..., :3].copy(); rgb[m] = ia[..., :3][m]; reg[..., :3] = rgb
    a = reg[..., 3].copy(); a[m] = np.clip(ia[..., 3][m].astype(np.float32) * GAIN, 0, CAP).astype(np.uint8)
    reg[..., 3] = a
    out[y0:y1, x0:x1] = reg
    return out


def compose(base, da):
    c = Image.new('RGBA', (CW, CCH), (26, 26, 30, 255))
    c.alpha_composite(base, (0, 0))
    c.alpha_composite(Image.fromarray(da, 'RGBA'), (0, 0))
    return c


cases = []
for bid in ['f0423', 'f0425', 'f0405']:
    box = mouth_box(bid); pk = None; op = None
    for sid in sorted(by_body[bid], key=lambda s: -use[s])[:14]:
        base, fa, da = baseline(bid, sid)
        k, hh = classify(fa, box)
        if k == '闭嘴' and pk is None:
            pk = sid
        if k == '张嘴' and op is None:
            op = sid
    if pk:
        cases.append((bid, pk, box, '闭嘴'))
    if bid == 'f0405' and op:
        cases.append((bid, op, box, '张嘴（不动）'))

rows = []
for bid, sid, box, kind in cases:
    base, fa, da = baseline(bid, sid)
    da2 = boost(da, fa, box) if kind == '闭嘴' else da.copy()
    ch = int((np.abs(da.astype(int) - da2.astype(int)).sum(axis=2) > 0).sum())
    before, after = compose(base, da), compose(base, da2)
    x0, y0, x1, y1 = box
    z = 10
    bw, bh = (x1 - x0) * z, (y1 - y0) * z
    w, h = int(CW * 1.02), int(CCH * 1.02)
    row = Image.new('RGBA', (2 * w + 2 * bw + 44, 30 + h), (18, 18, 22, 255))
    d = ImageDraw.Draw(row); x = 8
    for lbl, im in [('现状', before), ('gain%d' % GAIN, after)]:
        row.alpha_composite(im.resize((w, h), Image.LANCZOS), (x, 30))
        d.text((x + 2, 8), lbl, fill=(235, 235, 240), font=FS)
        x += w + 10
    for lbl, im in [('嘴 %dx·现状' % z, before), ('嘴 %dx·方案' % z, after)]:
        cr = im.crop(box).resize((bw, bh), Image.NEAREST)
        row.alpha_composite(cr, (x, 30))
        d.text((x + 2, 8), lbl, fill=(255, 190, 120), font=FS)
        x += bw + 10
    rows.append((bid, sid, kind, ch, row))

W = max(r[4].width for r in rows)
H = 46 + sum(r[4].height + 36 for r in rows)
out = Image.new('RGBA', (W, H), (18, 18, 22, 255))
dd = ImageDraw.Draw(out)
dd.text((10, 12), '闭嘴唇线方案：colors=原画墨色, alpha=min(cap, 原alpha x %d / cap %d) ｜仅闭嘴' % (GAIN, CAP),
        fill=(255, 255, 255), font=FT)
y = 46
for bid, sid, kind, ch, r in rows:
    dd.text((10, y), '%s %s · %s · 改动像素 %d' % (bid, sid, kind, ch),
            fill=(150, 215, 255) if kind == '闭嘴' else (255, 170, 170), font=FS)
    out.alpha_composite(r, (0, y + 22))
    y += r.height + 36

p = os.path.join(r'C:\Users\Administrator\Desktop', NAME)
out.convert('RGB').save(p, quality=96)
print('saved', p, out.size)
for bid, sid, kind, ch, _ in rows:
    print('  %s %s %s 改动像素 %d' % (bid, sid, kind, ch))
