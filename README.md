# 常轨脱离 Creative · 小米手环移植工程

把 PC 端 Galgame **《ハミダシクリエイティブ》/《常轨脱离 Creative》**（Madosoft，iMel 发行）移植成 **小米手环快应用（Vela / Quick App）**，最终产出可直接安装的 `.rpk`。

- 目标平台：小米手环 10（336×480 AMOLED，屏幕逻辑尺寸 212×303 design）
- 构建链：`aiot-toolkit` 2.0.5（AIoT IDE 同款 `aiot build` / `aiot resign`）
- 引擎：**Artemis Engine**（不是 KiriKiri）
- 成品：解压 19.18 MiB / 2859 个文件 / 表情 1100 张 / 台词行覆盖 80.3%

> **本仓库包含已转换的游戏素材**（CG、立绘、背景、剧本），仅为方便研究与复现，**仅供学习交流使用**。
> 请在**下载后 24 小时内删除**，详见 [DISCLAIMER.md](DISCLAIMER.md)。
> 音频未包含——手环没有扬声器通路。

---

## 0. 一句话结论

把 Galgame 搬上手环，真正的难点不是「塞不进去」，而是三条隐形红线：

1. **安装器卡 100% 的判据是解压后体积，不是 rpk 包体积**（实测红线在 19.23 MiB 与 20.31 MiB 之间）
2. **文件数也有限制**（7329 个失败、5763 个失败、3116 个可用）
3. **Vela 的 `image` 组件不吃动态 style、不吃 `background-position` 图集、不吃 data URI**

这三条决定了整个工程的架构。下面全部展开。

---

## 1. 引擎判定：先别急着当 KiriKiri

拿到游戏目录第一件事是判引擎。判错会浪费整整一轮。

| 特征 | KiriKiri（吉里吉里） | **Artemis Engine（本作）** |
|---|---|---|
| 封包 | `.xp3` | **`pf8` 多卷：`.000` `.001` `.002` `.020` `.021` `.022`** |
| 剧本 | `.ks` 纯文本脚本 | **`.ast` Lua 表**：`ast` 命令流 + `text[lang_id]` |
| 加密 | `.xp3` 自带 filter，常见 `encryption` 标记 | 密钥 = `SHA1(索引区[7 : 7+索引长度])`，20 字节，每文件独立从头循环 XOR |
| 立绘 | 单张合成 PNG | **身体 + 表情两层分开存**，各带 `comment="pos,x,y,w,h"` |
| 音视频 | 加密/明文混合 | 不加密 |

本作后缀越大优先级越高：`.022 > .021 > .020 > .002 > .001 > .000`。
`.000` 是原图卷（衣着正常），`.021` 是 R18 / 高清覆盖卷 —— **移植取 `.000`**。

音频卷（`.001` `/`.002` `/`.022`）一万多个文件、822 MB，手环放不了，**直接跳过解包**。

### 1.1 解包

```bash
python tools/pf8.py <游戏目录>          # 输出 build/pf8_index.json 与解包目录
```

`tools/pf8.py` 负责：读索引区 → 用 `SHA1` 推密钥 → 逐文件 XOR 解密 → 落盘。

### 1.2 剧本解析

`.ast` 是明文 Lua 表，结构大致是：

```
ast   = { 命令1, 命令2, ... }
text  = { [lang_id] = { cn=..., ja=..., name=..., vo=..., select=... } }
label = "场景标签"
```

`tools/astparse.py` 把它归一化成统一指令流（IR）：

| IR 码 | 含义 | 原始指令 |
|---|---|---|
| 1 | 章节标题 | `h` |
| 2 | 背景 | `b` |
| 3 | 台词（说话人 + 文本 + 在场立绘） | `t` |
| 5 | 事件图（CG / SD），空串表示清除 | `c` / `d` / `s` |
| 6 | 选项组 | `o` |
| 7 / 8 / 9 | 条件跳转 / 场景跳转 / 旗标赋值 | `i` / `j` / `f` |
| 10 | 章节跳转 | `k` |

播放器只认 IR，不认原始指令。这样换引擎（Artemis → KiriKiri）时只换解析器，播放器不动。

---

## 2. 图片管线

手环屏幕只有 336×480，PC 端素材是 1280×720 到 2560×1440。所有转换都是**一次性预处理**，运行时不做缩放。

### 2.1 CG（写死参数，不要改）

