"""章节切分器

将上传的 txt/md 全文按常见章节标题格式切分成章节列表。
支持中文章回体、章节体、卷章嵌套以及英文 Chapter / Prologue 等。

设计要点：
- 仅依赖标准库，不引入 chardet（按 UTF-8 → GBK → GB18030 顺序尝试）。
- 章节序号统一按出现顺序重新编号 1..N，避免汉字数字（如"第三百零一章"）解析错误。
- 标题行必须独占一行（前后可有空白），避免误匹配正文中的"第X章"。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


# ============================================================
# 编码识别
# ============================================================

_TRY_ENCODINGS: Tuple[str, ...] = ("utf-8-sig", "utf-8", "gb18030", "gbk")


def decode_text(raw_bytes: bytes) -> Tuple[str, str]:
    """按常见中文小说编码顺序尝试解码。

    返回 (text, encoding_used)。失败抛 UnicodeDecodeError。
    """
    last_error: Optional[UnicodeDecodeError] = None
    for enc in _TRY_ENCODINGS:
        try:
            return raw_bytes.decode(enc), enc
        except UnicodeDecodeError as e:
            last_error = e
    # 所有编码都失败：用 utf-8 + replace 兜底，让用户至少能看到部分内容
    if last_error is not None:
        raise last_error
    return raw_bytes.decode("utf-8", errors="replace"), "utf-8(replace)"


# ============================================================
# 汉字数字转阿拉伯数字（仅用于元信息展示，章节号本身不依赖）
# ============================================================

_CN_DIGIT_MAP = {
    "零": 0, "〇": 0, "○": 0,
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    "壹": 1, "贰": 2, "叁": 3, "肆": 4, "伍": 5,
    "陆": 6, "柒": 7, "捌": 8, "玖": 9,
}
_CN_UNIT_MAP = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000, "万": 10000, "亿": 100000000}


def cn_num_to_int(s: str) -> Optional[int]:
    """将形如"一百二十三""三十一""二零二三"的汉字数字转为整数；失败返回 None。"""
    if not s:
        return None
    s = s.strip()
    # 阿拉伯数字直通
    if s.isdigit():
        try:
            return int(s)
        except ValueError:
            return None
    # 全部为汉字数字（无单位），按位拼接：如"二零二三" → 2023
    if all(c in _CN_DIGIT_MAP for c in s):
        try:
            return int("".join(str(_CN_DIGIT_MAP[c]) for c in s))
        except (ValueError, KeyError):
            return None
    # 含单位：使用栈式累加
    total = 0
    section = 0  # 万/亿 之间的临时段
    current = 0
    for ch in s:
        if ch in _CN_DIGIT_MAP:
            current = _CN_DIGIT_MAP[ch]
        elif ch in _CN_UNIT_MAP:
            unit = _CN_UNIT_MAP[ch]
            if unit == 10 and current == 0:
                # "十" 单字开头表示 10
                current = 1
            if unit >= 10000:
                section = (section + current) * unit
                total += section
                section = 0
            else:
                section += current * unit
            current = 0
        else:
            return None
    return total + section + current


# ============================================================
# 标题正则
# ============================================================

# 一个章节标题"序号"段：阿拉伯数字 或 汉字数字（含单位）
_NUM_PART = r"(?:[0-9]+|[零〇○一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟]+)"

# 标题行内空白：仅允许行内空白（空格/Tab/全角空格），禁止换行，避免跨行匹配
_INLINE_WS = r"[ \t\u3000]*"

# 部分阅读器 / 网站导出的 txt 会在标题前加流水号："1.第1章 xxx" / "12、第十二章 xxx" / "3: 第3章"
# 只在紧跟「第X章」时视为前缀，避免把正文里的编号列表（"1.准备工作"）当标题
_SERIAL_PREFIX = rf"(?:[0-9]+{_INLINE_WS}[.．、:：]{_INLINE_WS})?"

# 中文章节标题主体（第X章/第X回/第X节）
# 例："第一章 起源" / "第 1 章" / "第十二回　悟空大闹天宫" / "1.第1章这是个意外"
# 严格要求标题独占一行：使用 _INLINE_WS 而非 \s，禁止 \n 进入匹配
_CN_CHAPTER_RE = re.compile(
    rf"^{_INLINE_WS}{_SERIAL_PREFIX}第{_INLINE_WS}({_NUM_PART}){_INLINE_WS}([章回节卷篇折])"
    rf"(?:{_INLINE_WS}[:：、,，.\-—]?{_INLINE_WS}([^\n]{{0,80}}?))?{_INLINE_WS}$",
    re.MULTILINE,
)

# 中文卷+章嵌套（"第一卷 风起 第一章 少年"），仅识别其中"第X章/回/节/篇"部分
# 此处通过 _CN_CHAPTER_RE 已能覆盖独立卷号行；真正小说正文里"卷"行会被识别为类型 [卷]，
# 我们在切分时把卷类型剔除（因为内容仍按"章"切，避免空卷干扰）。

# 特殊章节标题：序章 / 楔子 / 引子 / 前言 / 番外 / 终章 / 尾声 / 后记
_CN_SPECIAL_RE = re.compile(
    rf"^{_INLINE_WS}(序章|序言|序|楔子|引子|前言|开篇|番外篇?|终章|尾声|结语|后记)"
    rf"(?:{_INLINE_WS}[:：、,，.\-—]?{_INLINE_WS}([^\n]{{0,80}}?))?{_INLINE_WS}$",
    re.MULTILINE,
)

# 英文 Chapter
_EN_CHAPTER_RE = re.compile(
    rf"^{_INLINE_WS}(?:CHAPTER|Chapter){_INLINE_WS}([0-9IVXLCDM]+|[A-Za-z]+)"
    rf"(?:{_INLINE_WS}[:：\-—.]?{_INLINE_WS}([^\n]{{0,80}}?))?{_INLINE_WS}$",
    re.MULTILINE,
)

# 英文 Prologue / Epilogue / Preface
_EN_SPECIAL_RE = re.compile(
    rf"^{_INLINE_WS}(PROLOGUE|Prologue|EPILOGUE|Epilogue|PREFACE|Preface|FOREWORD|Foreword)"
    rf"(?:{_INLINE_WS}[:：\-—.]?{_INLINE_WS}([^\n]{{0,80}}?))?{_INLINE_WS}$",
    re.MULTILINE,
)


# ============================================================
# 数据结构
# ============================================================


@dataclass
class ChapterMatch:
    """章节标题匹配位置"""
    start: int       # 标题在原文的起始 offset（含）
    end: int         # 标题行结束 offset（不含），即正文起点
    raw_title: str   # 完整匹配的标题文本（去前后空白）
    kind: str        # 类型：chapter / special / english


@dataclass
class Chapter:
    """切分后的章节"""
    chapter_number: int   # 重新编号，从 1 开始
    title: str            # 标题（不含序号前缀），如"起源"
    raw_title: str        # 原始标题行，如"第一章 起源"
    content: str          # 正文（不含标题）
    word_count: int       # 中文字符数（粗略）
    kind: str = "chapter"  # chapter / special / english / preamble


# ============================================================
# 正则匹配 → ChapterMatch 列表
# ============================================================


def _find_all_titles(text: str) -> List[ChapterMatch]:
    """汇总所有正则匹配，按位置排序。"""
    matches: List[ChapterMatch] = []

    for m in _CN_CHAPTER_RE.finditer(text):
        unit = m.group(2)
        # 卷标题暂不作为切分点（避免空卷），但保留"篇"作为切分点（部分小说用"第X篇"组织章节）
        if unit == "卷":
            continue
        matches.append(ChapterMatch(
            start=m.start(),
            end=m.end(),
            raw_title=m.group(0).strip(),
            kind="chapter",
        ))

    for m in _CN_SPECIAL_RE.finditer(text):
        matches.append(ChapterMatch(
            start=m.start(),
            end=m.end(),
            raw_title=m.group(0).strip(),
            kind="special",
        ))

    for m in _EN_CHAPTER_RE.finditer(text):
        matches.append(ChapterMatch(
            start=m.start(),
            end=m.end(),
            raw_title=m.group(0).strip(),
            kind="english",
        ))

    for m in _EN_SPECIAL_RE.finditer(text):
        matches.append(ChapterMatch(
            start=m.start(),
            end=m.end(),
            raw_title=m.group(0).strip(),
            kind="english",
        ))

    matches.sort(key=lambda x: x.start)

    # 去重：同一位置可能被多个正则同时匹配，保留第一个
    deduped: List[ChapterMatch] = []
    seen_starts: set = set()
    for cm in matches:
        if cm.start in seen_starts:
            continue
        seen_starts.add(cm.start)
        deduped.append(cm)

    return deduped


# ============================================================
# 标题清洗（提取 title 与 raw_title）
# ============================================================

# 用于从 raw_title 中剥离序号前缀，保留纯标题。
_TITLE_STRIP_PATTERNS = [
    re.compile(rf"^{_SERIAL_PREFIX}第\s*{_NUM_PART}\s*[章回节卷篇折]\s*[:：、,，.\-—\s]?\s*"),
    re.compile(r"^(?:CHAPTER|Chapter)\s+(?:[0-9IVXLCDM]+|[A-Za-z]+)\s*[:：\-—.\s]?\s*"),
]


def _extract_title(raw_title: str, kind: str) -> str:
    """从原始标题行剥离序号前缀，得到纯标题；找不到就回退原文。"""
    text = raw_title.strip()
    if kind in ("special",):
        return text  # 序章/楔子等本身就是标题
    for pat in _TITLE_STRIP_PATTERNS:
        new = pat.sub("", text, count=1)
        if new != text:
            return new.strip() or text
    return text


# ============================================================
# 主入口
# ============================================================

# 章节内容长度门槛：低于此值的"章节"通常是误识别（如目录页中的章节标题列表）
MIN_CHAPTER_CONTENT_CHARS = 50

# 章节数量门槛：识别到的章节数低于此值则视为切分失败
MIN_VALID_CHAPTERS = 1


def _normalize_text(text: str) -> str:
    """统一换行符 + 去 BOM。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\ufeff"):
        text = text[1:]
    return text


