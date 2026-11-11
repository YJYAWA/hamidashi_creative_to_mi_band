"""alpha 级数对比：同一表情，2/3/4/8 级量化，放大边缘看锯齿
输出 work/cmp_alpha.png
"""
import sys, os, json, io
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

picks = []
for sid, n in sorted(use.items(), key=lambda x: -x[1]):
    m = CH.get(sid)
    if not m or not m[1]:
        continue
    if '/kan/' not in ART.get(m[0], {}).get('src', ''):
        continue
    picks.append(sid)
    if len(picks) >= 8:
        break
sid = picks[0]

body = IF.body_canvas(CH[sid][0])
ink = IF.ink_layer(sid)
real = body.copy()
real.alpha_composite(ink)


def quant_alpha(im, levels, colors=32):
    a = np.array(im).copy()
    steps = [round(i * 255 / (levels - 1)) for i in range(levels)]
    ai = a[..., 3].astype(np.int16)[..., None]
    sp = np.array(steps, dtype=np.int16)[None, None, :]
    a[..., 3] = np.array(steps, dtype=np.uint8)[np.abs(ai - sp).argmin(axis=2)]
    q = Image.fromarray(a, 'RGBA').quantize(colors=min(256, colors * levels), method=Image.FASTOCTREE).convert('RGBA')
    return q


tiles, labels = [], []
tiles.append(real); labels.append('原画')
for lv in (8, 4, 3, 2):
    lay = quant_alpha(ink, lv)
    comp = body.copy()
    comp.alpha_composite(lay)
    tiles.append(comp)
    labels.append('alpha %d 级' % lv)

ink_arr = np.array(ink)[..., 3]
ys_, xs_ = np.nonzero(ink_arr)
x0, y0 = int(xs_.min()) - 6, int(ys_.min()) - 6
x1, y1 = int(xs_.max()) + 6, int(ys_.max()) + 6

SCALE = 5
cw, chh = (x1 - x0) * SCALE, (y1 - y0) * SCALE
pad = 6
canvas = Image.new('RGB', (cw * len(tiles) + pad * (len(tiles) + 1), chh + pad * 2), (24, 20, 26))
for i, t in enumerate(tiles):
    crop = t.crop((x0, y0, x1, y1)).resize((cw, chh), Image.NEAREST)
    bg = Image.new('RGB', (cw, chh), (250, 246, 248))
    bg.paste(crop, (0, 0), crop)
    canvas.paste(bg, (pad + i * (cw + pad), pad))
canvas.save('work/cmp_alpha.png')
print('sid', sid, 'labels', labels, 'out work/cmp_alpha.png', canvas.size)