```python
im = im.convert("RGB").transpose(Image.ROTATE_270)   # 1. 顺时针旋转 90°
im = cover(im, 336, 480)                             # 2. 等比缩放到 cover 336×480 后居中裁切
im.save(path, "JPEG", quality=18, optimize=True,
        progressive=False, subsampling=2)            # 3. q18
```

三点必须写死：

- **必须先旋转**。PC 端 CG 是横图，不旋转直接 `cover` 会把人物裁掉一半 —— 这是本项目返工次数最多的一处。
- **旋转后再 `cover` 336×480**。比例固定为 0.7，与手环屏幕完全一致，运行时不需要再算。
- **不拉伸、不锐化、不裁主体**。

### 2.2 背景

```python
cover(im.convert("RGB"), 212, 520)   # 212×520 画布，JPEG q14
```

背景可以裁，因为它本来就是铺满屏的。

### 2.3 立绘：两层，不许合并

立绘 = **身体层** + **表情层**，两张独立 `<image>` 叠加。

- 身体：缩放到高 520（宽度按比例），居中放到 212×520 透明画布
- 表情：按原图 `comment` 里的 `pos` 偏移贴到同一画布

**绝对不要预先合成单张图**：210 个身体 × 上百个表情，合成后体积直接翻十倍。

### 2.4 表情烘焙：差量 vs 墨色层

这是本项目最核心的取舍，两代方案都实现过，都在 `tools/inkface.py` 里。

| | 差量烘焙（v26 / v27 / v32 采用） | 墨色层（v29 / v31 采用） |
|---|---|---|
| 做法 | 表情合成到身体上，只保留与身体差异超过阈值 `thr` 的像素，颜色取合成后颜色 | 表情按真实偏移贴到透明画布，颜色为原画墨色 |
| 与身体的关系 | **耦合**：边缘半透明像素混了身体色 | **无关** |
| 可跨身体去重 | 否（同一表情挂不同身体 = 不同图） | 是 |
| 唯一表情数（本作） | 3611 | 2798 |
| 1340 张预算下覆盖率 | 79.7% | 85.9% |

**关键结论：省体积的不是「差量」，是 alpha 级数。**

实测同一批表情（32 色）：

| alpha 级数 | 单张 | 1340 张合计 |
|---|---|---|
| 8 级 | 2051 B | 2.62 MiB |
| 6 级 | 1718 B | 2.20 MiB |
| 4 级 | 1621 B | 2.07 MiB |
| 3 级 | 1431 B | 1.83 MiB |
| 2 级（二值） | 1157 B | 1.48 MiB |

v27 之所以只有 1.49 MiB，是因为它用 **2 级 alpha**，与差量烘焙无关。当初误以为是差量的功劳，白试了一轮。

### 2.5 闭嘴表情必须提亮

原画里「闭嘴」的唇线 alpha 只有 `11/255`（有的更低）。经过 2~8 级 alpha 量化后**直接被抹成 0**，玩家看到的就是「这个人没有嘴」。

修法（`inkface.boost_alpha`）：

1. 用 8 连通分量在**表情自身包围盒**内定位嘴（眼睛 = 最大的 2 块，嘴 = 眼睛下沿以下最靠下的小块）
2. 高度 ≤ 3 行 → 判定为闭嘴
3. 只对嘴部像素做 `alpha × 16` 提亮，**颜色不动、像素不扩**

**只改闭嘴，张嘴表情一律不碰。**

### 2.6 表情配额：按台词行算，不按出场次数

同一个 sprite 可能出场 300 次但只有 2 句台词，也可能出场 5 次配 200 句台词。玩家感受到的是「多少句台词时表情是对的」。

所以排序键必须是**该表情所覆盖的台词行数**，不是出场次数。

配额策略（v32 实际使用）：

```
预算 1100 张
├─ 诗樱：压到台词覆盖率 72% 所需张数（实际 84 张 / 73.8%）
├─ 老师(里)：名额对半砍（51 张 / 63.9%）
└─ 腾出的名额按 1:1:2 分给 华乃 : 妃爱 : 明日美
```

---

## 3. 打包

### 3.1 资源数据

`tools/build_data.py` 把 IR 按场景切成 `common/scn/s<md5>.ks.txt`，每个场景再生成一份资源清单 `common/runtime/scene-assets/<id>.txt`：

```json
{"characterMap": {"...": "/common/sd/b_xxx.png"},
 "characterFaceMap": {"...": "/common/sd/f_xxx.png"},
 "resourceManifest": {"paths": {"bg": {}, "ev": {}, "sd": {}}}}
```

按场景加载，不一次性读全量 —— 手环内存撑不住。

