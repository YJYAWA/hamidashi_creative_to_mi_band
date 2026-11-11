"""对比两种表情烘焙口径在 BUDGET=1340 + 诗樱72% + 里砍半 + 1:1:2 下的分角色覆盖率

口径 A（差量烘焙，v26/v27 用的）：表情贴到身体上做 alpha 合成后的整幅像素做哈希
  -> 同一表情挂在不同身体上，边缘半透明像素混了身体色 -> 哈希不同 -> 不可去重
口径 B（墨色层，v29+ 用的）：表情按真实偏移贴到透明画布，颜色为原画墨色
  -> 与身体无关 -> 可跨身体去重

用法: python tools/sim_bake_compare.py [budget]
"""
import sys, os, json, hashlib, collections, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inkface as IF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
CH, ART = IF.CH, IF.ART
SC = json.load(open('build/scenes.json', encoding='utf-8'))
BUDGET = int(sys.argv[1]) if len(sys.argv) > 1 else 1340
t0 = time.time()

use = collections.Counter()
for sc in SC.values():
    for op in sc['ops']:
        if op[0] == 'g' and op[2]:
            use[op[2]] += 1

sids = [s for s in CH if CH[s][1]]
bid2code = {}
for bid, v in ART.items():
    s = v.get('src', '')
    if '/fg/' in s:
        p = s.split('/')
        i = p.index('fg')
        if i + 1 < len(p):
            bid2code[bid] = p[i + 1]
NAME = {'kan': '华乃', 'hiy': '妃爱', 'asu': '明日美', 'shi': '诗樱',
        'mir': '老师(里)', 'ame': '龙闲', 'hir': '广梦', 'rir': '莉々子', 'yuk': '其他'}
ORDER = ['kan', 'hiy', 'asu', 'shi', 'mir', 'ame', 'hir', 'rir', 'yuk']

# ---------- 两种口径的 hash ----------
ink_h, delta_h = {}, {}
for i, sid in enumerate(sids):
    m = CH[sid]
    lay = IF.ink_layer(sid)
    ink_h[sid] = hashlib.md5(lay.tobytes()).hexdigest()[:10]
    comp = IF.body_canvas(m[0]).copy()
    comp.alpha_composite(lay)
    delta_h[sid] = hashlib.md5(comp.tobytes()).hexdigest()[:10]
    if i % 500 == 0:
        print('  烘焙 %d/%d %.0fs' % (i, len(sids), time.time() - t0), flush=True)


def report(h_of, tag):
    hash_lines = collections.Counter()
    _acc = collections.defaultdict(lambda: collections.Counter())
    for sc in SC.values():
        cur = None
        for op in sc['ops']:
            if op[0] == 'g':
                cur = op[2] if op[2] else None
            elif op[0] == 't' and cur in CH and CH[cur][1]:
                hash_lines[h_of[cur]] += 1
    for sid, h in h_of.items():
        _acc[h][bid2code.get(CH[sid][0], '?')] += use.get(sid, 0) or 1
    hash_code = {h: c.most_common(1)[0][0] for h, c in _acc.items()}

    tot = collections.Counter()
    for sc in SC.values():
        cur = None
        for op in sc['ops']:
            if op[0] == 'g':
                cur = op[2] if op[2] else None
            elif op[0] == 't' and cur in CH and CH[cur][1]:
                tot[bid2code.get(CH[cur][0], '?')] += 1

    by_body = collections.defaultdict(lambda: collections.Counter())
    for sid, h in h_of.items():
        by_body[CH[sid][0]][h] += use.get(sid, 0)
    forced = set(c.most_common(1)[0][0] for c in by_body.values())

    by_char = collections.defaultdict(list)
    for h, c in hash_code.items():
        by_char[c].append(h)
    for c in by_char:
        by_char[c].sort(key=lambda h: -hash_lines[h])

    # policy: 全局行贪心 -> 诗樱72% -> 里砍半 -> 腾出按 1:1:2 给三女主
    base = set(forced)
    for h in sorted(hash_lines, key=lambda x: -hash_lines[x]):
        if len(base) >= BUDGET:
            break
        base.add(h)
    cnt = collections.Counter()
    for h in base:
        cnt[hash_code[h]] += 1
    target = dict(cnt)
    acc = n = 0
    for h in by_char.get('shi', []):
        if acc >= tot.get('shi', 0) * 0.72:
            break
        acc += hash_lines[h]
        n += 1
    if 'shi' in target:
        target['shi'] = max(1, n)
    if 'mir' in target:
        target['mir'] = max(1, cnt['mir'] // 2)
    freed = sum(cnt[c] - target[c] for c in target)
    if freed > 0:
        for c, r in zip(['kan', 'hiy', 'asu'], (1, 1, 2)):
            target[c] = target.get(c, 0) + freed * r // 4

    sel = set(forced)
    for c in ORDER:
        k = 0
        for h in by_char.get(c, []):
            if k >= target.get(c, 0):
                break
            if h in sel:
                k += 1
                continue
            sel.add(h)
            k += 1
    if len(sel) > BUDGET:
        for h in sorted([x for x in sel if x not in forced], key=lambda h: hash_lines[h]):
            if len(sel) <= BUDGET:
                break
            sel.discard(h)
    for h in sorted(hash_lines, key=lambda x: -hash_lines[x]):
        if len(sel) >= BUDGET:
            break
        sel.add(h)

    cov = collections.Counter()
    for sc in SC.values():
        cur = None
        for op in sc['ops']:
            if op[0] == 'g':
                cur = op[2] if op[2] else None
            elif op[0] == 't' and cur in CH and CH[cur][1]:
                if h_of[cur] in sel:
                    cov[bid2code.get(CH[cur][0], '?')] += 1
    total_pool = sum(tot.values())
    overall = 100.0 * sum(cov.values()) / max(1, total_pool)
    print('\n== %s ==' % tag)
    print('唯一表情 %d 张 / 保留 %d 张 / 整体覆盖 %.1f%%' % (len(hash_lines), len(sel), overall))
    for c in ORDER:
        if tot.get(c, 0) < 50:
            continue
        k = sum(1 for h in sel if hash_code[h] == c)
        print('   %-8s %3d 张  %.1f%%  (%d/%d 行)' % (
            NAME.get(c, c), k, 100.0 * cov.get(c, 0) / max(1, tot[c]), cov.get(c, 0), tot[c]))
    return overall


a = report(delta_h, '口径A 差量烘焙（v26/v27）')
b = report(ink_h, '口径B 墨色层（v29/v31）')
print('\n整体差: %.1f 个百分点' % (b - a))
print('用时 %.0fs' % (time.time() - t0))
