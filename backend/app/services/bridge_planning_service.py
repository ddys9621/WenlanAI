"""工程化桥段流水线 — 桥段规划服务。

三段式（设计文档 @/agent-docs/features/engineered_bridge_pipeline.md）：
1. plan_bridges：按主线节点由代码算出槽位表，建 N 个 status=draft 的桥段（无 LLM）
2. fill_bridges：按主线节点分批调 LLM 填 title/goal/爽点/四章卡/伏笔计划 → ready（可续跑；滚动规划只填近处）
3. expand_bridge_to_chapters：把 ready 桥段展开为其章号区间（变长桥段 3-12 章；旧数据每桥段 4 章）的章纲，
   带叙事任务（伏笔 / 承诺），回写剧情线节点覆盖账本
4. CRUD：列表、读取、删除、重置

调用 V4.3 PromptAssembler 获取拆书参考包注入的 prompt 上下文。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter_outline import ChapterOutline
from app.models.chapter_outline_plot_line_link import ChapterOutlinePlotLineLink
from app.models.plot_bridge import PlotBridge
from app.models.plot_card import PlotCard
from app.models.plot_card_chapter_outline_link import PlotCardChapterOutlineLink
from app.models.plot_line import PlotLine
from app.models.project import Project
from app.models.story_outline import StoryOutline
from app.services.bridge_prompt_context import (
    actual_progress_block,
    beat_facts_lines,
    build_fill_provenance,
    filled_ledger_block,
    foreshadow_plan_block,
    next_bridge_block,
    open_promises_block,
    opening_block,
    pov_line,
    prev_bridge_last_chapter_block,
    story_core_lines,
    written_upto,
)
from app.services.bridge_rhythm import RHYTHM_FILL_RULES, RHYTHM_LABELS, position_note, positions_for
from app.services.narrative_tasks import has_tasks, normalize_narrative_tasks
from app.services.platform_presets import default_chapter_words
from app.services.bridge_hook_style import (
    C3_HOOK_NONE,
    expansion_c3_rule,
    methodology_for,
    normalize_c3_hook_style,
)
from app.services.bridge_phases import (
    PHASE_SPLIT_MIN_BRIDGES,
    parse_phases,
    phase_facts,
    phase_for_bridge,
    phase_ranges,
    render_phase_block,
    render_phase_split_task,
)
from app.services.bridge_shapes import (
    SHAPE_STANDARD,
    bridge_shape,
    climax_beat_index,
    shape_expansion_block,
    shape_fill_rule,
    shape_label,
)
from app.services.bridge_slot_planner import (
    BridgePlanningConflictError,
    BridgePlanningPreconditionError,
    BridgeSlotPlan,
    PlotLineData,
    bridge_chapter_range,
    compute_bridge_slots,
    parse_plot_line,
)
from app.services.bridge_templates import BridgeTemplate, resolve_template
from app.services.generation_trace import stage_scope
from app.services.reference_pack import (
    AssemblyContext,
    PromptAssembler,
)
from app.services.reference_pack.policy_tables import get_policy
from app.services.reference_pack.slot_builders import get_first_attached_pack
from app.utils.json_cleaner import parse_partial_json, safe_parse_json
from app.utils.story_outline_fields import parse_story_outline_fields

logger = logging.getLogger(__name__)


def bridge_to_dict(b: PlotBridge) -> dict[str, Any]:
    """ORM → API dict：解析 secondary_beats / generation_meta JSON，补 chapter_start/chapter_end。"""
    try:
        secondary = json.loads(b.secondary_beats) if b.secondary_beats else []
    except (json.JSONDecodeError, TypeError):
        secondary = []
    try:
        meta = json.loads(b.generation_meta) if b.generation_meta else None
    except (json.JSONDecodeError, TypeError):
        meta = None
    if not isinstance(meta, dict):
        meta = None
    try:
        foreshadow_plan = json.loads(b.foreshadow_plan) if getattr(b, "foreshadow_plan", None) else None
    except (json.JSONDecodeError, TypeError):
        foreshadow_plan = None
    c_start, c_end = bridge_chapter_range(b)
    return {
        "id": b.id,
        "project_id": b.project_id,
        "bridge_number": b.bridge_number,
        "title": b.title,
        "goal": b.goal,
        "showoff_point": b.showoff_point,
        "payoff_type": b.payoff_type,
        "golden_finger_usage": b.golden_finger_usage,
        "c1_intro": b.c1_intro,
        "c2_build": b.c2_build,
        "c3_payoff": b.c3_payoff,
        "c4_aftermath": b.c4_aftermath,
        "next_bridge_hook": b.next_bridge_hook,
        "status": b.status,
        "order_index": b.order_index,
        "plot_line_id": b.plot_line_id,
        "beat_index": b.beat_index,
        "beat_coverage_start": b.beat_coverage_start,
        "beat_coverage_end": b.beat_coverage_end,
        "secondary_beats": secondary if isinstance(secondary, list) else [],
        "chapter_start": c_start,
        "chapter_end": c_end,
        "chapter_count": c_end - c_start + 1,
        "rhythm_role": getattr(b, "rhythm_role", None),
        "foreshadow_plan": foreshadow_plan if isinstance(foreshadow_plan, dict) else None,
        "generation_meta": meta,
        "template": meta.get("template") if meta else None,
    }


async def load_plot_line_data(db: AsyncSession, project_id: str) -> list[PlotLineData]:
    result = await db.execute(
        select(PlotLine).where(PlotLine.project_id == project_id).order_by(PlotLine.order_index)
    )
    return [parse_plot_line(line) for line in result.scalars().all()]


async def _bridge_shape_for(db: AsyncSession, bridge: PlotBridge) -> str:
    """桥段形态：需要主线节点权重找全书高潮节点；桥段未绑节点 → standard。"""
    if not bridge.plot_line_id or bridge.beat_index is None:
        return SHAPE_STANDARD
    line = (await db.execute(select(PlotLine).where(PlotLine.id == bridge.plot_line_id))).scalar_one_or_none()
    climax = climax_beat_index(parse_plot_line(line)) if line is not None else None
    return bridge_shape(bridge.beat_coverage_end, bridge.beat_index, climax)


def _opt_index(raw_beat: dict[str, Any]) -> int | None:
    try:
        return int(raw_beat.get("index"))
    except (TypeError, ValueError):
        return None


def _task_progress_text(t: dict[str, Any]) -> str:
    """副线任务进度文案；保温任务且节点已完成（coverage 1→1）时不显示误导性的 100%→100%。"""
    start, end = float(t.get("coverage_start", 0)), float(t.get("coverage_end", 0))
    if t.get("role", "primary") == "mention" and start >= 1.0 and end >= 1.0:
        return "（已完成，只带过现状）"
    return f"进度 {start * 100:.0f}% → {end * 100:.0f}%"


def _secondary_task_line(t: dict[str, Any], *, with_desc: bool) -> str:
    text = (
        f"- {t.get('line_type')}《{t.get('line_title')}》[节点 {t.get('beat_index')}] {t.get('beat_title')}："
        f"{_task_progress_text(t)}"
    )
    if with_desc and t.get("beat_description"):
        text += f"｜{str(t['beat_description'])[:120]}"
    return text


async def _load_beat_context_for_bridge(
    db: AsyncSession, bridge: PlotBridge
) -> str:
    """V4.1 方案 C：为 expand_bridge_to_chapters 构造「本桥段所属节点 + 进度区间 +
    前后节点」上下文，供 LLM 写章纲时保持主线连贯。

    返回空串当桥段没绑节点（free 模式）或剧情线缺数据 — 上层 prompt 自然退化为只用
    桥段四章方法论的老路径。

    返回的文本块结构示例：
        【📍 桥段所属节点（V4.1 方案 C 分层契合）】
        - 剧情线：主线《青云路》
        - 所属节点：[节点 2] 历劫渡难（权重 25%）
          描述：主角第一次遭遇宗门内斗...
        - 本桥段在该节点占进度：25% - 50%（共 4 桥段中的第 2 个）
        - 上一节点：[节点 1] 拜入门派（已收尾）
        - 下一节点：[节点 3] 灵兽试炼（待开启）

        请确保 4 章内容在节点主题内推进，C4 末尾对应进度 50%。
    """
    if not bridge.plot_line_id or bridge.beat_index is None:
        return ""

    line_result = await db.execute(
        select(PlotLine).where(PlotLine.id == bridge.plot_line_id)
    )
    plot_line = line_result.scalar_one_or_none()
    if not plot_line or not plot_line.timeline_data:
        return ""

    beats = list(parse_plot_line(plot_line).beats)   # 已按 index 排序
    if not beats:
        return ""

    # 找到对应 beat（按 index 匹配；找不到容错）
    current_beat = next((b for b in beats if b.index == bridge.beat_index), None)
    if not current_beat:
        return ""

    line_type_label = {
        "main": "主线",
        "sub": "支线",
        "character": "角色线",
    }.get(plot_line.line_type or "main", "其他")

    cs = bridge.beat_coverage_start
    ce = bridge.beat_coverage_end
    coverage_text = (
        f"{int((cs or 0) * 100)}% - {int((ce or 0) * 100)}%"
        if cs is not None and ce is not None
        else "未指定"
    )

    lines = ["【📍 桥段所属节点（V4.1 方案 C 分层契合）】"]
    lines.append(f"- 剧情线：{line_type_label}《{plot_line.title}》")
    cur_idx = current_beat.index
    lines.append(f"- 所属节点：[节点 {cur_idx}] {current_beat.title}（权重 {current_beat.weight:.0%}）")
    if current_beat.description:
        lines.append(f"  描述：{current_beat.description[:200]}")
    lines.extend(beat_facts_lines(current_beat))
    if current_beat.review_note:
        lines.append(f"  上一卷复盘修正（按它调整本段章纲）：{current_beat.review_note[:300]}")
    lines.append(f"- 本桥段在该节点覆盖进度：{coverage_text}")
    phase = phase_for_bridge(current_beat.phases, bridge.bridge_number) if current_beat.phases else None
    if phase:
        lines.append(
            f"- 所属阶段：阶段 {phase['index']}/{len(current_beat.phases)}《{phase['title']}》"
            f"（桥段 {phase['bridge_start']}-{phase['bridge_end']}）：{phase['goal']}"
        )
        facts = phase_facts(phase)
        if facts:
            lines.append(f"  {facts}")

    # 前后节点摘要
    prev_beat = next((b for b in reversed(beats) if b.index < cur_idx), None)
    next_beat = next((b for b in beats if b.index > cur_idx), None)
    if prev_beat:
        lines.append(f"- 上一节点：[节点 {prev_beat.index}] {prev_beat.title}（已收尾）")
    if next_beat:
        lines.append(f"- 下一节点：[节点 {next_beat.index}] {next_beat.title}（待开启）")

    lines.append("")
    end_pct = int((ce or 0) * 100) if ce is not None else None
    if end_pct is not None:
        lines.append(
            f"请确保 4 章内容在节点主题内推进，C4 章末尾对应节点进度推进到 ~{end_pct}%。"
        )
    else:
        lines.append("请确保 4 章内容在节点主题内推进，C4 章末尾给下一节点留好引子。")

    try:
        secondary = json.loads(bridge.secondary_beats) if bridge.secondary_beats else []
    except (json.JSONDecodeError, TypeError):
        secondary = []
    if secondary:
        primary = [t for t in secondary if isinstance(t, dict) and t.get("role", "primary") != "mention"]
        mention = [t for t in secondary if isinstance(t, dict) and t.get("role", "primary") == "mention"]
        if primary:
            lines.append("")
            lines.append("【🧵 副线任务 · 主 B 线（本桥段 4 章内须推进到位，不得抢占主线爽点）】")
            lines.extend(_secondary_task_line(t, with_desc=True) for t in primary)
        if mention:
            lines.append("")
            lines.append("【🧵 副线任务 · 保温提及（一句话带过现状，不展开新事件）】")
            lines.extend(_secondary_task_line(t, with_desc=False) for t in mention)
    return "\n".join(lines)


# 每次 LLM 调用最多填几个桥段：推理模型一次输出 10+ 桥段（7-9K tokens）必被 max_tokens 截断
FILL_BATCH_MAX = 4

BRIDGE_FILL_TASK_PROMPT = """请为下面 {count} 个桥段槽位填写内容。槽位的编号、所属节点、覆盖区间、章号已由系统确定，**只填创意内容**。

