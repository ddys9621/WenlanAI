"""长节点阶段拆分（纯函数 + prompt；无 DB / 无 LLM 调用）。

问题：主线节点 300 字描述要撑起 10-60 个 4 章桥段，填充 LLM 只看到"节点进度 X%→Y%"，必然同质化、原地打转。
网文实际是三层：卷 → 剧情单元（10-30 章一件事）→ 章。节点 ≈ 卷，桥段 ≈ 章组，中间缺"剧情单元"这一层。

方案：节点桥段数 ≥ PHASE_SPLIT_MIN_BRIDGES 时，填充前先把节点拆成 K = ceil(n / PHASE_MAX_BRIDGES) 个连续阶段，
阶段↔桥段的对应关系由代码算定（phase_ranges），LLM 只填每个阶段的创意内容（目标 / 对手 / 赌注 / 收获 / 境界 / 舞台 / 钩子）。
阶段存进 PlotLine.timeline_data.beats[i].phases，填充按阶段分批、展开按桥段查所属阶段。
"""
from __future__ import annotations

import math
from typing import Any

from app.services.bridge_slot_planner import chapter_range

PHASE_SPLIT_MIN_BRIDGES = 5   # 节点桥段数达到这个值才拆阶段（4 个桥段 = 16 章，一个剧情单元就够了）
PHASE_MAX_BRIDGES = 4         # 每阶段最多几个桥段（= 一次 LLM 填充批次）

PHASE_TEXT_FIELDS: tuple[str, ...] = ("title", "goal", "antagonist", "stake", "gain", "realm", "location", "hook")
_PHASE_FIELD_LIMITS = {"title": 40, "goal": 300, "antagonist": 120, "stake": 120, "gain": 120, "realm": 80, "location": 80, "hook": 120}


def phase_ranges(bridge_numbers: list[int], max_per_phase: int = PHASE_MAX_BRIDGES) -> list[list[int]]:
    """把节点的桥段号（已排序）均匀切成 ceil(n / max) 个连续组，组间大小相差 ≤ 1，大的在前。"""
    numbers = sorted(bridge_numbers)
    if not numbers:
        return []
    k = max(1, math.ceil(len(numbers) / max_per_phase))
    base, extra = divmod(len(numbers), k)
    out: list[list[int]] = []
    pos = 0
    for i in range(k):
        size = base + (1 if i < extra else 0)
        out.append(numbers[pos:pos + size])
        pos += size
    return out


def parse_phases(raw: Any, ranges: list[list[int]]) -> list[dict[str, Any]] | None:
    """校验并归一化 LLM 输出：数量必须等于 ranges，title / goal 必填；其余字段可空。返回 None = 不合格。"""
    if not isinstance(raw, list) or len(raw) != len(ranges) or not ranges:
        return None
    phases: list[dict[str, Any]] = []
    for i, (item, numbers) in enumerate(zip(raw, ranges)):
        if not isinstance(item, dict):
            return None
        phase: dict[str, Any] = {"index": i + 1}
        for field in PHASE_TEXT_FIELDS:
            phase[field] = " ".join(str(item.get(field) or "").split())[:_PHASE_FIELD_LIMITS[field]]
        if not phase["title"] or not phase["goal"]:
            return None
        phase["bridge_start"], phase["bridge_end"] = numbers[0], numbers[-1]
        phases.append(phase)
    return phases


def phase_for_bridge(phases: Any, bridge_number: int) -> dict[str, Any] | None:
    for p in phases or ():
        if isinstance(p, dict) and _int(p.get("bridge_start")) <= bridge_number <= _int(p.get("bridge_end"), default=-1):
            return p
    return None


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def phase_facts(p: dict[str, Any]) -> str:
    """对手 ｜ 赌注 ｜ 收获 ｜ 境界 ｜ 舞台（空字段跳过）。"""
    facts = [
        f"{label}：{p.get(key)}"
        for key, label in (("antagonist", "对手"), ("stake", "赌注"), ("gain", "阶段末收获"), ("realm", "境界"), ("location", "舞台"))
        if p.get(key)
    ]
    return " ｜ ".join(facts)


