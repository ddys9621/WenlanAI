"""拆书参考包各维度的三档压缩（light ≤300 字 / medium ≤900 字 / deep ≤2200 字），产出给提示词用的自然文本。

维度和作者自己的规划链用同一套说法：synopsis ≈ 总纲（梗概 / 全书主线 / 分卷）、bridges = 剧情单元库
（卷纲里的一件件事：经过、结束时的变化、长短与强弱交替）、methodology = 写法手册、structure = 节奏统计、
character_archive = 人物功能谱、style = 文风。
"""
from __future__ import annotations

import re
from typing import Any, Optional, Sequence

LEVEL_CHAR_BUDGET = {"light": 300, "medium": 900, "deep": 2200}

_ROLE_LABEL = {"open": "开启", "advance": "推进", "turn": "转折", "close": "收束", "transition": "过渡"}
_METHOD_SECTIONS = (
    ("opening_pattern", "开篇"),
    ("volume_rhythm", "分卷节奏"),
    ("unit_design", "剧情单元设计"),
    ("tension_rhythm", "张弛节奏"),
    ("growth_progression", "成长颗粒度"),
    ("advantage_usage", "特殊能力用法"),
)


def compress_v5(dimension: str, data: Any, level: str) -> str:
    """维度 → 三档文本；未知维度 / 非 dict 返回空串。"""
    if not isinstance(data, dict) or level not in LEVEL_CHAR_BUDGET:
        return ""
    fn = {
        "bridges": _units,
        "synopsis": _synopsis,
        "methodology": _methodology,
        "style": _style,
        "character_archive": _character_archive,
        "structure": _structure,
    }.get(dimension)
    if fn is None:
        return ""
    return _fit(fn(data, level), LEVEL_CHAR_BUDGET[level])


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _s(value: Any, limit: int = 0) -> str:
    text = " ".join(str(value).split()) if value not in (None, "") else ""
    return text[:limit] if limit and len(text) > limit else text


