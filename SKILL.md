---
name: srt-cn-translate
version: 1.0
description: 把外文影视字幕（.srt）做成「纯中文」+「中英双语」两份成品，编号与时间轴 100% 沿用源英文轨。含 SubHD 程序化下载现成中字、时间轴漂移校验、参考译文对齐、分批审校翻译、机械自检全流程。触发词：字幕翻译、中文字幕、中英双语字幕、srt 翻译、给字幕做中文、双语字幕制作、字幕三件套、subhd 下载字幕。
agent_created: true
---

# 字幕翻译流水线（外文 → 中文单语 + 中英双语）

> 版本：v1.0　最后更新：2026-10-06
> 配套脚本：`scripts/srt_tools.py`（probe / align / assemble / verify 四个子命令）

## 何时用

用户给一个字幕文件（多为 `.srt`），要求「翻译成中文」「做中英双语」「照着某个已有字幕的格式处理」。
典型说法：*"根据 King Lear 三个文件处理 Wrath of Man 的英文字幕"*、
*"把这片字幕翻成中文，要双语版"*、*"帮我做个中文字幕"*。

## 成品长什么样（规范）

### 文件三件套

| 文件 | 内容 | 命名 |
|---|---|---|
| 英文轨 | 纯英文 | 源文件，通常已有 |
| 中文轨 | 纯中文 | `<源文件名去语言后缀>.zh-CN.srt` |
| 双语轨 | 英文行 + 中文行 | `<源文件名去语言后缀>.zh-en.srt` |

命名以**源英文字幕的完整文件名为基底**，只换语言后缀：

```
Wrath.Of.Man.2021.1080p.AMZN.WEB-DL.DDP5.1.H.264-TEPES.[eng].srt   ← 源
Wrath.Of.Man.2021.1080p.AMZN.WEB-DL.DDP5.1.H.264-TEPES.zh-CN.srt  ← 产出
Wrath.Of.Man.2021.1080p.AMZN.WEB-DL.DDP5.1.H.264-TEPES.zh-en.srt  ← 产出
```

### 硬性规范

1. **编号与时间码 100% 沿用源英文轨** —— 不合并、不拆分、不增删。中文轨 cue 数 == 源 cue 数。
2. **编码 UTF-8 with BOM**（中文轨与双语轨必须带 BOM，否则部分播放器乱码）；**换行 CRLF**。
3. **中文一律全角标点**：`，。！？、；：“”……——`。正文里半角标点残留必须为 0。
   省略号用两个全角 `……`，破折号用 `——`。
4. **每 cue ≤ 2 行，单行 ≤ 32 字**（实测参考样板：平均 8.7–8.8 字）。
5. **双语轨严格机械拼接**：`双语行 == 源英文行 + 中文行`，须 100% 成立，英文在上。
6. 中文与拉丁字母/数字之间**保留一个半角空格**（`Orange Delta 安保`、`118 万`、`70% 的及格线`）。

### 标记处理（关键，必须与用户确认口径）

源字幕里的三类「非对白」元素，**默认口径是原样保留英文**（改动最小、最可逆）：

| 类型 | 源例 | 默认产出 |
|---|---|---|
| 说话人前缀 | `MICK: The grease` | `MICK: 问题不在油上。` |
| 方括号音效/说明 | `[GRUNTS]`、`[ON RADIO]` | 原样保留，不译 |
| 纯音效 cue | 整条只有 `[CHARLIE SCOFFS]` | 原样保留该行 |
| 双人对话破折号 | `-Oh, fuck!` / `-MICK: Shit!` | `-操！` / `-MICK: 妈的！` |
| 歌词 | `[SINGING]` + 歌词 | 歌词照译，`[SINGING]` 保留 |

⚠️ **口径必须问过用户**。备选口径：全部中文化（`[GRUNTS]`→`[哼]`，需另立音效对照表）、
全部删除（字幕更干净但丢信息）、音效留英文+说话人删掉。不同口径成品差异极大。

## 流程

### 步骤 0 — 体检源文件

```bash
python scripts/srt_tools.py probe "target.[eng].srt"
```

记下 **cue 数、首末时间码、总时长** —— 这是后面所有校验的基准。

### 步骤 1 — 检索现成中文字幕

**先找现成的当参考，不要一上来就硬翻。** 优先挑标注了**同片源**（如都是 `AMZN.WEB-DL`）的条目。

| 站点 | 说明 |
|---|---|
| subhd.tv | 中文站，片源标注清晰，**可程序化下载**（见下） |
| 字幕库 zimoku | 中英双语多 |
| assrt.net | 射手网存档 |
| OpenSubtitles / Subscene | 外语站，中字较少，下载多需登录 |

**SubHD 程序化下载（实测可用，五步走）**

```bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# 1) 先访问详情页拿 Cookie
curl -s -L -A "$UA" -c cj.txt "https://subhd.tv/a/<SID>" -o page.html

# 2) 取下载中转地址（返回 {"success":true,"url":"/down/<SID>"}）
curl -s -L -A "$UA" -b cj.txt -c cj.txt -H "Referer: https://subhd.tv/a/<SID>" \
  -H "Content-Type: application/json" -H "X-Requested-With: XMLHttpRequest" \
  -X POST --data '{"sid":"<SID>"}' "https://subhd.tv/api/sub/prepare-download"

# 3) 访问中转页（必须带 Referer，否则 403）
curl -s -L -A "$UA" -b cj.txt -c cj.txt -H "Referer: https://subhd.tv/a/<SID>" \
  "https://subhd.tv/down/<SID>" -o mid.html

# 4) 调真实接口拿文件 URL（返回 dl.subhd.me 上的 .rar）
curl -s -L -A "$UA" -b cj.txt -c cj.txt -H "Referer: https://subhd.tv/down/<SID>" \
  -H "Content-Type: application/json" -X POST --data '{"sid":"<SID>"}' \
  "https://subhd.tv/api/sub/down"

# 5) 下载并解压（Windows 本机有 WinRAR）
curl -s -L -A "$UA" -H "Referer: https://subhd.tv/down/<SID>" "<url>" -o sub.rar
"/c/Program Files/WinRAR/UnRAR.exe" x -o+ -y sub.rar ./out/
```

**四个坑：**
- 第 3 步不带 `Referer` 直接访问 `/down/` → **403**。
- 详情页「下载字幕文件」按钮是 JS 渲染的，`href="#"`，**抓不到链接**，必须走 API。
- 详情页的 `/api/sub/preview/<SID>` 预览接口**只返回英文轨**，拿不到中文。
- 搜索页 URL：`https://subhd.tv/search/<关键词 URL 编码>`，结果里 `<SID>` 是 `/a/<SID>` 的末段。

### 步骤 2 — 校验现成中字能不能用

⚠️ **绝不要直接拿来替换。** 现成中字大概率是别的片源（BluRay / HBO / 其它流媒体），时间轴会漂移。

```bash
python scripts/srt_tools.py probe "target.[eng].srt" "ref_chs.srt"
```

必查三项：
1. **cue 数**是否一致；
2. **首末时间码**差多少；
3. 偏移量是否**恒定**。恒定 = 同一片源做了平移（可整体校正）；
   不恒定 = 不同剪辑版本，**必须重新对齐**。

> 实测案例：《Wrath of Man》官方亚马逊译本与本片英文轨差 **+100ms 恒定偏移**，
> 但 cue 数只有 1693（本片 1990）—— 它把纯音效 cue 和说话人前缀全合并掉了。
> 结论：**不能直接用**，只能当译文参考。

### 步骤 3 — 对齐参考译文到本片时间轴

```bash
python scripts/srt_tools.py align "target.[eng].srt" \
  --ref-bilingual ref_双语.srt --ref-chs ref_纯中文.srt --out _work
```

内部做法：剥掉说话人前缀 / `[音效]` / 破折号 → 规范化小写纯文本 →
把词序列展开成「词 → cue 下标」→ `difflib.SequenceMatcher` 对齐参考与目标 →
产出每条 cue 的候选译文清单，按 250 条一批导出 `_work/batches/batch_XX.txt`。

> 实测《Wrath of Man》：1444 条双参考、293 条单参考、253 条无参考。
> 无参考的基本都是纯音效 cue 和参考字幕丢弃的说话人 cue。

### 步骤 4 — 分批审校翻译

- **参考译文只做参考，必须以本片英文轨为准重译。** 实测两份参考都有硬伤：
  粉丝译本把 `The game's gonna be startin' soon` 译成「马上就是早高峰了」（错译）；
  官方译本把 `Like the bomb, or like Jesus H.` 译成「就是希罕的希，或希望的希」（错译）。
- 按 **250 条一批**处理，每批产出 `{"cue编号": ["中文行1", "中文行2"]}` 的 JSON，
  存到 `_work/zh/batch_XX.json`。
- 每批同步执行规范：全角标点、≤2 行、标记保留、人名术语全片统一。
- 建一张人名/术语对照表，**同一专名全片只用一个译法**。

### 步骤 5 — 组装

```bash
python scripts/srt_tools.py assemble "target.[eng].srt" \
  --zh _work/zh --base "Wrath.Of.Man.2021....TEPES"
```

### 步骤 6 — 独立校验（不可省）

```bash
python scripts/srt_tools.py verify "target.[eng].srt" out.zh-CN.srt out.zh-en.srt
```

**自检脚本必须独立读盘、独立解析**，不要用组装时的中间变量自证。
校验清单：cue 数 / 编号 / 时间轴 / BOM / CRLF / 双语拼接 / 行数 / 行长 / 半角标点 / 空译文。
全部通过才算完成。

## 通用坑

| 坑 | 症状 | 对策 |
|---|---|---|
| 直接套用现成中字 | 字幕整体提前/延后几十秒 | 先做步骤 2 的三项校验 |
| 参考是双语但中英在同一 cue | 无法按行拆分 | 按「含不含汉字」逐行判定（`split_bilingual`） |
| 说话人前缀混在对白里 | 双语轨看起来重复 | 这是保留英文标记的必然结果；要避免就得在中文行删掉前缀（属另一口径） |
| 正则切分丢中文 | 中文整段消失 | `re.split` 时模式**外层必须有捕获组** |
| 用组装时的变量自证 | 校验永远通过但成品有错 | 自检脚本独立读盘、独立解析 |
| Windows 下 `/tmp` 路径 | Python 打不开 Git Bash 的 `/tmp` | 用工作目录内的相对路径 |
| 删除临时文件 | 用户有「禁止不确认即删除」的硬规定 | 只报告不删，或先问 |

## 质量基线

一次完整交付的实测规模参考：1990 条 cue、约 2800 行中文、正文半角标点 0、
最长行 30 字、平均 8.8 字、双语拼接 1990/1990 机械一致。
