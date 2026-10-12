#!/usr/bin/env python3
"""srt_tools.py — 外文字幕 → 中文单语 + 中英双语 的流水线工具

四个子命令：
  probe    体检字幕文件（cue 数、编码、换行、时间轴、行数分布、标点）
  align    把参考中字按「规范化英文文本 + 词序列」对齐到目标英文轨，导出分批工作稿
  assemble 把译文 JSON 组装成 zh-CN.srt 与 zh-en.srt（UTF-8 BOM + CRLF）
  verify   独立校验成品是否满足规范（结构 / 时间轴 / 双语拼接 / 标点 / 行数）

用法示例：
  python srt_tools.py probe   target.[eng].srt ref_chs.srt ref_bilingual.srt
  python srt_tools.py align   target.[eng].srt --ref-bilingual ref.srt --out _work
  python srt_tools.py assemble target.[eng].srt --zh _work/zh --base out_base_name
  python srt_tools.py verify  target.[eng].srt out_base_name.zh-CN.srt out_base_name.zh-en.srt
"""
import re
import os
import sys
import json
import argparse
import difflib
from collections import Counter


# ---------------------------------------------------------------- 基础工具

def read_srt(path):
    """返回 (bom, crlf, cues)；cue = {'idx','time','body':[...]}"""
    if not os.path.exists(path):
        sys.exit('!! 文件不存在: %s' % path)
    raw = open(path, 'rb').read()
    bom = raw[:3] == b'\xef\xbb\xbf'
    crlf = b'\r\n' in raw
    txt = raw.decode('utf-8-sig', errors='replace')
    blocks = [b for b in re.split(r'\r?\n\r?\n', txt.strip()) if b.strip()]
    cues = []
    for b in blocks:
        L = [x.rstrip('\r') for x in b.split('\n')]
        cues.append({'idx': L[0].strip(),
                     'time': L[1].strip() if len(L) > 1 else '',
                     'body': [x.strip() for x in L[2:] if x.strip()]})
    return bom, crlf, cues


def write_srt(path, lines):
    """UTF-8 BOM + CRLF 写出"""
    body = '\r\n'.join(lines) + '\r\n'
    open(path, 'wb').write(b'\xef\xbb\xbf' + body.encode('utf-8'))


SPEAKER_RE = re.compile(r'^-\s*([A-Z][A-Z0-9 \'\.\-]{0,20}):\s*')
BRACKET_RE = re.compile(r'\[[^\]]*\]')


def norm_en(lines):
    """剥掉说话人前缀、[音效]、破折号、标点，只留纯文本用于比对"""
    s = ' '.join(lines)
    s = re.sub(r'^\s*-\s*', '', s)
    s = s.replace('-', ' ')
    s = BRACKET_RE.sub(' ', s)
    s = re.sub(r'^[A-Z][A-Z0-9 \'\.\-]{0,20}:\s*', '', s)
    s = re.sub(r'[^a-zA-Z0-9\' ]', ' ', s.lower())
    return re.sub(r'\s+', ' ', s).strip()


def words(s):
    return s.split()


def t2ms(t):
    m = re.match(r'(\d+):(\d+):(\d+)[,.](\d+)', t or '')
    if not m:
        return None
    h, mi, s, ms = m.groups()
    return ((int(h) * 60 + int(mi)) * 60 + int(s)) * 1000 + int(ms)


def strip_markup(line):
    """去 [音效] 与说话人前缀，用于标点检查"""
    s = BRACKET_RE.sub('', line)
    s = re.sub(r'^-\s*', '', s)
    s = re.sub(r'^[A-Za-z][A-Za-z0-9 \'\.\-]{0,20}:\s*', '', s)
    return s


# ---------------------------------------------------------------- probe

def cmd_probe(a):
    for p in a.files:
        if not os.path.exists(p):
            print(f'!! 不存在: {p}')
            continue
        bom, crlf, cues = read_srt(p)
        lens = [len(l) for c in cues for l in c['body']]
        lines_per = Counter(len(c['body']) for c in cues)
        half = sum(strip_markup(l).count(ch)
                   for c in cues for l in c['body'] for ch in ',.?!;')
        print(f'\n=== {os.path.basename(p)}')
        print(f'  cue 数 {len(cues)} | BOM {bom} | CRLF {crlf}')
        print(f'  首 {cues[0]["time"] if cues else "-"} | 末 {cues[-1]["time"] if cues else "-"}')
        print(f'  行数分布 {dict(lines_per)}')
        if lens:
            print(f'  行长 最长 {max(lens)} 平均 {sum(lens)/len(lens):.1f}')
        print(f'  正文半角标点 {half}')
        has_cjk = any(re.search(r'[\u4e00-\u9fff]', l) for c in cues for l in c['body'])
        print(f'  含中文 {has_cjk}')