def _count_words(text: str) -> int:
    """粗略中文字数：中日韩字符 + 英文单词数。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    en_words = len(re.findall(r"[A-Za-z]+", text))
    return cjk + en_words


def split_into_chapters(text: str) -> List[Chapter]:
    """切分主入口。

    返回章节列表，章节号从 1 开始按出现顺序重新编号。
    若识别不到任何章节，会把整段文本作为单章返回。
    """
    text = _normalize_text(text)
    if not text.strip():
        return []

    matches = _find_all_titles(text)

    # 没有任何标题：整本作为单章
    if len(matches) < MIN_VALID_CHAPTERS:
        return [Chapter(
            chapter_number=1,
            title="全文",
            raw_title="全文",
            content=text.strip(),
            word_count=_count_words(text),
            kind="preamble",
        )]

    chapters: List[Chapter] = []

    # 第一个标题之前的内容（前言/未标记区域）
    first = matches[0]
    if first.start > 0:
        preamble = text[:first.start].strip()
        if len(preamble) >= MIN_CHAPTER_CONTENT_CHARS:
            chapters.append(Chapter(
                chapter_number=len(chapters) + 1,
                title="前言",
                raw_title="前言",
                content=preamble,
                word_count=_count_words(preamble),
                kind="preamble",
            ))

    # 标题之间的正文
    for i, cm in enumerate(matches):
        content_start = cm.end
        content_end = matches[i + 1].start if i + 1 < len(matches) else len(text)
        content = text[content_start:content_end].strip()

        # 过滤空章节（典型如目录页中只有标题没有正文）
        if len(content) < MIN_CHAPTER_CONTENT_CHARS and i + 1 < len(matches):
            # 内容太短，且后面还有章节，跳过
            continue

        chapters.append(Chapter(
            chapter_number=len(chapters) + 1,
            title=_extract_title(cm.raw_title, cm.kind),
            raw_title=cm.raw_title,
            content=content,
            word_count=_count_words(content),
            kind=cm.kind,
        ))

    return chapters


def split_bytes(raw: bytes) -> Tuple[List[Chapter], str]:
    """从原始字节切分章节，返回 (chapters, encoding_used)。"""
    text, enc = decode_text(raw)
    chapters = split_into_chapters(text)
    return chapters, enc