# 桥段四章方法论（{template_name}）
{methodology}

# 桥段长度与节奏
- 桥段章数以槽位表为准（3-12 章不等）：多出的章是加长的拉扯、第二波兑现或收尾的缓冲章；c1-c4 四张卡分别写开场 / 拉扯 / 兑现 / 收尾四个阶段的设计，展开章纲时按章数分配
{rhythm_rules}

# 本节点全部槽位（标 ★ 的 {count} 个为本批要填的，其余仅供衔接参考）
{slot_table}

# 约束
- 只输出标 ★ 的 {count} 个对象，严格按槽位顺序，`bridge_number` 必须与槽位一致
- 每个桥段的 goal 必须落在所属节点主题内，进度按覆盖区间推进（区间末尾对应节点完成度）
- 标「主B线」的桥段：该支线节点所述事件必须在本桥段内发生并推进到位（建议放开场下半或收尾，不得抢占主线{payoff_label}）
- 标「保温」的支线：只需一句话带过其现状，不得展开新事件
- 金手指使用方式在相邻桥段间不得重复
- payoff_type 只能从列表中选：{payoff_types}；相邻桥段不得同型，参考账本里的「兑现方式累计」优先选全书用得少的
- 人名、地名、势力名只能使用【本书角色】【世界规则表】里已有的；确需新角色时在 goal 里用“新角色：身份”标注
- 最后一个桥段的 next_bridge_hook 要为下一节点开头留引子
- foreshadow_plan（可空）：plant = 本桥段要埋下的长线伏笔（最多 2 条，payoff_after = 计划多少章后回收，长线可以几十上百章）；payoff = 本桥段要回收的旧伏笔标题（只能来自【当前未回收的伏笔】，标了"临近 / 超期"的优先）
- 已有【实际剧情进展】时以它为准：已经发生的事不能改，计划与实际冲突时顺着实际往下规划
{extra_constraints}

