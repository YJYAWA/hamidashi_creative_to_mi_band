#!/usr/bin/env node
/**
 * 用 rspack 自带的 swc 压缩快应用页面 JS。
 *
 * 为什么需要：aiot build 是 development 模式，不做 JS 压缩；全新编译时
 * pages 下的 JS 会是源码形态（本项目 detail.js 约 224 KB），而历史增量构建
 * 可能保留压缩产物（约 61 KB）。包体积会凭空多出 0.73 MiB。
 *
 * 关键：compress:false + mangle:false —— 只去空白，不改任何变量名。
 *
 * 用法: node tools/minswc.js app/build/pages/<page>/<name>.js
 */
const fs = require('fs')
const path = require('path')

const APP_NM = path.join(__dirname, '..', 'app', 'node_modules')
const binding = require(require.resolve('@rspack/binding', { paths: [APP_NM] }))

const files = process.argv.slice(2)
if (!files.length) {
  console.error('usage: node tools/minswc.js <js files...>')
  process.exit(1)
}

let before = 0
let after = 0
for (const f of files) {
  const code = fs.readFileSync(f, 'utf8')
  const res = binding.minifySync(code, JSON.stringify({ module: true, compress: false, mangle: false }))
  const out = typeof res === 'string' ? res : (res && res.code) || ''
  if (!out) {
    console.error('minify returned empty:', f)
    process.exit(1)
  }
  fs.writeFileSync(f, out)
  before += Buffer.byteLength(code)
  after += Buffer.byteLength(out)
  console.log(path.basename(f), Buffer.byteLength(code), '->', Buffer.byteLength(out))
}
console.log('TOTAL', before, '->', after,
  '节省', ((before - after) / 1048576).toFixed(2), 'MiB')
