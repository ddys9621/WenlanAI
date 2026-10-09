"""层级剧情摘要：单元（桥段 / 4 章）→ 阶段（节点阶段 / 16 章）→ 卷（主线节点 / 64 章）。

- resolve_arcs：章节属于哪个单元 / 阶段 / 卷。桥段模式按桥段实际章号区间、主线节点与节点阶段；
  不在任何桥段里的章节退回固定分块（4 / 16 / 64 章）。
- maybe_rollup：每章分析完调用。所在单元 / 阶段 / 卷的章节全部有摘要时汇总（先补齐缺失的子摘要），
  子摘要指纹不变就跳过；卷汇总同时产出「卷末复盘」并回写到下一主线节点的 review_note，
  下一卷的桥段填充 / 章纲展开会读到它（计划随实际写出来的内容修正）。
  另外每次顺带补几个更早的缺口（项目中途启用本功能时逐步追平）。
- invalidate_covering：某章被重新分析 / 覆盖后，删掉覆盖它的各级摘要（之后自然重算）。
- render_story_so_far：「前情脉络」——对每段章节取能覆盖它的最高一级摘要，超预算先压缩最早的。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.arc_summary import ArcSummary
from app.models.chapter import Chapter
from app.models.memory import StoryMemory
from app.models.plot_bridge import PlotBridge
from app.models.plot_line import PlotLine
from app.services.bridge_slot_planner import bridge_chapter_range
from app.services.context_budget import clip_text

logger = get_logger(__name__)

LEVELS: tuple[str, ...] = ("unit", "phase", "volume")
LEVEL_RANK = {"unit": 1, "phase": 2, "volume": 3}
BLOCK_SIZES = {"unit": 4, "phase": 16, "volume": 64}
SUMMARY_LIMITS = {"unit": 220, "phase": 320, "volume": 450}
BACKFILL_BUDGET = 3
COMPRESSED_CHARS = 80


@dataclass(frozen=True)
class ArcRef:
    level: str
    key: str
    start: int
    end: int
    title: str = ""
    plot_line_id: Optional[str] = None
    beat_index: Optional[int] = None


@dataclass
class ChapterArcs:
    unit: ArcRef
    phase: Optional[ArcRef]
    volume: ArcRef


@dataclass
class _BridgeInfo:
    number: int
    beat_index: Optional[int]
    plot_line_id: Optional[str]
    start: int
    end: int
    title: str


@dataclass
class ArcIndex:
    """一次查库把桥段 / 主线节点 / 节点阶段装进内存，之后按章号纯计算三级归属。"""

    bridges: list[_BridgeInfo] = field(default_factory=list)
    beats: dict[int, dict[str, Any]] = field(default_factory=dict)
    main_line_id: Optional[str] = None

    @classmethod
    async def load(cls, db: AsyncSession, project_id: str) -> "ArcIndex":
        rows = (await db.execute(
            select(PlotBridge).where(PlotBridge.project_id == project_id).order_by(PlotBridge.bridge_number)
        )).scalars().all()
        bridges = []
        for b in rows:
            start, end = bridge_chapter_range(b)
            bridges.append(_BridgeInfo(b.bridge_number, b.beat_index, b.plot_line_id, start, end, b.title or ""))
        beats: dict[int, dict[str, Any]] = {}
        main_line_id = next((b.plot_line_id for b in bridges if b.plot_line_id), None)
        if main_line_id:
            line = (await db.execute(select(PlotLine).where(PlotLine.id == main_line_id))).scalar_one_or_none()
            if line is not None and line.timeline_data:
                try:
                    data = json.loads(line.timeline_data)
                except (json.JSONDecodeError, TypeError):
                    data = {}
                for raw in (data.get("beats") or []) if isinstance(data, dict) else []:
                    if isinstance(raw, dict) and str(raw.get("index", "")).lstrip("-").isdigit():
                        beats[int(raw["index"])] = raw
        return cls(bridges=bridges, beats=beats, main_line_id=main_line_id)

    # ---------------- 归属 ----------------

    def _bridge_at(self, chapter_number: int) -> Optional[_BridgeInfo]:
        return next((b for b in self.bridges if b.start <= chapter_number <= b.end), None)

    def _beat_bridges(self, beat_index: int) -> list[_BridgeInfo]:
        return [b for b in self.bridges if b.beat_index == beat_index]

    def _phases(self, beat_index: int) -> list[dict[str, Any]]:
        phases = (self.beats.get(beat_index) or {}).get("phases") or []
        return [p for p in phases if isinstance(p, dict) and p.get("bridge_start") and p.get("bridge_end")]

    def _unit_ref(self, b: _BridgeInfo) -> ArcRef:
        return ArcRef("unit", f"bridge:{b.number}", b.start, b.end, b.title, b.plot_line_id, b.beat_index)

    def _phase_ref(self, beat_index: int, phase: dict[str, Any]) -> Optional[ArcRef]:
        members = [b for b in self._beat_bridges(beat_index)
                   if int(phase["bridge_start"]) <= b.number <= int(phase["bridge_end"])]
        if not members:
            return None
        return ArcRef("phase", f"phase:{beat_index}:{phase.get('index')}", min(b.start for b in members),
                      max(b.end for b in members), str(phase.get("title") or ""), self.main_line_id, beat_index)

    def _volume_ref(self, beat_index: int) -> ArcRef:
        members = self._beat_bridges(beat_index)
        title = str((self.beats.get(beat_index) or {}).get("title") or "")
        return ArcRef("volume", f"beat:{beat_index}", min(b.start for b in members), max(b.end for b in members),
                      title, self.main_line_id, beat_index)

    @staticmethod
    def _block_ref(level: str, chapter_number: int) -> ArcRef:
        size = BLOCK_SIZES[level]
        index = (chapter_number - 1) // size
        return ArcRef(level, f"block{size}:{index}", index * size + 1, (index + 1) * size)

    def arcs_for(self, chapter_number: int) -> ChapterArcs:
        bridge = self._bridge_at(chapter_number)
        if bridge is None or bridge.beat_index is None:
            unit = self._unit_ref(bridge) if bridge else self._block_ref("unit", chapter_number)
            return ChapterArcs(unit, self._block_ref("phase", chapter_number), self._block_ref("volume", chapter_number))
        phase = next(
            (ref for p in self._phases(bridge.beat_index)
             if int(p["bridge_start"]) <= bridge.number <= int(p["bridge_end"])
             and (ref := self._phase_ref(bridge.beat_index, p)) is not None),
            None,
        )
        return ChapterArcs(self._unit_ref(bridge), phase, self._volume_ref(bridge.beat_index))

    def children(self, arc: ArcRef) -> list[ArcRef]:
        if arc.level == "unit":
            return []
        if arc.key.startswith("block"):
            child_level = "unit" if arc.level == "phase" else "phase"
            size = BLOCK_SIZES[child_level]
            return [self._block_ref(child_level, n) for n in range(arc.start, arc.end + 1, size)]
        if arc.level == "volume" and arc.beat_index is not None:
            phases = [ref for p in self._phases(arc.beat_index) if (ref := self._phase_ref(arc.beat_index, p))]
            if phases:
                return sorted(phases, key=lambda r: r.start)
        return [self._unit_ref(b) for b in self.bridges if arc.start <= b.start and b.end <= arc.end]

    def all_arcs(self, upto_chapter: int) -> list[ArcRef]:
        """upto_chapter 之前已结束的全部各级弧（按结束章、层级排序），供补缺口。"""
        seen: dict[tuple[str, str], ArcRef] = {}
        for n in range(1, max(upto_chapter, 1) + 1):
            arcs = self.arcs_for(n)
            for arc in (arcs.unit, arcs.phase, arcs.volume):
                if arc is not None and arc.end <= upto_chapter:
                    seen.setdefault((arc.level, arc.key), arc)
        return sorted(seen.values(), key=lambda a: (a.end, LEVEL_RANK[a.level]))


async def resolve_arcs(db: AsyncSession, project_id: str, chapter_number: int) -> ChapterArcs:
    return (await ArcIndex.load(db, project_id)).arcs_for(chapter_number)


async def _chapter_summaries(db: AsyncSession, project_id: str) -> dict[int, str]:
    rows = (await db.execute(
        select(Chapter.chapter_number, StoryMemory.content)
        .join(Chapter, Chapter.id == StoryMemory.chapter_id)
        .where(StoryMemory.project_id == project_id, StoryMemory.memory_type == "chapter_summary")
    )).all()
    out: dict[int, str] = {}
    for number, content in rows:
        if content:
            out.setdefault(number, content)
    return out


def _signature(parts: list[str]) -> str:
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def _model_kwargs(ai_service: Any) -> dict[str, Any]:
    model = getattr(ai_service, "analysis_model", None)
    return {"model": model} if isinstance(model, str) and model.strip() else {}


UNIT_PROMPT = """你是长篇网文的编辑助理。下面是第{start}-{end}章{title}的逐{child_label}摘要，请合并成一段 {limit} 字以内的剧情摘要：
- 只写发生了什么、结果如何，以及人物处境 / 实力 / 关系发生了哪些变化
- 最后一句交代结尾时悬而未决的事（下一段要接住的线头）
- 用白话，不评价、不升华，不用"本章 / 本卷"之类的元叙述

