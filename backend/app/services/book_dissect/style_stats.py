"""拆书 V5 S4a：纯代码文风量化指标（无 LLM、无分词依赖）。

统计基于正则与字符计数，不做分词；高频口头禅（catchphrases）留待后续用 n-gram + 角色名过滤补。
"""
from __future__ import annotations

import re
from typing import Any, Sequence

_SENT_END = re.compile(r"[。！？!?]+[」”’』]?|……|…")
_DIALOGUE = re.compile(r"[「“][^」”]{1,300}[」”]")
_DIALOGUE_START = ("「", "“", "\"")
_LEN_BUCKETS = ("≤10", "11-20", "21-30", ">30")


def pick_even_indices(n: int, k: int) -> list[int]:
    """在 [1, n-2] 内均匀取 k 个下标（避开首末章）；n 太小时返回全部。"""
    if n <= k + 2:
        return list(range(n))
    body = n - 2
    step = body / k
    return [1 + int(i * step + step / 2) for i in range(k)]


def _bucket(n: int) -> str:
    return "≤10" if n <= 10 else "11-20" if n <= 20 else "21-30" if n <= 30 else ">30"


def compute_style_metrics(texts: Sequence[str]) -> dict[str, Any]:
    paragraphs = [p.strip() for t in texts for p in (t or "").split("\n") if p.strip()]
    total_chars = sum(len(p) for p in paragraphs)
    if total_chars == 0:
        return {"sample_chars": 0}
    sentences: list[str] = []
    for p in paragraphs:
        sentences.extend(s.strip() for s in _SENT_END.split(p) if s and s.strip())
    sent_lens = [len(s) for s in sentences] or [0]
    n_sent = len(sentences) or 1
    joined = "\n".join(paragraphs)
    dialogue_chars = sum(len(m.group(0)) for m in _DIALOGUE.finditer(joined))
    terminators = sum(len(_SENT_END.findall(p)) for p in paragraphs)
    single_sentence_paras = sum(1 for p in paragraphs if len(_SENT_END.findall(p)) <= 1)

    dist = {b: 0 for b in _LEN_BUCKETS}
    for n in sent_lens:
        dist[_bucket(n)] += 1
    return {
        "sample_chars": total_chars,
        "avg_sentence_len": round(sum(sent_lens) / len(sent_lens), 1),
        "sentence_len_dist": {b: round(v / len(sent_lens), 2) for b, v in dist.items()},
        "avg_paragraph_len": round(total_chars / len(paragraphs), 1),
        "short_paragraph_pct": round(sum(1 for p in paragraphs if len(p) <= 30) / len(paragraphs), 2),
        "single_sentence_paragraph_pct": round(single_sentence_paras / len(paragraphs), 2),
        "dialogue_char_ratio": round(dialogue_chars / total_chars, 2),
        "dialogue_paragraph_pct": round(sum(1 for p in paragraphs if p.startswith(_DIALOGUE_START)) / len(paragraphs), 2),
        "question_ratio": round((joined.count("？") + joined.count("?")) / n_sent, 2),
        "exclamation_ratio": round((joined.count("！") + joined.count("!")) / n_sent, 2),
        "ellipsis_per_1k": round((joined.count("……") + joined.count("...")) / total_chars * 1000, 2),
        "dash_per_1k": round(joined.count("——") / total_chars * 1000, 2),
        "le_per_100": round(joined.count("了") / total_chars * 100, 2),
        "de_per_100": round(joined.count("的") / total_chars * 100, 2),
        "terminators_per_paragraph": round(terminators / len(paragraphs), 2),
    }


def format_metrics_brief(m: dict[str, Any]) -> str:
    if not m or not m.get("sample_chars"):
        return "（无统计）"
    return (
        f"统计样本 {m['sample_chars']} 字：平均句长 {m.get('avg_sentence_len')} 字"
        f"（≤10 字句占 {m.get('sentence_len_dist', {}).get('≤10', 0):.0%}），平均段长 {m.get('avg_paragraph_len')} 字，"
        f"短段（≤30 字）占 {m.get('short_paragraph_pct', 0):.0%}，对话字符占 {m.get('dialogue_char_ratio', 0):.0%}，"
        f"对话段占 {m.get('dialogue_paragraph_pct', 0):.0%}，问句率 {m.get('question_ratio', 0):.0%}，感叹率 {m.get('exclamation_ratio', 0):.0%}，"
        f"省略号 {m.get('ellipsis_per_1k')}/千字，破折号 {m.get('dash_per_1k')}/千字，「了」{m.get('le_per_100')}/百字，「的」{m.get('de_per_100')}/百字。"
    )