# 输出格式（纯 JSON 数组，不要 markdown）
[
  {{
    "bridge_number": <槽位编号>,
    "title": "桥段简洁标题（8-15 字）",
    "goal": "本桥段要解决的具体问题（30-60 字）",
    "showoff_point": "{payoff_hint}（40-80 字）",
    "payoff_type": "兑现方式，从【{payoff_types}】中选一个原词",
    "golden_finger_usage": "{golden_finger_hint}（20-40 字）",
    "c1_intro": "{c1_hint}（80-120 字）",
    "c2_build": "{c2_hint}（80-120 字）",
    "c3_payoff": "{c3_hint}（80-120 字）",
    "c4_aftermath": "{c4_hint}（60-100 字）",
    "next_bridge_hook": "给下一桥段的钩子（20-40 字）",
    "foreshadow_plan": {{"plant": [{{"title": "伏笔名", "content": "怎么埋（20-40 字）", "payoff_after": 60}}], "payoff": ["要回收的旧伏笔标题"]}}
  }}
]
"""


def render_fill_task(
    template: BridgeTemplate,
    count: int,
    slot_table: str,
    shape_rules: tuple[str, ...] = (),
    c3_hook_style: str = C3_HOOK_NONE,
    rhythm_rules: tuple[str, ...] = (),
) -> str:
    """按题材模板渲染填充任务段；shape_rules = 本批收官 / 高潮桥段的形态约束行；c3_hook_style = C3 章末风格；
    rhythm_rules = 本批桥段节奏角色（卷中高潮 / 低谷 / 卷末收官…）对应的写法。"""
    return BRIDGE_FILL_TASK_PROMPT.format(
        count=count,
        template_name=template.name,
        methodology=methodology_for(template.methodology, c3_hook_style),
        rhythm_rules="\n".join(f"- {r}" for r in rhythm_rules),
        slot_table=slot_table,
        payoff_label=template.payoff_label,
        payoff_types=" / ".join(template.payoff_types),
        extra_constraints="\n".join(f"- {c}" for c in (*template.extra_constraints, *shape_rules)),
        payoff_hint=template.payoff_hint,
        golden_finger_hint=template.golden_finger_hint,
        c1_hint=template.card_hints["c1_intro"],
        c2_hint=template.card_hints["c2_build"],
        c3_hint=template.card_hints["c3_payoff"],
        c4_hint=template.card_hints["c4_aftermath"],
    )


@dataclass
class FillContext:
    text: str
    story_fields: list[str]
    next_beat_title: str | None
    prev_bridge_number: int | None
    ledger_numbers: list[int]
    opening: bool
    phase: dict[str, Any] | None = None   # {"index", "title", "count"}；节点未拆阶段时 None


OPENING_C1_RULE = "本桥段是开篇桥段（黄金三章）：C1 日常代入压缩到不超过章篇幅的 1/3，其余篇幅直接进入钩子"
CONTINUED_C1_RULE = (
    "本桥段非开篇：C1 前 1/4 直接承接上桥段的收尾与钩子（人物已在路上 / 已到现场），"
    "不得写无关日常、不得重述前情，其余篇幅进入本桥段的信息差"
)


_FILL_FIELDS = (
    "title", "goal", "showoff_point", "golden_finger_usage",
    "c1_intro", "c2_build", "c3_payoff", "c4_aftermath", "next_bridge_hook",
)
_FILL_SHORT_FIELDS = {"title": 200, "goal": 500, "showoff_point": 500}

# 滚动规划前瞻：桥段填充只做到已写章节之后约 3 个剧情单元；章纲展开只做到之后约 3 个桥段
FILL_LOOKAHEAD_CHAPTERS = 48
EXPAND_LOOKAHEAD_CHAPTERS = 12
FORESHADOW_PLANT_MAX = 2
FORESHADOW_PAYOFF_MAX = 3


def normalize_foreshadow_plan(raw: Any) -> str | None:
    """桥段伏笔计划 → 规整 JSON（plant ≤2 条含 payoff_after，payoff ≤3 个旧伏笔标题）；空 / 坏数据 → None。"""
    if not isinstance(raw, dict):
        return None
    plant = []
    for item in raw.get("plant") or []:
        if not isinstance(item, dict) or not str(item.get("title") or "").strip():
            continue
        try:
            payoff_after = int(item.get("payoff_after")) if item.get("payoff_after") is not None else None
        except (TypeError, ValueError):
            payoff_after = None
        plant.append({
            "title": str(item["title"]).strip()[:60],
            "content": str(item.get("content") or "").strip()[:160],
            "payoff_after": payoff_after if payoff_after and payoff_after > 0 else None,
        })
    payoff = [str(t).strip()[:60] for t in (raw.get("payoff") or []) if str(t).strip()]
    plan = {"plant": plant[:FORESHADOW_PLANT_MAX], "payoff": payoff[:FORESHADOW_PAYOFF_MAX]}
    return json.dumps(plan, ensure_ascii=False) if plan["plant"] or plan["payoff"] else None


def _valid_word_count(raw: Any, default: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if 500 <= value <= 10000 else default


def _map_task_ids(raw: Any, mapping: dict[str, str]) -> Any:
    """章纲 narrative_tasks 里的短编号（P3）→ 真实承诺 id；其余原样（normalize 时按未回收清单过滤）。"""
    if not isinstance(raw, dict):
        return raw
    out = dict(raw)
    for kind in ("resolve", "advance"):
        items = []
        for item in raw.get(kind) or []:
            if isinstance(item, dict):
                pid = str(item.get("promise_id") or "").strip()
                items.append({**item, "promise_id": mapping.get(pid.upper(), pid)})
        out[kind] = items
    return out


def normalize_payoff_type(raw: Any, template: BridgeTemplate) -> str | None:
    """LLM 给的兑现方式 → 模板枚举原词；精确匹配优先，否则取字符串里出现的第一个枚举（"打脸（当众碾压）"→"打脸"）；都不是 → None。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text in template.payoff_types:
        return text
    hits = [(text.find(t), t) for t in template.payoff_types if t in text]
    return min(hits)[1] if hits else None


def parse_partial_bridges(text: str, numbers: list[int]) -> list[dict[str, Any]]:
    """把半截 JSON 解析成 partial 快照：只留目标槽位、只留已写出的非空字段，按 numbers 排序。"""
    data = parse_partial_json(text, expected_type="array")
    if not isinstance(data, list):
        return []
    by_number: dict[int, dict[str, Any]] = {}
    for item in data:
        if not isinstance(item, dict) or not str(item.get("bridge_number", "")).isdigit():
            continue
        n = int(item["bridge_number"])
        if n not in numbers:
            continue
        snap: dict[str, Any] = {"bridge_number": n}
        for field_name in _FILL_FIELDS:
            value = item.get(field_name)
            if isinstance(value, str) and value.strip():
                snap[field_name] = value
        by_number[n] = snap
    return [by_number[n] for n in numbers if n in by_number]


def _collected_json_text(resp: Any, *, what: str) -> str:
    """校验 generate_text_stream_collect 的返回，把"截断 / 空内容"翻译成可操作的错误。

    这两种情况若直接交给 safe_parse_json，会退化成 [] 或残缺数组，最终报出误导性的
    "数量不符：期望 [1, 2]，LLM 返回 []"，让用户去怀疑模型输出格式而不是 Max Tokens。
    """
    if not isinstance(resp, dict):
        raise ValueError(f"{what}：LLM 未返回任何内容")
    content = resp.get("content") or ""
    if resp.get("finish_reason") == "length":
        raise ValueError(
            f"{what}：LLM 输出被 Max Tokens 截断（已输出 {len(content)} 字符，无法解析为完整 JSON），"
            f"请在「设置」中调大 Max Tokens 后重试"
        )
    if not content.strip():
        raise ValueError(f"{what}：LLM 未返回任何内容（finish_reason={resp.get('finish_reason')}）")
    return content


CHAPTER_EXPANSION_TASK_PROMPT = """请把下面这个桥段展开为 {count} 个详细章纲（第 {start_chapter}-{end_chapter} 章），\
**每个章纲再细分为 3-5 个场景卡片**（一张卡 ≈ 500-800 字，用于后续场景级流式生成）。

# 桥段信息
- 标题：{title}
- 目标：{goal}
- {payoff_name}：{showoff_point}
- 金手指用法：{golden_finger_usage}
- 开场（C1）提示：{c1_intro}
- 拉扯（C2）提示：{c2_build}
- 兑现（C3）提示：{c3_payoff}
- 收尾（C4）提示：{c4_aftermath}
- 节奏角色：{rhythm_label}
- 起始章号：第 {start_chapter} 章

# 各章位置（{template_name}）
{position_lines}
- {c1_rule}
- {pov_rule}
- 人名只能使用【本书角色】里的名字；`characters_involved` / `pov` 不得出现新名字
{shape_block}
# 叙事任务（伏笔 / 承诺）
- 每章可带 `narrative_tasks`：resolve = 本章回收的旧承诺（promise_id 填【当前未回收的伏笔】里的编号，如 P3，how 写怎么回收）；\
advance = 本章顺带推进 / 提一句的旧承诺（保温，不解决）；plant = 本章新埋的伏笔（payoff_after = 计划多少章后回收）
- 【本桥段伏笔计划】里的条目要落到具体某一章；清单里标了"临近计划回收 / 已超期"的优先安排回收；没有合适的就留空，不要硬塞

# 场景卡片设计要求
- 每章 3-5 张，按章内时间顺序排列
- `card_type` 取值之一：`event`（事件推进）/ `scene`（场景描写）/ `dialogue`（关键对话）/ `inner`（内心独白）/ `conflict`（冲突高潮）
- `content` 字段要写清"这段写什么 / 谁在场 / 解决什么 / 产出什么"，方便后续直接据此生成正文
- 开场章必须有 1 张 `inner` 或 `dialogue` 做代入；拉扯章必须有 1 张 `conflict` 做拉扯；兑现章场景密度最大（可加密到 5 张）；\
收尾章最后一张要含"下桥段引子"；缓冲章以 `dialogue` / `scene` 为主

# 输出格式（纯 JSON 数组，{count} 个章纲对象，按章号顺序，每个内嵌 scenes 数组）

[
  {{
    "chapter_number": {start_chapter},
    "title": "章节标题",
    "bridge_position": "{first_position}",
    "scene": "场景地点",
    "pov": "视角角色名",
    "plot_points": "详细剧情要点 300-400 字",
    "key_events": ["事件1", "事件2", "章末落点事件"],
    "characters_involved": ["角色1", "角色2"],
    "target_word_count": {default_words},
    "narrative_tasks": {{"resolve": [{{"promise_id": "P1", "how": "怎么回收"}}], "advance": [], "plant": [{{"title": "伏笔名", "content": "怎么埋", "payoff_after": 40}}]}},
    "scenes": [
      {{
        "title": "场景标题（如：清晨醒来回忆任务）",
        "content": "本场景写什么、谁在场、解决什么、产出什么（200-300 字描述）",
        "card_type": "scene",
        "scene_order": 0,
        "word_count_target": 600
      }},
      {{ "title": "...", "content": "...", "card_type": "dialogue", "scene_order": 1, "word_count_target": 500 }}
    ]
  }}
  …共 {count} 个对象，chapter_number 从 {start_chapter} 到 {end_chapter}，bridge_position 依次为：{position_sequence}
]

直接返回 JSON 数组，不要 markdown 标记。
"""

