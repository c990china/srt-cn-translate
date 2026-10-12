# srt-cn-translate · 外文字幕翻译流水线

**把外文影视字幕（.srt）做成「纯中文」＋「中英双语」两份成品：编号与时间轴 100% 沿用源英文轨，机械自检全流程把关。**

一个 `.srt` 进去，两个成品出来——中文轨 `.zh-CN.srt` + 双语轨 `.zh-en.srt`。整合了检索现成中字、时间轴漂移校验、参考译文对齐、分批审校翻译与独立校验的完整流程。

> **零第三方依赖**：单个脚本 `srt_tools.py`，纯 Python 标准库（`re/os/sys/json/argparse/difflib`），Clone 即用。

---

## 成品长什么样（规范）

| 文件 | 内容 | 命名 |
|---|---|---|
| 英文轨 | 纯英文 | 源文件，通常已有 |
| 中文轨 | 纯中文 | `<源文件名去语言后缀>.zh-CN.srt` |
| 双语轨 | 英文行 + 中文行 | `<源文件名去语言后缀>.zh-en.srt` |

```
Wrath.Of.Man.2021.1080p.AMZN.WEB-DL.DDP5.1.H.264-TEPES.[eng].srt    ← 源
Wrath.Of.Man.2021.1080p.AMZN.WEB-DL.DDP5.1.H.264-TEPES.zh-CN.srt   ← 中文轨
Wrath.Of.Man.2021.1080p.AMZN.WEB-DL.DDP5.1.H.264-TEPES.zh-en.srt   ← 双语轨
```

## 硬性规范

1. **编号与时间码 100% 沿用源英文轨**——不合并、不拆分、不增删，中文轨 cue 数 == 源 cue 数；
2. **编码 UTF-8 with BOM**（否则部分播放器乱码）+ **换行 CRLF**；
3. 中文一律**全角标点**（`，。！？、；：""……——`），正文里半角标点残留必须为 0；
4. 每 cue ≤ 2 行，单行 ≤ 32 字（实测参考样板：平均 8.7–8.8 字）；
5. 双语轨**严格机械拼接**：`双语行 == 源英文行 + 中文行`，必须 100% 成立，英文在上；
6. 中文与拉丁字母/数字之间保留一个半角空格（`Orange Delta 安保`、`118 万`）。

---

## 快速开始

```bash
# 0) 体检源文件：记下 cue 数、首末时间码、总时长（后面所有校验的基准）
python scripts/srt_tools.py probe "target.[eng].srt"

# 1) 先找现成中字当参考，不要一上来就硬翻（SubHD 可程序化下载，五步见指南）
# 2) 校验现成中字能不能用（cue 数 / 首末时间码差 / 偏移量是否恒定）
python scripts/srt_tools.py probe "target.[eng].srt" "ref_chs.srt"

# 3) 把参考译文对齐到本片时间轴，导出分批工作稿（250 条一批）
python scripts/srt_tools.py align "target.[eng].srt" --ref-bilingual ref_双语.srt --ref-chs ref_纯中文.srt --out _work

# 4) 分批审校翻译：按 _work/batches/batch_XX.txt 逐批产出译文 JSON 到 _work/zh/

# 5) 组装成品
python scripts/srt_tools.py assemble "target.[eng].srt" --zh _work/zh --base "Wrath.Of.Man.2021.1080p...TEPES"

# 6) 独立校验（不可省）
python scripts/srt_tools.py verify "target.[eng].srt" out.zh-CN.srt out.zh-en.srt
```

**原则**：参考译文只做参考，必须以本片英文轨为准重译——实测两份「现成中字」都有硬伤
（粉丝译本错译、官方译本漏 cue），直接拿来替换会翻车。

## 四个子命令

| 命令 | 职责 |
|---|---|
| `probe` | 体检：cue 数、编码、BOM、换行、时间轴、行数分布、标点；可对比参考字幕 |
| `align` | 剥标记 → 规范化小写 → 词序列 `difflib.SequenceMatcher` 对齐参考与目标 → 分批工作稿 |
| `assemble` | 把译文 JSON 组装成 `.zh-CN.srt` 与 `.zh-en.srt`（BOM + CRLF + 全角标点） |
| `verify` | **独立读盘、独立解析**校验：cue 数 / 编号 / 时间轴 / BOM / CRLF / 双语拼接 / 行数 / 行长 / 半角标点 / 空译文 |

> 自检脚本必须独立读盘，**不要用组装时的中间变量自证**——校验永远通过但成品有错就是这么来的。

---

## 实测基线

一次完整交付的规模参考：**1990 条 cue、约 2800 行中文、正文半角标点 0、最长行 30 字、平均 8.8 字、双语拼接 1990/1990 机械一致**。

踩过的坑（拿不到 SubHD 下载链接、中英同 cue 拆行、`re.split` 丢中文等）与对策见 [SKILL.md](SKILL.md)。

---

## 开源许可

[MIT License](LICENSE) · Copyright (c) 2026 c990china · 零第三方依赖
