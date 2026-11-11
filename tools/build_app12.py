#!/usr/bin/env python3
"""资产管线：立绘分层烘焙 / 表情配额 / 剧本分块
- 立绘 = 212x520 画布（身体去重 / 表情按 sprite 烘焙 + 内容去重）
- 表情不再逐张落盘：打包为调色板精确的图集 PNG + 静态 CSS 定位类（像素零损失）
  * 每张图集的调色板 = 组内表情调色板并集（≤256 才收入），逐像素精确映射
  * 引擎表情层用 <div class="person-face {{cls}}"> + background-position 定位
- scn 文本 / 全局立绘表 / bg·ev·sd 拷贝逻辑同 v18
"""
import os, json, hashlib, shutil, io, sys
import numpy as np
from PIL import Image, ImageStat, ImageFilter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
from build_assets import read_img as read_game_img
import inkface as INK

ROOT = os.getcwd()
# 目录约定：
#   build/raw  —— 从正版解包出的原始素材（用户自行生成，不入库）
#   build/prep —— build_assets10.py 的转换中间产物（bcgi/evig/cimg/chars.json）
#   app/src    —— 快应用源码与最终资源
SRC = os.environ.get('PREP_DIR') or os.path.join(ROOT, 'build', 'prep')
DST = os.environ.get('OUT_DIR') or os.path.join(ROOT, 'app', 'src', 'common')
TMP = os.path.join(ROOT, 'work', 'face_tmp')
SC = json.load(open(os.path.join(ROOT, 'build', 'scenes.json'), encoding='utf-8'))
CH = json.load(open(os.path.join(SRC, 'chars.json'), encoding='utf-8'))
ART = json.load(open(os.path.join(ROOT, 'build', 'assets.json'), encoding='utf-8'))['images']
BODY_COLORS = int(os.environ.get('BODY_COLORS', 48))
FACE_COLORS = int(os.environ.get('FACE_COLORS', 32))
BODY_ALPHA = int(os.environ.get('BODY_ALPHA', 5))
FACE_ALPHA = int(os.environ.get('FACE_ALPHA', 2))
DELTA_THR = int(os.environ.get('DELTA_THR', 8))
FACE_AMP = float(os.environ.get('FACE_AMP', 2.0))      # 低差量细节（嘴线/腮红）加深倍率
FACE_BLUR = float(os.environ.get('FACE_BLUR', 0.9))    # 掩膜高斯半径，用于边缘圆润
GROUPS = [('common', ('gamestart', 'pack', '共通')), ('hiy', ('妃愛', '妃爱')),
          ('kan', ('華乃', '华乃')), ('asu', ('あすみ', '明日美')),
          ('kin', ('錦', '锦')), ('other', ())]

def grp(s):
    for g, px in GROUPS:
        if g != 'other' and any(s.startswith(p) for p in px):
            return g
    return 'other'

def safename(s):
    return 's' + hashlib.md5(s.encode()).hexdigest()[:8]

used = {'g': set(), 'b': set(), 'c': set(), 's': set()}
for sc in SC.values():
    for op in sc['ops']:
        if op[0] == 'g' and op[2]:
            used['g'].add(op[2])
        elif op[0] == 'b' and op[1]:
            used['b'].add(op[1])
        elif op[0] == 'c' and op[1]:
            used['c'].add(op[1])
        elif op[0] == 's' and op[1]:
            used['s'].add(op[1])

CW, CCH = 212, 520
P7 = len('/common/')  # 剥离 '/common/' 前缀（mappedPath 会补回）
SDC = os.path.join(DST, 'sd')
os.makedirs(SDC, exist_ok=True)
os.makedirs(TMP, exist_ok=True)
body_c, face_c = {}, {}
body_img = {}
stat = {'b': 0, 'f': 0, 'bytes': 0}

def save_face(p, im, colors, levels):
    """表情层落盘：alpha 量化为 levels 级，再压到 min(256, colors*levels) 调色板"""
    a = np.array(im).astype(np.uint8)
    steps = [round(i * 255 / (levels - 1)) for i in range(levels)]
    ai = a[..., 3].astype(np.int16)[..., None]
    sp = np.array(steps, dtype=np.int16)[None, None, :]
    a[..., 3] = np.array(steps, dtype=np.uint8)[np.abs(ai - sp).argmin(axis=2)]
    q = Image.fromarray(a, 'RGBA').quantize(colors=min(256, colors * levels), method=Image.FASTOCTREE)
    q.save(p, 'PNG', optimize=True)
    stat['bytes'] += os.path.getsize(p)


