"""按角色统计 v29（1340 名额）覆盖率，并给出"补满某角色"的代价与收益

用法: python tools/ink_char_stats.py [budget]
输出: work/ink_char_stats.json + 控制台报表
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
    if i % 800 == 0:
        print('  哈希 %d/%d %.0fs' % (i, len(sids), time.time() - t0), flush=True)

bid2code = {}
for bid, v in ART.items():
    s = v.get('src', '')
    if '/fg/' in s:
        p = s.split('/'); i = p.index('fg')
        if i + 1 < len(p):
            bid2code[bid] = p[i + 1]
NAME = {'hiy': '妃爱', 'kan': '华乃', 'asu': '明日美', 'shi': '诗樱',
        'mir': '里', 'ame': '龙闲', 'hir': '广梦', 'rir': '莉々子', 'yuk': '老师'}

# 选择（与构建脚本同算法）
body_default = {}
by_body = collections.defaultdict(lambda: collections.Counter())
for sid, h in h_of.items():
    by_body[CH[sid][0]][h] += use.get(sid, 0)
for b, c in by_body.items():
    body_default[b] = c.most_common(1)[0][0]
hash_use = collections.Counter()
for sid, h in h_of.items():
    hash_use[h] += use.get(sid, 0)
sel = set(body_default.values())
for h, _ in hash_use.most_common():
    if len(sel) >= BUDGET:
        break
    sel.add(h)

# 每个 hash 归属哪个角色（取使用最多的那个 sid 的角色）
hash_code = {}
for sid, h in h_of.items():
    c = bid2code.get(CH[sid][0], '?')
    if h not in hash_code:
        hash_code[h] = collections.Counter()
    hash_code[h][c] += use.get(sid, 0)
hash_code = {h: c.most_common(1)[0][0] for h, c in hash_code.items()}

# 台词行覆盖：按角色
stat = collections.defaultdict(lambda: {'lines': 0, 'covered': 0})
for sc in SC.values():
    cur = None
    for op in sc['ops']:
        if op[0] == 'g':
            cur = op[2] if op[2] else None
        elif op[0] == 't' and cur in CH and CH[cur][1]:
            code = bid2code.get(CH[cur][0], '?')
            stat[code]['lines'] += 1
            if h_of[cur] in sel:
                stat[code]['covered'] += 1

# 每个 hash 覆盖的台词行数（含该 hash 的所有 sprite 的台词行）
hash_lines = collections.Counter()
for sc in SC.values():
    cur = None
    for op in sc['ops']:
        if op[0] == 'g':
            cur = op[2] if op[2] else None
        elif op[0] == 't' and cur in CH and CH[cur][1]:
            hash_lines[h_of[cur]] += 1

rows = []
for code, d in stat.items():
    mine = [h for h, c in hash_code.items() if c == code]
    missing = [h for h in mine if h not in sel]
    gain = sum(hash_lines[h] for h in missing)
    rows.append({
        'code': code, 'name': NAME.get(code, code),
        'lines': d['lines'], 'covered': d['covered'],
        'rate': 100.0 * d['covered'] / max(1, d['lines']),
        'faces_total': len(mine), 'faces_have': len(mine) - len(missing),
        'faces_missing': len(missing),
        'lines_gain': int(gain),
        'per_face': (gain / len(missing)) if missing else 0.0,
    })
rows.sort(key=lambda r: -r['lines'])

print()
print('%-6s %7s %7s %8s | %6s %6s %6s | %8s %8s' % (
    '角色', '台词行', '已覆盖', '覆盖率', '表情总', '已有', '缺', '补满收益', '每张收益'))
for r in rows:
    print('%-6s %7d %7d %7.1f%% | %6d %6d %6d | %8d %8.2f' % (
        r['name'], r['lines'], r['covered'], r['rate'],
        r['faces_total'], r['faces_have'], r['faces_missing'],
        r['lines_gain'], r['per_face']))
T = sum(r['lines'] for r in rows)
C = sum(r['covered'] for r in rows)
print('合计 %d 行, 覆盖 %d = %.1f%%' % (T, C, 100.0 * C / T))
print('若全部补满：+%d 张表情, +%d 行' % (
    sum(r['faces_missing'] for r in rows), sum(r['lines_gain'] for r in rows)))
json.dump({'budget': BUDGET, 'rows': rows}, open(os.path.join(ROOT, 'work/ink_char_stats.json'), 'w'),
          ensure_ascii=False, indent=1)
print('DONE %.0fs' % (time.time() - t0))
