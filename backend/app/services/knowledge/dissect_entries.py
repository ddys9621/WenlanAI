"""拆书产物 → 知识库条目草稿（纯函数：不调模型、不碰数据库）。

一本书产出：导读 + 全书骨架 + 人物功能谱 + 写法手册 + 结构统计 + 文风 + 典型片段 + 分卷 + 剧情单元 + 章卡。
每条两份正文：body 保留原名（给作者读、给智能体查细节）；denamed_body 把人名换成功能位（仿写注入用）。
分卷的去名版即「分卷结构模板」（单元序列：作用｜章数｜强弱｜兑现方式）；剧情单元的去名版即「单元节拍模板」
（单元第 k 章的位置、功能、节奏、张力、钩子）。
data 里另存对位用的结构化字段（设计稿 6.10）：章卡 arc_role / unit_pos / unit_len，剧情单元 unit_in_volume /
units_in_volume / strength / length，分卷 arc_indexes / unit_count。
早期 v5 参考包（stages / one_line_premise / top_payoffs / 旧写法手册键 / intro·build·payoff·aftermath）照样转换；
认不出的字段原样列在「其他」里，不丢内容。
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from app.services.book_dissect.v5_types import ChapterCard, StoryArc
from app.services.knowledge.denamer import Denamer, build_name_map
from app.services.knowledge.entry_types import entry_label, entry_layer, entry_sort_order

SUMMARY_MAX = 160
ROLE_LABEL = {"open": "开启", "advance": "推进", "turn": "转折", "close": "收束", "transition": "过渡"}
ROLE_ALIASES = {
    "intro": "open", "setup": "open", "build": "advance", "buildup": "advance", "rising": "advance",
    "payoff": "turn", "climax": "turn", "twist": "turn", "aftermath": "close", "resolution": "close", "ending": "close",
}
SYNOPSIS_FIELDS = (
    ("genre_tag", "题材"), ("premise", "梗概"), ("one_line_premise", "一句话梗概"), ("main_conflict", "大矛盾"),
    ("main_plot", "全书主线"), ("golden_finger", "主角特殊能力"), ("selling_points", "卖点"), ("main_tropes", "主要套路"),
    ("growth_route", "成长路线"), ("growth_system", "成长体系"), ("power_system", "力量体系"),
    ("ultimate_goal", "终极目标"), ("reading_promise", "阅读承诺"), ("opening_strategy", "开篇策略"),
)
SYNOPSIS_LISTS = ("high_points", "top_payoffs", "long_foreshadowing")
SYNOPSIS_SKIP = {"volumes", "stages", "pipeline_version"}
METHOD_SECTIONS = (
    ("opening_pattern", "开篇"), ("volume_rhythm", "分卷节奏"), ("unit_design", "剧情单元设计"),
    ("tension_rhythm", "张弛节奏"), ("growth_progression", "成长颗粒度"), ("advantage_usage", "特殊能力用法"),
    ("opening_hook_pattern", "开篇钩子"), ("facepunch_rhythm", "打脸节奏"), ("highlight_density", "爽点密度"),
    ("power_progression", "实力进阶"), ("golden_finger_pattern", "金手指用法"),
)
METHOD_FIELDS = (("pattern", "规律"), ("evidence", "依据"), ("writing_tips", "写法建议"))
VOLUME_FIELDS = (
    ("summary", "本卷故事"), ("goal", "目标与冲突"), ("core_conflict", "核心冲突"), ("protagonist_goal", "主角目标"),
    ("climax", "卷末高潮"), ("signature_arc", "标志单元"), ("ending_hook", "卷末钩子"), ("growth", "主角成长"),
    ("key_upgrades", "关键提升"),
)
ARC_EXTRA_LABELS = {"protagonist_chain": "推进链", "golden_finger_usage": "主角靠（特殊能力）"}
EXCERPT_KIND = {
    "opening": "开场", "dialogue": "对白", "action": "动作", "payoff": "兑现", "ending_hook": "章末钩子",
    "description": "描写",
}


@dataclass
class DissectSnapshot:
    title: str
    chapter_count: int
    total_words: int
    cards: list[ChapterCard]
    arcs: list[StoryArc]
    synopsis: Optional[dict] = None
    characters: Optional[dict] = None
    methodology: Optional[dict] = None
    structure: Optional[dict] = None
    style: Optional[dict] = None
    arc_extras: dict[int, dict] = field(default_factory=dict)


@dataclass
class EntryDraft:
    entry_key: str
    entry_type: str
    title: str
    summary: str
    body: str
    denamed_body: str
    data: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    chapter_start: Optional[int] = None
    chapter_end: Optional[int] = None
    volume_index: Optional[int] = None
    arc_index: Optional[int] = None
    position: Optional[float] = None
    sort_order: int = 0

    @property
    def layer(self) -> str:
        return entry_layer(self.entry_type)


@dataclass(frozen=True)
class _ArcSlot:
    volume_index: int
    unit_in_volume: int
    units_in_volume: int


@dataclass(frozen=True)
class _ChapterPlace:
    arc_index: int
    role: str
    unit_pos: int
    unit_len: int


def _s(value: Any) -> str:
    return " ".join(str(value).split()) if value not in (None, "") else ""


def _is_none(text: str) -> bool:
    return text in ("", "无", "没有")


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _summary(value: Any) -> str:
    text = _s(value)
    return text if len(text) <= SUMMARY_MAX else text[: SUMMARY_MAX - 1] + "…"


def _first_sentence(value: Any, limit: int = 80) -> str:
    return re.split(r"(?<=[。！？!?])", _s(value), maxsplit=1)[0][:limit]


def _range(start: Optional[int], end: Optional[int]) -> str:
    if start is None:
        return ""
    return f"第{start}章" if end in (None, start) else f"第{start}-{end}章"


def _position(start: int, end: int, total: int) -> float:
    return round((start + end) / 2 / max(total, 1), 4)


def _pct(value: Any) -> str:
    try:
        return f"{float(value):.0%}"
    except (TypeError, ValueError):
        return "—"


def _lines(*parts: Optional[str]) -> str:
    return "\n".join(p for p in parts if p)


def _field(label: str, value: Any) -> Optional[str]:
    text = _s(value)
    return None if _is_none(text) else f"- {label}：{text}"


def _texts(values: Any, sep: str) -> str:
    return sep.join(t for t in (_s(v) for v in values) if t) if isinstance(values, list) else ""


def _records(values: Any) -> list[dict]:
    return [v for v in values if isinstance(v, dict)] if isinstance(values, list) else []


def _pairs(value: Any, unit: str = "") -> str:
    return "、".join(f"{k}{unit} {v}" for k, v in value.items()) if isinstance(value, dict) else ""


def _value_text(value: Any) -> str:
    """认不出的字段也要能读：字典写成「键：值」，列表用分号连起来。"""
    if isinstance(value, dict):
        return "；".join(f"{k}：{t}" for k, t in ((k, _value_text(v)) for k, v in value.items()) if t)
    if isinstance(value, list):
        return "；".join(t for t in (_value_text(v) for v in value) if t)
    return _s(value)


def _first_text(*values: Any) -> str:
    return next((t for t in (_s(v) for v in values) if not _is_none(t)), "")


def _strength(arc: StoryArc, tension: dict[int, int]) -> str:
    peak = max((tension.get(ch, 0) for ch in arc.chapters), default=0)
    return "强" if peak >= 4 else "中" if peak == 3 else "弱"


def _role_of(arc: StoryArc, chapter: int, pos: int, length: int) -> str:
    """章内位置：拆书给了就用（早期的 intro / build / payoff / aftermath 换成现行说法）；没给按位置推。"""
    role = arc.chapter_roles.get(str(chapter), "")
    role = ROLE_ALIASES.get(role, role)
    if role in ROLE_LABEL:
        return role
    return "open" if pos == 1 else "close" if pos == length else "advance"


def _golden_finger(value: Any) -> str:
    if not isinstance(value, dict):
        text = _s(value)
        return "" if _is_none(text) else text
    what = _s(value.get("what"))
    if _is_none(what):
        return ""
    evolution = _texts(value.get("evolution"), " → ")
    parts = [what, _s(value.get("how_it_works")),
             f"限制：{_s(value.get('limits'))}" if _s(value.get("limits")) else "",
             f"演进：{evolution}" if evolution else ""]
    return "；".join(p for p in parts if p)


def resolve_volumes(synopsis: Any, arcs: Sequence[StoryArc]) -> list[dict]:
    """全书骨架的分卷（早期叫 stages）→ 带章号区间的卷；只有单元编号时按单元区间推出章号，推不出的卷跳过。"""
    by_idx = {a.arc_index: a for a in arcs}
    data = synopsis if isinstance(synopsis, dict) else {}
    raw_volumes = _records(data.get("volumes")) or _records(data.get("stages"))
    out: list[dict] = []
    for raw in raw_volumes:
        start, end = _int(raw.get("chapter_start")), _int(raw.get("chapter_end"))
        if start is None or end is None:
            first, last = by_idx.get(_int(raw.get("arc_start"))), by_idx.get(_int(raw.get("arc_end")))
            if first is not None and last is not None:
                start, end = first.start_chapter, last.end_chapter
        if start is None or end is None or end < start:
            continue
        out.append({**raw, "chapter_start": start, "chapter_end": end})
    return out


def _synopsis_entry(data: dict, dn: Denamer) -> EntryDraft:
    special = {
        "golden_finger": _golden_finger(data.get("golden_finger")),
        "selling_points": _texts(data.get("selling_points"), "；"),
        "main_tropes": _texts(data.get("main_tropes"), "、"),
    }
    fields_ = [_field(label, special[key] if key in special else _value_text(data.get(key)))
               for key, label in SYNOPSIS_FIELDS]
    highs, payoffs = _records(data.get("high_points")), _records(data.get("top_payoffs"))
    fores = _records(data.get("long_foreshadowing"))
    known = {k for k, _ in SYNOPSIS_FIELDS} | set(SYNOPSIS_LISTS) | SYNOPSIS_SKIP
    others = [(k, _value_text(v)) for k, v in data.items() if k not in known]
    others = [(k, t) for k, t in others if t]
    body = _lines(
        "# 全书骨架",
        *fields_,
        "## 高光时刻" if highs else None,
        *(f"- [{_s(h.get('volume'))}] 铺垫：{_s(h.get('setup'))}；转折：{_s(h.get('trigger'))}；结果：{_s(h.get('result'))}"
          for h in highs),
        "## 高光兑现" if payoffs else None,
        *(f"- [{_s(p.get('stage'))}] {_s(p.get('arcs'))}：{_s(p.get('buildup'))} → {_s(p.get('trigger'))} → {_s(p.get('reward'))}"
          for p in payoffs),
        "## 长线伏笔" if fores else None,
        *(f"- 埋：{_s(f.get('setup'))} → 揭：{_s(f.get('payoff'))}（{_s(f.get('role'))}）" for f in fores),
        "## 其他" if others else None,
        *(f"- {k}：{t}" for k, t in others),
    )
    genre = _s(data.get("genre_tag"))
    return EntryDraft(
        entry_key="synopsis", entry_type="synopsis", title="全书骨架",
        summary=_summary(_first_text(data.get("premise"), data.get("one_line_premise"), data.get("main_plot"))),
        body=body, denamed_body=dn(body), data=dict(data), tags=[genre] if genre else [],
        sort_order=entry_sort_order("synopsis"),
    )


def _characters_entry(data: dict, dn: Denamer) -> EntryDraft:
    hero = data.get("protagonist") if isinstance(data.get("protagonist"), dict) else {}
    allies, foes = _records(data.get("allies")), _records(data.get("antagonists"))
    slots = _records(data.get("function_slots"))
    track = " → ".join("：".join(x for x in (_s(t.get("volume")), _s(t.get("state"))) if x)
                       for t in _records(hero.get("growth_track")))
    body = _lines(
        "# 人物功能谱",
        f"## 主角：{_s(hero.get('name')) or '（未命名）'}",
        _field("人设", hero.get("persona")),
        _field("核心优势", hero.get("advantage")),
        _field("缺陷与压力", hero.get("flaws_and_pressure")),
        _field("成长轨迹", track),
        "## 盟友" if allies else None,
        *(f"- {_s(a.get('name'))}（{_s(a.get('function_role'))}｜{_s(a.get('arc_span'))}）：{_s(a.get('technique'))}"
          for a in allies),
        "## 对手" if foes else None,
        *(f"- {_s(a.get('name'))}（{_s(a.get('tier'))}）：" + "；".join(
            x for x in (_s(a.get("conflict_nature")), _s(a.get("escalation")), _s(a.get("outcome"))) if x)
          for a in foes),
        "## 功能位" if slots else None,
        *(f"- {_s(s.get('slot'))}：{_s(s.get('how_used'))}" for s in slots),
    )
    return EntryDraft(
        entry_key="characters", entry_type="characters", title="人物功能谱",
        summary=_summary(f"主角{_s(hero.get('persona'))}；盟友 {len(allies)} 人，对手 {len(foes)} 人，功能位 {len(slots)} 个"),
        body=body, denamed_body=dn(body), data=dict(data), sort_order=entry_sort_order("characters"),
    )


def _method_sections(data: dict) -> list[tuple[str, dict]]:
    labels = dict(METHOD_SECTIONS)
    ordered = [k for k, _ in METHOD_SECTIONS if isinstance(data.get(k), dict)]
    ordered += [k for k, v in data.items() if isinstance(v, dict) and k not in labels]
    return [(labels.get(k, k), data[k]) for k in ordered]


def _methodology_entry(data: dict, dn: Denamer) -> EntryDraft:
    blocks: list[Optional[str]] = []
    sections = _method_sections(data)
    for label, item in sections:
        known = dict(METHOD_FIELDS)
        blocks.append(f"## {label}")
        blocks += [_field(name, item.get(key)) for key, name in METHOD_FIELDS]
        blocks += [_field(k, _value_text(v)) for k, v in item.items() if k not in known]
    body = _lines("# 写法手册", *blocks)
    return EntryDraft(
        entry_key="methodology", entry_type="methodology", title="写法手册",
        summary=_summary("、".join(label for label, _ in sections) + "：规律、依据与写法建议"), body=body,
        denamed_body=dn(body), data=dict(data), sort_order=entry_sort_order("methodology"),
    )


def _structure_entry(data: dict, dn: Denamer) -> EntryDraft:
    pace = data.get("pace_distribution") if isinstance(data.get("pace_distribution"), dict) else {}
    tension = [str(t) for t in data.get("tension_by_decile") or []]
    deciles = data.get("function_tags_by_decile") or []
    examples = _records(data.get("hook_examples"))
    payoffs, rhythm = _pairs(data.get("payoff_type_distribution")), _s(data.get("unit_rhythm"))
    tags = _pairs(data.get("function_tag_distribution"))
    body = _lines(
        "# 结构统计",
        f"- 规模：{data.get('chapter_count', 0)} 章，平均每章 {data.get('avg_chapter_words', 0)} 字",
        f"- 节奏：快 {_pct(pace.get('快'))} / 中 {_pct(pace.get('中'))} / 慢 {_pct(pace.get('慢'))}",
        f"- 章末钩子出现率 {_pct(data.get('hook_rate'))}：{_pairs(data.get('hook_type_distribution')) or '—'}",
        f"- 兑现密度：约每 {data.get('payoff_density_chapters', '—')} 章有 1 章兑现",
        f"- 有兑现的章占比：{_pct(data.get('payoff_chapter_rate'))}" if data.get("payoff_chapter_rate") is not None else None,
        f"- 功能标签分布：{tags}" if tags else None,
        f"- 剧情单元 {data.get('arc_count', 0)} 个，平均 {data.get('avg_arc_length', 0)} 章；长度分布："
        f"{_pairs(data.get('arc_length_distribution'), '章') or '—'}",
        f"- 兑现方式：{payoffs}" if payoffs else None,
        f"- 单元强弱（按顺序）：{rhythm}；强单元后接缓和 {_pct(data.get('relief_after_strong'))}" if rhythm else None,
        f"- 张力曲线（全书十分位）：{' / '.join(tension)}" if tension else None,
        "- 各段主导功能：" + " → ".join("+".join(t[:2]) if t else "—" for t in deciles) if any(deciles) else None,
        "## 章末钩子示例" if examples else None,
        *(f"- 第{e.get('chapter')}章［{_s(e.get('type'))}］{_s(e.get('text'))}" for e in examples),
    )
    return EntryDraft(
        entry_key="structure", entry_type="structure", title="结构统计",
        summary="节奏分布、章末钩子、兑现密度、剧情单元长短与强弱、张力曲线", body=body, denamed_body=dn(body),
        data=dict(data), sort_order=entry_sort_order("structure"),
    )


def _style_entries(data: dict, dn: Denamer) -> list[EntryDraft]:
    metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    traits = [t for t in (_s(x) for x in data.get("traits") or []) if t]
    metric_line = (
        f"- 量化：平均句长 {metrics.get('avg_sentence_len', '—')} 字，短段（≤30 字）{_pct(metrics.get('short_paragraph_pct'))}，"
        f"对话段 {_pct(metrics.get('dialogue_paragraph_pct'))}，问句 {_pct(metrics.get('question_ratio'))}，"
        f"感叹 {_pct(metrics.get('exclamation_ratio'))}，省略号 {metrics.get('ellipsis_per_1k', '—')}/千字"
        if metrics.get("sample_chars") else None
    )
    name = _s(data.get("name")) or "文风"
    body = _lines(
        f"# 文风：{name}",
        _field("一句话", data.get("description")),
        "## 写作指令",
        _s(data.get("prompt_content")) or "（无）",
        _field("特征", "；".join(traits)),
        _field("对话", data.get("dialogue_style")),
        _field("叙述", data.get("narration_habits")),
        _field("不用的写法", _texts(data.get("avoid_list"), "；")),
        metric_line,
    )
    drafts = [EntryDraft(
        entry_key="style", entry_type="style", title=f"文风：{name}",
        summary=_summary(data.get("description") or data.get("prompt_content")), body=body, denamed_body=dn(body),
        data={k: v for k, v in data.items() if k != "examples"}, tags=traits[:8], sort_order=entry_sort_order("style"),
    )]
    examples = [e for e in _records(data.get("examples")) if str(e.get("text") or "").strip()]
    for i, item in enumerate(examples, 1):
        kind = EXCERPT_KIND.get(_s(item.get("kind")), _s(item.get("kind")) or "片段")
        chapter = _int(item.get("chapter"))
        text = str(item.get("text") or "").strip()
        head = f"# 典型片段 {i}：{kind}" + (f"（第{chapter}章）" if chapter else "")
        drafts.append(EntryDraft(
            entry_key=f"excerpt:{i}", entry_type="excerpt",
            title=f"片段{i}·{kind}" + (f"·第{chapter}章" if chapter else ""),
            summary=_summary(text), body=f"{head}\n\n{text}", denamed_body=f"{head}\n\n{dn(text)}", data=dict(item),
            tags=[kind], chapter_start=chapter, chapter_end=chapter, sort_order=entry_sort_order("excerpt", i),
        ))
    return drafts


def _volume_entry(index: int, vol: dict, units: Sequence[StoryArc], tension: dict[int, int], total: int,
                  dn: Denamer) -> EntryDraft:
    start, end = vol["chapter_start"], vol["chapter_end"]
    name = _s(vol.get("title")) or f"第{index}卷"
    body = _lines(
        f"# 第{index}卷《{name}》（{_range(start, end)}）",
        *(_field(label, vol.get(key)) for key, label in VOLUME_FIELDS),
        _field("线索", _texts(vol.get("threads"), "；")),
        f"## 剧情单元（{len(units)} 个）" if units else None,
        *(f"{i}. #{a.arc_index}《{_s(a.title)}》{_range(a.start_chapter, a.end_chapter)}｜{len(a.chapters)}章｜"
          f"{_strength(a, tension)}｜{a.payoff_type}" for i, a in enumerate(units, 1)),
    )
    goal = _first_text(vol.get("goal"), "；".join(t for t in (_s(vol.get("protagonist_goal")), _s(vol.get("core_conflict"))) if t))
    avg = round(sum(len(a.chapters) for a in units) / len(units), 1) if units else 0
    template = _lines(
        f"# 分卷结构模板：第{index}卷（{end - start + 1}章，约占全书 {round((start - 1) / max(total, 1) * 100)}%-"
        f"{round(end / max(total, 1) * 100)}%）",
        _field("本卷目标与冲突", dn(goal)),
        _field("卷末高潮", dn(_first_text(vol.get("climax"), vol.get("signature_arc")))),
        _field("卷末钩子", dn(vol.get("ending_hook"))),
        _field("主角成长", dn(_first_text(vol.get("growth"), vol.get("key_upgrades")))),
        f"## 单元序列（{len(units)} 个，平均 {avg} 章）：作用｜章数｜强弱｜兑现方式" if units else None,
        *(f"{i}. {dn(_s(a.function)) or '推进'}｜{len(a.chapters)}章｜{_strength(a, tension)}｜{a.payoff_type}"
          for i, a in enumerate(units, 1)),
    )
    return EntryDraft(
        entry_key=f"volume:{index}", entry_type="volume", title=f"第{index}卷《{name}》",
        summary=_summary(_first_text(vol.get("summary"), goal)), body=body, denamed_body=template,
        data={**vol, "arc_indexes": [a.arc_index for a in units], "unit_count": len(units)},
        chapter_start=start, chapter_end=end, volume_index=index, position=_position(start, end, total),
        sort_order=entry_sort_order("volume", index),
    )


def _beat_line(pos: int, chapter: int, arc: StoryArc, card: Optional[ChapterCard], dn: Denamer) -> str:
    role = ROLE_LABEL[_role_of(arc, chapter, pos, len(arc.chapters))]
    if card is None:
        return f"- 单元第{pos}章（{role}）：本章拆书卡缺失"
    tags = "/".join(card.function_tags) or "—"
    hook = "无钩子" if card.ending_hook_type == "无" else card.ending_hook_type
    return f"- 单元第{pos}章（{role}）［{tags}］{card.pace}·张力{card.tension}·{hook}：{dn(_first_sentence(card.outline))}"


def _arc_entry(arc: StoryArc, extras: dict, cards: dict[int, ChapterCard], slot: Optional[_ArcSlot],
               tension: dict[int, int], total: int, dn: Denamer) -> EntryDraft:
    chapters, strength = arc.chapters, _strength(arc, tension)
    head = f"{len(chapters)}章，{strength}，{arc.payoff_type}"
    others = [(k, _value_text(v)) for k, v in extras.items() if k not in ARC_EXTRA_LABELS and k != "pipeline_version"]
    fields_ = [
        ("作用", _s(arc.function)), ("经过", _s(arc.story)),
        (ARC_EXTRA_LABELS["protagonist_chain"], _value_text(extras.get("protagonist_chain"))),
        ("落到章", _s(arc.structure)), ("主角靠", _s(arc.approach)),
        (ARC_EXTRA_LABELS["golden_finger_usage"], _value_text(extras.get("golden_finger_usage"))),
        ("结束时", _s(arc.turn)), ("情绪", _s(arc.emotion_curve)), ("高点", _s(arc.payoff)),
        ("人物变化", _s(arc.character_changes)), ("得失", _s(arc.gains_costs)), ("留给下一单元", _s(arc.foreshadowing)),
        *others,
    ]
    body = _lines(
        f"# 剧情单元 #{arc.arc_index}《{_s(arc.title)}》（{_range(arc.start_chapter, arc.end_chapter)}，{head}）",
        *(_field(label, text) for label, text in fields_),
    )
    template = _lines(
        f"# 单元节拍模板：{head}",
        *(_field(label, dn(text)) for label, text in fields_ if label != "人物变化"),
        "## 节拍",
        *(_beat_line(pos, ch, arc, cards.get(ch), dn) for pos, ch in enumerate(chapters, 1)),
    )
    gist = _first_text(arc.story, extras.get("protagonist_chain"), arc.function, arc.payoff)
    data = {
        **arc.to_dict(), **extras, "strength": strength, "length": len(chapters),
        "unit_in_volume": slot.unit_in_volume if slot else None,
        "units_in_volume": slot.units_in_volume if slot else None,
    }
    return EntryDraft(
        entry_key=f"arc:{arc.arc_index}", entry_type="arc", title=f"#{arc.arc_index}《{_s(arc.title)}》",
        summary=_summary(f"{arc.payoff_type}·{len(chapters)}章：{gist}"), body=body, denamed_body=template,
        data=data, tags=[arc.payoff_type, strength], chapter_start=arc.start_chapter, chapter_end=arc.end_chapter,
        volume_index=slot.volume_index if slot else None, arc_index=arc.arc_index,
        position=_position(arc.start_chapter, arc.end_chapter, total),
        sort_order=entry_sort_order("arc", arc.arc_index),
    )


def _chapter_entry(card: ChapterCard, place: Optional[_ChapterPlace], volume_index: Optional[int], total: int,
                   dn: Denamer) -> EntryDraft:
    name = _s(card.title) or f"第{card.chapter_number}章"
    hook_text = _s(card.ending_hook_text)
    if card.ending_hook_type == "无":
        hook = None
    elif hook_text:
        hook = f"- 章末钩子：{card.ending_hook_type}｜「{hook_text}」"
    else:
        hook = f"- 章末钩子：{card.ending_hook_type}"
    body = _lines(
        f"# 第{card.chapter_number}章《{name}》",
        f"- 所属剧情单元：#{place.arc_index}（{ROLE_LABEL[place.role]}）· 单元第 {place.unit_pos}/{place.unit_len} 章"
        if place else None,
        _field("章纲", card.outline),
        _field("功能", "、".join(card.function_tags)),
        f"- 节奏：{card.pace}｜张力 {card.tension}/5｜情绪 {_s(card.emotion_tone) or '—'}",
        hook,
        _field("兑现", "；".join(card.payoff_points)),
        _field("亮点", "；".join(card.highlights)),
        _field("出场", "、".join(card.characters)),
        _field("主角变化", card.protagonist_delta),
        _field("新设定", "；".join(card.new_settings)),
    )
    data = {
        **card.to_dict(),
        "arc_role": place.role if place else None,
        "unit_pos": place.unit_pos if place else None,
        "unit_len": place.unit_len if place else None,
    }
    return EntryDraft(
        entry_key=f"chapter:{card.chapter_number}", entry_type="chapter", title=f"第{card.chapter_number}章《{name}》",
        summary=_summary(card.outline), body=body, denamed_body=dn(body), data=data,
        tags=list(dict.fromkeys([*card.function_tags, card.pace, card.ending_hook_type])),
        chapter_start=card.chapter_number, chapter_end=card.chapter_number, volume_index=volume_index,
        arc_index=place.arc_index if place else None,
        position=_position(card.chapter_number, card.chapter_number, total),
        sort_order=entry_sort_order("chapter", card.chapter_number),
    )


def _coverage_line(snap: DissectSnapshot, cards: Sequence[ChapterCard]) -> Optional[str]:
    if not cards:
        return None
    head = f"- 拆书范围：第{cards[0].chapter_number}-{cards[-1].chapter_number}章（{len(cards)} 张章卡"
    if len(cards) < snap.chapter_count:
        return head + f"；原书共 {snap.chapter_count} 章，未拆的部分不在知识库里）"
    return head + "，全书已拆完）"


def _guide_entry(snap: DissectSnapshot, drafts: Sequence[EntryDraft], cards: Sequence[ChapterCard],
                 dn: Denamer) -> EntryDraft:
    count = Counter(d.entry_type for d in drafts)
    volumes = [d.title for d in drafts if d.entry_type == "volume"]
    synopsis = snap.synopsis if isinstance(snap.synopsis, dict) else {}
    directory = [f"- {entry_label(t)}：{count[t]} 条"
                 for t in ("synopsis", "characters", "methodology", "structure", "style", "excerpt") if count[t]]
    if volumes:
        directory.append(f"- 分卷 {len(volumes)} 条：" + "、".join(volumes[:12]) + ("…" if len(volumes) > 12 else ""))
    if count["arc"]:
        directory.append(f"- 剧情单元 {count['arc']} 条：按编号或章号定位（如「#12」「第37章」）")
    if count["chapter"]:
        directory.append(f"- 章卡 {count['chapter']} 条：搜「第N章」直达")
    body = _lines(
        f"# 导读：《{snap.title}》",
        f"- 规模：{snap.chapter_count} 章 · 约 {snap.total_words:,} 字 · {len(volumes)} 卷 · {count['arc']} 个剧情单元",
        _coverage_line(snap, cards),
        _field("题材", synopsis.get("genre_tag")),
        _field("梗概", _first_text(synopsis.get("premise"), synopsis.get("one_line_premise"))),
        "## 条目目录",
        *directory,
        "## 读取路线",
        "| 任务 | 先读 | 再按需读 |",
        "| --- | --- | --- |",
        "| 设计世界观 / 金手指 | 全书骨架（力量体系、主角特殊能力） | 相关章卡的新设定 |",
        "| 设计人物 | 人物功能谱 | 相关剧情单元的人物变化 |",
        "| 规划总纲 | 全书骨架、写法手册 | 结构统计 |",
        "| 规划分卷 | 对应分卷的去名版（分卷结构模板） | 写法手册 · 分卷节奏 |",
        "| 写章纲 | 对应剧情单元的去名版（单元节拍模板） | 该单元各章章卡 |",
        "| 写正文 | 文风 | 典型片段、同位章卡 |",
        "## 仿写边界",
        f"- 以上是《{snap.title}》的设计，不是你作品的设定：学结构、节奏、人物功能和爽点机制。",
        "- 人名、地名、专有设定和具体桥段要换掉；不复制原文句子，片段只用来体会语感。",
    )
    return EntryDraft(
        entry_key="guide", entry_type="guide", title=f"导读：《{snap.title}》",
        summary="先读这一条：全书概况、条目目录、按任务的读取路线与仿写边界", body=body, denamed_body=dn(body),
        data={"counts": dict(count)}, sort_order=entry_sort_order("guide"),
    )


def build_entries(snap: DissectSnapshot) -> list[EntryDraft]:
    dn = Denamer(build_name_map(snap.characters, snap.cards, protected=(snap.title,)))
    cards = sorted((c for c in snap.cards if c.has_content()), key=lambda c: c.chapter_number)
    arcs = sorted(snap.arcs, key=lambda a: a.arc_index)
    total = max([snap.chapter_count, 1, *(c.chapter_number for c in cards), *(a.end_chapter for a in arcs)])
    tension = {c.chapter_number: c.tension for c in cards}
    by_number = {c.chapter_number: c for c in cards}
    volumes = resolve_volumes(snap.synopsis, arcs)
    volume_units = [[a for a in arcs if v["chapter_start"] <= a.start_chapter <= v["chapter_end"]] for v in volumes]

    slots: dict[int, _ArcSlot] = {}
    for vi, units in enumerate(volume_units, 1):
        for k, arc in enumerate(units, 1):
            slots.setdefault(arc.arc_index, _ArcSlot(vi, k, len(units)))
    places: dict[int, _ChapterPlace] = {}
    for arc in arcs:
        chapters = arc.chapters
        for pos, ch in enumerate(chapters, 1):
            places.setdefault(ch, _ChapterPlace(arc.arc_index, _role_of(arc, ch, pos, len(chapters)), pos, len(chapters)))

    def volume_of(chapter: int) -> Optional[int]:
        return next((i for i, v in enumerate(volumes, 1) if v["chapter_start"] <= chapter <= v["chapter_end"]), None)

    drafts: list[EntryDraft] = []
    if isinstance(snap.synopsis, dict):
        drafts.append(_synopsis_entry(snap.synopsis, dn))
    if isinstance(snap.characters, dict):
        drafts.append(_characters_entry(snap.characters, dn))
    if isinstance(snap.methodology, dict) and _method_sections(snap.methodology):
        drafts.append(_methodology_entry(snap.methodology, dn))
    if isinstance(snap.structure, dict) and snap.structure.get("chapter_count"):
        drafts.append(_structure_entry(snap.structure, dn))
    if isinstance(snap.style, dict):
        drafts.extend(_style_entries(snap.style, dn))
    drafts.extend(_volume_entry(i, v, units, tension, total, dn)
                  for i, (v, units) in enumerate(zip(volumes, volume_units), 1))
    drafts.extend(_arc_entry(a, snap.arc_extras.get(a.arc_index, {}), by_number, slots.get(a.arc_index), tension, total, dn)
                  for a in arcs)
    drafts.extend(_chapter_entry(c, places.get(c.chapter_number), volume_of(c.chapter_number), total, dn) for c in cards)
    return [_guide_entry(snap, drafts, cards, dn), *drafts]
