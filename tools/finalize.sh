#!/bin/bash
# 收尾：压缩 build 里的页面 JS（swc，保留变量名）→ aiot resign 重签 → 输出 rpk
#
# 用法: bash tools/finalize.sh [输出文件名]
# 前提: 已在 app/ 下跑过 aiot build，且 app/build/ 存在
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT="${1:-hamidashi-band10.rpk}"

if [ ! -d app/build ]; then
  echo "app/build 不存在，请先在 app/ 下执行 aiot build"
  exit 1
fi

# 1) 压缩页面 JS（只去空白，不改名）
node tools/minswc.js app/build/pages/*/*.js

# 2) 重签打包
(cd app && ./node_modules/.bin/aiot resign) > build_resign.log 2>&1 || true

SRC="app/dist/com.madosoft.hamidashi.band10.debug.1.0.rpk"
if [ ! -f "$SRC" ]; then
  echo "resign 未产出 rpk，见 build_resign.log"
  exit 1
fi

cp "$SRC" "$OUT"

S=$(unzip -l "$OUT" | tail -1 | awk '{print $1}')
N=$(unzip -l "$OUT" | tail -1 | awk '{print $2}')
python - "$S" "$N" <<'PY'
import sys
s, n = int(sys.argv[1]), int(sys.argv[2])
print(f'解压 {s/1048576:.2f} MiB, {n} 条目')
PY
ls -l "$OUT" | awk '{printf "rpk 包 %.2f MiB (%.1f MB)\n", $5/1048576, $5/1000000}'