# ---------------------------------------------------------------- align

def align_map(our_norm, ref_norm):
    """返回 {our_index: ref_index}"""
    a, b = words(' '.join(our_norm)), words(' '.join(ref_norm))
    oi = [i for i, t in enumerate(our_norm) for _ in words(t)]
    ri = [i for i, t in enumerate(ref_norm) for _ in words(t)]
    sm = difflib.SequenceMatcher(None, b, a, autojunk=False)   # ref -> our
    m = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                m[oi[j1 + k]] = ri[i1 + k]
    return m


def split_bilingual(body):
    """把「中文行 + 英文行」拆成 (中文行, 英文行)"""
    zh, en = [], []
    for l in body:
        if re.search(r'[\u4e00-\u9fff]', l):
            zh.append(l)
        else:
            en.append(l)
    return zh, en


def cmd_align(a):
    _, _, ours = read_srt(a.target)
    os.makedirs(a.out, exist_ok=True)
    refs = {}       # name -> list[list[str]] 中文行（按参考文件 cue 顺序）

    if a.ref_bilingual:
        _, _, rc = read_srt(a.ref_bilingual)
        zh_list = []
        for c in rc:
            zh, _ = split_bilingual(c['body'])
            zh_list.append(zh)
        refs['ref-bilingual'] = (rc, zh_list)

    if a.ref_chs:
        _, _, rc = read_srt(a.ref_chs)
        refs['ref-chs'] = (rc, [c['body'] for c in rc])

    our_norm = [norm_en(c['body']) for c in ours]
    maps = {}
    for name, (rc, _) in refs.items():
        rn = [norm_en(c['body']) for c in rc]
        maps[name] = align_map(our_norm, rn)
        print(f'{name}: {len(rc)} cues -> 命中 {len(maps[name])}')

    res = []
    for i, c in enumerate(ours):
        cands = []
        for name, (rc, zh_list) in refs.items():
            r = maps[name].get(i)
            if r is not None and zh_list[r]:
                cands.append({'src': name, 'zh': zh_list[r]})
        res.append({'i': i, 'idx': c['idx'], 'time': c['time'],
                    'en': c['body'], 'cands': cands})

    B = a.batch
    for bi in range(0, len(res), B):
        chunk = res[bi:bi + B]
        lines = []
        for r in chunk:
            lines.append(f"[{r['idx']}] {r['time']}")
            for k, e in enumerate(r['en']):
                lines.append(('EN: ' if k == 0 else '    ') + e)
            for c in r['cands']:
                lines.append(f"{c['src']}: " + ' / '.join(c['zh']))
            if not r['cands']:
                lines.append('(无参考译文)')
            lines.append('')
        p = os.path.join(a.out, f'batch_{bi//B+1:02d}.txt')
        open(p, 'w', encoding='utf-8').write('\n'.join(lines))
        print('  ', p, len(chunk), 'cues')

    json.dump(res, open(os.path.join(a.out, 'aligned.json'), 'w',
                        encoding='utf-8'), ensure_ascii=False, indent=1)
    n0 = sum(1 for r in res if not r['cands'])
    n1 = sum(1 for r in res if len(r['cands']) == 1)
    n2 = sum(1 for r in res if len(r['cands']) >= 2)
    print(f'\n无参考 {n0} | 单参考 {n1} | 双参考 {n2}')
    print('下一步：读 _work/batches/batch_XX.txt，逐条审校，')
    print('       把结果写成 _work/zh/batch_XX.json（{"cue编号": ["行1","行2"]}）')


# ---------------------------------------------------------------- assemble

