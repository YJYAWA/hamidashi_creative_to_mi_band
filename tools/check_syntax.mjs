// 语法门禁：检查 app/src 下所有 JS 与 .ux 内 <script> 是否可解析
import fs from 'fs'
import path from 'path'
import { createRequire } from 'module'
const require = createRequire(import.meta.url)
const terser = require(path.resolve('app/node_modules/terser'))

function walk(dir, out = []) {
  for (const f of fs.readdirSync(dir)) {
    const p = path.join(dir, f)
    const st = fs.statSync(p)
    if (st.isDirectory()) walk(p, out)
    else out.push(p)
  }
  return out
}
const files = walk('app/src')
let bad = 0
for (const f of files) {
  let code = null
  if (f.endsWith('.js')) code = fs.readFileSync(f, 'utf8')
  else if (f.endsWith('.ux')) {
    const s = fs.readFileSync(f, 'utf8')
    const m = s.match(/<script>([\s\S]*?)<\/script>/)
    if (m) code = m[1]
  }
  if (!code) continue
  try { await terser.minify(code, { compress: false, mangle: false }) }
  catch (e) { bad++; console.log('❌ 语法错误:', f, '->', e.message) }
}
console.log(bad === 0 ? `✅ 全部 ${files.length} 个源文件语法正确` : `❌ ${bad} 个文件语法错误`)
process.exit(bad === 0 ? 0 : 1)