BREATHER_LABEL = "缓冲章：大高潮之后的日常 / 感情 / 群像 / 收获盘点，节奏放缓，人物关系往前走一小步，章末留一个温和的引子"


def _position_lines(
    template: BridgeTemplate, positions: tuple[str, ...], c_start: int, c3_end_rule: str,
) -> str:
    last_payoff = max((i for i, p in enumerate(positions) if p == "payoff"), default=-1)
    lines = []
    for i, pos in enumerate(positions):
        label = BREATHER_LABEL if pos == "breather" else template.position_labels.get(pos, pos)
        if i == last_payoff:
            label = f"{label}（{c3_end_rule}）"
        note = position_note(positions, i)
        lines.append(f"- 第 {c_start + i} 章（{pos}）：{label}" + (f"；{note}" if note else ""))
    return "\n".join(lines)


def render_expansion_task(
    template: BridgeTemplate,
    bridge: PlotBridge,
    c_start: int,
    pov_rule: str,
    shape: str = SHAPE_STANDARD,
    c3_hook_style: str = C3_HOOK_NONE,
    *,
    positions: tuple[str, ...] | None = None,
    default_words: int = 3000,
) -> str:
    """按题材模板渲染章纲展开任务段（N 章）；shape = 桥段形态（收官 / 高潮加密时追加「# 桥段形态」段）；
    c3_hook_style = C3 章末风格；positions = 各章位置序列（变长桥段），默认 4 章标准结构。"""
    positions = positions or positions_for(4)
    shape_block = shape_expansion_block(shape)
    rhythm_label = RHYTHM_LABELS.get(getattr(bridge, "rhythm_role", None) or "standard", "") or "常规"
    return CHAPTER_EXPANSION_TASK_PROMPT.format(
        count=len(positions),
        title=bridge.title,
        goal=bridge.goal,
        payoff_name=template.payoff_label,
        showoff_point=bridge.showoff_point,
        golden_finger_usage=bridge.golden_finger_usage or "",
        c1_intro=bridge.c1_intro or "",
        c2_build=bridge.c2_build or "",
        c3_payoff=bridge.c3_payoff or "",
        c4_aftermath=bridge.c4_aftermath or "",
        rhythm_label=rhythm_label,
        start_chapter=c_start,
        end_chapter=c_start + len(positions) - 1,
        template_name=template.name,
        position_lines=_position_lines(template, positions, c_start, expansion_c3_rule(c3_hook_style)),
        c1_rule=OPENING_C1_RULE if bridge.bridge_number == 1 else CONTINUED_C1_RULE,
        pov_rule=pov_rule,
        shape_block=f"\n{shape_block}\n" if shape_block else "",
        first_position=positions[0],
        default_words=default_words,
        position_sequence=" / ".join(positions),
    )

