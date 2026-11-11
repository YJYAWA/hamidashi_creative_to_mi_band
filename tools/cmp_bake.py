"""对比 v27 式差量烘焙 与 v31 墨色层 的实际观感（贴到同一身体上合成）
输出 work/cmp_bake.png（四列：原画合成 / 差量thr8 / 差量thr20 / 墨色层8档）
"""
import sys, os, json
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import inkface as IF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
CH, ART = IF.CH, IF.ART
SC = json.load(open('build/scenes.json', encoding='utf-8'))

use = {}
for sc in SC.values():
    for op in sc['ops']:
        if op[0] == 'g' and op[2]:
            use[op[2]] = use.get(op[2], 0) + 1

cands = []
for sid, n in sorted(use.items(), key=lambda x: -x[1]):
    m = CH.get(sid)
    if not m or not m[1]:
        continue
    if '/kan/' not in ART.get(m[0], {}).get('src', ''):
        continue
    lay, kind, mh, changed = IF.face(sid, do_boost=False)
    cands.append((sid, n, kind))
    if len(cands) >= 6:
        break
closed = [c for c in cands if c[2] == 'closed'] or cands
sid = closed[0][0]
print('sprite:', sid, CH[sid], 'kind', closed[0][2])

body = IF.body_canvas(CH[sid][0])
ink = IF.ink_layer(sid)
arr_b = np.array(body).astype(np.int16)

real = body.copy()
real.alpha_composite(ink)


def delta(thr):
    comp = body.copy()
    comp.alpha_composite(ink)
    a_c = np.array(comp)
    d = np.abs(a_c[..., :3].astype(np.int16) - arr_b[..., :3]).max(axis=2)
    keep = (d > thr) & (np.array(ink)[..., 3] > 0)
    out = np.zeros_like(a_c)
    out[keep] = a_c[keep]
    out[keep, 3] = 255
    return Image.fromarray(out, 'RGBA')


def ink8():
    q = np.array(ink).copy()
    steps = np.array([round(i * 255 / 7) for i in range(8)], dtype=np.int16)
    ai = q[..., 3].astype(np.int16)
    q[..., 3] = np.array(steps, dtype=np.uint8)[np.abs(ai[..., None] - steps[None, None, :]).argmin(axis=2)]
    return Image.fromarray(q, 'RGBA')


tiles = []
for name, lay in (('原画', None), ('差量 thr8', delta(8)), ('差量 thr20', delta(20)), ('墨色 8档', ink8())):
    if lay is None:
        comp = real
    else:
        comp = body.copy()
        comp.alpha_composite(lay)
    tiles.append(comp)

ink_arr = np.array(ink)[..., 3]
ys_, xs_ = np.nonzero(ink_arr)
x0 = int(xs_.min()) - 14
y0 = int(ys_.min()) - 14
x1 = int(xs_.max()) + 14
y1 = int(ys_.max()) + 14
print('cut', (x0, y0, x1, y1))

SCALE = 4
cw, chh = (x1 - x0) * SCALE, (y1 - y0) * SCALE
pad = 6
canvas = Image.new('RGB', (cw * len(tiles) + pad * (len(tiles) + 1), chh + pad * 2), (24, 20, 26))
for i, t in enumerate(tiles):
    crop = t.crop((x0, y0, x1, y1)).resize((cw, chh), Image.NEAREST)
    bg = Image.new('RGB', (cw, chh), (250, 246, 248))
    bg.paste(crop, (0, 0), crop)
    canvas.paste(bg, (pad + i * (cw + pad), pad))
canvas.save('work/cmp_bake.png')
print('out work/cmp_bake.png', canvas.size)
