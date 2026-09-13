"""桥段填充 / 展开的业务上下文构造（2026-09 评审问题 C/D/F/H）。

与 reference_pack 槽位的分工：槽位管"项目常量"（骨架 / 角色 / 规则 / 拆书维度），
这里管"随桥段位置变化的上下文"：大纲核心字段、开篇规则、已填桥段账本、上桥段实际章纲、
下桥段目标、视角规则，以及把一次 LLM 调用参考了什么记成 provenance。
所有函数只读 DB，不写。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter_outline import ChapterOutline
from app.models.plot_bridge import PlotBridge
from app.services.bridge_templates import BridgeTemplate

# 拆书维度中文名（provenance 警告用）
_DISSECT_DIM_LABEL = {
    "methodology": "方法论", "structure": "结构", "bridges": "桥段范本",
    "character_archive": "角色档案", "synopsis": "全书弧线", "archetypes": "角色塑造",
    "worldbuilding": "世界观", "corpus": "范本片段", "style": "文风",
}


def _clip(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


# ---------------- 节点结构化字段 ----------------

def beat_facts_lines(beat: Any, indent: str = "  ") -> list[str]:
    """节点类型 / 舞台 / 对手 / 境界（BeatData 的结构化字段；空字段跳过）。"""
    lines: list[str] = []
    if getattr(beat, "key", ""):
        lines.append(f"{indent}节点类型：{beat.key}")
    facts = [
        f"{label}：{value}"
        for label, value in (("舞台", getattr(beat, "location", "")), ("对手", getattr(beat, "antagonist", "")),
                             ("境界", getattr(beat, "realm", "")))
        if value
    ]
    if facts:
        lines.append(indent + " ｜ ".join(facts))
    return lines


# ---------------- 大纲核心字段 ----------------

def story_core_lines(fields: dict[str, Any]) -> list[str]:
    """【📖 故事前提】梗概 / 金手指 / 卖点 / 套路 / 升级路线 / 终极目标（空字段跳过）。

    opening_hook 不在这里：只在开篇桥段用（见 opening_block），避免每批都被引导回开头。
    """
    lines = ["【📖 故事前提】"]
    if fields.get("premise"):
        lines.append(f"- 梗概：{_clip(fields['premise'], 400)}")
    if fields.get("golden_finger"):
        lines.append(f"- 金手指：{_clip(fields['golden_finger'], 200)}")
    if fields.get("selling_points"):
        lines.append(f"- 核心卖点：{'、'.join(str(x) for x in fields['selling_points'][:6])}")
    if fields.get("main_tropes"):
        lines.append(f"- 主要套路：{'、'.join(str(x) for x in fields['main_tropes'][:6])}")
    if fields.get("power_system"):
        lines.append(f"- 升级路线：{_clip(fields['power_system'], 200)}")
    if fields.get("ultimate_goal"):
        lines.append(f"- 终极目标：{_clip(fields['ultimate_goal'], 200)}（每个桥段都要向它推进一步）")
    return lines


def opening_block(fields: dict[str, Any], template: BridgeTemplate) -> str:
    """【🥇 开篇桥段（黄金三章）】只在批次包含桥段 1 时注入。"""
    hook = _clip(fields.get("opening_hook"), 300) or "（大纲未填写，请自行设计一个强钩）"
    selling = "、".join(str(x) for x in (fields.get("selling_points") or [])[:6]) or "（大纲未填写）"
    return "\n".join([
        "【🥇 开篇桥段（黄金三章）】",
        f"- 开篇钩子：{hook}",
        f"- 第 1 章前 1000 字内必须出现：{template.opening_first_chapter}",
        f"- 第 3 章前必须完成第一次{template.payoff_label}兑现；前 4 章要亮出全部核心卖点：{selling}",
        "- 本桥段 C1 的“日常代入”压缩到不超过章篇幅的 1/3，其余篇幅直接进入钩子",
    ])


# ---------------- 已填桥段账本 ----------------

def payoff_type_stats_line(filled: list[Any], *, recent: int = 3) -> str:
    """兑现方式全书统计：累计次数（多→少）+ 最近 recent 次序列 + 上一桥段同型警告。全部未标 → 空串。"""
    types = [getattr(b, "payoff_type", None) for b in filled]
    if not any(types):
        return ""
    counts: dict[str, int] = {}
    for t in types:
        if t:
            counts[t] = counts.get(t, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    text = "兑现方式累计：" + "、".join(f"{t}×{n}" for t, n in ranked)
    text += "｜最近：" + " → ".join(t or "未标" for t in types[-recent:])
    if types[-1]:
        text += f"｜上一桥段用了「{types[-1]}」，本批第一个桥段不得再用"
    return text


async def filled_ledger_block(
    db: AsyncSession,
    project_id: str,
    before_number: int,
    *,
    recent: int = 3,
    max_chars: int = 1800,
) -> tuple[str, list[int]]:
    """【📒 已填桥段账本】bridge_number < before_number 且非 draft 的桥段。

    最近 recent 个：目标 / 兑现 / 收尾 / 钩子；更早的一行一个（编号 + 标题 + 目标[:30]）。
    超过 max_chars 先丢早期列表再硬截。返回 (文本, 入账桥段编号)。
    """
    result = await db.execute(
        select(PlotBridge)
        .where(
            PlotBridge.project_id == project_id,
            PlotBridge.bridge_number < before_number,
            PlotBridge.status != "draft",
        )
        .order_by(PlotBridge.bridge_number)
    )
    filled = list(result.scalars().all())
    if not filled:
        return "", []

    recent_ones = filled[-recent:] if recent > 0 else []
    older = filled[: len(filled) - len(recent_ones)]

    lines = ["【📒 已填桥段账本（承接其状态；已揭示的信息、已用过的兑现方式不得重复）】"]
    for b in recent_ones:
        parts = [f"目标 {_clip(b.goal, 80)}"]
        if b.showoff_point:
            tag = f"[{b.payoff_type}]" if getattr(b, "payoff_type", None) else ""
            parts.append(f"兑现{tag} {_clip(b.showoff_point, 60)}")
        if b.c4_aftermath:
            parts.append(f"收尾 {_clip(b.c4_aftermath, 80)}")
        if b.next_bridge_hook:
            parts.append(f"钩子 {_clip(b.next_bridge_hook, 60)}")
        lines.append(f"- 桥段 {b.bridge_number}《{_clip(b.title, 20)}》：{'｜'.join(parts)}")
    stats = payoff_type_stats_line(filled)
    if stats:
        lines.append(stats)

    text = "\n".join(lines)
    if older:
        older_line = "早期：" + "；".join(
            f"桥段 {b.bridge_number}《{_clip(b.title, 12)}》— {_clip(b.goal, 30)}" for b in older
        )
        if len(text) + 1 + len(older_line) <= max_chars:
            text = f"{text}\n{older_line}"
        else:
            text = f"{text}\n早期：桥段 {older[0].bridge_number}-{older[-1].bridge_number} 略"
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…(账本截断)"
    return text, [b.bridge_number for b in filled]


# ---------------- 展开层衔接 ----------------

async def prev_bridge_last_chapter_block(db: AsyncSession, project_id: str, bridge_number: int) -> str:
    """【⛓ 上一桥段实际收尾】上一桥段已展开的最后一章章纲；未展开则退回卡片 C4 + 钩子。"""
    if bridge_number <= 1:
        return ""
    prev = (await db.execute(
        select(PlotBridge).where(
            PlotBridge.project_id == project_id, PlotBridge.bridge_number == bridge_number - 1
        )
    )).scalar_one_or_none()
    if prev is None or prev.status == "draft":
        return ""

    last = (await db.execute(
        select(ChapterOutline)
        .where(ChapterOutline.bridge_id == prev.id)
        .order_by(ChapterOutline.chapter_number.desc())
        .limit(1)
    )).scalar_one_or_none()

    if last is None:
        lines = [
            "【⛓ 上一桥段（尚未展开，按卡片衔接）】",
            f"- 桥段 {prev.bridge_number}《{prev.title}》",
        ]
        if prev.c4_aftermath:
            lines.append(f"- C4 收尾：{_clip(prev.c4_aftermath, 200)}")
        if prev.next_bridge_hook:
            lines.append(f"- 留给本桥段的钩子：{prev.next_bridge_hook}")
        return "\n".join(lines)

    try:
        events = json.loads(last.key_events) if last.key_events else []
    except (json.JSONDecodeError, TypeError):
        events = []
    lines = [
        "【⛓ 上一桥段实际收尾（C1 必须从这里接，不得重述）】",
        f"- 桥段 {prev.bridge_number}《{prev.title}》→ 第 {last.chapter_number} 章《{last.title}》",
    ]
    if last.plot_points:
        lines.append(f"- 剧情要点：{_clip(last.plot_points, 300)}")
    if isinstance(events, list) and events:
        lines.append(f"- 关键事件：{'、'.join(str(e) for e in events[:6])}")
    if prev.next_bridge_hook:
        lines.append(f"- 留给本桥段的钩子：{prev.next_bridge_hook}")
    return "\n".join(lines)


async def next_bridge_block(db: AsyncSession, project_id: str, bridge_number: int) -> str:
    """【➡ 下一桥段目标】下一桥段已填充时给出，供 C4 引子精确指向。"""
    nxt = (await db.execute(
        select(PlotBridge).where(
            PlotBridge.project_id == project_id, PlotBridge.bridge_number == bridge_number + 1
        )
    )).scalar_one_or_none()
    if nxt is None or nxt.status == "draft" or not (nxt.goal or "").strip():
        return ""
    return f"【➡ 下一桥段目标（C4 引子要指向这里）】\n- 桥段 {nxt.bridge_number}《{nxt.title}》：{_clip(nxt.goal, 150)}"


def pov_line(narrative_perspective: str | None) -> str:
    perspective = (narrative_perspective or "").strip() or "第三人称"
    if "第一" in perspective:
        return "叙事视角：第一人称（“我”= 主角；章纲 pov 字段固定填主角名，卡片用第三人称记录）"
    return f"叙事视角：{perspective}"


# ---------------- provenance ----------------

def build_fill_provenance(
    prompt: Any,
    *,
    model: str,
    template_key: str,
    beat_index: int,
    beat_title: str,
    bridge_numbers: list[int],
    next_beat_title: str | None,
    prev_bridge_number: int | None,
    ledger_numbers: list[int],
    opening: bool,
    story_fields: list[str],
    pack_title: str | None,
    dimensions: dict[str, str],
    phase: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """一次桥段填充调用"参考了什么、缺了什么"。落 plot_bridges.generation_meta，也随 SSE meta 事件下发。"""
    filled = list(prompt.slots_filled)
    truncated = list(prompt.slots_truncated)
    skipped = list(prompt.slots_skipped)

    warnings: list[str] = []
    if "project_skeleton" in truncated:
        warnings.append(
            f"项目信息被截断（模型档位 {prompt.model_tier or '?'}）：请精简世界观文字，或在「设置」里选更大窗口的模型"
        )
    if not pack_title:
        dims = "/".join(
            _DISSECT_DIM_LABEL.get(d, d)
            for d in ("methodology", "structure", "bridges", "character_archive", "synopsis")
        )
        warnings.append(f"未挂载拆书参考包：{dims} 维度均未注入（项目 → 参考包页可挂载）")
    if "project_characters" in skipped:
        warnings.append("项目没有角色档案：LLM 会自行起名，建议先生成角色再填充")
    if "world_rules_table" in skipped:
        warnings.append("未配置世界规则表（境界 / 装备 / 地图）：升级节奏与地点无硬约束")

    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scene": prompt.scene or "bridge_planning",
        "model": model,
        "model_tier": prompt.model_tier,
        "template": template_key,
        "reference_pack": {"title": pack_title, "dimensions": dimensions} if pack_title else None,
        "slots": {"filled": filled, "truncated": truncated, "skipped": skipped},
        "inputs": {
            "story_outline_fields": list(story_fields),
            "beat": {"index": beat_index, "title": beat_title},
            "next_beat_title": next_beat_title,
            "prev_bridge_number": prev_bridge_number,
            "ledger_bridge_numbers": list(ledger_numbers),
            "opening_rules": opening,
            "bridge_numbers": list(bridge_numbers),
            "phase": dict(phase) if phase else None,
        },
        "tokens_estimate": prompt.actual_tokens_estimate,
        "warnings": warnings,
    }
