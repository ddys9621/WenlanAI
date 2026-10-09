"""去 AI 味检测（纯函数，零模型调用）。

逐章生成后算一遍：书面词密度、总结 / 升华句、句长变化（句长太整齐是机器味）、长段比例、对话占比、
与上一章的 8 字片段重复率、字数达标率。给出 0-100 的"AI 味分"（越高越像 AI）、问题清单与该重写的段落下标，
供批量生成的质量闸门与「去 AI 味」局部重写使用。
"""
from __future__ import annotations

import re
import statistics
from typing import Optional

BOOKISH_WORDS: tuple[str, ...] = (
    "随即", "旋即", "径自", "俨然", "宛如", "恍若", "犹如", "仿佛", "些许", "颇为", "甚是", "略显",
    "须臾", "刹那间", "霎时", "眼眸", "眸中", "眸子", "唇角", "指尖", "发丝", "氤氲", "斑驳", "静谧", "寂寥",
    "黯淡", "心底", "蔓延", "涌起", "泛起", "弥漫", "难以名状", "伫立", "摇曳", "如墨",
)
SUMMARY_PHRASES: tuple[str, ...] = (
    "他知道", "她知道", "这一刻", "命运", "信念", "本质", "真理", "无论前方", "一往无前", "道心坚定",
    "艰难险阻", "齿轮", "从未如此", "一丝坚定", "眼神逐渐坚定", "心中暗道", "嘴角勾起一抹",
)
_SENTENCE_SPLIT = re.compile(r"[。！？!?…]+|\n+")
_QUOTED = re.compile(r"“[^”]*”|「[^」]*」|\"[^\"]*\"")
LONG_PARAGRAPH = 120
NGRAM = 8


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in (text or "").splitlines() if p.strip()]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if len(s.strip()) >= 2]


def _count(text: str, words: tuple[str, ...]) -> int:
    return sum(text.count(w) for w in words)


def _ngrams(text: str, n: int = NGRAM) -> set[str]:
    compact = re.sub(r"\s+", "", text or "")
    return {compact[i:i + n] for i in range(max(len(compact) - n + 1, 0))}


def flagged_paragraph_indices(paragraphs: list[str]) -> list[int]:
    """该重写的段落：书面词 / 升华句扎堆（≥2）或超长段。"""
    out = []
    for i, p in enumerate(paragraphs):
        if _count(p, BOOKISH_WORDS) + _count(p, SUMMARY_PHRASES) >= 2 or len(p) > LONG_PARAGRAPH * 1.25:
            out.append(i)
    return out


def analyze_text(text: str, previous_text: str = "", target_word_count: Optional[int] = None) -> dict:
    text = text or ""
    chars = len(re.sub(r"\s+", "", text))
    paragraphs = split_paragraphs(text)
    sentences = _sentences(text)
    lengths = [len(s) for s in sentences]
    mean = statistics.mean(lengths) if lengths else 0.0
    cv = (statistics.pstdev(lengths) / mean) if mean and len(lengths) > 1 else 0.0
    quoted = sum(len(m) for m in _QUOTED.findall(text))
    dialogue_ratio = quoted / chars if chars else 0.0
    long_ratio = sum(1 for p in paragraphs if len(p) > LONG_PARAGRAPH) / len(paragraphs) if paragraphs else 0.0
    bookish = _count(text, BOOKISH_WORDS)
    bookish_per_1k = bookish * 1000 / chars if chars else 0.0
    summary_hits = _count(text, SUMMARY_PHRASES)
    repeat_ratio = 0.0
    if previous_text and chars:
        current, prev = _ngrams(text), _ngrams(previous_text)
        repeat_ratio = len(current & prev) / len(current) if current else 0.0

    score = 0.0
    issues: list[str] = []
    if bookish_per_1k > 3:
        score += min(30, (bookish_per_1k - 3) * 4)
        issues.append(f"书面词偏多（每千字 {bookish_per_1k:.1f} 个，如：{'、'.join(w for w in BOOKISH_WORDS if w in text)[:40]}）")
    if summary_hits > 1:
        score += min(25, (summary_hits - 1) * 6)
        issues.append(f"总结 / 升华句 {summary_hits} 处（“他知道”“命运”“一往无前”这类）")
    if len(lengths) >= 5 and cv < 0.35:
        score += 15
        issues.append(f"句长太整齐（变异系数 {cv:.2f}），长短句要错开")
    if long_ratio > 0.25:
        score += 10
        issues.append(f"长段落占 {long_ratio:.0%}，手机阅读要短段")
    if chars >= 800 and dialogue_ratio < 0.12:
        score += 10
        issues.append(f"对话只占 {dialogue_ratio:.0%}，剧情多靠叙述交代")
    if repeat_ratio > 0.08:
        score += min(20, repeat_ratio * 60)
        issues.append(f"与上一章重复片段占 {repeat_ratio:.0%}，可能在复述前情")

    return {
        "chars": chars,
        "paragraphs": len(paragraphs),
        "avg_paragraph_chars": round(chars / len(paragraphs), 1) if paragraphs else 0.0,
        "long_paragraph_ratio": round(long_ratio, 3),
        "dialogue_ratio": round(dialogue_ratio, 3),
        "sentence_len_mean": round(mean, 1),
        "sentence_len_cv": round(cv, 3),
        "bookish_per_1k": round(bookish_per_1k, 2),
        "summary_phrases": summary_hits,
        "repeat_ratio": round(repeat_ratio, 3),
        "word_count_ratio": round(chars / target_word_count, 3) if target_word_count else None,
        "score": int(min(100, round(score))),
        "issues": issues,
        "flagged_paragraphs": flagged_paragraph_indices(paragraphs),
    }