def save_canvas(p, im, colors, alpha_levels, dither=True):
    """调色板抖动配方：RGB 用 Floyd-Steinberg 抖动量化（打破色阶断层），
    alpha 量化为 alpha_levels 级（边缘平滑），调色板总数 = 颜色数 x alpha级数 ≤ 256，
    保证抖动图案不会被最终重量化抹掉。透明区先填平均色，避免黑边/红边。"""
    im = im.convert('RGBA')
    alpha = im.getchannel('A')
    mask = alpha.point(lambda v: 255 if v > 0 else 0)
    rgb = im.convert('RGB')
    try:
        mean = tuple(int(c) for c in ImageStat.Stat(rgb, mask).mean)
    except Exception:
        mean = (128, 128, 128)
    filled = Image.composite(rgb, Image.new('RGB', im.size, mean), mask)
    dmode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    p_img = filled.quantize(colors=colors, method=Image.MEDIANCUT, dither=dmode).convert('RGB')
    out = p_img.convert('RGBA')
    step = max(1, 255 // max(1, alpha_levels - 1))
    aq = alpha.point(lambda v: min(255, int(round(v / step)) * step))
    out.putalpha(aq)
    q = out.quantize(colors=min(256, max(2, colors * alpha_levels)), method=Image.FASTOCTREE)
    q.save(p, 'PNG', optimize=True)
    stat['bytes'] += os.path.getsize(p)

# ---------- 1. 身体 / 表情烘焙 ----------
face_files = {}  # hash -> tmp 路径
for sid in sorted(used['g']):
    m = CH.get(sid)
    if not m:
        continue
    bid, fid = m[0], m[1]
    if bid not in body_c:
        art = ART.get(bid)
        b = read_game_img(art['src']).convert('RGBA') if art else Image.open(os.path.join(SRC, 'cimg', 'b', bid + '.png')).convert('RGBA')
        b = b.resize((max(1, round(b.width * CCH / b.height)), CCH), Image.LANCZOS)
        c = Image.new('RGBA', (CW, CCH), (0, 0, 0, 0))
        c.alpha_composite(b, ((CW - b.width) // 2, 0))
        p = os.path.join(SDC, 'b_%s.png' % bid)
        body_img[bid] = c.copy()
        save_canvas(p, c, BODY_COLORS, BODY_ALPHA)
        body_c[bid] = '/common/sd/b_%s.png' % bid
        stat['b'] += 1
    if fid and sid not in face_c:
        # 差量烘焙（v27 口径）：合成到身体上只留差异像素，alpha 二值 -> 可装进 19.2MiB
        lay, kind, mh, changed = INK.delta_face(sid, do_boost=True, thr=DELTA_THR)
        h = hashlib.md5(lay.tobytes()).hexdigest()[:10]
        if h not in face_files:
            save_face(os.path.join(TMP, h + '.png'), lay, FACE_COLORS, FACE_ALPHA)
            face_files[h] = True
            stat['f'] += 1
        face_c[sid] = h

# ---------- 2. 表情文件筛选（台词行排序 + 角色配额） ----------
FACE_BUDGET = int(os.environ.get('FACE_BUDGET', 1340))
SHI_PCT = float(os.environ.get('SHI_PCT', 72))     # 诗樱目标覆盖率（%）
MIR_CUT = int(os.environ.get('MIR_CUT', 2))        # 老师(里) 名额除以这个数
TRIO_RATIO = (1, 1, 2)                              # 腾出名额给 华乃:妃爱:明日美

import collections
use = collections.Counter()
for _sc in SC.values():
    for _op in _sc['ops']:
        if _op[0] == 'g' and _op[2]:
            use[_op[2]] += 1

# 每个 hash 覆盖的台词行数（覆盖率口径）与所属角色
hash_lines = collections.Counter()
hash_code = {}
_code_acc = collections.defaultdict(lambda: collections.Counter())
_bid2code = {}
for _bid, _v in ART.items():
    _src = _v.get('src', '')
    if '/fg/' in _src:
        _p = _src.split('/'); _i = _p.index('fg')
        if _i + 1 < len(_p):
            _bid2code[_bid] = _p[_i + 1]
for _sc in SC.values():
    _cur = None
    for _op in _sc['ops']:
        if _op[0] == 'g':
            _cur = _op[2] if _op[2] else None
        elif _op[0] == 't' and _cur in face_c:
            hash_lines[face_c[_cur]] += 1
for sid, h in face_c.items():
    m = CH.get(sid)
    if not m:
        continue
    hash_code_ = _bid2code.get(m[0], '?')
    _code_acc[h][hash_code_] += use.get(sid, 0) or 1
for h, c in _code_acc.items():
    hash_code[h] = c.most_common(1)[0][0]

# 每个身体的默认表情（该身体下使用最多的 hash，强制保留 -> 任何立绘都有脸）
_body_hash_use = collections.defaultdict(lambda: collections.Counter())
for sid, h in face_c.items():
    m = CH.get(sid)
    if m:
        _body_hash_use[m[0]][h] += use.get(sid, 0) or 1
body_default = {bid: c.most_common(1)[0][0] for bid, c in _body_hash_use.items()}
forced = set(body_default.values())

by_char = collections.defaultdict(list)
for h, c in hash_code.items():
    by_char[c].append(h)
for c in by_char:
    by_char[c].sort(key=lambda h: -hash_lines[h])

# 基线：按台词行全局贪心（用于得到各角色当前张数）
base = set(forced)
for h in sorted(hash_lines, key=lambda x: -hash_lines[x]):
    if len(base) >= FACE_BUDGET:
        break
    base.add(h)
cnt = collections.Counter()
for h in base:
    cnt[hash_code[h]] += 1

# 台词行总数（按角色）
_tot = collections.Counter()
for _sc in SC.values():
    _cur = None
    for _op in _sc['ops']:
        if _op[0] == 'g':
            _cur = _op[2] if _op[2] else None
        elif _op[0] == 't' and _cur in face_c:
            m = CH.get(_cur)
            if m:
                _tot[_bid2code.get(m[0], '?')] += 1

target = dict(cnt)
# 诗樱：降到目标覆盖率所需张数
_acc = 0; _n = 0
for h in by_char.get('shi', []):
    if _acc >= _tot.get('shi', 0) * SHI_PCT / 100.0:
        break
    _acc += hash_lines[h]; _n += 1
if 'shi' in target:
    target['shi'] = max(1, _n)
# 老师(里)：名额砍半
if 'mir' in target:
    target['mir'] = max(1, cnt['mir'] // max(1, MIR_CUT))
# 腾出的名额按比例分给三位女主
_freed = sum(cnt[c] - target[c] for c in target)
if _freed > 0:
    _W = sum(TRIO_RATIO)
    for _c, _r in zip(['kan', 'hiy', 'asu'], TRIO_RATIO):
        target[_c] = target.get(_c, 0) + _freed * _r // _W

selected = set(forced)
for _c, _n2 in target.items():
    _k = 0
    for h in by_char.get(_c, []):
        if _k >= _n2:
            break
        if h in selected:
            _k += 1
            continue
        selected.add(h); _k += 1
# 超出预算则按台词行从低到高剔除（不动 forced）
if len(selected) > FACE_BUDGET:
    for h in sorted([x for x in selected if x not in forced], key=lambda h: hash_lines[h]):
        if len(selected) <= FACE_BUDGET:
            break
        selected.discard(h)
# 未满则按台词行补足
for h in sorted(hash_lines, key=lambda x: -hash_lines[x]):
    if len(selected) >= FACE_BUDGET:
        break
    selected.add(h)

covered = sum(hash_lines[h] for h in selected)
_total_lines = sum(hash_lines.values())
print('表情: 唯一 %d 张, 保留 %d 张, 台词行覆盖 %.1f%%（诗樱 %d 张 / 里 %d 张）' % (
    len(hash_lines), len(selected), 100.0 * covered / max(1, _total_lines),
    target.get('shi', 0), target.get('mir', 0)), flush=True)
for _c in ['kan', 'hiy', 'asu', 'shi', 'mir']:
    _nn = sum(1 for h in selected if hash_code[h] == _c)
    _ln = sum(hash_lines[h] for h in selected if hash_code[h] == _c)
    print('   %s: %d 张, 覆盖 %.1f%%' % (_c, _nn, 100.0 * _ln / max(1, _tot.get(_c, 1))), flush=True)

for h in selected:
    shutil.copy2(os.path.join(TMP, h + '.png'), os.path.join(SDC, 'f_%s.png' % h))

face_path = {h: '/common/sd/f_%s.png' % h for h in selected}

# ---------- 3. 剧本 ----------
order = sorted(SC.keys(), key=lambda s: (grp(s) != 'common', s))
idmap = {x: safename(x) for x in order}
groups = {g: [] for g, _ in GROUPS}
for x in order:
    groups[grp(x)].append({'id': idmap[x], 'path': idmap[x] + '.ks.txt'})

lbl = [0]
scnB = [0]
allm = {}
for sid in order:
    ops, chars = [], []
    for op in SC[sid]['ops']:
        c = op[0]
        if c == 'b':
            ops.append([2, op[1]])
        elif c == 'c':
            ops.append([5, 'ev' + op[1][1:]])
        elif c == 's':
            ops.append([5, 'sd_' + op[1]])
        elif c == 'd':
            ops.append([5, ''])
        elif c == 'g':
            # sabb 原始 4 字段结构 [角色, '', '', '']
            chars = [[op[2], '', '', '']] if CH.get(op[2]) else chars
        elif c == 'h':
            ops.append([1, op[1]])
        elif c == 't':
            n = [3, op[1], op[2]]
            if chars:
                n.append(chars)
            ops.append(n)
        elif c == 'o':
            ch = []
            for o in op[1]:
                if not o[0]:
                    continue
                lbl[0] += 1
                L = '*L%d' % lbl[0]
                ch.append([o[0], L, ''])
                if o[1]:
                    ops.append([0, L])
                    ops.append([8, idmap.get(o[1], '')])
            if ch:
                ops.append([4, ch])
        elif c == 'i':
            ops.append([7, op[1], idmap.get(op[2], '')])
        elif c == 'j':
            ops.append([8, idmap.get(op[1], '')])
        elif c == 'f':
            ops.append([9, op[1]])
    t = json.dumps(ops, ensure_ascii=False, separators=(',', ':'))
    if any(ord(ch) > 0xFFFF for ch in t):
        # 4 字节 UTF-8 字符转义为 \uXXXX 代理对（设备文件解码器兼容），文本内容不变
        out = []
        for ch in t:
            cp = ord(ch)
            if cp > 0xFFFF:
                cp -= 0x10000
                out.append('\\u%04x\\u%04x' % (0xD800 + (cp >> 10), 0xDC00 + (cp & 0x3FF)))
            else:
                out.append(ch)
        t = ''.join(out)
    open(os.path.join(DST, 'scn', idmap[sid] + '.ks.txt'), 'w', encoding='utf-8').write(t)
    scnB[0] += len(t.encode('utf-8'))
    # 按场景清单（sabb 原生加载模式，运行时只解析当前场景映射，防过载）
    cm, fm = {}, {}
    for op in SC[sid]['ops']:
        if op[0] == 'g':
            m = CH.get(op[2])
            if not m:
                continue
            k = op[2] + '||'
            if m[0] in body_c:
                cm[k] = body_c[m[0]][P7:]
            if m[1] and face_c.get(op[2]):
                h2 = face_c[op[2]]
                fm[k] = face_path.get(h2) or face_path.get(body_default.get(m[0])) or ''
                if not fm[k]:
                    fm.pop(k)
    allm[idmap[sid]] = {'characterMap': cm, 'characterFaceMap': fm,
                        'resourceManifest': {'paths': {'bg': {}, 'ev': {}, 'sd': {}}}}

# ---------- 4b. bg/ev/sd 拷贝 + 场景索引/清单落盘 ----------
def _rejpeg(src, dst, q):
    im = Image.open(src).convert('RGB')
    im.save(dst, 'JPEG', quality=q, optimize=True, subsampling=2)

for aid in used['b']:
    s2 = os.path.join(SRC, 'bcgi', aid + '.jpg')
    if os.path.exists(s2):
        _rejpeg(s2, os.path.join(DST, 'bg', aid + '.jpg'), 1)
for aid in used['c']:
    s2 = os.path.join(SRC, 'evig', aid + '.jpg')
    if os.path.exists(s2):
        shutil.copy2(s2, os.path.join(DST, 'ev', 'ev%s.jpg' % aid[1:]))
for aid in used['s']:
    s2 = os.path.join(SRC, 'bcgi', aid + '.jpg')
    if os.path.exists(s2):
        _rejpeg(s2, os.path.join(DST, 'sd', 'sd_%s.jpg' % aid), 1)

open(os.path.join(DST, 'runtime', 'scene-index.txt'), 'w', encoding='utf-8').write(
    json.dumps({g: groups[g] for g, _ in GROUPS if groups[g]}, ensure_ascii=False, separators=(',', ':')))
madir = os.path.join(DST, 'runtime', 'scene-assets')
os.makedirs(madir, exist_ok=True)
for sid2, man in allm.items():
    open(os.path.join(madir, sid2 + '.txt'), 'w', encoding='utf-8').write(
        json.dumps(man, ensure_ascii=False, separators=(',', ':')))

# ---------- 5. 清空 detail.ux 的 FACECSS 段（表情改回 <image src>） ----------
ux = os.path.join(ROOT, 'app', 'src', 'pages', 'detail', 'detail.ux')
src_ux = open(ux, encoding='utf-8').read()
START, END = '/*FACECSS-START*/', '/*FACECSS-END*/'
if START in src_ux:
    i0, i1 = src_ux.index(START) + len(START), src_ux.index(END)
    open(ux, 'w', encoding='utf-8').write(src_ux[:i0] + '\n' + src_ux[i1:])

print('立绘 body %d / 表情文件 %d, %.1fMB' % (stat['b'], len(selected), stat['bytes'] / 1048576))
print('scn %d 个场景, %.1fMB' % (len(order), scnB[0] / 1048576))
print('bg %d, ev %d, sd图 %d' % (
    len(os.listdir(os.path.join(DST, 'bg'))),
    len(os.listdir(os.path.join(DST, 'ev'))),
    len([f for f in os.listdir(os.path.join(DST, 'sd')) if f.startswith('sd_')])))
