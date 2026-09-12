"""去 AI 味措辞层的确定性统计：07_style_zh.md 里能用正则 / 统计做的那部分判据，本地算、带原文位置、可复现。

三个用途：
1. 喂给 07 措辞轮当"候选位置"提示（format_hints），LLM 只做判断不做搜索；
2. 诊断结果里带一份 metrics 面板；
3. 去 AI 味改稿前后各算一次，metrics_delta 给出"这次改稿到底动了什么"。

数字只是方向（HC3 中文语料：人类句长标准差高、连词密度低、语气词密度高），不是阈值；词表与 07 规则文件保持一致。
"""
from __future__ import annotations

import re
import statistics
from typing import Any

# 词表（与 prompts/deai/review/07_style_zh.md 同步维护）
MACHINE_PHRASES = (
    "空气仿佛凝固", "露出一抹笑", "深吸一口气", "嘴角勾起", "眼神一凛", "这一刻",
    "仿佛", "似乎", "不禁", "顿时", "一丝", "一抹", "一股",
)
CONJUNCTIONS = ("与此同时", "以及", "并且", "同时", "此外", "因此", "然而", "而且", "但是", "所以", "于是", "不过", "和")
FILTER_WORDS = ("意识到", "注意到", "感到", "似乎", "仿佛", "发现")
PARTICLES = "啊吧呢嘛啦呗哦呀哟"
DIALOGUE_TAG_ADVERBS = (
    "低声", "沉声", "淡淡", "轻笑", "冷冷", "缓缓", "轻声", "沙哑", "冷声", "柔声", "朗声", "正色", "苦笑", "冷笑", "嗤笑",
)
FILLER_VERBS = ("进行", "加以", "予以", "做出", "作出")
FILLER_OBJECTS = (
    "讨论", "说明", "处理", "决定", "分析", "调整", "思考", "判断", "回应", "反应", "解释", "检查", "准备", "观察", "选择",
    "尝试", "交流", "沟通", "评估", "确认",
)

_SENTENCE_END = "。！？!?…；;"
_MACHINE_RE = re.compile("|".join(map(re.escape, MACHINE_PHRASES)))
_CONJ_RE = re.compile("|".join(map(re.escape, CONJUNCTIONS)))
_FILTER_RE = re.compile("|".join(map(re.escape, FILTER_WORDS)))
_PARTICLE_RE = re.compile(rf"[{PARTICLES}](?=[{_SENTENCE_END}，,”」’』\s]|$)")
_CONTRAST_RE = re.compile(rf"不是[^{_SENTENCE_END}\n]{{1,30}}?而是")
_FILLER_RE = re.compile("(?:" + "|".join(FILLER_VERBS) + ")(?:" + "|".join(FILLER_OBJECTS) + ")")
_TAG_RE = re.compile("(?:" + "|".join(DIALOGUE_TAG_ADVERBS) + ")(?:道|说)")
_SENTENCE_RE = re.compile(rf"[^{_SENTENCE_END}\n]+[{_SENTENCE_END}]*[”」’』]*")
_QUOTE_CHARS = "“”「」\""

FLAT_RUN_MIN = 3  # 连续这么多句长度接近才算"句长扁平"
FLAT_TOLERANCE_ABS = 3
FLAT_TOLERANCE_RATIO = 0.15
CLUSTER_MIN = 2  # 同一段 ≥ 这么多个机器词才算"成群"
TAG_VARIETY_MIN = 3  # 说话标记花样 ≥ 这么多种才报"轮换"

Hit = dict[str, Any]


def _paragraphs(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"[^\n]+", text) if m.group().strip()]


def _sentences(text: str, start: int, end: int) -> list[tuple[int, int]]:
    return [(start + m.start(), start + m.end()) for m in _SENTENCE_RE.finditer(text[start:end]) if m.group().strip()]


def _hit(feature: str, text: str, start: int, end: int, evidence: str | None = None) -> Hit:
    return {"feature": feature, "evidence": (evidence if evidence is not None else text[start:end]).strip(), "start": start, "end": end}


def _per_k(count: int, chars: int) -> float:
    return round(count / chars * 1000, 1) if chars else 0.0


def _flat_runs(text: str, sentences: list[tuple[int, int]]) -> list[Hit]:
    lengths = [len(text[s:e].strip()) for s, e in sentences]
    hits: list[Hit] = []
    i = 0
    while i < len(lengths):
        j = i
        while j + 1 < len(lengths) and abs(lengths[j + 1] - lengths[j]) <= max(FLAT_TOLERANCE_ABS, FLAT_TOLERANCE_RATIO * max(lengths[j], lengths[j + 1])):
            j += 1
        if j - i + 1 >= FLAT_RUN_MIN:
            start, end = sentences[i][0], sentences[j][1]
            hits.append(_hit("句长扁平", text, start, end, text[start:min(end, start + 60)]))
        i = j + 1
    return hits