{items}

直接输出摘要正文。"""

VOLUME_PROMPT = """你是长篇网文的主编，现在做「卷末复盘」。下面是第{start}-{end}章（主线节点《{title}》）的分段摘要，以及该节点原计划：

【原计划】
{plan}

【实际写成】
{items}

请输出 JSON（不要 markdown）：
{{
  "summary": "本卷实际剧情摘要，{limit} 字以内：主线推进到哪、主角得到 / 失去了什么、关键人物关系变化、留下的线头",
  "review": "复盘 200 字以内：实际与原计划的偏差（新增了什么人物 / 设定、哪些计划没写到）；下一卷开头必须接住的线头；最该在下一卷回收的 1-3 个伏笔"
}}"""


async def _generate(ai_service: Any, arc: ArcRef, items: list[str], plan: str = "") -> tuple[str, Optional[str]]:
    """调 LLM 汇总；失败 / 无 AI 时退化为子摘要拼接（保证前情脉络总有内容）。返回 (摘要, 复盘)。"""
    limit = SUMMARY_LIMITS[arc.level]
    fallback = clip_text("；".join(items), limit)
    if ai_service is None or not hasattr(ai_service, "generate_text_stream_collect"):
        return fallback, None
    title = f"《{arc.title}》" if arc.title else ""
    numbered = "\n".join(f"- {item}" for item in items)
    try:
        if arc.level == "volume":
            prompt = VOLUME_PROMPT.format(start=arc.start, end=arc.end, title=arc.title or "未命名",
                                          plan=plan or "（无）", items=numbered, limit=limit)
        else:
            prompt = UNIT_PROMPT.format(start=arc.start, end=arc.end, title=title, limit=limit, items=numbered,
                                        child_label="章" if arc.level == "unit" else "段")
        resp = await ai_service.generate_text_stream_collect(
            prompt=prompt, temperature=0.3, context=f"ArcSummary-{arc.key}", **_model_kwargs(ai_service),
        )
        content = (resp or {}).get("content", "").strip()
        if arc.level == "volume":
            from app.utils.json_cleaner import safe_parse_json

            data = safe_parse_json(content, default=None, expected_type="object", log_prefix="[卷末复盘]")
            if isinstance(data, dict) and str(data.get("summary") or "").strip():
                return clip_text(str(data["summary"]).strip(), limit + 100), (str(data.get("review") or "").strip() or None)
            return fallback, None
        return (clip_text(content, limit + 80) if content else fallback), None
    except Exception as exc:  # noqa: BLE001 - 汇总失败不影响分析主流程
        logger.warning("⚠️ 剧情摘要汇总失败（%s），退化为拼接: %s", arc.key, exc)
        return fallback, None


async def _write_back_review(db: AsyncSession, arc: ArcRef, review: str) -> None:
    """卷末复盘回写到下一个主线节点的 review_note（不改原描述）。"""
    if not arc.plot_line_id or arc.beat_index is None or not review:
        return
    line = (await db.execute(select(PlotLine).where(PlotLine.id == arc.plot_line_id))).scalar_one_or_none()
    if line is None or not line.timeline_data:
        return
    try:
        data = json.loads(line.timeline_data)
    except (json.JSONDecodeError, TypeError):
        return
    beats = [b for b in (data.get("beats") or []) if isinstance(b, dict)] if isinstance(data, dict) else []
    following = sorted((b for b in beats if str(b.get("index", "")).isdigit() and int(b["index"]) > arc.beat_index),
                       key=lambda b: int(b["index"]))
    if not following:
        return
    following[0]["review_note"] = f"（第{arc.start}-{arc.end}章复盘）{review}"
    line.timeline_data = json.dumps(data, ensure_ascii=False)


class _Rollup:
    def __init__(self, db: AsyncSession, project_id: str, ai_service: Any, index: ArcIndex,
                 summaries: dict[int, str], existing: dict[tuple[str, str], ArcSummary]):
        self.db, self.project_id, self.ai, self.index = db, project_id, ai_service, index
        self.summaries, self.existing = summaries, existing
        self.llm_calls = 0

    def complete(self, arc: ArcRef) -> bool:
        return all(n in self.summaries for n in range(arc.start, arc.end + 1))

    async def ensure(self, arc: ArcRef) -> Optional[ArcSummary]:
        if not self.complete(arc):
            return None
        if arc.level == "unit":
            items = [f"第{n}章：{self.summaries[n]}" for n in range(arc.start, arc.end + 1)]
        else:
            items = []
            for child in self.index.children(arc):
                row = await self.ensure(child)
                if row is None:
                    return None
                head = f"第{row.chapter_start}-{row.chapter_end}章" + (f"《{row.title}》" if row.title else "")
                items.append(f"{head}：{row.content}")
        signature = _signature(items)
        row = self.existing.get((arc.level, arc.key))
        if row is not None and row.source_signature == signature:
            return row
        plan = ""
        if arc.level == "volume" and arc.beat_index is not None:
            plan = str((self.index.beats.get(arc.beat_index) or {}).get("description") or "")
        content, review = await _generate(self.ai, arc, items, plan)
        self.llm_calls += 1
        if row is None:
            row = ArcSummary(project_id=self.project_id, level=arc.level, arc_key=arc.key)
            self.db.add(row)
            self.existing[(arc.level, arc.key)] = row
        row.chapter_start, row.chapter_end, row.title = arc.start, arc.end, arc.title or None
        row.content, row.review, row.source_signature = content, review, signature
        if review:
            await _write_back_review(self.db, arc, review)
        await self.db.flush()
        logger.info("🧩 剧情摘要已汇总: %s %s 第%s-%s章", arc.level, arc.key, arc.start, arc.end)
        return row


async def maybe_rollup(
    db: AsyncSession, project_id: str, chapter_number: int, ai_service: Any, backfill_budget: int = BACKFILL_BUDGET,
) -> int:
    """汇总本章所在单元 / 阶段 / 卷（齐了才汇总），再顺带补几个更早的缺口。返回本次 LLM 汇总次数。"""
    index = await ArcIndex.load(db, project_id)
    summaries = await _chapter_summaries(db, project_id)
    existing = {
        (r.level, r.arc_key): r
        for r in (await db.execute(select(ArcSummary).where(ArcSummary.project_id == project_id))).scalars().all()
    }
    rollup = _Rollup(db, project_id, ai_service, index, summaries, existing)
    arcs = index.arcs_for(chapter_number)
    for arc in (arcs.unit, arcs.phase, arcs.volume):
        if arc is not None:
            await rollup.ensure(arc)
    current_calls = rollup.llm_calls
    for arc in index.all_arcs(upto_chapter=max(summaries) if summaries else 0):
        if rollup.llm_calls - current_calls >= backfill_budget:
            break
        if (arc.level, arc.key) not in existing:
            await rollup.ensure(arc)
    await db.commit()
    return rollup.llm_calls


async def invalidate_covering(db: AsyncSession, project_id: str, chapter_number: int) -> int:
    result = await db.execute(
        delete(ArcSummary).where(
            ArcSummary.project_id == project_id,
            ArcSummary.chapter_start <= chapter_number,
            ArcSummary.chapter_end >= chapter_number,
        )
    )
    return result.rowcount or 0


def _line(row: ArcSummary, content: str) -> str:
    title = f"《{row.title}》" if row.title else ""
    return f"- 第{row.chapter_start}-{row.chapter_end}章{title}：{content}"


async def render_story_so_far(
    db: AsyncSession, project_id: str, current_chapter: int, budget_chars: int = 4000,
) -> tuple[str, int]:
    """前情脉络：每段章节用能覆盖它的最高一级摘要；返回 (文本, 覆盖到的最后一章)。"""
    rows = (await db.execute(
        select(ArcSummary).where(ArcSummary.project_id == project_id, ArcSummary.chapter_end < current_chapter)
    )).scalars().all()
    if not rows:
        return "", 0
    selected: list[ArcSummary] = []
    pos, last_end = 1, max(r.chapter_end for r in rows)
    while pos <= last_end:
        covering = [r for r in rows if r.chapter_start <= pos <= r.chapter_end]
        if not covering:
            pos += 1
            continue
        best = max(covering, key=lambda r: (LEVEL_RANK.get(r.level, 0), r.chapter_end))
        selected.append(best)
        pos = best.chapter_end + 1
    covered = max(r.chapter_end for r in selected)
    contents = [r.content for r in selected]
    text = "\n".join(_line(r, c) for r, c in zip(selected, contents))
    i = 0
    while len(text) > budget_chars and i < len(selected) - 1:
        contents[i] = clip_text(contents[i], COMPRESSED_CHARS)
        text = "\n".join(_line(r, c) for r, c in zip(selected, contents))
        i += 1
    if len(text) > budget_chars:
        text = clip_text(text, budget_chars, keep="tail")
    return text, covered
