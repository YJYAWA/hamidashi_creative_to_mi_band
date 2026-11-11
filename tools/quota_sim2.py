"""配额方案对比：诗樱 72% / 老师(里) 对半砍 / 两者都砍，腾出名额一律按 1:1:2 给 华乃:妃爱:明日美

用法: python tools/quota_sim2.py [总名额]
"""
import sys, os, json, hashlib, collections, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inkface as IF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CH, ART = IF.CH, IF.ART
SC = json.load(open(os.path.join(ROOT, 'build/scenes.json'), encoding='utf-8'))
BUDGET = int(sys.argv[1]) if len(sys.argv) > 1 else 1340
t0 = time.time()

use = collections.Counter()
for sc in SC.values():
    for op in sc['ops']:
        if op[0] == 'g' and op[2]:
            use[op[2]] += 1
sids = [s for s in CH if CH[s][1]]
h_of = {}
for i, sid in enumerate(sids):
    lay, k, h, ch = IF.face(sid)
    h_of[sid] = hashlib.md5(lay.tobytes()).hexdigest()[:10]
    if i % 1000 == 0:
        print('  哈希 %d/%d %.0fs' % (i, len(sids), time.time() - t0), flush=True)

bid2code = {}
for bid, v in ART.items():
    s = v.get('src', '')
    if '/fg/' in s:
        p = s.split('/'); i = p.index('fg')
        if i + 1 < len(p):
            bid2code[bid] = p[i + 1]
NAME = {'kan': '华乃', 'hiy': '妃爱', 'asu': '明日美', 'shi': '诗樱',
        'mir': '老师(里)', 'ame': '龙闲', 'hir': '广梦', 'rir': '莉々子', 'yuk': '未知角色'}
ORDER = ['kan', 'hiy', 'asu', 'shi', 'mir', 'ame', 'hir', 'rir', 'yuk']

hash_lines = collections.Counter()
hash_code = {}
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
for h, c in _acc.items():
    hash_code[h] = c.most_common(1)[0][0]

tot = collections.Counter()
for sc in SC.values():
    cur = None
    for op in sc['ops']:
        if op[0] == 'g':
            cur = op[2] if op[2] else None
        elif op[0] == 't' and cur in CH and CH[cur][1]:
            tot[bid2code.get(CH[cur][0], '?')] += 1

body_default = {}
by_body = collections.defaultdict(lambda: collections.Counter())
for sid, h in h_of.items():
    by_body[CH[sid][0]][h] += use.get(sid, 0)
for b, c in by_body.items():
    body_default[b] = c.most_common(1)[0][0]
forced = set(body_default.values())

by_char = collections.defaultdict(list)
for h, c in hash_code.items():
    by_char[c].append(h)
for c in by_char:
    by_char[c].sort(key=lambda h: -hash_lines[h])


def evaluate(sel):
    cov = collections.Counter()
    for sc in SC.values():
        cur = None
        for op in sc['ops']:
            if op[0] == 'g':
                cur = op[2] if op[2] else None
            elif op[0] == 't' and cur in CH and CH[cur][1]:
                if h_of[cur] in sel:
                    cov[bid2code.get(CH[cur][0], '?')] += 1
    return cov


def policy(shi_pct=None, mir_cut=None, ratio=(1, 1, 2)):
    """先取"按台词行全局贪心"作为基准分配，再按配额调整"""
    base = set(forced)
    for h in sorted(hash_lines, key=lambda x: -hash_lines[x]):
        if len(base) >= BUDGET:
            break
        base.add(h)
    cnt = collections.Counter()
    for h in base:
        cnt[hash_code[h]] += 1
    target = dict(cnt)
    if shi_pct is not None:
        acc = 0; n = 0
        for h in by_char['shi']:
            if acc >= tot['shi'] * shi_pct / 100.0:
                break
            acc += hash_lines[h]; n += 1
        target['shi'] = max(1, n)
    if mir_cut is not None:
        target['mir'] = max(1, cnt['mir'] // mir_cut)
    trio = ['kan', 'hiy', 'asu']
    freed = sum(cnt[c] - target[c] for c in target)
    if freed > 0:
        W = sum(ratio)
        for c, r in zip(trio, ratio):
            target[c] += freed * r // W
    # 组装：每个角色取 target 张（按台词行排序），forced 必留
    sel = set(forced)
    for c in ORDER:
        n = 0
        for h in by_char.get(c, []):
            if n >= target[c]:
                break
            if h in sel:
                n += 1
                continue
            sel.add(h); n += 1
    if len(sel) > BUDGET:
        for h in sorted([x for x in sel if x not in forced], key=lambda h: hash_lines[h]):
            if len(sel) <= BUDGET:
                break
            sel.discard(h)
    for h in sorted(hash_lines, key=lambda x: -hash_lines[x]):
        if len(sel) >= BUDGET:
            break
        sel.add(h)
    return sel


cases = [('基线(全局行贪心)', policy()),
         ('诗樱50% + 里对半', policy(shi_pct=50, mir_cut=2)),
         ('诗樱40% + 里对半', policy(shi_pct=40, mir_cut=2)),
         ('诗樱30% + 里对半', policy(shi_pct=30, mir_cut=2)),
         ('诗樱20% + 里对半', policy(shi_pct=20, mir_cut=2))]
print()
for label, sel in cases:
    cov = evaluate(sel)
    T = sum(tot.values()); C = sum(cov.values())
    print('== %s：%d 张, 总覆盖 %.1f%%' % (label, len(sel), 100.0 * C / T))
    line = []
    for c in ORDER:
        if c in tot:
            line.append('%s %.0f%%(%d)' % (NAME[c], 100.0 * cov.get(c, 0) / tot[c],
                                           sum(1 for h in sel if hash_code[h] == c)))
    print('   ' + ' | '.join(line))
print('DONE %.0fs' % (time.time() - t0))