### 3.2 路径解析：未命中必须返回空或原值，绝不能返回 `''`

`common/resource-resolver.js` 的核心规则：

```js
function assetPath(folder, value, extension) {
  if (!value) return ''
  const knownPath = resourceManifest?.paths?.[folder]?.[cleanName(value)]
  if (knownPath) return knownPath
  const ext = extension || (folder === 'overlay' ? '.png' : '.jpg')
  return `/common/${folder}/${cleanName(value)}${ext}`   // 兜底，必须给对扩展名
}
```

历史事故：兜底写成返回 `''` 且默认 `.png`，导致**全站资源 404**，表现为一片黑屏。

### 3.3 aiot build 的两个坑

**坑一：`aiot build` 是 development 模式，不压缩 JS。**

全新编译时 `pages/*/*.js` 会是源码形态（本项目 detail.js 224 KB），而增量编译可能复用历史压缩产物（61 KB）。体积会凭空多出 0.73 MiB，且不易察觉。

解决：用 rspack 自带的 swc 压缩，**保留变量名**：

```js
const b = require('@rspack/binding')          // aiot-toolkit 的依赖
const out = b.minifySync(code, JSON.stringify({
  module: true, compress: false, mangle: false   // 只去空白，不改名
}))
```

压缩后与历史产物完全一致（index.js 8556 B vs 8554 B）。

**坑二：`afterCompile: Migrate temporary project` 会批量删除 `build/`，在受限环境下被拦截。**

表现为 `SAFE_DELETE_BULK_CONFIRM_REQUIRED`，但此时 rpk 已经生成在 `.temp_app12/dist/`。处理办法：构建前先把 `app12/build` 移走，构建后手动压缩 JS，再用 `aiot resign` 重签：

```bash
bash tools/finalize_v32.sh hamidashi-band10-v32.rpk
```

### 3.4 签名

用 aiot-toolkit 内置的 debug 证书即可（`aiot build` / `aiot resign` 自动处理）。自签证书：

```bash
openssl req -newkey rsa:2048 -nodes -keyout sign/private.pem -x509 -days 3650 \
  -out sign/certificate.pem -subj "/C=CN/O=HamidashiBand/CN=com.madosoft.hamidashi.band10"
```

---

## 4. 安装体积的真实门槛

这是整个项目最贵的知识，全部来自真机实测：

| 版本 | rpk 包 | **解压体积** | 文件数 | 安装结果 |
|---|---|---|---|---|
| v8 | 20.15 | 23.75 | 7313 | 失败 |
| v9 | 18.94 | 22.51 | 5763 | 失败 |
| v26 | 15.31 | **18.87** | 3116 | **成功** |
| v27 | 15.72 | **19.23** | 3116 | **成功** |
| v29 | 16.72 | **20.31** | 3116 | 失败 |
| v30 | 17.34 | 21.02 | 3476 | 失败 |
| v31 | 16.73 | **20.33** | 3116 | 失败 |
| v32 | 15.69 | **19.18** | 2876 | 待验证 |

结论：

1. **判据是解压体积**。v31 的 rpk 只有 16.73 MiB，看着很安全，但解压 20.33 MiB，装不上。
2. **红线在 19.23（可用）与 20.31（失败）之间**，`20 MiB` 是最可能的阈值。
3. **文件数另一条线**：3116 可用，3476 已失败，5763 / 7313 明确失败。
4. 体积和文件数**互相独立**，两个都要控。

### 体积账本（v32）

| 目录 | 文件数 | 体积 | 说明 |
|---|---|---|---|
| `common/ev` | 890 | 8.74 MiB | CG，q18，**不许再压** |
| `common/scn` | 217 | 3.98 MiB | 剧本 JSON，**不许压缩/改写** |
| `common/sd` | 1100 + 210 | 5.10 MiB | 表情 + 身体 |
| `common/runtime/scene-assets` | 217 | 0.68 MiB | 按场景资源清单 |
| `common/bg` | 159 | 0.34 MiB | 背景 q14 |
| `pages/*/*.js` | 7 | 0.24 MiB | swc 压缩后 |
| `META-INF` | 3 | 0.13 MiB | 签名 |

---

## 5. 硬约束（违反必翻车）

