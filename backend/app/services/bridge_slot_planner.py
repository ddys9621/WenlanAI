"""工程化桥段流水线 — 槽位规划器（纯函数，无 DB / 无 LLM）。

规则（设计文档 @/agent-docs/plans/2026-09-10-sub-line-anchoring-phase1.md §0.3）：
- 且仅一条主线；桥段总数 T = max(1, round(estimated_chapters / 4))
- 节点配额 = 最大余数法，每节点至少 1 个桥段；份额优先用节点 chapters（篇幅），缺失时用 weight（重要性）
- 主线 ≥ 5 个节点时首节点最多 OPENING_BEAT_MAX_BRIDGES 个桥段（开篇不拖），超出配额按份额回流
- 桥段 n 覆盖第 4(n-1)+1 … 4n 章
- 锚定支线（所有节点带 anchor_beat）：节点整体落进所锚定主线节点的一个桥段（merge → 末桥段，offset → 均匀散开避开末桥段）；
  主推配额多于节点数时，权重最高的 offset 节点扩成 2 个连续桥段（用满预算）
- 未锚定支线（旧数据）：节点按累计权重铺满全书 [0,1]，与桥段区间求交
- 每桥段只保留一条主 B 线（role=primary），其余 mention；锚定支线主推桥段数受 estimated_chapters/4 配额约束
- companion（伴生）支线：首次出场后到锚定终点之间没有任务的桥段自动补 mention（保温一句），不让线消失几十章
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from app.utils.plot_line_types import normalize_plot_line_type

CHAPTERS_PER_BRIDGE = 4
SUB_BUDGET_SHARE = 0.4   # 支线总篇幅预算占全书上限（网文 B 线占比经验 20-40%）
# 开篇节点（觉醒 / 金手指到手）最多占几个桥段：网文前 30 章定生死，开篇不能拖。
# 只对 ≥ OPENING_CAP_MIN_BEATS 个节点的主线生效——节点更少时首节点是"卷"级单元，不夹。
OPENING_BEAT_MAX_BRIDGES = 3
OPENING_CAP_MIN_BEATS = 5


class BridgePlanningPreconditionError(ValueError):
    """前置条件不满足（API 层映射为 400）。"""


class BridgePlanningConflictError(RuntimeError):
    """状态冲突，例如骨架已存在 / 已有展开章纲（API 层映射为 409）。"""


VALID_MODES: tuple[str, ...] = ("companion", "inserted", "converge")
VALID_RELATIONS: tuple[str, ...] = ("offset", "merge")
MENTION_FILL_MODES: tuple[str, ...] = ("companion",)   # 锚定区间内自动补保温的支线模式


@dataclass(frozen=True)
class BeatData:
    index: int
    title: str
    description: str
    weight: float                    # 重要性（全书高潮最高）；主线篇幅优先用 chapters，缺失时才按 weight 分
    anchor_beat: int | None = None   # 锚定的主线节点 index；None = 未锚定（旧数据）
    relation: str = "offset"         # offset（与主线错峰推进）/ merge（汇入主线该节点的兑现桥段）
    key: str = ""                    # 节点类型（opening / power_up / face_slap …），进桥段 prompt
    chapters: int | None = None      # 本节点预计章数（篇幅）；None = 旧数据
    location: str = ""               # 主要舞台（地图 / 势力 / 城市）
    antagonist: str = ""             # 主要对手 / 压力来源及层级
    realm: str = ""                  # 主角境界 / 实力 / 地位从哪到哪
    phases: tuple[dict[str, Any], ...] = ()   # 长节点阶段拆分结果（bridge_phases.parse_phases 产出；空 = 未拆）


@dataclass(frozen=True)
class PlotLineData:
    id: str
    title: str
    line_type: str
    estimated_chapters: int | None
    beats: tuple[BeatData, ...]
    mode: str | None = None          # companion / inserted / converge；None = 未锚定
    anchor_start_beat: int | None = None
    anchor_end_beat: int | None = None


@dataclass(frozen=True)
class SecondaryBeatTask:
    plot_line_id: str
    line_title: str
    line_type: str
    beat_index: int
    beat_title: str
    beat_description: str
    coverage_start: float
    coverage_end: float
    role: str = "primary"            # primary（本桥段主 B 线，须推进）/ mention（保温提及一句）
    relation: str = "offset"


def is_anchored(line: PlotLineData) -> bool:
    """全部节点都带 anchor_beat 才算锚定支线；否则整条线走均匀铺满（旧算法）。"""
    return bool(line.beats) and all(b.anchor_beat is not None for b in line.beats)


def _opt_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class BridgeSlot:
    bridge_number: int
    plot_line_id: str
    beat_index: int
    beat_title: str
    beat_description: str
    beat_weight: float
    coverage_start: float
    coverage_end: float
    chapter_start: int
    chapter_end: int
    secondary: tuple[SecondaryBeatTask, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LineBudget:
    """一条副线在本次规划中的预算账：配额 vs 实际主推 / 保温桥段数（供预览与 prompt 骨架显示）。"""
    plot_line_id: str
    line_title: str
    line_type: str
    anchored: bool
    mode: str | None
    anchor_start_beat: int | None
    anchor_end_beat: int | None
    estimated_chapters: int | None
    primary_quota: int          # 锚定线：round(est/4) 夹 [1,T]；未锚定线：0（不限）
    primary_bridges: int
    mention_bridges: int


@dataclass(frozen=True)
class BridgeSlotPlan:
    main_line_id: str
    total_bridges: int
    total_chapters: int
    beat_quotas: dict[int, int]
    slots: tuple[BridgeSlot, ...]
    line_budgets: tuple[LineBudget, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "main_line_id": self.main_line_id,
            "total_bridges": self.total_bridges,
            "total_chapters": self.total_chapters,
            "beat_quotas": {str(k): v for k, v in self.beat_quotas.items()},
            "slots": [
                {**asdict(s), "secondary": [asdict(t) for t in s.secondary]}
                for s in self.slots
            ],
            "line_budgets": [asdict(b) for b in self.line_budgets],
        }


def chapter_range(bridge_number: int) -> tuple[int, int]:
    start = CHAPTERS_PER_BRIDGE * (bridge_number - 1) + 1
    return start, start + CHAPTERS_PER_BRIDGE - 1


def primary_quota(estimated_chapters: int | None, total_bridges: int) -> int:
    """支线篇幅预算 → 主推桥段配额：round(章数 / 4)，夹在 [1, 桥段总数]。"""
    if not estimated_chapters or estimated_chapters < 1:
        return 1
    return max(1, min(total_bridges, round(estimated_chapters / CHAPTERS_PER_BRIDGE)))


def sub_budget_cap(chapter_count: int, sub_line_count: int) -> int:
    """单条支线篇幅预算上限（章）：全书 SUB_BUDGET_SHARE 均分给各支线，最少 1 个桥段。"""
    if sub_line_count <= 0:
        return 0
    return max(CHAPTERS_PER_BRIDGE, int(chapter_count * SUB_BUDGET_SHARE / sub_line_count))


def apportion(weights: list[float], total: int, minimum: int = 1) -> list[int]:
    """最大余数法分配整数配额。每项至少 minimum，sum == max(total, minimum*n)。同余数索引小者优先。"""
    n = len(weights)
    if n == 0:
        return []
    total = max(total, minimum * n)
    safe = [max(0.0, float(w)) for w in weights]
    w_sum = sum(safe) or 1.0
    remaining = total - minimum * n
    raw = [w / w_sum * remaining for w in safe]
    floors = [int(math.floor(r)) for r in raw]
    deficit = remaining - sum(floors)
    order = sorted(range(n), key=lambda i: (raw[i] - floors[i], -i), reverse=True)
    for i in order[:deficit]:
        floors[i] += 1
    return [minimum + f for f in floors]


def parse_plot_line(line: Any) -> PlotLineData:
    """ORM PlotLine → 纯数据。timeline_data 损坏 / 非 dict / 非 dict 元素一律丢弃；锚点字段缺失或非法 → None / offset。"""
    raw: dict[str, Any] = {}
    if getattr(line, "timeline_data", None):
        try:
            loaded = json.loads(line.timeline_data)
            raw = loaded if isinstance(loaded, dict) else {}
        except (json.JSONDecodeError, TypeError):
            raw = {}
    raw_beats = raw.get("beats") or []
    if not isinstance(raw_beats, list):
        raw_beats = []
    beats: list[BeatData] = []
    for i, b in enumerate(raw_beats):
        if not isinstance(b, dict):
            continue
        try:
            weight = float(b.get("weight") or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        relation = b.get("relation")
        chapters = _opt_int(b.get("chapters"))
        raw_phases = b.get("phases")
        phases = tuple(p for p in raw_phases if isinstance(p, dict)) if isinstance(raw_phases, list) else ()
        beats.append(BeatData(
            index=int(b.get("index", i + 1)),
            title=str(b.get("title") or f"节点{i + 1}").strip(),
            description=str(b.get("description") or "").strip(),
            weight=weight,
            anchor_beat=_opt_int(b.get("anchor_beat")),
            relation=relation if relation in VALID_RELATIONS else "offset",
            key=str(b.get("key") or "").strip(),
            chapters=chapters if chapters and chapters > 0 else None,
            location=str(b.get("location") or "").strip(),
            antagonist=str(b.get("antagonist") or "").strip(),
            realm=str(b.get("realm") or "").strip(),
            phases=phases,
        ))
    beats.sort(key=lambda x: x.index)
    mode = raw.get("mode")
    return PlotLineData(
        id=line.id,
        title=(line.title or "").strip(),
        line_type=normalize_plot_line_type(getattr(line, "line_type", None)),
        estimated_chapters=getattr(line, "estimated_chapters", None),
        beats=tuple(beats),
        mode=mode if mode in VALID_MODES else None,
        anchor_start_beat=_opt_int(raw.get("anchor_start_beat")),
        anchor_end_beat=_opt_int(raw.get("anchor_end_beat")),
    )


def select_main_line(lines: list[PlotLineData]) -> PlotLineData:
    mains = [l for l in lines if l.line_type == "main"]
    if not mains:
        raise BridgePlanningPreconditionError("项目没有主线剧情线，请先生成主线（line_type=main）")
    if len(mains) > 1:
        raise BridgePlanningPreconditionError(
            f"项目存在 {len(mains)} 条主线，工程化流水线要求且仅要求一条主线，请合并或删除多余主线"
        )
    main = mains[0]
    if not main.beats:
        raise BridgePlanningPreconditionError(f"主线《{main.title}》没有节点（beats），请先生成节点")
    if not main.estimated_chapters or main.estimated_chapters < 1:
        raise BridgePlanningPreconditionError(f"主线《{main.title}》缺少预计章节数（estimated_chapters）")
    if any(b.weight <= 0 for b in main.beats):
        raise BridgePlanningPreconditionError(f"主线《{main.title}》存在权重 ≤ 0 的节点，请修正节点权重")
    return main


def _secondary_tasks(
    lines: list[PlotLineData], frac_start: float, frac_end: float
) -> list[SecondaryBeatTask]:
    tasks: list[SecondaryBeatTask] = []
    for line in lines:
        w_sum = sum(max(0.0, b.weight) for b in line.beats) or 1.0
        cum = 0.0
        for b in line.beats:
            b_start = cum
            b_end = cum + max(0.0, b.weight) / w_sum
            cum = b_end
            span = b_end - b_start
            if span <= 0:
                continue
            o_start = max(frac_start, b_start)
            o_end = min(frac_end, b_end)
            if o_end - o_start <= 1e-9:
                continue
            tasks.append(SecondaryBeatTask(
                plot_line_id=line.id,
                line_title=line.title,
                line_type=line.line_type,
                beat_index=b.index,
                beat_title=b.title,
                beat_description=b.description,
                coverage_start=round((o_start - b_start) / span, 4),
                coverage_end=round((o_end - b_start) / span, 4),
            ))
    return tasks


def _task(line: PlotLineData, beat: BeatData, start: float = 0.0, end: float = 1.0) -> SecondaryBeatTask:
    return SecondaryBeatTask(
        plot_line_id=line.id, line_title=line.title, line_type=line.line_type,
        beat_index=beat.index, beat_title=beat.title, beat_description=beat.description,
        coverage_start=start, coverage_end=end, role="primary", relation=beat.relation,
    )


def _anchored_tasks(
    line: PlotLineData, bridges_by_beat: dict[int, list[int]], total_bridges: int
) -> dict[int, list[SecondaryBeatTask]]:
    """锚定支线落位：每个支线节点整体进一个桥段（coverage 0→1），锚定区间外的桥段休眠。

    - merge：进所锚定主线节点的最后一个桥段（该节点的兑现桥段）
    - offset：在该节点的桥段里均匀散开；节点有 ≥2 个桥段时避开最后一个（兑现桥段留给主线）
    - anchor_beat 不是主线节点 index 时夹到最近的主线节点（容错，不抛错）
    - 预算解耦：主推配额（estimated_chapters/4）多于节点数时，权重最高的 offset 节点扩成 2 个连续桥段
      （前半 0→50%、后半 50→100%），只向同锚定节点内的相邻非末桥段扩，不与本线其他节点撞桥段
    """
    grouped: dict[int, list[BeatData]] = {}
    for b in line.beats:
        grouped.setdefault(_nearest_main_beat(b.anchor_beat, bridges_by_beat), []).append(b)

    out: dict[int, list[SecondaryBeatTask]] = {}
    placement: dict[int, tuple[int, list[int]]] = {}   # beat.index → (落位桥段, 该锚定节点可用的 offset 候选桥段)
    for anchor in sorted(grouped):
        numbers = bridges_by_beat[anchor]
        offsets = [b for b in grouped[anchor] if b.relation != "merge"]
        candidates = numbers[:-1] if len(numbers) > 1 else numbers
        for k, b in enumerate(offsets):
            target = candidates[int((k + 0.5) * len(candidates) / len(offsets))]
            out.setdefault(target, []).append(_task(line, b))
            placement[b.index] = (target, candidates)
        for b in grouped[anchor]:
            if b.relation == "merge":
                out.setdefault(numbers[-1], []).append(_task(line, b))

    spare = primary_quota(line.estimated_chapters, total_bridges) - len(line.beats)
    offsets_by_weight = sorted((b for b in line.beats if b.relation != "merge"), key=lambda b: (-b.weight, b.index))
    if spare >= 1 and offsets_by_weight:
        top = offsets_by_weight[0]
        target, candidates = placement[top.index]
        for neighbour in (target + 1, target - 1):
            if neighbour in candidates and neighbour not in out:
                out[target] = [replace(t, coverage_end=0.5) if t.beat_index == top.index else t for t in out[target]]
                out[neighbour] = [_task(line, top, 0.5, 1.0)]
                break
    return out


def _resolve_roles(
    tasks_by_bridge: dict[int, list[SecondaryBeatTask]], lines: list[PlotLineData]
) -> dict[int, list[SecondaryBeatTask]]:
    """每桥段只留一条主 B 线，其余降为 mention。

    优先级：本桥段含 merge 节点 > 距上次主推最远（首次出现 = 桥段号）> estimated_chapters 大 > 剧情线顺序。
    同线同桥段的多个任务同角色。
    """
    est = {l.id: l.estimated_chapters or 0 for l in lines}
    order = {l.id: i for i, l in enumerate(lines)}
    last_primary = {l.id: 0 for l in lines}
    out: dict[int, list[SecondaryBeatTask]] = {}
    for n in sorted(tasks_by_bridge):
        tasks = tasks_by_bridge[n]
        line_ids = list(dict.fromkeys(t.plot_line_id for t in tasks))
        if not line_ids:
            out[n] = []
            continue
        winner = min(line_ids, key=lambda lid: (
            0 if any(t.plot_line_id == lid and t.relation == "merge" for t in tasks) else 1,
            -(n - last_primary[lid]),
            -est[lid],
            order[lid],
        ))
        out[n] = [t if t.plot_line_id == winner else replace(t, role="mention") for t in tasks]
        last_primary[winner] = n
    return out


def _apply_budget_caps(
    tasks_by_bridge: dict[int, list[SecondaryBeatTask]], lines: list[PlotLineData], total: int
) -> dict[int, list[SecondaryBeatTask]]:
    """锚定支线主推桥段数超过预算配额时降级：节点权重低者先降、同权重桥段号大者先降；含 merge 的桥段永不降。"""
    for line in lines:
        if not is_anchored(line):
            continue
        quota = primary_quota(line.estimated_chapters, total)
        weights = {b.index: b.weight for b in line.beats}
        primary_bridges = [
            n for n, ts in sorted(tasks_by_bridge.items())
            if any(t.plot_line_id == line.id and t.role == "primary" for t in ts)
        ]
        excess = len(primary_bridges) - quota
        if excess <= 0:
            continue
        demotable: list[tuple[float, int, int]] = []
        for n in primary_bridges:
            mine = [t for t in tasks_by_bridge[n] if t.plot_line_id == line.id]
            if any(t.relation == "merge" for t in mine):
                continue
            demotable.append((max(weights.get(t.beat_index, 0.0) for t in mine), -n, n))
        for _, _, n in sorted(demotable)[:excess]:
            tasks_by_bridge[n] = [
                replace(t, role="mention") if t.plot_line_id == line.id else t for t in tasks_by_bridge[n]
            ]
    return tasks_by_bridge


def _nearest_main_beat(anchor: int | None, bridges_by_beat: dict[int, list[int]]) -> int | None:
    if anchor is None or not bridges_by_beat:
        return None
    if anchor in bridges_by_beat:
        return anchor
    return min(sorted(bridges_by_beat), key=lambda m: (abs(m - anchor), m))


def _fill_companion_mentions(
    tasks_by_bridge: dict[int, list[SecondaryBeatTask]], lines: list[PlotLineData], bridges_by_beat: dict[int, list[int]]
) -> dict[int, list[SecondaryBeatTask]]:
    """伴生型支线保温：从本线首次出场的桥段起，到锚定终点节点的最后一个桥段，没有任务的桥段补一条 mention。

    引用最近一个已出场的支线节点（coverage 1→1 = 已完成，只带过现状）。首次出场之前不补——事件还没发生。
    只对 MENTION_FILL_MODES 生效：inserted 是一次性插入后退场，converge 独立发展后并入，都不该被硬塞保温。
    """
    for line in lines:
        if not is_anchored(line) or line.mode not in MENTION_FILL_MODES:
            continue
        present = sorted(n for n, ts in tasks_by_bridge.items() if any(t.plot_line_id == line.id for t in ts))
        if not present:
            continue
        end_anchor = _nearest_main_beat(line.anchor_end_beat, bridges_by_beat)
        last = max(bridges_by_beat[end_anchor]) if end_anchor is not None else present[-1]
        latest: SecondaryBeatTask | None = None
        for n in range(present[0], max(last, present[-1]) + 1):
            mine = [t for t in tasks_by_bridge[n] if t.plot_line_id == line.id]
            if mine:
                latest = max(mine, key=lambda t: t.beat_index)
            elif latest is not None:
                tasks_by_bridge[n].append(replace(latest, role="mention", coverage_start=1.0, coverage_end=1.0))
    return tasks_by_bridge


def _line_budgets(
    tasks_by_bridge: dict[int, list[SecondaryBeatTask]], lines: list[PlotLineData], total: int
) -> tuple[LineBudget, ...]:
    out: list[LineBudget] = []
    for line in lines:
        primary = mention = 0
        for ts in tasks_by_bridge.values():
            mine = [t for t in ts if t.plot_line_id == line.id]
            if not mine:
                continue
            if any(t.role == "primary" for t in mine):
                primary += 1
            else:
                mention += 1
        anchored = is_anchored(line)
        out.append(LineBudget(
            plot_line_id=line.id, line_title=line.title, line_type=line.line_type,
            anchored=anchored, mode=line.mode,
            anchor_start_beat=line.anchor_start_beat, anchor_end_beat=line.anchor_end_beat,
            estimated_chapters=line.estimated_chapters,
            primary_quota=primary_quota(line.estimated_chapters, total) if anchored else 0,
            primary_bridges=primary, mention_bridges=mention,
        ))
    return tuple(out)


def beat_shares(main: PlotLineData) -> list[float]:
    """节点篇幅份额：所有节点都带 chapters 时按 chapters（重要性与篇幅分离），否则退回 weight。"""
    if all(b.chapters for b in main.beats):
        return [float(b.chapters) for b in main.beats]
    return [b.weight for b in main.beats]


def main_beat_quotas(main: PlotLineData, total: int) -> list[int]:
    """主线节点 → 桥段配额：最大余数法 + 开篇节点上限（超出部分按份额回流给其余节点，总数不变）。"""
    shares = beat_shares(main)
    quotas = apportion(shares, total, minimum=1)
    if len(quotas) >= OPENING_CAP_MIN_BEATS and quotas[0] > OPENING_BEAT_MAX_BRIDGES:
        rest_total = sum(quotas) - OPENING_BEAT_MAX_BRIDGES
        quotas = [OPENING_BEAT_MAX_BRIDGES, *apportion(shares[1:], rest_total, minimum=1)]
    return quotas


def compute_bridge_slots(lines: list[PlotLineData]) -> BridgeSlotPlan:
    main = select_main_line(lines)
    total = max(1, round(main.estimated_chapters / CHAPTERS_PER_BRIDGE))
    quotas = main_beat_quotas(main, total)
    total = sum(quotas)
    secondaries = [l for l in lines if l.line_type != "main" and l.beats]

    # 主线槽位骨架（先不挂副线）
    skeleton: list[tuple[int, BeatData, int, int]] = []   # (bridge_number, beat, quota, j)
    bridges_by_beat: dict[int, list[int]] = {}
    number = 0
    for beat, quota in zip(main.beats, quotas):
        for j in range(quota):
            number += 1
            skeleton.append((number, beat, quota, j))
            bridges_by_beat.setdefault(beat.index, []).append(number)

    # 副线落位：锚定线按节点落位；未锚定线沿用全书进度求交
    tasks_by_bridge: dict[int, list[SecondaryBeatTask]] = {n: [] for n in range(1, total + 1)}
    for line in secondaries:
        if is_anchored(line):
            for n, ts in _anchored_tasks(line, bridges_by_beat, total).items():
                tasks_by_bridge[n].extend(ts)
        else:
            for n in range(1, total + 1):
                tasks_by_bridge[n].extend(_secondary_tasks([line], (n - 1) / total, n / total))
    tasks_by_bridge = _resolve_roles(tasks_by_bridge, secondaries)
    tasks_by_bridge = _apply_budget_caps(tasks_by_bridge, secondaries, total)
    tasks_by_bridge = _fill_companion_mentions(tasks_by_bridge, secondaries, bridges_by_beat)

    slots = [
        BridgeSlot(
            bridge_number=n,
            plot_line_id=main.id,
            beat_index=beat.index,
            beat_title=beat.title,
            beat_description=beat.description,
            beat_weight=beat.weight,
            coverage_start=j / quota,
            coverage_end=(j + 1) / quota,
            chapter_start=chapter_range(n)[0],
            chapter_end=chapter_range(n)[1],
            secondary=tuple(tasks_by_bridge[n]),
        )
        for n, beat, quota, j in skeleton
    ]
    return BridgeSlotPlan(
        main_line_id=main.id,
        total_bridges=total,
        total_chapters=total * CHAPTERS_PER_BRIDGE,
        beat_quotas={b.index: q for b, q in zip(main.beats, quotas)},
        slots=tuple(slots),
        line_budgets=_line_budgets(tasks_by_bridge, secondaries, total),
    )