def render_phase_block(phases: list[dict[str, Any]], current_index: int) -> str:
    """【🧭 节点内阶段】当前阶段 ★ 展开全部字段；其余阶段一行（已收尾 / 待开启）。"""
    total = len(phases)
    lines = [f"【🧭 节点内阶段（本批属于阶段 {current_index}/{total}）】"]
    for p in phases:
        head = f"阶段 {p['index']}《{p['title']}》桥段 {p['bridge_start']}-{p['bridge_end']}"
        if p["index"] == current_index:
            lines.append(f"★ {head}：{p['goal']}")
            facts = phase_facts(p)
            if facts:
                lines.append(f"  {facts}")
            if p.get("hook"):
                lines.append(f"  阶段末钩子：{p['hook']}")
        else:
            state = "已收尾" if p["index"] < current_index else "待开启"
            lines.append(f"- {head}（{state}）：{p['goal'][:60]}")
    lines.append("")
    lines.append(
        f"本批桥段共同完成阶段 {current_index} 的目标：对手与赌注不得低于上一阶段，"
        f"本阶段最后一个桥段的 C4 收获 = 阶段末收获，并用阶段末钩子转入下一阶段。"
    )
    return "\n".join(lines)


PHASE_SPLIT_TASK_PROMPT = """请把主线节点 [节点 {beat_index}] {beat_title} 拆成 {count} 个递进阶段。该节点共 {bridge_count} 个桥段（第 {c_start}-{c_end} 章，每桥段 4 章），阶段与桥段的对应关系已由系统确定，**只填创意内容**：
{ranges_table}

# 阶段设计纪律（网文剧情单元）
- 每个阶段 = 一个 10-16 章的剧情单元：一件完整的事（一张小地图 / 一个对手 / 一次任务），自带起承转合
- 对手层级、赌注、舞台逐阶段抬高，不得回落、不得原地打转；相邻阶段必须换对手或换舞台
- 最后一个阶段的末尾完成本节点的目标与钩子（节点描述里的收尾），前面的阶段只能部分推进，不得提前兑现节点终点
- 每个阶段末有可见收获（实力 / 资源 / 人脉 / 信息之一）和转入下一阶段的钩子
- {payoff_label}节奏：每个阶段至少一次完整的{payoff_label}兑现，相邻阶段兑现方式不得同型
- 人名、地名、势力名只能使用【本书角色】【世界规则表】里已有的；确需新角色时用"新角色：身份"标注

# 输出格式（纯 JSON 数组，{count} 个对象，按阶段顺序，不要 markdown）
[
  {{
    "index": 1,
    "title": "阶段标题（6-12 字）",
    "goal": "本阶段要解决的事（40-80 字）",
    "antagonist": "对手 / 压力来源及其层级（≤30 字）",
    "stake": "赌注 / 危机升级点（≤30 字）",
    "gain": "阶段末可见收获（≤30 字）",
    "realm": "主角境界 / 地位从哪到哪（可空）",
    "location": "主要舞台（可空）",
    "hook": "转入下一阶段的钩子（≤30 字）"
  }}
]
"""


def render_phase_split_task(beat_index: int, beat_title: str, ranges: list[list[int]], payoff_label: str) -> str:
    rows = []
    for i, numbers in enumerate(ranges, start=1):
        c_start, c_end = chapter_range(numbers[0])[0], chapter_range(numbers[-1])[1]
        rows.append(f"- 阶段 {i}：桥段 {numbers[0]}-{numbers[-1]}（第 {c_start}-{c_end} 章）")
    all_numbers = [n for r in ranges for n in r]
    return PHASE_SPLIT_TASK_PROMPT.format(
        beat_index=beat_index, beat_title=beat_title, count=len(ranges), bridge_count=len(all_numbers),
        c_start=chapter_range(all_numbers[0])[0], c_end=chapter_range(all_numbers[-1])[1],
        ranges_table="\n".join(rows), payoff_label=payoff_label,
    )