def cmd_assemble(a):
    _, _, cues = read_srt(a.target)
    if not os.path.isdir(a.zh):
        sys.exit('!! 译文目录不存在: %s（先跑 align 导出工作稿，再把译文 JSON 写进去）' % a.zh)
    zh = {}
    for fn in sorted(os.listdir(a.zh)):
        if fn.endswith('.json'):
            d = json.load(open(os.path.join(a.zh, fn), encoding='utf-8'))
            dup = [k for k in d if k in zh]
            if dup:
                print('!! 重复 cue:', dup[:10])
            zh.update(d)
            print(f'  {fn}: {len(d)}')

    missing = [c['idx'] for c in cues if c['idx'] not in zh]
    if missing:
        sys.exit(f'!! 缺失 {len(missing)} 条，前 20: {missing[:20]}')
    print(f'译文 {len(zh)} 条，源 {len(cues)} 条 —— 齐了')

    zh_lines, bi_lines = [], []
    for c in cues:
        z = zh[c['idx']]
        zh_lines += [c['idx'], c['time']] + z + ['']
        bi_lines += [c['idx'], c['time']] + c['body'] + z + ['']

    pz = a.base + '.zh-CN.srt'
    pb = a.base + '.zh-en.srt'
    write_srt(pz, zh_lines)
    write_srt(pb, bi_lines)
    print('写出', pz, os.path.getsize(pz), 'bytes')
    print('写出', pb, os.path.getsize(pb), 'bytes')


# ---------------------------------------------------------------- verify

def cmd_verify(a):
    b1, c1, src = read_srt(a.target)
    b2, c2, zh = read_srt(a.zh)
    b3, c3, bi = read_srt(a.bi)
    ok = True

    print('=== 1. 结构 ===')
    same_n = len(src) == len(zh) == len(bi)
    same_i = [x['idx'] for x in src] == [x['idx'] for x in zh] == [x['idx'] for x in bi]
    same_t = [x['time'] for x in src] == [x['time'] for x in zh] == [x['time'] for x in bi]
    print(f'  cue 数 源={len(src)} zh-CN={len(zh)} zh-en={len(bi)} → {same_n}')
    print(f'  BOM zh-CN={b2} zh-en={b3} (须 True)')
    print(f'  CRLF zh-CN={c2} zh-en={c3} (须 True)')
    print(f'  编号一致 {same_i} | 时间轴一致 {same_t}')
    ok &= same_n and same_i and same_t and b2 and b3 and c2 and c3

    print('\n=== 2. 双语 = 英文原文行 + 中文行 ===')
    bad = [s['idx'] for s, z, b in zip(src, zh, bi)
           if b['body'] != s['body'] + z['body']]
    print(f'  机械一致 {len(src)-len(bad)}/{len(src)}', '' if not bad else f'坏 {bad[:5]}')
    ok &= not bad

    print('\n=== 3. 中文行规范 ===')
    maxlines = max((len(z['body']) for z in zh), default=0)
    lens = [len(l) for z in zh for l in z['body'] if l.strip()]
    half = sum(strip_markup(l).count(ch)
               for z in zh for l in z['body'] for ch in ',.?!;')
    print(f'  每 cue 最大行数 {maxlines} (须 ≤2)')
    print(f'  最长行 {max(lens) if lens else 0} 字 / 平均 {sum(lens)/len(lens):.1f} 字 (上限约 32)')
    print(f'  正文半角标点 {half} (须 0)')
    empty = [z['idx'] for z in zh if not any(l.strip() for l in z['body'])]
    print(f'  空译文 {len(empty)} 条 (须 0)')
    ok &= maxlines <= 2 and half == 0 and not empty

    print('\n结果:', '✅ 全部通过' if ok else '❌ 有未通过项')
    sys.exit(0 if ok else 1)


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description='外文字幕 → 中文单语 + 中英双语')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('probe', help='体检字幕文件')
    p.add_argument('files', nargs='+')
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser('align', help='对齐参考中字并导出工作稿')
    p.add_argument('target', help='目标英文轨')
    p.add_argument('--ref-bilingual', help='参考：中英双语字幕')
    p.add_argument('--ref-chs', help='参考：纯中文字幕')
    p.add_argument('--out', default='_work')
    p.add_argument('--batch', type=int, default=250)
    p.set_defaults(func=cmd_align)

    p = sub.add_parser('assemble', help='组装 zh-CN 与 zh-en')
    p.add_argument('target', help='目标英文轨')
    p.add_argument('--zh', default='_work/zh', help='译文 JSON 目录')
    p.add_argument('--base', required=True, help='输出文件名基底（不含语言后缀）')
    p.set_defaults(func=cmd_assemble)

    p = sub.add_parser('verify', help='校验成品')
    p.add_argument('target')
    p.add_argument('zh')
    p.add_argument('bi')
    p.set_defaults(func=cmd_verify)

    a = ap.parse_args()
    a.func(a)


if __name__ == '__main__':
    main()