def compute_metrics(content: str) -> dict[str, Any]:
    """返回 {"metrics": {...数值...}, "hits": [{"feature","evidence","start","end"}...]}；空文本安全。"""
    text = content or ""
    chars = len(re.sub(r"\s", "", text))
    paragraphs = _paragraphs(text)
    hits: list[Hit] = []

    all_sentences: list[tuple[int, int]] = []
    single_sentence_paragraphs = 0
    quote_paragraphs = quote_end = 0
    clusters = 0
    for p_start, p_end in paragraphs:
        para = text[p_start:p_end]
        sentences = _sentences(text, p_start, p_end)
        all_sentences.extend(sentences)
        if len(sentences) == 1:
            single_sentence_paragraphs += 1
        if any(ch in para for ch in _QUOTE_CHARS):
            quote_paragraphs += 1
            if para.rstrip().endswith(("”", "」", '"')):
                quote_end += 1
        machine = list(_MACHINE_RE.finditer(para))
        if len(machine) >= CLUSTER_MIN:
            clusters += 1
            excerpt = para[machine[0].start():machine[-1].end()]
            hits.append(_hit("高频机器词成群", text, p_start, p_end, excerpt[:80]))

    flat_hits = _flat_runs(text, all_sentences)
    hits.extend(flat_hits)
    hits.extend(_hit("对比框架", text, m.start(), m.end()) for m in _CONTRAST_RE.finditer(text))
    hits.extend(_hit("双音节填充", text, m.start(), m.end()) for m in _FILLER_RE.finditer(text))

    tags = list(_TAG_RE.finditer(text))
    tag_variety = len({m.group() for m in tags})
    if tag_variety >= TAG_VARIETY_MIN:
        hits.append(_hit("说话标记轮换", text, tags[0].start(), tags[-1].end(), "、".join(sorted({m.group() for m in tags}))))

    sentence_lengths = [len(text[s:e].strip()) for s, e in all_sentences]
    paragraph_lengths = [len(text[s:e].strip()) for s, e in paragraphs]
    metrics = {
        "chars": chars,
        "sentences": len(all_sentences),
        "sentence_len_mean": round(statistics.fmean(sentence_lengths), 1) if sentence_lengths else 0.0,
        "sentence_len_std": round(statistics.pstdev(sentence_lengths), 1) if len(sentence_lengths) > 1 else 0.0,
        "flat_runs": len(flat_hits),
        "conjunctions_per_k": _per_k(len(_CONJ_RE.findall(text)), chars),
        "particles_per_k": _per_k(len(_PARTICLE_RE.findall(text)), chars),
        "filter_words_per_k": _per_k(len(_FILTER_RE.findall(text)), chars),
        "machine_phrase_total": len(_MACHINE_RE.findall(text)),
        "machine_phrase_clusters": clusters,
        "contrast_frames": len(_CONTRAST_RE.findall(text)),
        "disyllabic_fillers": len(_FILLER_RE.findall(text)),
        "tag_variety": tag_variety,
        "paragraphs": len(paragraphs),
        "paragraph_len_cv": round(statistics.pstdev(paragraph_lengths) / statistics.fmean(paragraph_lengths), 2)
        if len(paragraph_lengths) > 1 and statistics.fmean(paragraph_lengths) else 0.0,
        "single_sentence_paragraphs": single_sentence_paragraphs,
        "quote_end_ratio": round(quote_end / quote_paragraphs, 2) if quote_paragraphs else 0.0,
    }
    hits.sort(key=lambda h: (h["start"], h["end"]))
    return {"metrics": metrics, "hits": hits}


METRIC_LABELS = {
    "sentence_len_std": "句长标准差（字，人类偏高）",
    "flat_runs": "句长扁平段数（连续 3 句以上长度接近）",
    "conjunctions_per_k": "连词密度（每千字，AI 偏高）",
    "particles_per_k": "语气词密度（每千字，人类偏高）",
    "filter_words_per_k": "滤镜词密度（每千字）",
    "machine_phrase_total": "高频机器词总数",
    "machine_phrase_clusters": "机器词成群段数（同段 ≥2 个）",
    "contrast_frames": "「不是…而是…」对比框架",
    "disyllabic_fillers": "双音节填充（进行讨论类）",
    "tag_variety": "说话标记花样数（低声道 / 沉声道…）",
    "paragraph_len_cv": "段长变异系数（人类参差）",
    "quote_end_ratio": "引语收段比例",
}


def format_hints(report: dict[str, Any], limit: int = 30) -> str:
    """给 LLM 的本地统计提示块：指标一览 + 候选位置（带原文），只作排查线索。"""
    metrics = report.get("metrics") or {}
    lines = ["指标（本地统计，只是方向）：" + "；".join(f"{label} {metrics.get(key, 0)}" for key, label in METRIC_LABELS.items())]
    hits = list(report.get("hits") or [])[: max(limit, 0)]
    if hits:
        lines.append("候选位置（逐条判断，不成立就不报）：")
        lines.extend(f"- {h['feature']}（原文：“{h['evidence']}”）" for h in hits)
    return "\n".join(lines)


def metrics_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, float]:
    """同时出现在前后两份 metrics 里的数值键：after - before。"""
    out: dict[str, float] = {}
    for key, value in (after or {}).items():
        prev = (before or {}).get(key)
        if isinstance(value, (int, float)) and isinstance(prev, (int, float)):
            delta = value - prev
            out[key] = round(delta, 2) if isinstance(delta, float) else delta
    return out
