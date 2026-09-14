"""拆书 V5 参考包维度的三档压缩（light ≤300 字 / medium ≤900 字 / deep ≤2200 字）。

各维度按 book_dissect_v5_design.md §5 的分档规则产出给 prompt 用的自然文本；
`pipeline_version < 5` 的老包不走这里（dimension_compressor 按版本分流到通用算法）。
methodology 形状与 V3 相同，仍由通用算法处理。
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

LEVEL_CHAR_BUDGET = {"light": 300, "medium": 900, "deep": 2200}

_ROLE_LABEL = {"intro": "代入", "build": "拉扯", "payoff": "兑现", "aftermath": "善后", "transition": "过渡"}


def compress_v5(dimension: str, data: Any, level: str) -> str:
    """V5 维度 → 三档文本；未知维度 / 非 dict 返回空串。"""
    if not isinstance(data, dict) or level not in LEVEL_CHAR_BUDGET:
        return ""
    fn = {
        "bridges": _bridges,
        "synopsis": _synopsis,
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


# ---------------------------------------------------------------------------
# bridges：桥段库聚合
# ---------------------------------------------------------------------------


def _arc_head(arc: dict) -> str:
    rng = f"第{arc.get('start_chapter')}-{arc.get('end_chapter')}章"
    return f"#{arc.get('arc_index', '?')} {_s(arc.get('title'), 30)}（{rng}｜{_s(arc.get('payoff_type'))}）"


def _arc_block(arc: dict, *, deep: bool) -> str:
    lines = [_arc_head(arc)]
    if arc.get("function"):
        lines.append(f"  功能：{_s(arc['function'], 80)}")
    if arc.get("structure"):
        lines.append(f"  结构：{_s(arc['structure'], 200 if deep else 120)}")
    if arc.get("payoff"):
        lines.append(f"  爽点：{_s(arc['payoff'], 160 if deep else 100)}")
    if deep:
        if arc.get("protagonist_chain"):
            lines.append(f"  行动链：{_s(arc['protagonist_chain'], 200)}")
        if arc.get("emotion_curve"):
            lines.append(f"  情绪曲线：{_s(arc['emotion_curve'], 120)}")
        if arc.get("gains_costs"):
            lines.append(f"  收获/代价：{_s(arc['gains_costs'], 120)}")
        roles = arc.get("chapter_roles")
        if isinstance(roles, dict) and roles:
            lines.append("  章内位置：" + " / ".join(f"{k}{_ROLE_LABEL.get(v, v)}" for k, v in list(roles.items())[:8]))
    return "\n".join(lines)


def _bridges(data: dict, level: str) -> str:
    typical = [a for a in (data.get("typical_arcs") or []) if isinstance(a, dict)]
    types = _top_items(data.get("payoff_type_distribution"), 3)
    head = [
        f"原书识别出 {data.get('arc_count', 0)} 个情节单元，{_s(data.get('payoff_density'))}，平均 {data.get('avg_arc_length', '?')} 章一个单元",
        "常用兑现方式：" + "、".join(f"{k}×{v}" for k, v in types) if types else None,
    ]
    if level == "light":
        return _join(head + [f"典型单元：{'；'.join(_arc_head(a) for a in typical[:2])}" if typical else None])
    roles = data.get("role_pattern") or {}
    if isinstance(roles, dict) and roles:
        head.append(
            f"单元内位置：平均代入 {roles.get('avg_intro_chapters', '?')} 章、拉扯 {roles.get('avg_build_chapters', '?')} 章，"
            f"兑现章占 {_pct(roles.get('payoff_position_ratio'))}"
        )
    count, deep = (3, False) if level == "medium" else (6, True)
    blocks = [_arc_block(a, deep=deep) for a in typical[:count]]
    return _join(head + (["【典型单元】"] + blocks if blocks else []))


# ---------------------------------------------------------------------------
# synopsis：全书骨架
# ---------------------------------------------------------------------------


def _synopsis(data: dict, level: str) -> str:
    lines = [
        f"题材：{_s(data.get('genre_tag'))}" if data.get("genre_tag") else None,
        f"一句话：{_s(data.get('one_line_premise'), 150)}" if data.get("one_line_premise") else None,
        f"大矛盾：{_s(data.get('main_conflict'), 200)}" if data.get("main_conflict") else None,
    ]
    if level == "light":
        return _join(lines)
    gf = data.get("golden_finger")
    if isinstance(gf, dict) and (gf.get("what") or gf.get("how_it_works")):
        evo = gf.get("evolution")
        evo_text = f"；演进：{' → '.join(_s(e, 40) for e in evo[:3])}" if isinstance(evo, list) and evo else ""
        lines.append(f"金手指：{_s(gf.get('what'), 60)}｜{_s(gf.get('how_it_works'), 120)}{evo_text}")
    stages = [s for s in (data.get("stages") or []) if isinstance(s, dict)]
    if stages:
        lines.append("阶段：" + " → ".join(
            f"{_s(s.get('title'), 20)}（第{s.get('chapter_start', '?')}-{s.get('chapter_end', '?')}章）" for s in stages[:10]
        ))
    if data.get("reading_promise"):
        lines.append(f"卖点/读者预期：{_s(data['reading_promise'], 150)}")
    if level == "medium":
        return _join(lines)
    payoffs = [p for p in (data.get("top_payoffs") or []) if isinstance(p, dict)]
    if payoffs:
        lines.append("【高光爽点】")
        lines.extend(
            f"- [{_s(p.get('stage'), 20)}] 铺垫：{_s(p.get('buildup'), 60)}；触发：{_s(p.get('trigger'), 60)}；收获：{_s(p.get('reward'), 60)}"
            for p in payoffs[:5]
        )
    if data.get("growth_system"):
        lines.append(f"成长体系：{_s(data['growth_system'], 200)}")
    if data.get("power_system") and _s(data["power_system"]) != "无":
        lines.append(f"力量体系：{_s(data['power_system'], 200)}")
    fore = [f for f in (data.get("long_foreshadowing") or []) if isinstance(f, dict)]
    if fore:
        lines.append("长线伏笔：" + "；".join(f"{_s(f.get('setup'), 30)}→{_s(f.get('payoff'), 30)}（{_s(f.get('role'), 20)}）" for f in fore[:5]))
    if data.get("opening_strategy"):
        lines.append(f"开篇策略：{_s(data['opening_strategy'], 300)}")
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
    avoid = data.get("avoid_list")
    if isinstance(avoid, list) and avoid:
        lines.append("不用的写法：" + "、".join(_s(a, 30) for a in avoid[:5]))
    examples = [e for e in (data.get("examples") or []) if isinstance(e, dict) and e.get("text")]
    picked: list[dict] = []
    for kind in ("ending_hook", "payoff"):
        hit = next((e for e in examples if e.get("kind") == kind), None)
        if hit:
            picked.append(hit)
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
    if p.get("golden_finger"):
        lines.append(f"  金手指：{_s(p['golden_finger'], 80)}")
    if p.get("flaws_and_pressure"):
        lines.append(f"  缺陷/压力：{_s(p['flaws_and_pressure'], 100)}")
    if level == "light":
        return _join(lines)
    allies = [a for a in (data.get("allies") or []) if isinstance(a, dict)]
    if allies:
        lines.append("盟友：" + "；".join(f"{_s(a.get('name'), 20)}（{_s(a.get('function_role'), 20)}）" for a in allies[:6]))
    antagonists = [a for a in (data.get("antagonists") or []) if isinstance(a, dict)]
    if antagonists:
        lines.append("反派：" + "；".join(f"{_s(a.get('name'), 20)}（{_s(a.get('tier'), 20)}）" for a in antagonists[:6]))
    if level == "medium":
        return _join(lines)
    track = p.get("growth_track")
    if isinstance(track, list) and track:
        lines.append("主角成长：" + " → ".join(
            f"{_s(t.get('stage'), 20)}:{_s(t.get('state'), 40)}" for t in track[:8] if isinstance(t, dict)
        ))
    for a in allies[:4]:
        if a.get("technique"):
            lines.append(f"- {_s(a.get('name'), 20)}用法：{_s(a['technique'], 120)}")
    for a in antagonists[:4]:
        detail = "；".join(x for x in (_s(a.get("conflict_nature"), 60), _s(a.get("escalation"), 80), _s(a.get("outcome"), 60)) if x)
        if detail:
            lines.append(f"- {_s(a.get('name'), 20)}递进：{detail}")
    slots = [s for s in (data.get("function_slots") or []) if isinstance(s, dict)]
    if slots:
        lines.append("功能位：" + "；".join(f"{_s(s.get('slot'), 20)}—{_s(s.get('how_used'), 60)}" for s in slots[:6]))
    return _join(lines)


# ---------------------------------------------------------------------------
# structure：结构统计
# ---------------------------------------------------------------------------


def _structure(data: dict, level: str) -> str:
    pace = data.get("pace_distribution") or {}
    hooks = _top_items(data.get("hook_type_distribution"), 4)
    lines = [
        f"原书 {data.get('chapter_count', '?')} 章，平均每章 {data.get('avg_chapter_words', '?')} 字；"
        f"节奏 快 {_pct(pace.get('快'))} / 中 {_pct(pace.get('中'))} / 慢 {_pct(pace.get('慢'))}",
        f"章末钩子出现率 {_pct(data.get('hook_rate'))}（{'、'.join(f'{k} {v}' for k, v in hooks)}）；"
        f"约每 {data.get('payoff_density_chapters', '?')} 章 1 章兑现爽点",
    ]
    if level == "light":
        return _join(lines)
    lengths = data.get("arc_length_distribution")
    if isinstance(lengths, dict):
        lines.append(f"情节单元 {data.get('arc_count', '?')} 个，平均 {data.get('avg_arc_length', '?')} 章；长度分布："
                     + "、".join(f"{k}章 {v}" for k, v in lengths.items()))
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
    examples = [e for e in (data.get("hook_examples") or []) if isinstance(e, dict) and e.get("text")]
    if examples:
        lines.append("章末钩子示例：" + "；".join(f"第{e.get('chapter')}章[{e.get('type')}]{_s(e['text'], 60)}" for e in examples[:4]))
    return _join(lines)