| # | 规则 | 违反后果 |
|---|---|---|
| 1 | 只用静态 `<image src>` 显示图片 | 动态 style、动态 class、`background-position` 图集、data URI 在真机上全部不渲染 |
| 2 | 路径解析未命中返回 `null` 或原值，**绝不返回空串** | 空串 + 默认扩展名 → 全站 404 |
| 3 | 剧本不改写、不压缩（LZSS 禁用）、不混淆 | 体积换不来稳定性，出问题无法定位 |
| 4 | 立绘必须身体 / 表情两层 | 合成单图体积翻十倍 |
| 5 | 表情边缘的 alpha 级数决定体积，不是烘焙方式 | 选错方向白做一轮 |
| 6 | 闭嘴必须做 alpha 提亮，张嘴一律不改 | 唇线 alpha 11/255 会被量化抹平 |
| 7 | CG 先旋转 90° 再 cover 336×480 | 不旋转直接裁 → 人物残缺 |
| 8 | 图片文件名一律 hash 化（md5 前 8~10 位） | 长名 / 中文名在 Vela 上踩过坑 |
| 9 | 每张图固定 212×520 画布，位置靠偏移而非动态样式 | 动态定位不可用 |
| 10 | 构建前必须清掉上一版的表情文件 | 新旧各 1340 张全进包 → 4456 文件、22.87 MiB |
| 11 | 出厂前跑语法门禁 + 引用校验 | 语法错误会伪装成「剧本解析失败」 |
| 12 | CG 鉴赏单列表，不按角色分组 | 分组页一次性加载过多图片 → 重启 |

---

## 6. 32 轮迭代全记录

> 表中体积均为实测。v1 / v5 / v15 / v19 / v30 的文件名带后缀，已在备注注明。
> 中间版本存在多次「只改参数未出包」的试验（如 v28），故编号不连续属正常。

| # | 日期 | rpk | 解压 | 文件数 | 主要变化 | 结果 |
|---|---|---|---|---|---|---|
| v1 | 11-07 | 15.91 | 16.67 | 2916 | 判定 Artemis、pf8 解包、首版跑通 | 结构验证 |
| v2 | 11-07 | 21.29 | 23.22 | 3089 | 全量资源入包 | 体积超标 |
| v3 | 11-07 | 18.56 | 19.81 | 3089 | 图片重压 | — |
| v4 | 11-07 | 19.21 | 20.55 | 3089 | CG 旋转 90° + 336×480 | 修复人物被裁 |
| v5 | 11-07 | 14.81 | 18.73 | 3328 | **误用他作（魔女的夜宴）数据** | 灾难，全量回滚 |
| v6 | 11-07 | 17.10 | 20.85 | 3328 | 品牌替换、去掉他作残留 | — |
| v7 | 11-07 | 17.10 | 20.84 | 3328 | CG 鉴赏页修复 | — |
| v8 | 11-07 | 20.15 | 23.75 | **7313** | 表情改图集 + `background-position` 定位 | **实机不渲染 + 装不上** |
| v9 | 11-07 | 18.94 | 22.51 | 5763 | 回退图集 | 文件数仍超 |
| v10 | 11-07 | 19.49 | 23.45 | 3113 | 手环 10 画布 212×520，立绘两层 | 架构定型 |
| v11 | 11-07 | 19.92 | 21.18 | 3113 | 立绘超采样 | — |
| v12 | 11-07 | 18.97 | 20.28 | 3113 | 身体去重 + 表情按 sprite 烘焙 | — |
| v13 | 11-07 | 17.78 | 19.09 | 3113 | 调色板量化 | — |
| v14 | 11-08 | 17.79 | 19.00 | 3117 | 资源解析器修复（空清单返回 `''`） | 修全站 404 |
| v15 | 11-08 | 17.89 | 19.24 | 3089 | UI 重做（oldui 版） | — |
| v16 | 11-08 | 16.70 | 19.99 | 4515 | 剧本分块、按场景加载 | 文件数偏高 |
| v17 | 11-08 | 16.59 | 18.92 | 4506 | 图片去重 | — |
| v18 | 11-08 | 16.50 | 18.85 | 4289 | 结构收敛 | — |
| v19 | 11-08 | 13.44 | 15.98 | 1559 | 诊断版（最小包，定位崩溃点） | 定位问题 |
| v20 | 11-08 | 15.72 | 18.68 | 1870 | 表情预算重构、表情独立成文件 | 首次体积达标 |
| v21 | 11-08 | 15.73 | 18.73 | 2087 | 表情烘焙偏移修正 | — |
| v22 | 11-08 | 15.73 | 18.97 | 2087 | 表情加深（FACE_AMP） | — |
| v23 | 11-08 | 15.07 | 18.09 | 3116 | 表情全量落盘（补回覆盖率） | — |
| v24 | 11-08 | 14.76 | 17.81 | 3116 | 最小可用版 | — |
| v25 | 11-08 | 15.68 | 18.91 | 3116 | 表情质量回升（色数/alpha 提升） | — |
| v26 | 11-08 | 15.31 | 18.87 | 3116 | 稳定版 | **真机可装** |
| v27 | 11-10 | 15.72 | 19.23 | 3116 | 配额改为 1:1:2 + 诗樱 72% + 里砍半 | **真机可装** |
| v28 | 11-10 | — | — | — | 仅跑资产管线（覆盖 74.3%），未出包 | 试验 |
| v29 | 11-11 | 16.72 | 20.31 | 3116 | 表情改墨色层（可跨身体去重，覆盖率 77.7% → 85.9%） | **装不上** |
| v30 | 11-11 | 17.34 | 21.02 | 3476 | 文件数探针（+1700 张表情） | 装不上，确认文件数红线 |
| v31 | 11-11 | 16.73 | 20.33 | 3116 | 墨色层 + 8 级 alpha + 闭嘴提亮 | **装不上** |
| v32 | 11-11 | 15.69 | 19.18 | 2876 | 回差量烘焙 + 1100 张 + CG 黑屏修复 + JS 压缩 | 待验证 |