def _fit(text: str, budget: int) -> str:
    text = text.strip()
    if len(text) <= budget:
        return text
    cut = text[:budget].rsplit("\n", 1)[0]
    return (cut if len(cut) >= budget // 2 else text[:budget]) + "\n…（截断）"


def _join(lines: Sequence[Optional[str]]) -> str:
    return "\n".join(line for line in lines if line)


def _top_items(dist: Any, n: int) -> list[tuple[str, Any]]:
    if not isinstance(dist, dict):
        return []
    return sorted(dist.items(), key=lambda kv: -(kv[1] if isinstance(kv[1], (int, float)) else 0))[:n]


def _pct(v: Any) -> str:
    try:
        return f"{float(v):.0%}"
    except (TypeError, ValueError):
        return "—"


def _first_sentence(text: str, limit: int = 80) -> str:
    first = re.split(r"(?<=[。！？!?])", text.strip(), maxsplit=1)[0].strip() if text else ""
    return first[:limit]


def _records(value: Any) -> list[dict]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _texts(value: Any, limit: int, n: int) -> list[str]:
    return [t for t in (_s(x, limit) for x in value[:n]) if t] if isinstance(value, list) else []


def _is_none(text: str) -> bool:
    return text in ("", "无", "没有")


# ---------------------------------------------------------------------------
# bridges：剧情单元库
# ---------------------------------------------------------------------------


def _arc_head(arc: dict) -> str:
    rng = f"第{arc.get('start_chapter')}-{arc.get('end_chapter')}章"
    return f"#{arc.get('arc_index', '?')} {_s(arc.get('title'), 30)}（{rng}｜{_s(arc.get('payoff_type'))}）"


def _arc_block(arc: dict, *, deep: bool) -> str:
    lines = [_arc_head(arc)]
    if arc.get("function"):
        lines.append(f"  作用：{_s(arc['function'], 80)}")
    if arc.get("story"):
        lines.append(f"  经过：{_s(arc['story'], 220 if deep else 140)}")
    if arc.get("turn"):
        lines.append(f"  结束时：{_s(arc['turn'], 100)}")
    if arc.get("payoff"):
        lines.append(f"  高点：{_s(arc['payoff'], 120 if deep else 80)}")
    if deep:
        if arc.get("structure"):
            lines.append(f"  落到章：{_s(arc['structure'], 160)}")
        if arc.get("approach"):
            lines.append(f"  主角靠：{_s(arc['approach'], 120)}")
        if arc.get("emotion_curve"):
            lines.append(f"  情绪：{_s(arc['emotion_curve'], 100)}")
        if arc.get("gains_costs"):
            lines.append(f"  得失：{_s(arc['gains_costs'], 100)}")
        roles = arc.get("chapter_roles")
        if isinstance(roles, dict) and roles:
            lines.append("  章内位置：" + " / ".join(f"{k}{_ROLE_LABEL.get(v, v)}" for k, v in list(roles.items())[:8]))
    return "\n".join(lines)


def _units(data: dict, level: str) -> str:
    typical = _records(data.get("typical_arcs"))
    types = _top_items(data.get("payoff_type_distribution"), 4)
    head = [
        f"原书 {data.get('arc_count', 0)} 个剧情单元，{_s(data.get('payoff_density'))}"
        f"（平均 {data.get('avg_arc_length', '?')} 章，长短按事件大小）",
        "兑现方式：" + "、".join(f"{k}×{v}" for k, v in types) if types else None,
    ]
    if level == "light":
        return _join(head + [f"典型单元：{'；'.join(_arc_head(a) for a in typical[:2])}" if typical else None])
    lengths = data.get("arc_length_distribution")
    if isinstance(lengths, dict) and lengths:
        head.append("单元长度：" + "、".join(f"{k}章 {v}" for k, v in lengths.items()))
    rhythm = _s(data.get("unit_rhythm"))
    if rhythm:
        head.append(f"单元强弱（按顺序）：{rhythm[:30]}；强单元后接缓和 {_pct(data.get('relief_after_strong'))}")
    count, deep = (3, False) if level == "medium" else (6, True)
    blocks = [_arc_block(a, deep=deep) for a in typical[:count]]
    return _join(head + (["【典型单元】"] + blocks if blocks else []))


# ---------------------------------------------------------------------------
# synopsis：全书骨架（≈ 总纲）
# ---------------------------------------------------------------------------


def _advantage(value: Any) -> str:
    """主角的特殊能力 / 核心优势；没有（「无」）返回空串，提示词里就不提。"""
    if isinstance(value, dict):
        what = _s(value.get("what"), 60)
        if _is_none(what):
            return ""
        parts = [what, _s(value.get("how_it_works"), 100)]
        if value.get("limits"):
            parts.append(f"限制：{_s(value['limits'], 60)}")
        evo = _texts(value.get("evolution"), 30, 3)
        if evo:
            parts.append("演进：" + " → ".join(evo))
        return "｜".join(p for p in parts if p)
    text = _s(value, 120)
    return "" if _is_none(text) else text


def _synopsis(data: dict, level: str) -> str:
    lines = [
        f"题材：{_s(data.get('genre_tag'))}" if data.get("genre_tag") else None,
        f"梗概：{_s(data.get('premise'), 150)}" if data.get("premise") else None,
        f"大矛盾：{_s(data.get('main_conflict'), 200)}" if data.get("main_conflict") else None,
    ]
    if level == "light":
        return _join(lines)
    if data.get("main_plot"):
        lines.append(f"全书主线：{_s(data['main_plot'], 320 if level == 'medium' else 600)}")
    advantage = _advantage(data.get("golden_finger"))
    if advantage:
        lines.append(f"主角特殊能力：{advantage}")
    volumes = _records(data.get("volumes"))
    if volumes:
        lines.append("分卷：" + " → ".join(
            f"{_s(v.get('title'), 20)}（第{v.get('chapter_start', '?')}-{v.get('chapter_end', '?')}章）" for v in volumes[:10]
        ))
    selling = _texts(data.get("selling_points"), 40, 5)
    if selling:
        lines.append("卖点：" + "；".join(selling))
    if level == "medium":
        return _join(lines)
    for v in volumes[:8]:
        detail = "；".join(x for x in (
            f"目标 {_s(v.get('goal'), 60)}" if v.get("goal") else "",
            f"高潮 {_s(v.get('climax'), 50)}" if v.get("climax") else "",
            f"卷末 {_s(v.get('ending_hook'), 40)}" if v.get("ending_hook") else "",
        ) if x)
        if detail:
            lines.append(f"- 《{_s(v.get('title'), 20)}》{detail}")
    for key, label in (("growth_route", "成长路线"), ("power_system", "力量体系"), ("ultimate_goal", "终极目标")):
        text = _s(data.get(key), 200)
        if not _is_none(text):
            lines.append(f"{label}：{text}")
    tropes = _texts(data.get("main_tropes"), 20, 6)
    if tropes:
        lines.append("主要套路：" + "、".join(tropes))
    highs = _records(data.get("high_points"))
    if highs:
        lines.append("【高光时刻】")
        lines.extend(
            f"- [{_s(h.get('volume'), 20)}] 铺垫：{_s(h.get('setup'), 60)}；转折：{_s(h.get('trigger'), 60)}；结果：{_s(h.get('result'), 60)}"
            for h in highs[:5]
        )
    fore = _records(data.get("long_foreshadowing"))
    if fore:
        lines.append("长线伏笔：" + "；".join(f"{_s(f.get('setup'), 30)}→{_s(f.get('payoff'), 30)}（{_s(f.get('role'), 20)}）" for f in fore[:5]))
    if data.get("opening_strategy"):
        lines.append(f"开篇策略：{_s(data['opening_strategy'], 300)}")
    return _join(lines)


# ---------------------------------------------------------------------------
# methodology：写法手册
# ---------------------------------------------------------------------------


def _methodology(data: dict, level: str) -> str:
    lines: list[str] = []
    for key, label in _METHOD_SECTIONS:
        item = data.get(key)
        if not isinstance(item, dict):
            continue
        pattern = _s(item.get("pattern"), 120)
        tips = _s(item.get("writing_tips"))
        if level == "light":
            first = _first_sentence(tips) or pattern[:60]
            if first:
                lines.append(f"- {label}：{first}")
            continue
        block = [f"【{label}】{pattern}"]
        if level == "deep" and item.get("evidence"):
            block.append(f"  依据：{_s(item['evidence'], 100)}")
        if tips:
            block.append(f"  ▸ {tips[:120 if level == 'medium' else 300]}")
        lines.append("\n".join(block))
    return _join(lines)


# ---------------------------------------------------------------------------
# style：文风指纹
# ---------------------------------------------------------------------------


def _metrics_line(m: Any) -> str:
    if not isinstance(m, dict) or not m.get("sample_chars"):
        return ""
    return (
        f"量化：平均句长 {m.get('avg_sentence_len', '?')} 字，短段（≤30 字）占 {_pct(m.get('short_paragraph_pct'))}，"
        f"对话段 {_pct(m.get('dialogue_paragraph_pct'))}，问句率 {_pct(m.get('question_ratio'))}，感叹率 {_pct(m.get('exclamation_ratio'))}，"
        f"省略号 {m.get('ellipsis_per_1k', '?')}/千字"
    )


def _style(data: dict, level: str) -> str:
    name = _s(data.get("name")) or "未命名"
    prompt = _s(data.get("prompt_content"))
    if level == "light":
        return f"【文风：{name}】{prompt[:280]}"
    lines = [f"【文风：{name}】{_s(data.get('description'), 100)}", prompt[:700 if level == "medium" else 1200]]
    metrics = _metrics_line(data.get("metrics"))
    if metrics:
        lines.append(metrics)
    if level == "medium":
        return _join(lines)
    if data.get("dialogue_style"):
        lines.append(f"对话：{_s(data['dialogue_style'], 150)}")
    if data.get("narration_habits"):
        lines.append(f"叙述：{_s(data['narration_habits'], 150)}")
    avoid = _texts(data.get("avoid_list"), 30, 5)
    if avoid:
        lines.append("不用的写法：" + "、".join(avoid))
    examples = [e for e in _records(data.get("examples")) if e.get("text")]
    picked = [hit for kind in ("ending_hook", "payoff") if (hit := next((e for e in examples if e.get("kind") == kind), None))]
    if picked:
        lines.append("【原文例句】")
        lines.extend(f"- 第{e.get('chapter', '?')}章（{e.get('kind')}）：{_s(e['text'], 200)}" for e in picked)
    return _join(lines)


# ---------------------------------------------------------------------------
# character_archive：人物功能谱
# ---------------------------------------------------------------------------


def _character_archive(data: dict, level: str) -> str:
    p = data.get("protagonist") if isinstance(data.get("protagonist"), dict) else {}
    lines = [f"主角 {_s(p.get('name')) or '（未命名）'}：{_s(p.get('persona'), 120)}"]
    advantage = _s(p.get("advantage"), 80)
    if not _is_none(advantage):
        lines.append(f"  核心优势：{advantage}")
    if p.get("flaws_and_pressure"):
        lines.append(f"  缺陷/压力：{_s(p['flaws_and_pressure'], 100)}")
    if level == "light":
        return _join(lines)
    allies = _records(data.get("allies"))
    if allies:
        lines.append("盟友：" + "；".join(f"{_s(a.get('name'), 20)}（{_s(a.get('function_role'), 20)}）" for a in allies[:6]))
    antagonists = _records(data.get("antagonists"))
    if antagonists:
        lines.append("对手：" + "；".join(f"{_s(a.get('name'), 20)}（{_s(a.get('tier'), 20)}）" for a in antagonists[:6]))
    if level == "medium":
        return _join(lines)
    track = _records(p.get("growth_track"))
    if track:
        lines.append("主角成长：" + " → ".join(f"{_s(t.get('volume'), 20)}:{_s(t.get('state'), 40)}" for t in track[:8]))
    for a in allies[:4]:
        if a.get("technique"):
            lines.append(f"- {_s(a.get('name'), 20)}用法：{_s(a['technique'], 120)}")
    for a in antagonists[:4]:
        detail = "；".join(x for x in (_s(a.get("conflict_nature"), 60), _s(a.get("escalation"), 80), _s(a.get("outcome"), 60)) if x)
        if detail:
            lines.append(f"- {_s(a.get('name'), 20)}递进：{detail}")
    slots = _records(data.get("function_slots"))
    if slots:
        lines.append("功能位：" + "；".join(f"{_s(s.get('slot'), 20)}—{_s(s.get('how_used'), 60)}" for s in slots[:6]))
    return _join(lines)


# ---------------------------------------------------------------------------
# structure：结构统计
# ---------------------------------------------------------------------------


def _structure(data: dict, level: str) -> str:
    if not data.get("chapter_count"):
        return ""
    pace = data.get("pace_distribution") or {}
    hooks = _top_items(data.get("hook_type_distribution"), 4)
    lines = [
        f"原书 {data.get('chapter_count', '?')} 章，平均每章 {data.get('avg_chapter_words', '?')} 字；"
        f"节奏 快 {_pct(pace.get('快'))} / 中 {_pct(pace.get('中'))} / 慢 {_pct(pace.get('慢'))}",
        f"章末钩子出现率 {_pct(data.get('hook_rate'))}（{'、'.join(f'{k} {v}' for k, v in hooks)}）；"
        f"约每 {data.get('payoff_density_chapters', '?')} 章有 1 章兑现",
    ]
    if level == "light":
        return _join(lines)
    lengths = data.get("arc_length_distribution")
    if isinstance(lengths, dict):
        lines.append(f"剧情单元 {data.get('arc_count', '?')} 个，平均 {data.get('avg_arc_length', '?')} 章；长度分布："
                     + "、".join(f"{k}章 {v}" for k, v in lengths.items()))
    rhythm = _s(data.get("unit_rhythm"))
    if rhythm:
        lines.append(f"单元强弱：{rhythm[:40]}；强单元后接缓和 {_pct(data.get('relief_after_strong'))}")
    types = _top_items(data.get("payoff_type_distribution"), 6)
    if types:
        lines.append("兑现方式：" + "、".join(f"{k} {v}" for k, v in types))
    tension = data.get("tension_by_decile")
    if isinstance(tension, list) and tension:
        lines.append("张力曲线（按全书十分位）：" + " / ".join(str(t) for t in tension))
    if level == "medium":
        return _join(lines)
    by_decile = data.get("function_tags_by_decile")
    if isinstance(by_decile, list) and any(by_decile):
        lines.append("各段主导功能：" + " → ".join("+".join(tags[:2]) if tags else "—" for tags in by_decile))
    examples = [e for e in _records(data.get("hook_examples")) if e.get("text")]
    if examples:
        lines.append("章末钩子示例：" + "；".join(f"第{e.get('chapter')}章[{e.get('type')}]{_s(e['text'], 60)}" for e in examples[:4]))
    return _join(lines)
