"""拆书 V5 派生统计（无 LLM）：结构统计（structure_json）与桥段库聚合（bridges_json）。"""
from __future__ import annotations

from collections import Counter
from typing import Any, Sequence

from app.services.book_dissect.v5_types import PACES, ChapterCard, StoryArc

_LENGTH_BUCKETS = ("1-2", "3", "4", "5-6", "7+")


def _ratio(n: int, d: int, digits: int = 2) -> float:
    return round(n / d, digits) if d else 0.0


def _deciles(items: Sequence[Any]) -> list[list[Any]]:
    n = len(items)
    if n == 0:
        return [[] for _ in range(10)]
    return [items[(n * i) // 10: (n * (i + 1)) // 10] for i in range(10)]


def _length_bucket(length: int) -> str:
    if length <= 2:
        return "1-2"
    if length == 3:
        return "3"
    if length == 4:
        return "4"
    if length <= 6:
        return "5-6"
    return "7+"


def _length_distribution(lengths: Sequence[int]) -> dict[str, int]:
    return {b: sum(1 for n in lengths if _length_bucket(n) == b) for b in _LENGTH_BUCKETS}


def build_structure_stats(cards: Sequence[ChapterCard], arcs: Sequence[StoryArc]) -> dict[str, Any]:
    ordered = sorted(cards, key=lambda c: c.chapter_number)
    n = len(ordered)
    pace = Counter(c.pace for c in ordered)
    hooks = Counter(c.ending_hook_type for c in ordered)
    hook_chapters = sum(1 for c in ordered if c.ending_hook_type != "无")
    payoff_chapters = sum(1 for c in ordered if c.payoff_points)
    tags = Counter(t for c in ordered for t in c.function_tags)
    lengths = [len(a.chapters) for a in arcs]
    seen_types: set[str] = set()
    hook_examples: list[dict[str, Any]] = []
    for c in sorted(ordered, key=lambda c: -c.tension):
        if c.ending_hook_text and c.ending_hook_type != "无" and c.ending_hook_type not in seen_types:
            seen_types.add(c.ending_hook_type)
            hook_examples.append({"chapter": c.chapter_number, "type": c.ending_hook_type, "text": c.ending_hook_text})
        if len(hook_examples) >= 6:
            break
    return {
        "chapter_count": n,
        "avg_chapter_words": int(sum(c.word_count for c in ordered) / n) if n else 0,
        "pace_distribution": {p: _ratio(pace.get(p, 0), n) for p in PACES},
        "tension_by_decile": [round(sum(c.tension for c in d) / len(d), 2) if d else 0.0 for d in _deciles(ordered)],
        "hook_type_distribution": dict(hooks),
        "hook_rate": _ratio(hook_chapters, n),
        "payoff_chapter_rate": _ratio(payoff_chapters, n),
        "payoff_density_chapters": round(n / payoff_chapters, 1) if payoff_chapters else 0.0,
        "function_tag_distribution": dict(tags.most_common()),
        "function_tags_by_decile": [
            [t for t, _ in Counter(t for c in d for t in c.function_tags).most_common(3)] for d in _deciles(ordered)
        ],
        "arc_count": len(arcs),
        "avg_arc_length": round(sum(lengths) / len(lengths), 1) if lengths else 0.0,
        "arc_length_distribution": _length_distribution(lengths),
        "payoff_type_distribution": dict(Counter(a.payoff_type for a in arcs).most_common()),
        "hook_examples": hook_examples,
    }


def build_bridges_payload(arcs: Sequence[StoryArc], cards: Sequence[ChapterCard], *, max_typical: int = 12) -> dict[str, Any]:
    """注入用聚合：每种兑现方式先各取 1 个（峰值张力最高、3-6 章优先），再按张力补满 max_typical。"""
    tension = {c.chapter_number: c.tension for c in cards}

    def score(a: StoryArc) -> tuple[int, int, int]:
        peak = tension.get(a.tension_peak_chapter or -1, 0)
        ideal_len = 1 if 3 <= len(a.chapters) <= 6 else 0
        return (0 if a.origin == "fallback" else 1, peak, ideal_len)

    by_type: dict[str, list[StoryArc]] = {}
    for a in sorted(arcs, key=score, reverse=True):
        by_type.setdefault(a.payoff_type, []).append(a)
    typical: list[StoryArc] = []
    for t in sorted(by_type, key=lambda t: (t == "无强爽点", -len(by_type[t]))):
        typical.append(by_type[t][0])
    rest = sorted((a for a in arcs if a not in typical), key=score, reverse=True)
    typical = (typical + rest)[:max_typical]

    roles = Counter(r for a in arcs for r in a.chapter_roles.values())
    total_roles = sum(roles.values()) or 1
    lengths = [len(a.chapters) for a in arcs]
    chapter_count = len(cards)
    return {
        "pipeline_version": 5,
        "arc_count": len(arcs),
        "avg_arc_length": round(sum(lengths) / len(lengths), 1) if lengths else 0.0,
        "arc_length_distribution": _length_distribution(lengths),
        "payoff_type_distribution": dict(Counter(a.payoff_type for a in arcs).most_common()),
        "payoff_density": f"约每 {round(chapter_count / len(arcs), 1)} 章 1 个情节单元" if arcs else "未识别",
        "typical_arcs": [a.to_dict() for a in typical],
        "role_pattern": {
            "avg_intro_chapters": _ratio(roles.get("intro", 0), len(arcs) or 1),
            "avg_build_chapters": _ratio(roles.get("build", 0), len(arcs) or 1),
            "payoff_position_ratio": _ratio(roles.get("payoff", 0), total_roles),
        },
    }


def format_stats_brief(stats: dict[str, Any]) -> str:
    """给 S3 prompt 的客观数据一段话（≤600 字）。"""
    hooks = "、".join(f"{k} {v} 章" for k, v in sorted(stats["hook_type_distribution"].items(), key=lambda kv: -kv[1])[:5])
    types = "、".join(f"{k} {v}" for k, v in list(stats["payoff_type_distribution"].items())[:6])
    pace = stats["pace_distribution"]
    return (
        f"全书 {stats['chapter_count']} 章，平均每章 {stats['avg_chapter_words']} 字；"
        f"节奏 快 {pace.get('快', 0):.0%} / 中 {pace.get('中', 0):.0%} / 慢 {pace.get('慢', 0):.0%}；"
        f"章末钩子出现率 {stats['hook_rate']:.0%}（{hooks}）；"
        f"约每 {stats['payoff_density_chapters']} 章有 1 章兑现爽点；"
        f"识别出 {stats['arc_count']} 个情节单元，平均 {stats['avg_arc_length']} 章，"
        f"兑现方式分布：{types}；"
        f"张力按十分位：{' / '.join(str(t) for t in stats['tension_by_decile'])}。"
    )