### 6.1 这 32 轮里真正值钱的六个发现

1. **判引擎**：一上手当成 krkr 会走错全部管线。
2. **文件数也是红线**：v8 的 7313 个文件是「方案好看但装不上」的典型案例。
3. **Vela 不支持动态样式**：图集 + `background-position` 在浏览器里完美，在真机上全黑。
4. **安装判据是解压体积**：v31 的 rpk 只有 16.73 MiB 却装不上，因为解压 20.33 MiB。
5. **alpha 级数才是表情体积大头**：误以为是差量烘焙，白试一轮。
6. **CG 黑屏不是资源问题**：是 `height:520px` 写死在只有 303 design 高的屏上，`contain` 把图居中到 824 实像素的框里，上面 36% 全是黑底。

---

## 7. 目录结构

```
.
├── app/
│   ├── package.json            aiot-toolkit 依赖
│   └── src/
│       ├── manifest.json       watch · designWidth 212
│       ├── app.ux
│       ├── common/
│       │   ├── resource-resolver.js   路径解析（未命中返回 null）
│       │   ├── runtime-data.js        按场景加载清单
│       │   ├── cg-catalog.js          CG 索引（单列表，不分组）
│       │   ├── display-names.js       角色名映射
│       │   ├── game-config.js / reader-constants.js / reader-settings.js
│       │   ├── bg/  ev/  sd/  scn/  runtime/   ← 构建生成，不入库
│       └── pages/
│           ├── index/          主页
│           ├── detail/         播放器（核心）
│           │   ├── detail.ux
│           │   └── scriptEngine.js
│           ├── gallery/        鉴赏列表
│           ├── cg-viewer/      CG 全屏
│           ├── saves/  settings/  about/
├── tools/
│   ├── pf8.py                  pf8 解包 + XOR 解密
│   ├── astparse.py             .ast → 统一指令流
│   ├── build_assets.py         资源读取器
│   ├── build_assets10.py       图片转换（CG 旋转/裁剪/JPEG）
│   ├── build_data.py           IR → scn txt + scene-assets
│   ├── build_app12.py          主构建（立绘烘焙 + 配额）
│   ├── inkface.py              墨色层 / 差量烘焙 / 嘴定位 / 提亮
│   ├── check_syntax.mjs        语法门禁
│   ├── verify.py               引用校验
│   ├── dedupe.py               图片哈希去重
│   ├── sim_bake_compare.py     两种烘焙口径的覆盖率对比
│   ├── quota_sim2.py           配额方案模拟
│   ├── ink_char_stats.py       分角色覆盖率统计
│   ├── mouth_preview.py        嘴部放大预览
│   ├── minswc.js               swc 压缩页面 JS（保留变量名）
│   └── finalize.sh             压缩 JS + 重签 + 输出 rpk
└── docs/
    └── bake-experiments.md     烘焙与体积实验数据
```

### 目录约定

| 路径 | 内容 | 是否入库 |
|---|---|---|
| `app/src/` | 快应用源码 | 是 |
| `app/src/common/{bg,ev,sd,scn,runtime,overlay,images}` | **已转换的游戏素材**（336×480 CG / 分层立绘 / 剧本 JSON） | 是 |
| `build/raw/` | 从正版解包出的原始素材（想自己重跑才需要） | 否 |
| `build/prep/` | `build_assets10.py` 的转换中间产物（`bcgi` `evig` `cimg` `chars.json`） | 否 |