class BridgePlanningService:
    """桥段规划服务（工程化流水线：plan → fill → expand）。"""

    def __init__(self, ai_service, *, partial_interval: float = 0.4):
        self.ai_service = ai_service
        self.assembler = PromptAssembler()
        # partial 快照最小间隔（秒）；测试传 0 让每个 chunk 都触发
        self.partial_interval = partial_interval

    # ---------------- 骨架层（无 LLM） ----------------

    async def preview_plan(self, db: AsyncSession, project_id: str) -> BridgeSlotPlan:
        """纯计算：主线节点 → 桥段槽位表。前置不满足抛 BridgePlanningPreconditionError。

        项目 bridge_rhythm=varied → 变长桥段（3-12 章，带卷内节奏角色）；其余（含旧项目 NULL）→ 每桥段 4 章。
        """
        project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        rhythm = "varied" if getattr(project, "bridge_rhythm", None) == "varied" else "fixed4"
        return compute_bridge_slots(await load_plot_line_data(db, project_id), rhythm=rhythm)

    async def plan_bridges(self, db: AsyncSession, project_id: str) -> list[PlotBridge]:
        """建骨架：按槽位表创建 N 个 draft 桥段（无 LLM）。已有桥段 → Conflict。"""
        existing = await db.execute(
            select(PlotBridge.id).where(PlotBridge.project_id == project_id).limit(1)
        )
        if existing.scalar_one_or_none():
            raise BridgePlanningConflictError("项目已存在桥段骨架，请先重置（DELETE /bridges）后再规划")

        plan = await self.preview_plan(db, project_id)
        created: list[PlotBridge] = []
        prev: PlotBridge | None = None
        for slot in plan.slots:
            bridge = PlotBridge(
                project_id=project_id,
                plot_line_id=slot.plot_line_id,
                beat_index=slot.beat_index,
                beat_coverage_start=slot.coverage_start,
                beat_coverage_end=slot.coverage_end,
                secondary_beats=json.dumps([asdict(t) for t in slot.secondary], ensure_ascii=False),
                bridge_number=slot.bridge_number,
                chapter_start=slot.chapter_start,
                chapter_end=slot.chapter_end,
                rhythm_role=slot.rhythm_role,
                title=f"桥段 {slot.bridge_number} · {slot.beat_title}",
                goal="",
                showoff_point="",
                status="draft",
                order_index=slot.bridge_number,
            )
            db.add(bridge)
            await db.flush()
            if prev is not None:
                bridge.prev_bridge_id = prev.id
            prev = bridge
            created.append(bridge)
        await db.commit()
        for b in created:
            await db.refresh(b)
        logger.info(
            "[BridgePlan] project=%s 建骨架 %d 个桥段（主线 %s）",
            project_id, len(created), plan.main_line_id,
        )
        return created

    async def reset_bridges(self, db: AsyncSession, project_id: str) -> int:
        """删除项目全部桥段。存在 completed 桥段或已展开章纲 → Conflict。"""
        bridges = await self.list_bridges(db, project_id)
        if any(b.status == "completed" for b in bridges):
            raise BridgePlanningConflictError("存在已展开为章纲的桥段，不能重置骨架；请先删除对应章纲")
        expanded = await db.execute(
            select(ChapterOutline.id)
            .where(ChapterOutline.project_id == project_id, ChapterOutline.bridge_id.isnot(None))
            .limit(1)
        )
        if expanded.scalar_one_or_none():
            raise BridgePlanningConflictError("项目内存在已展开章纲（bridge_id 非空），不能重置骨架")
        for b in bridges:
            await db.delete(b)
        await db.commit()
        return len(bridges)

    # ---------------- 填充层（LLM，按主线节点分批） ----------------

    @staticmethod
    def _beat_block(main: PlotLineData, beat_index: int, heading: str) -> tuple[list[str], str | None]:
        """【📍 所属主线节点】当前节点（描述 / 类型 / 舞台 / 对手 / 境界）+ 上一节点 + 下一节点。返回 (行, 下一节点标题)。"""
        beats = list(main.beats)
        cur = next(b for b in beats if b.index == beat_index)
        pos = beats.index(cur)
        parts = [heading, f"- 主线：《{main.title}》（全书 {main.estimated_chapters} 章）",
                 f"- 当前节点：[节点 {cur.index}] {cur.title}（权重 {cur.weight:.0%}）"]
        if cur.description:
            parts.append(f"  描述：{cur.description[:300]}")
        parts.extend(beat_facts_lines(cur))
        if cur.review_note:
            parts.append(f"  上一卷复盘修正（按它调整本节点规划）：{cur.review_note[:300]}")
        if pos > 0:
            p = beats[pos - 1]
            parts.append(f"- 上一节点：[节点 {p.index}] {p.title}（已收尾）")
        next_beat_title: str | None = None
        if pos + 1 < len(beats):
            nx = beats[pos + 1]
            next_beat_title = nx.title
            desc = f"｜{nx.description[:150]}" if nx.description else ""
            parts.append(f"- 下一节点：[节点 {nx.index}] {nx.title}（待开启）{desc}")
        return parts, next_beat_title

    async def _build_fill_context(
        self,
        db: AsyncSession,
        project_id: str,
        main: PlotLineData,
        beat_index: int,
        chunk: list[PlotBridge],
        template: BridgeTemplate,
        fields: dict[str, Any],
        phases: list[dict[str, Any]] | None = None,
    ) -> FillContext:
        """故事前提（含终极目标）+ 开篇规则（仅桥段 1）+ 所属节点（含前后节点描述）+ 节点内阶段 + 已填桥段账本。"""
        parts: list[str] = story_core_lines(fields)
        story_fields = [
            k for k in ("premise", "golden_finger", "selling_points", "main_tropes", "power_system", "ultimate_goal")
            if fields.get(k)
        ]

        opening = any(b.bridge_number == 1 for b in chunk)
        if opening:
            parts.append("")
            parts.append(opening_block(fields, template))

        beat_lines, next_beat_title = self._beat_block(main, beat_index, "【📍 本批所属主线节点】")
        parts.append("")
        parts.extend(beat_lines)

        phase = phase_for_bridge(phases, chunk[0].bridge_number) if phases else None
        if phase:
            parts.append("")
            parts.append(render_phase_block(phases, current_index=phase["index"]))

        ledger, ledger_numbers = await filled_ledger_block(db, project_id, before_number=chunk[0].bridge_number)
        if ledger:
            parts.append("")
            parts.append(ledger)

        # 滚动规划：已写正文的实际进展 + 未回收伏笔（供 foreshadow_plan.payoff 选择）
        first_chapter = bridge_chapter_range(chunk[0])[0]
        progress = await actual_progress_block(db, project_id, before_chapter=first_chapter)
        if progress:
            parts.append("")
            parts.append(progress)
        promises, _mapping, _items = await open_promises_block(db, project_id, before_chapter=first_chapter, limit=10)
        if promises:
            parts.append("")
            parts.append(promises)

        return FillContext(
            text="\n".join(parts),
            story_fields=story_fields,
            next_beat_title=next_beat_title,
            prev_bridge_number=ledger_numbers[-1] if ledger_numbers else None,
            ledger_numbers=ledger_numbers,
            opening=opening,
            phase={"index": phase["index"], "title": phase["title"], "count": len(phases)} if phase else None,
        )

    @staticmethod
    def _slot_table(
        beat_bridges: list[PlotBridge],
        target_numbers: list[int],
        phases: list[dict[str, Any]] | None = None,
        climax_index: int | None = None,
    ) -> str:
        """节点全部槽位；本批要填的前缀 ★，其余仅供衔接参考；有阶段拆分时按阶段分组；收官 / 高潮桥段带形态标签。"""
        rows: list[str] = []
        current_phase: int | None = None
        for b in beat_bridges:
            phase = phase_for_bridge(phases, b.bridge_number) if phases else None
            if phase and phase["index"] != current_phase:
                current_phase = phase["index"]
                rows.append(f"── 阶段 {phase['index']}《{phase['title']}》（桥段 {phase['bridge_start']}-{phase['bridge_end']}）：{phase['goal'][:60]}")
            c_start, c_end = bridge_chapter_range(b)
            cs = (b.beat_coverage_start or 0.0) * 100
            ce = (b.beat_coverage_end or 0.0) * 100
            mark = "★ " if b.bridge_number in target_numbers else "- "
            label = shape_label(bridge_shape(b.beat_coverage_end, b.beat_index, climax_index))
            rhythm = RHYTHM_LABELS.get(getattr(b, "rhythm_role", None) or "standard", "")
            rhythm_tag = f"【{rhythm}】" if rhythm else ""
            row = (f"{mark}桥段 {b.bridge_number}：第 {c_start}-{c_end} 章（{c_end - c_start + 1} 章），"
                   f"节点进度 {cs:.0f}% → {ce:.0f}%{label}{rhythm_tag}")
            try:
                secondary = json.loads(b.secondary_beats) if b.secondary_beats else []
            except (json.JSONDecodeError, TypeError):
                secondary = []
            for t in secondary:
                if not isinstance(t, dict):
                    continue
                label = "保温" if t.get("role", "primary") == "mention" else "主B线"
                progress = _task_progress_text(t)
                row += (
                    f"\n    · {label}：{t.get('line_type')}《{t.get('line_title')}》"
                    f"[节点 {t.get('beat_index')}] {t.get('beat_title')}"
                    f"{progress if progress.startswith('（') else ' ' + progress}"
                )
                if label == "主B线" and t.get("beat_description"):
                    row += f"｜{str(t['beat_description'])[:80]}"
            rows.append(row)
        return "\n".join(rows)

    async def _stream_llm(
        self,
        *,
        prompt: str,
        system_prompt: str,
        model: str,
        live: dict[str, Any],
        snapshot: Callable[[str], Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式调 LLM：转发 thinking / partial 事件（携带 live 里的 beat_index / bridge_numbers），
        最后 yield {"type": "_collected", "content", "finish_reason"} 供调用方解析。"""
        buffer: list[str] = []
        content_chars = 0
        finish_reason: str | None = None
        last_partial = float("-inf")
        async for ev in self.ai_service.generate_text_stream_events(
            prompt=prompt, system_prompt=system_prompt, model=model or None, temperature=0.6,
        ):
            if ev.kind == "content":
                buffer.append(ev.text)
                content_chars += len(ev.text)
                now = time.monotonic()
                if snapshot is not None and now - last_partial >= self.partial_interval:
                    snap = snapshot("".join(buffer))
                    if snap:
                        last_partial = now
                        yield {"type": "partial", **live, "bridges": snap, "content_chars": content_chars,
                               "elapsed": round(ev.elapsed, 1)}
            elif ev.kind in ("reasoning", "heartbeat"):
                yield {"type": "thinking", **live, "reasoning_chars": ev.reasoning_chars,
                       "content_chars": content_chars, "elapsed": round(ev.elapsed, 1)}
            elif ev.kind == "done":
                finish_reason = ev.finish_reason
        yield {"type": "_collected", "content": "".join(buffer), "finish_reason": finish_reason}

    @staticmethod
    def _fill_chunks(beat_bridges: list[PlotBridge], phases: list[dict[str, Any]]) -> list[list[PlotBridge]]:
        """填充批次：有阶段时一个阶段一批（只含仍是 draft 的桥段；阶段超长再按 FILL_BATCH_MAX 切），否则按 FILL_BATCH_MAX 切。"""
        groups: list[list[PlotBridge]] = []
        if phases:
            by_phase: dict[int, list[PlotBridge]] = {}
            rest: list[PlotBridge] = []
            for b in beat_bridges:
                phase = phase_for_bridge(phases, b.bridge_number)
                (by_phase.setdefault(phase["index"], []) if phase else rest).append(b)
            groups = [by_phase[k] for k in sorted(by_phase)] + ([rest] if rest else [])
        else:
            groups = [beat_bridges]
        return [g[i:i + FILL_BATCH_MAX] for g in groups for i in range(0, len(g), FILL_BATCH_MAX)]

    async def _plan_beat_phases(
        self,
        db: AsyncSession,
        project_id: str,
        main: PlotLineData,
        beat: Any,
        all_numbers: list[int],
        template: BridgeTemplate,
        fields: dict[str, Any],
        prompt: Any,
        model: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """长节点阶段拆分：一次 LLM 调用把节点拆成 K 个递进阶段，落 PlotLine.timeline_data，最后 yield phase_plan。"""
        ranges = phase_ranges(all_numbers)
        beat_lines, _ = self._beat_block(main, beat.index, "【📍 待拆分的主线节点】")
        rows = (await db.execute(
            select(PlotBridge).where(PlotBridge.project_id == project_id, PlotBridge.bridge_number.in_(all_numbers))
        )).scalars().all()
        chapter_ranges = {b.bridge_number: bridge_chapter_range(b) for b in rows}
        user_prompt = "\n\n".join([
            prompt.user_prompt,
            "\n".join(story_core_lines(fields)),
            "\n".join(beat_lines),
            render_phase_split_task(beat.index, beat.title, ranges, template.payoff_label, chapter_ranges),
        ])
        collected: dict[str, Any] = {}
        async for ev in self._stream_llm(
            prompt=user_prompt, system_prompt=prompt.system_prompt, model=model,
            live={"beat_index": beat.index, "bridge_numbers": all_numbers, "stage": "phase_plan"},
        ):
            if ev["type"] == "_collected":
                collected = ev
            else:
                yield ev
        what = f"节点 {beat.index} 阶段拆分"
        content = _collected_json_text(collected, what=what)
        raw = safe_parse_json(content, default=[], expected_type="array", log_prefix="[BridgePhase]")
        phases = parse_phases(raw, ranges)
        if phases is None:
            got = len(raw) if isinstance(raw, list) else 0
            raise ValueError(f"节点 {beat.index} 的阶段数量不符或字段缺失：期望 {len(ranges)} 个阶段（含 title/goal），LLM 返回 {got} 个")

        line = (await db.execute(select(PlotLine).where(PlotLine.id == main.id))).scalar_one()
        td = json.loads(line.timeline_data) if line.timeline_data else {}
        for raw_beat in td.get("beats") or []:
            if isinstance(raw_beat, dict) and _opt_index(raw_beat) == beat.index:
                raw_beat["phases"] = phases
        line.timeline_data = json.dumps(td, ensure_ascii=False)
        await db.commit()
        logger.info("[BridgePhase] project=%s 节点 %d 拆成 %d 个阶段（桥段 %d-%d）",
                    project_id, beat.index, len(phases), all_numbers[0], all_numbers[-1])
        yield {"type": "phase_plan", "beat_index": beat.index, "bridge_numbers": all_numbers, "phases": phases}

    async def fill_bridges(
        self,
        db: AsyncSession,
        project_id: str,
        model_name: Optional[str],
        beat_index: Optional[int] = None,
        max_chapter: Optional[int] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """按主线节点顺序，把 status=draft 的桥段分批交给 LLM 填内容 → ready。

        可续跑：只处理 draft；beat_index 指定时只填该节点。
        滚动规划（项目 rolling_planning 开启，或显式传 max_chapter）：只填起始章 ≤ 已写章节 + FILL_LOOKAHEAD_CHAPTERS
        的桥段——远处的桥段等写到附近、带着实际进展再填，避免规划与正文越走越远。
        节点桥段数 ≥ PHASE_SPLIT_MIN_BRIDGES 且尚未拆阶段 → 先一次 LLM 拆阶段（落 timeline_data，续跑复用），
        之后一个阶段一批；否则同节点桥段每 FILL_BATCH_MAX 个一次 LLM 调用（子批之间靠账本衔接）。
        LLM 返回条目与槽位不一致 → ValueError（该批保持 draft，调用方终止流）。
        事件：beat_start → [phase_plan] → batch_done（每批，含 provenance）→ beat_done → … → done
        """
        effective_model = model_name or getattr(self.ai_service, "default_model", None) or ""
        project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        drafts_result = await db.execute(
            select(PlotBridge)
            .where(PlotBridge.project_id == project_id, PlotBridge.status == "draft")
            .order_by(PlotBridge.bridge_number)
        )
        drafts = list(drafts_result.scalars().all())
        if beat_index is not None:
            drafts = [b for b in drafts if b.beat_index == beat_index]
        if max_chapter is None and getattr(project, "rolling_planning", None):
            max_chapter = await written_upto(db, project_id) + FILL_LOOKAHEAD_CHAPTERS
        if max_chapter is not None:
            drafts = [b for b in drafts if bridge_chapter_range(b)[0] <= max_chapter]
        if not drafts:
            remaining = await db.execute(
                select(PlotBridge.id).where(PlotBridge.project_id == project_id, PlotBridge.status == "draft")
            )
            yield {"type": "done", "filled": 0, "remaining_drafts": len(remaining.scalars().all())}
            return

        lines = await load_plot_line_data(db, project_id)
        main = next(l for l in lines if l.id == drafts[0].plot_line_id)
        climax_index = climax_beat_index(main)
        by_beat: dict[int, list[PlotBridge]] = {}
        for b in drafts:
            by_beat.setdefault(b.beat_index, []).append(b)

        template = resolve_template(getattr(project, "genre", None))
        c3_hook_style = normalize_c3_hook_style(getattr(project, "c3_hook_style", None))
        outline = (await db.execute(
            select(StoryOutline)
            .where(StoryOutline.project_id == project_id, StoryOutline.is_active == True)  # noqa: E712
            .order_by(StoryOutline.version.desc())
            .limit(1)
        )).scalar_one_or_none()
        fields = parse_story_outline_fields(outline.content if outline else None)

        ctx = AssemblyContext(scene="bridge_planning", model_name=effective_model, project_id=project_id)
        prompt = await self.assembler.assemble(db, ctx)
        pack = await get_first_attached_pack(db, project_id)
        pack_title = (getattr(pack, "source_book_title", None) or "") if pack else None
        dimensions = {
            dim: strength
            for dim, strength in get_policy("bridge_planning", effective_model).items()
            if f"dissect_{dim}" in prompt.slots_filled
        }

        filled = 0
        for b_idx in sorted(by_beat):
            beat_bridges = by_beat[b_idx]
            numbers = [b.bridge_number for b in beat_bridges]
            yield {"type": "beat_start", "beat_index": b_idx, "bridge_numbers": numbers}
            cur_beat = next(b for b in main.beats if b.index == b_idx)
            beat_title = cur_beat.title

            # 长节点：先拆阶段（已存 timeline_data 的直接复用），再按阶段分批
            all_numbers = sorted((await db.execute(
                select(PlotBridge.bridge_number).where(
                    PlotBridge.project_id == project_id, PlotBridge.plot_line_id == main.id, PlotBridge.beat_index == b_idx,
                )
            )).scalars().all())
            phases: list[dict[str, Any]] = [dict(p) for p in cur_beat.phases]
            if not phases and len(all_numbers) >= PHASE_SPLIT_MIN_BRIDGES:
                async for ev in self._plan_beat_phases(
                    db, project_id, main, cur_beat, all_numbers, template, fields, prompt, effective_model,
                ):
                    if ev["type"] == "phase_plan":
                        phases = ev["phases"]
                    yield ev

            for chunk in self._fill_chunks(beat_bridges, phases):
                chunk_numbers = [b.bridge_number for b in chunk]
                fill_ctx = await self._build_fill_context(db, project_id, main, b_idx, chunk, template, fields, phases)
                shape_rules = tuple(
                    rule for b in chunk
                    if (rule := shape_fill_rule(
                        bridge_shape(b.beat_coverage_end, b.beat_index, climax_index), b.bridge_number, template.payoff_label,
                    ))
                )
                rhythm_rules = tuple(dict.fromkeys(
                    f"桥段 {b.bridge_number}（{RHYTHM_LABELS[b.rhythm_role]}）：{RHYTHM_FILL_RULES[b.rhythm_role]}"
                    for b in chunk if getattr(b, "rhythm_role", None) in RHYTHM_FILL_RULES
                ))
                user_prompt = "\n\n".join([
                    prompt.user_prompt,
                    fill_ctx.text,
                    render_fill_task(
                        template, len(chunk),
                        self._slot_table(beat_bridges, chunk_numbers, phases, climax_index),
                        shape_rules, c3_hook_style, rhythm_rules,
                    ),
                ])
                what = f"节点 {b_idx} 桥段 {chunk_numbers[0]}-{chunk_numbers[-1]} 填充"
                collected: dict[str, Any] = {}
                async for ev in self._stream_llm(
                    prompt=user_prompt, system_prompt=prompt.system_prompt, model=effective_model,
                    live={"beat_index": b_idx, "bridge_numbers": chunk_numbers},
                    snapshot=lambda text: parse_partial_bridges(text, chunk_numbers),
                ):
                    if ev["type"] == "_collected":
                        collected = ev
                    else:
                        yield ev
                content = _collected_json_text(collected, what=what)
                data = safe_parse_json(content, default=[], expected_type="array", log_prefix="[BridgeFill]")
                items = {
                    int(d["bridge_number"]): d
                    for d in data
                    if isinstance(d, dict) and str(d.get("bridge_number", "")).isdigit()
                }
                if set(items) != set(chunk_numbers):
                    raise ValueError(
                        f"节点 {b_idx} 的桥段数量不符：期望 {chunk_numbers}，LLM 返回 {sorted(items)}"
                    )

                provenance = build_fill_provenance(
                    prompt,
                    model=effective_model,
                    template_key=template.key,
                    beat_index=b_idx,
                    beat_title=beat_title,
                    bridge_numbers=chunk_numbers,
                    next_beat_title=fill_ctx.next_beat_title,
                    prev_bridge_number=fill_ctx.prev_bridge_number,
                    ledger_numbers=fill_ctx.ledger_numbers,
                    opening=fill_ctx.opening,
                    story_fields=fill_ctx.story_fields,
                    pack_title=pack_title or None,
                    dimensions=dimensions,
                    phase=fill_ctx.phase,
                )
                meta_json = json.dumps(provenance, ensure_ascii=False)
                for b in chunk:
                    item = items[b.bridge_number]
                    for field_name in _FILL_FIELDS:
                        value = item.get(field_name)
                        if not isinstance(value, str) or not value.strip():
                            continue
                        value = value.strip()
                        limit = _FILL_SHORT_FIELDS.get(field_name)
                        setattr(b, field_name, value[:limit] if limit else value)
                    b.payoff_type = normalize_payoff_type(item.get("payoff_type"), template)
                    plan = normalize_foreshadow_plan(item.get("foreshadow_plan"))
                    if plan:
                        b.foreshadow_plan = plan
                    b.generation_meta = meta_json
                    b.status = "ready"
                await db.commit()
                for b in chunk:
                    await db.refresh(b)
                filled += len(chunk)
                yield {
                    "type": "batch_done",
                    "beat_index": b_idx,
                    "bridge_numbers": chunk_numbers,
                    "bridges": [bridge_to_dict(b) for b in chunk],
                    "provenance": provenance,
                }

            yield {"type": "beat_done", "beat_index": b_idx, "bridges": [bridge_to_dict(b) for b in beat_bridges]}

        remaining = await db.execute(
            select(PlotBridge.id).where(PlotBridge.project_id == project_id, PlotBridge.status == "draft")
        )
        yield {"type": "done", "filled": filled, "remaining_drafts": len(remaining.scalars().all())}

    # ---------------- 展开层（LLM，确定性章号 + 节点覆盖账本） ----------------

    async def expand_bridge_to_chapters(
        self,
        db: AsyncSession,
        bridge_id: str,
        model_name: Optional[str],
    ) -> list[ChapterOutline]:
        """把一个 ready 桥段展开为其章号区间内的 N 个 ChapterOutline（变长桥段 3-12 章；旧数据 4 章）。

        前置：status == ready；前一桥段已 completed；目标章号未被占用。
        上下文：所属节点（含上一卷复盘修正）、上一桥段实际收尾、下一桥段目标、已写正文的实际进展、
        未回收伏笔清单（短编号）、本桥段伏笔计划。
        产物：ChapterOutline(bridge_id/bridge_position/narrative_tasks) + PlotCard 场景卡 + ChapterOutlinePlotLineLink 账本。
        """
        bridge_result = await db.execute(select(PlotBridge).where(PlotBridge.id == bridge_id))
        bridge = bridge_result.scalar_one_or_none()
        if not bridge:
            raise ValueError(f"桥段不存在: {bridge_id}")
        if bridge.status != "ready":
            raise BridgePlanningPreconditionError(
                f"桥段 {bridge.bridge_number} 状态为 {bridge.status}，只有 ready 状态可展开"
            )
        if bridge.bridge_number > 1:
            prev_result = await db.execute(
                select(PlotBridge.status).where(
                    PlotBridge.project_id == bridge.project_id,
                    PlotBridge.bridge_number == bridge.bridge_number - 1,
                )
            )
            prev_status = prev_result.scalar_one_or_none()
            if prev_status != "completed":
                raise BridgePlanningPreconditionError(
                    f"桥段 {bridge.bridge_number - 1} 尚未展开（状态 {prev_status}），必须按顺序展开"
                )

        c_start, c_end = bridge_chapter_range(bridge)
        count = c_end - c_start + 1
        positions = positions_for(count)
        occupied = await db.execute(
            select(ChapterOutline.chapter_number).where(
                ChapterOutline.project_id == bridge.project_id,
                ChapterOutline.chapter_number.between(c_start, c_end),
            )
        )
        taken = sorted(occupied.scalars().all())
        if taken:
            raise BridgePlanningConflictError(
                f"章号冲突：第 {taken[0]} 章已存在，桥段 {bridge.bridge_number} 需要第 {c_start}-{c_end} 章"
            )

        effective_model = model_name or getattr(self.ai_service, "default_model", None) or ""
        project = (await db.execute(select(Project).where(Project.id == bridge.project_id))).scalar_one_or_none()
        try:
            recorded = (json.loads(bridge.generation_meta) or {}).get("template") if bridge.generation_meta else None
        except (json.JSONDecodeError, TypeError, AttributeError):
            recorded = None
        template = resolve_template(getattr(project, "genre", None), explicit_key=recorded)

        ctx = AssemblyContext(
            scene="chapter_outline", model_name=effective_model, project_id=bridge.project_id,
            bridge_context={"title": bridge.title, "goal": bridge.goal, "showoff_point": bridge.showoff_point},
        )
        prompt = await self.assembler.assemble(db, ctx)
        beat_block = await _load_beat_context_for_bridge(db, bridge)
        prev_block = await prev_bridge_last_chapter_block(db, bridge.project_id, bridge.bridge_number)
        next_block = await next_bridge_block(db, bridge.project_id, bridge.bridge_number)
        progress_block = await actual_progress_block(db, bridge.project_id, before_chapter=c_start)
        promise_block, promise_ids, open_promises = await open_promises_block(
            db, bridge.project_id, before_chapter=c_start, limit=15, with_ids=True,
        )
        plan_block = foreshadow_plan_block(getattr(bridge, "foreshadow_plan", None))
        default_words = default_chapter_words(getattr(project, "platform_preset", None))

        prompt_parts = [prompt.user_prompt]
        for block in (beat_block, progress_block, prev_block, next_block, promise_block, plan_block):
            if block:
                prompt_parts.append(block)
        prompt_parts.append(render_expansion_task(
            template, bridge, c_start, pov_line(getattr(project, "narrative_perspective", None)),
            shape=await _bridge_shape_for(db, bridge),
            c3_hook_style=normalize_c3_hook_style(getattr(project, "c3_hook_style", None)),
            positions=positions,
            default_words=default_words,
        ))
        user_prompt = "\n\n".join(prompt_parts)

        resp = await self.ai_service.generate_text_stream_collect(
            prompt=user_prompt,
            system_prompt=prompt.system_prompt,
            model=effective_model or None,
            temperature=0.6,
            context=f"BridgeExpansion-{effective_model or 'default'}",
        )
        content = _collected_json_text(resp, what=f"桥段 {bridge.bridge_number} 展开")
        chapters_data = safe_parse_json(content, default=[], expected_type="array", log_prefix="[BridgeExpansion]")
        if not isinstance(chapters_data, list) or len(chapters_data) < count:
            raise ValueError(f"展开的章纲少于 {count} 个或格式错误")

        try:
            secondary = json.loads(bridge.secondary_beats) if bridge.secondary_beats else []
        except (json.JSONDecodeError, TypeError):
            secondary = []
        main_cov_per_chapter = (
            (bridge.beat_coverage_end or 0.0) - (bridge.beat_coverage_start or 0.0)
        ) / count
        # 副线账本按剧情线归并：同一支线的多个节点可能落在同一桥段（桥段边界切在相邻节点之间、
        # 或多个锚定节点挤进一个桥段），而账本表 (chapter_outline_id, plot_line_id) 唯一，
        # 所以每条线只建一条 link，多个节点合进 beats_covered
        sub_ledger: dict[str, dict[str, Any]] = {}
        for t in secondary:
            if not isinstance(t, dict) or t.get("role", "primary") == "mention":
                continue
            cov = (float(t.get("coverage_end", 0)) - float(t.get("coverage_start", 0))) / count
            entry = sub_ledger.setdefault(t["plot_line_id"], {"role": t.get("line_type") or "sub", "beats_covered": []})
            entry["beats_covered"].append({"beat_index": int(t["beat_index"]), "coverage": cov})

        created: list[ChapterOutline] = []
        plot_card_count = 0
        for i, data in enumerate(chapters_data[:count]):
            if not isinstance(data, dict):
                raise ValueError(f"第 {i + 1} 个章纲不是对象")
            chapter_number = c_start + i
            tasks = normalize_narrative_tasks(_map_task_ids(data.get("narrative_tasks"), promise_ids), open_promises)
            co = ChapterOutline(
                project_id=bridge.project_id,
                chapter_number=chapter_number,
                title=(data.get("title") or f"第{chapter_number}章")[:200],
                scene=data.get("scene"),
                pov=data.get("pov"),
                plot_points=data.get("plot_points"),
                key_events=json.dumps(data.get("key_events", []), ensure_ascii=False),
                characters_involved=json.dumps(data.get("characters_involved", []), ensure_ascii=False),
                target_word_count=_valid_word_count(data.get("target_word_count"), default_words),
                order_index=chapter_number,
                bridge_id=bridge.id,
                bridge_position=positions[i],
                narrative_tasks=json.dumps(tasks, ensure_ascii=False) if has_tasks(tasks) else None,
            )
            db.add(co)
            await db.flush()
            created.append(co)

            if bridge.plot_line_id:  # 自由模式桥段（不挂剧情线）没有主线账本
                db.add(ChapterOutlinePlotLineLink(
                    chapter_outline_id=co.id,
                    plot_line_id=bridge.plot_line_id,
                    role="main",
                    order_index=0,
                    timeline_coverage=json.dumps(
                        {"beats_covered": [{"beat_index": bridge.beat_index, "coverage": main_cov_per_chapter}]},
                        ensure_ascii=False,
                    ),
                ))
            for order, (line_id, entry) in enumerate(sub_ledger.items(), start=1):
                db.add(ChapterOutlinePlotLineLink(
                    chapter_outline_id=co.id,
                    plot_line_id=line_id,
                    role=entry["role"],
                    order_index=order,
                    timeline_coverage=json.dumps({"beats_covered": entry["beats_covered"]}, ensure_ascii=False),
                ))

            scenes = data.get("scenes")
            if isinstance(scenes, list):
                for card_idx, scene_data in enumerate(scenes[:8]):
                    if not isinstance(scene_data, dict) or not scene_data.get("title"):
                        continue
                    plot_card = PlotCard(
                        project_id=bridge.project_id,
                        chapter_outline_id=co.id,
                        title=str(scene_data.get("title"))[:200],
                        content=scene_data.get("content", ""),
                        card_type=scene_data.get("card_type", "scene"),
                        order_index=scene_data.get("scene_order", card_idx),
                        tags=json.dumps(
                            [f"第{chapter_number}章", "桥段展开", positions[i], scene_data.get("card_type", "scene")],
                            ensure_ascii=False,
                        ),
                        word_count_target=scene_data.get("word_count_target", 500),
                        generation_order=card_idx,
                    )
                    db.add(plot_card)
                    await db.flush()
                    db.add(PlotCardChapterOutlineLink(
                        plot_card_id=plot_card.id, chapter_outline_id=co.id, usage_type="planned",
                    ))
                    plot_card_count += 1

        bridge.status = "completed"
        await db.commit()
        for c in created:
            await db.refresh(c)
        primary_count = sum(1 for t in secondary if isinstance(t, dict) and t.get("role", "primary") != "mention")
        logger.info(
            "[BridgeExpansion] 桥段 %d《%s》→ 第 %d-%d 章，%d 张场景卡，主B线任务 %d 条，保温 %d 条",
            bridge.bridge_number, bridge.title, c_start, c_end, plot_card_count,
            primary_count, len(secondary) - primary_count,
        )
        return created

    async def expand_all_ready_bridges(
        self,
        db: AsyncSession,
        project_id: str,
        model_name: Optional[str] = None,
        on_bridge_done: Optional[Callable[[PlotBridge, list[ChapterOutline]], Awaitable[None]]] = None,
    ) -> dict[str, Any]:
        """按 bridge_number 顺序展开全部 ready 桥段；首个失败即停止（后续桥段依赖前序 completed）。

        滚动规划（项目 rolling_planning 开启）：只展开起始章 ≤ 已写章节 + EXPAND_LOOKAHEAD_CHAPTERS 的桥段，
        其余留到写到附近再展开（届时带着实际进展），结果里 deferred = 延后的桥段数。
        on_bridge_done(bridge, created_chapters)：每个桥段成功后回调（后台任务用它实时推送翻卡事件）。
        每个桥段一个 stage（绑定了过程追踪时出现在前端时间线）。
        """
        bridges = await self.list_bridges(db, project_id)
        ready = sorted((b for b in bridges if b.status == "ready"), key=lambda b: b.bridge_number)
        if not ready:
            return {"total": 0, "succeeded": [], "failed": [], "created_chapter_count": 0}
        project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        deferred: int | None = None
        if getattr(project, "rolling_planning", None):
            limit = await written_upto(db, project_id) + EXPAND_LOOKAHEAD_CHAPTERS
            near = [b for b in ready if bridge_chapter_range(b)[0] <= limit]
            deferred, ready = len(ready) - len(near), near

        succeeded: list[str] = []
        failed: list[dict[str, Any]] = []
        created_count = 0
        # 先取出标识：失败后 rollback 会让 ORM 对象过期，再访问属性会触发同步 IO
        targets = [(b.id, b.bridge_number, b.title or "", bridge_chapter_range(b)) for b in ready]
        for bridge_id, bridge_number, title, (c_start, c_end) in targets:
            label = f"展开桥段 {bridge_number}《{title}》→ 第 {c_start}-{c_end} 章"
            try:
                async with stage_scope(f"bridge-{bridge_number}", label) as st:
                    created = await self.expand_bridge_to_chapters(db, bridge_id=bridge_id, model_name=model_name)
                    st.note(chapters=len(created))
            except Exception as exc:  # noqa: BLE001 - 记录后终止批量
                await db.rollback()
                logger.error(
                    "[BridgeExpansion-Batch] 桥段 %d (%s) 展开失败，终止批量: %s", bridge_number, bridge_id, exc
                )
                failed.append({"bridge_id": bridge_id, "error": str(exc)})
                break
            succeeded.append(bridge_id)
            created_count += len(created)
            if on_bridge_done is not None:
                await on_bridge_done(await self.get_bridge(db, bridge_id), created)

        result = {
            "total": len(ready),
            "succeeded": succeeded,
            "failed": failed,
            "created_chapter_count": created_count,
        }
        if deferred is not None:
            result["deferred"] = deferred
        return result

    # ---------------- CRUD ----------------

    async def list_bridges(
        self, db: AsyncSession, project_id: str
    ) -> list[PlotBridge]:
        result = await db.execute(
            select(PlotBridge)
            .where(PlotBridge.project_id == project_id)
            .order_by(PlotBridge.order_index, PlotBridge.bridge_number)
        )
        return list(result.scalars().all())

    async def get_bridge(
        self, db: AsyncSession, bridge_id: str
    ) -> Optional[PlotBridge]:
        result = await db.execute(
            select(PlotBridge).where(PlotBridge.id == bridge_id)
        )
        return result.scalar_one_or_none()

    async def delete_bridge(self, db: AsyncSession, bridge_id: str) -> bool:
        bridge = await self.get_bridge(db, bridge_id)
        if not bridge:
            return False
        await db.delete(bridge)
        await db.commit()
        return True