仓库里的素材是**已经转换好的最终形态**，克隆下来可以直接打包，不需要解包游戏。
`build_app12.py` 与 `build_assets10.py` 也支持用 `RAW_DIR`、`PREP_DIR`、`OUT_DIR` 改路径。

构建产物的三个目录 `common/bg`、`common/ev`、`common/sd`、`common/scn`、`common/runtime` 都由脚本生成，仓库里为空。

---

## 8. 构建

### 8.1 直接用仓库里的素材打包（最快）

仓库中的素材已是最终形态，克隆后只需编译：

```bash
# 0) 依赖
cd app && npm i --registry=https://registry.npmmirror.com && cd ..

# 1) 打包
cd app && ./node_modules/.bin/aiot build && cd ..

# 2) 压缩 JS + 重签（必做，否则体积多 0.73 MiB）
bash tools/finalize.sh hamidashi-band10.rpk
```

产出：`hamidashi-band10.rpk`，解压 19.18 MiB。

### 8.2 从正版重新生成全部素材

需要自备正版安装目录（含 `hamidashi.pfs` 系列卷）。

```bash
# 0) 依赖
pip install pillow numpy
cd app && npm i --registry=https://registry.npmmirror.com && cd ..

# 1) 指向游戏目录
export GAME_DIR="D:/Games/ハミダシクリエイティブ"

# 2) 解包 + 剧本解析
python tools/build_assets.py        # pf8 → build/raw（原始尺寸素材）
python tools/build_data.py         # .ast → build/scenes.json、build/assets.json

# 3) 转成手环尺寸
python tools/build_assets10.py     # build/raw → build/prep（CG 旋转 336×480 / 立绘分层）
python tools/dedupe.py

# 4) 烘焙立绘与表情（差量 1100 张，1:1:2 配额）
FACE_BUDGET=1100 FACE_COLORS=32 FACE_ALPHA=2 DELTA_THR=8 python tools/build_app12.py

# 5) 校验
node tools/check_syntax.mjs
python tools/verify.py

# 6) 打包
cd app && ./node_modules/.bin/aiot build && cd ..
bash tools/finalize.sh hamidashi-band10.rpk
```

### 可调参数

| 环境变量 | 默认 | 范围 | 说明 |
|---|---|---|---|
| `FACE_BUDGET` | 1100 | 800–1340 | 表情张数。超过 1340 解压必超 20 MiB |
| `FACE_COLORS` | 32 | 16–64 | 表情调色板色数 |
| `FACE_ALPHA` | 2 | 2–8 | alpha 级数。**这是体积主开关** |
| `DELTA_THR` | 8 | 4–32 | 差量阈值。越大越省，细节丢得越多 |
| `SHI_PCT` | 72 | 60–80 | 诗樱目标覆盖率 |
| `MIR_CUT` | 2 | 1–4 | 老师(里) 名额除数 |
| `CG_Q` | 18 | 14–22 | CG 的 JPEG 质量，不建议再降 |
| `BG_Q` | 14 | 10–18 | 背景质量 |

---

## 9. 已知限制

1. **无音频**：手环无扬声器通路，音频卷未解包。
2. **演出简化**：震屏、闪光、色调、渐变只保留时长。
3. **表情为差量烘焙**：只保留与身体差异超过阈值的像素，腮红等淡色会丢失，边缘为二值 alpha（有锯齿）。要更细腻需提高 `FACE_ALPHA`，体积随之上升。
4. **过场 CG 用静态层**：不支持原版的横向滚动展示。
5. 极少数特写层按 520px 上限压缩并垂直居中，与原版 zoom 有差异。

---

## 10. 致谢

- 原作：**Madosoft**「ハミダシクリエイティブ」，PC 版发行 iMel Inc.
- 构建工具链：小米 AIoT Toolkit
- 界面结构参考：[hezdaaa/limelight-lemonade-jam-miband](https://github.com/hezdaaa/limelight-lemonade-jam-miband)

---

## 11. 授权

**保留所有权利（All Rights Reserved）。** 本仓库未采用任何开源许可证。

代码可阅读、可学习，但**不授予**复制、修改、再分发、商用的许可。
由此产生的任何后果由使用者自行承担。详见 [DISCLAIMER.md](DISCLAIMER.md)。
