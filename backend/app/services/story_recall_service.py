"""写正文时的记忆召回：按「这一章需要什么」从账本里取，而不是把几路检索结果按固定顺序拼起来再硬截。

1. 前情脉络：层级摘要（卷 / 单元），每段章节取能覆盖它的最高一级
2. 近期衔接：最近 N 章 + 层级摘要没覆盖到的章（含中间的空洞）的档案摘要；缺档案的章用章纲兜底并注明「未分析」；
   末尾附上一章的章末状态（上一章分析过却没记，如整章回忆，就退到最近记过的那章）
3. 最近全文：最近 2 章正文（衔接口吻与动作）
4. 相关旧事（远程回忆）：只在近程窗口之外找与本章人物 / 地点 / 关键词有关的旧事件、旧因果、旧档案，
   按「人物命中 + 语义相似 + 关键词 + 重要度 + 新近度」打分，同一章最多 2 条，按章序排在预算内
   （旧版语义检索不排除最近几章，查回来的多是上一章已经给了全文的事）
叙事账本（伏笔清单 / 因果 / 时间轴 / 关系 / 归属）与视角信息边界由 narrative_state_service 出，
后者作为硬约束放进「出场角色与状态」区块，不跟账本一起被裁。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.chapter import Chapter
from app.models.chapter_causal_link import ChapterCausalLink
from app.models.chapter_outline import ChapterOutline
from app.models.timeline_event import TimelineEvent
from app.services import arc_summary_service
from app.services.chapter_digest_service import digests_by_number
from app.services.context_budget import clip_text
from app.services.memory_service import memory_service
from app.services.story_index_items import RECALL_KINDS, causal_text, event_text

logger = get_logger(__name__)

RECENT_FULL_COUNT = 2
RECENT_SUMMARY_COUNT = 10
RECENT_SUMMARY_MAX = 30
STORY_SO_FAR_BUDGET = 4000
LONG_RANGE_LIMIT = 8
LONG_RANGE_PER_CHAPTER = 2
LONG_RANGE_BUDGET = 2200
LONG_RANGE_POOL = 400  # 实体 / 关键词通道最多看最近这么多条事件
SEMANTIC_ONLY_MIN = 0.45  # 只有语义一路命中时的最低相似度（低于它多半是无关的）
WEIGHTS = {"entity": 0.40, "semantic": 0.35, "keyword": 0.15, "importance": 0.10}


@dataclass
class _Candidate:
    id: str
    kind: str
    chapter_number: int
    text: str
    importance: float = 0.5
    entity: float = 0.0
    semantic: float = 0.0
    keyword: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def score(self, current_chapter: int) -> float:
        recency = (self.chapter_number / current_chapter) if current_chapter else 0.0
        return (WEIGHTS["entity"] * self.entity + WEIGHTS["semantic"] * self.semantic
                + WEIGHTS["keyword"] * self.keyword + WEIGHTS["importance"] * self.importance + 0.05 * recency)

    def qualifies(self) -> bool:
        return self.entity > 0 or self.keyword > 0 or self.semantic >= SEMANTIC_ONLY_MIN


def recall_keywords(char_ctx: Any, outline: Any = None, limit: int = 12) -> list[str]:
    """远程回忆的关键词：本章相关人物（含曾用名）+ 章纲场景地点。"""
    words: list[str] = []
    for name in list(getattr(char_ctx, "involved", None) or []) + list(getattr(char_ctx, "names", None) or []):
        if name and len(name) >= 2 and name not in words:
            words.append(name)
    for part in re.split(r"[，,、/→\-—\s]+", str(getattr(outline, "scene", None) or "")):
        if len(part) >= 2 and part not in words:
            words.append(part)
    return words[:limit]


async def long_range_recall(
    db: AsyncSession,
    *,
    user_id: Optional[str],
    project_id: str,
    current_chapter: int,
    query_text: str = "",
    involved_ids: Iterable[str] = (),
    keywords: Iterable[str] = (),
    exclude_chapters: Iterable[int] = (),
    limit: int = LONG_RANGE_LIMIT,
    per_chapter: int = LONG_RANGE_PER_CHAPTER,
    budget: int = LONG_RANGE_BUDGET,
) -> tuple[str, list[dict]]:
    """返回 (相关旧事文本, 条目明细)；条目明细给召回预览看「为什么召回」。"""
    exclude = {int(n) for n in exclude_chapters}
    involved = {i for i in involved_ids if i}
    keys = [k for k in dict.fromkeys(keywords) if k and len(k) >= 2]
    found: dict[str, _Candidate] = {}

    def keyword_hits(text: str) -> list[str]:
        return [k for k in keys if k in text]

    def consider(candidate: _Candidate, ids: Iterable[str] = ()) -> None:
        overlap = len(set(ids) & involved) if involved else 0
        if overlap:
            candidate.entity = min(1.0, overlap / 2)
            candidate.reasons.append(f"涉及本章人物 {overlap} 位")
        hits = keyword_hits(candidate.text)
        if hits:
            candidate.keyword = min(1.0, len(hits) / 2)
            candidate.reasons.append("关键词：" + "、".join(hits[:3]))
        if candidate.entity or candidate.keyword:
            found[candidate.id] = candidate

    if involved or keys:
        timeline = (await db.execute(
            select(TimelineEvent).where(TimelineEvent.project_id == project_id, TimelineEvent.chapter_number < current_chapter)
            .order_by(TimelineEvent.chapter_number.desc()).limit(LONG_RANGE_POOL)
        )).scalars().all()
        for row in timeline:
            if (row.chapter_number or 0) in exclude:
                continue
            consider(_Candidate(f"event:{row.id}", "event", row.chapter_number or 0,
                                event_text(row.title, row.description, row.location, row.time_marker), 0.5),
                     [*(row.actor_ids or []), *(row.target_ids or [])])
        causal = (await db.execute(
            select(ChapterCausalLink).where(ChapterCausalLink.project_id == project_id,
                                            ChapterCausalLink.chapter_number < current_chapter)
            .order_by(ChapterCausalLink.chapter_number.desc()).limit(LONG_RANGE_POOL)
        )).scalars().all()
        for row in causal:
            if (row.chapter_number or 0) in exclude:
                continue
            consider(_Candidate(f"causal:{row.id}", "causal", row.chapter_number or 0,
                                causal_text(row.cause, row.event, row.effect), float(row.importance_score or 0.5)),
                     [*(row.actor_ids or []), *(row.target_ids or [])])
        if keys:
            for number, digest in (await digests_by_number(db, project_id, before=current_chapter)).items():
                if number not in exclude:
                    consider(_Candidate(f"digest:{digest.chapter_id}", "digest", number, digest.summary or "", 0.6))

    if query_text and user_id and memory_service.available:
        for hit in await memory_service.search(
            user_id, project_id, query_text, kinds=RECALL_KINDS, before_chapter=current_chapter,
            exclude_chapters=exclude, limit=20,
        ):
            if hit.chapter_number in exclude or hit.chapter_number >= current_chapter:
                continue
            candidate = found.get(hit.id) or _Candidate(hit.id, hit.kind, hit.chapter_number, hit.text,
                                                        0.6 if hit.kind == "digest" else 0.5)
            candidate.semantic = max(candidate.semantic, hit.similarity)
            candidate.reasons.append(f"语义相近 {hit.similarity:.2f}")
            if candidate.qualifies():
                found[hit.id] = candidate

    ranked = sorted((c for c in found.values() if c.qualifies() and c.text),
                    key=lambda c: (-c.score(current_chapter), -c.chapter_number))
    picked: list[_Candidate] = []
    per: dict[int, int] = {}
    for candidate in ranked:
        if per.get(candidate.chapter_number, 0) >= per_chapter:
            continue
        per[candidate.chapter_number] = per.get(candidate.chapter_number, 0) + 1
        picked.append(candidate)
        if len(picked) >= limit:
            break
    lines, used, kept = [], 0, []
    for candidate in sorted(picked, key=lambda c: c.chapter_number):
        line = f"- 第{candidate.chapter_number}章：{clip_text(candidate.text, 120)}"
        if used + len(line) > budget:
            continue
        used += len(line) + 1
        lines.append(line)
        kept.append({
            "id": candidate.id, "kind": candidate.kind, "chapter_number": candidate.chapter_number,
            "text": clip_text(candidate.text, 120), "score": round(candidate.score(current_chapter), 3),
            "reasons": candidate.reasons,
        })
    return "\n".join(lines), kept


def _end_state_line(digests: dict, last_number: int) -> str:
    """上一章的章末状态；上一章分析过却没记（整章回忆 / 往事，没回到现在）时退到最近记过的那章，上一章没分析就不退。"""
    last = digests.get(last_number)
    if last is None:
        return ""
    if (last.end_state or "").strip():
        return f"上一章（第{last_number}章）结束时：{last.end_state}"
    recorded = [n for n in sorted(digests, reverse=True) if n < last_number and (digests[n].end_state or "").strip()]
    if not recorded:
        return ""
    return f"上一章（第{last_number}章）没记章末状态；第{recorded[0]}章结束时：{digests[recorded[0]].end_state}"


async def build_story_context(
    db: AsyncSession,
    project_id: str,
    current_chapter_number: int,
    user_id: Optional[str],
    query_text: Optional[str] = None,
    involved_ids: Iterable[str] = (),
    keywords: Iterable[str] = (),
) -> dict:
    """前情脉络 / 近期概要（含上一章章末状态）/ 相关旧事 / 最近全文 + 统计。总长基本不随章数增长。"""
    parts: dict[str, Any] = {
        "story_skeleton": "", "relevant_history": "", "recent_summary": "", "recent_full": "", "stats": {},
        "relevant_items": [],
    }
    try:
        previous = (await db.execute(
            select(Chapter.id, Chapter.chapter_number, Chapter.title, Chapter.chapter_outline_id)
            .where(Chapter.project_id == project_id, Chapter.chapter_number < current_chapter_number,
                   Chapter.content.isnot(None), Chapter.content != "")
            .order_by(Chapter.chapter_number)
        )).all()
        if not previous:
            return parts

        story = await arc_summary_service.story_so_far_detail(
            db, project_id, current_chapter_number, budget_chars=STORY_SO_FAR_BUDGET,
        )
        if story.text:
            parts["story_skeleton"] = "【前情脉络】\n" + story.text

        full_rows = previous[-min(RECENT_FULL_COUNT, len(previous)):]
        full_numbers = {row.chapter_number for row in full_rows}
        candidates = [row for row in previous if row.chapter_number not in full_numbers]
        tail = candidates[-RECENT_SUMMARY_COUNT:]
        uncovered = [row for row in candidates if row.chapter_number not in story.covered]
        targets = sorted({row.chapter_number: row for row in [*uncovered, *tail]}.values(),
                         key=lambda row: row.chapter_number)[-RECENT_SUMMARY_MAX:]
        last_number = previous[-1].chapter_number
        digests = await digests_by_number(
            db, project_id, numbers=[row.chapter_number for row in [*targets, *full_rows]],
        )
        missing_outline_ids = [row.chapter_outline_id for row in targets
                               if row.chapter_number not in digests and row.chapter_outline_id]
        outline_text: dict[str, str] = {}
        if missing_outline_ids:
            for outline_id, summary, plot_points in (await db.execute(
                select(ChapterOutline.id, ChapterOutline.summary, ChapterOutline.plot_points)
                .where(ChapterOutline.id.in_(missing_outline_ids))
            )).all():
                outline_text[outline_id] = summary or plot_points or ""

        lines = []
        for row in targets:
            digest = digests.get(row.chapter_number)
            if digest is not None:
                lines.append(f"第{row.chapter_number}章《{row.title}》：{digest.summary}")
            elif outline_text.get(row.chapter_outline_id):
                lines.append(f"第{row.chapter_number}章《{row.title}》（未分析，按章纲）：{clip_text(outline_text[row.chapter_outline_id], 150)}")
        end_line = _end_state_line(digests, last_number)
        if end_line:
            lines.append(end_line)
        if lines:
            parts["recent_summary"] = "【近期章节概要】\n" + "\n".join(lines)

        window = full_numbers | {row.chapter_number for row in targets}
        if not query_text:
            outline = (await db.execute(
                select(ChapterOutline.title, ChapterOutline.summary, ChapterOutline.plot_points)
                .join(Chapter, Chapter.chapter_outline_id == ChapterOutline.id)
                .where(Chapter.project_id == project_id, Chapter.chapter_number == current_chapter_number)
            )).first()
            if outline:
                query_text = " ".join(x for x in (outline[0], outline[1], (outline[2] or "")[:200]) if x).strip()
        recall_text, recall_items = await long_range_recall(
            db, user_id=user_id, project_id=project_id, current_chapter=current_chapter_number,
            query_text=query_text or "", involved_ids=involved_ids, keywords=keywords, exclude_chapters=window,
        )
        if recall_text:
            parts["relevant_history"] = "【相关旧事】\n" + recall_text
        parts["relevant_items"] = recall_items

        content_by_id = dict((await db.execute(
            select(Chapter.id, Chapter.content).where(Chapter.id.in_([row.id for row in full_rows]))
        )).all())
        full_texts = [
            f"=== 第{row.chapter_number}章：{row.title} ===\n{content_by_id[row.id]}"
            for row in full_rows if content_by_id.get(row.id)
        ]
        if full_texts:
            parts["recent_full"] = "【最近章节完整内容】\n" + "\n\n".join(full_texts)

        parts["stats"] = {
            "total_previous": len(previous),
            "arc_covered_until": story.covered_until,
            "relevant_history": len(recall_items),
            "recent_summaries": len([ln for ln in lines if ln.startswith("第")]),
            "recent_full": len(full_texts),
            "gap_chapters": len([row for row in uncovered if row.chapter_number < story.covered_until]),
        }
        parts["stats"]["total_length"] = sum(
            len(parts[k]) for k in ("story_skeleton", "relevant_history", "recent_summary", "recent_full")
        )
    except Exception as exc:  # noqa: BLE001 - 召回失败不阻断写作（模型仍有章纲与角色卡）
        logger.error(f"❌ 构建前文上下文失败: {exc}", exc_info=True)
    return parts


@dataclass
class RecallPreview:
    chapter_number: int
    sections: list[dict]
    relevant_items: list[dict]
    stats: dict


async def recall_preview(db: AsyncSession, *, user_id: str, project_id: str, chapter_number: int) -> RecallPreview:
    """「写第 N 章时会注入什么」：和正文生成同一条召回链，不调用大模型（故事账本页 / 调试用）。"""
    from app.services.chapter_context_service import build_character_context, build_query_text
    from app.services.narrative_state_service import narrative_state_service
    from app.services.narrative_tasks import task_promise_ids

    chapter = (await db.execute(
        select(Chapter).where(Chapter.project_id == project_id, Chapter.chapter_number == chapter_number)
    )).scalar_one_or_none()
    outline = None
    if chapter is not None and chapter.chapter_outline_id:
        outline = await db.get(ChapterOutline, chapter.chapter_outline_id)
    if outline is None:
        outline = (await db.execute(
            select(ChapterOutline).where(ChapterOutline.project_id == project_id, ChapterOutline.chapter_number == chapter_number)
        )).scalar_one_or_none()
    char_ctx = await build_character_context(db, project_id, chapter_number, outline or SimpleNamespace())
    query = build_query_text(outline, char_ctx.involved or char_ctx.names) if outline is not None else ""
    story = await build_story_context(
        db, project_id, chapter_number, user_id, query_text=query,
        involved_ids=[c.id for c in char_ctx.selected], keywords=recall_keywords(char_ctx, outline),
    )
    ledger = await narrative_state_service.build_generation_context(
        db=db, project_id=project_id, current_chapter=chapter_number, pov_character_name=char_ctx.pov_name,
        character_names=char_ctx.names, focus_promise_ids=task_promise_ids(getattr(outline, "narrative_tasks", None)),
        character_ids=[c.id for c in char_ctx.selected],
    )
    character_parts = [
        f"故事时间：上一章结束于 {char_ctx.story_time_text}" if char_ctx.story_time_text else "",
        char_ctx.cards_text,
        ledger.get("pov_known_info", ""),
        ("已死亡 / 失踪：\n" + char_ctx.absent_text) if char_ctx.absent_text else "",
    ]
    sections = [
        ("characters", "出场角色与状态（硬约束）", "\n\n".join(p for p in character_parts if p and p.strip())),
        ("story_so_far", "前情脉络", story["story_skeleton"]),
        ("recent_summaries", "近期剧情", story["recent_summary"]),
        ("relevant_history", "相关旧事", story["relevant_history"]),
        ("promises", "伏笔清单", ledger.get("narrative_promises", "")),
        ("causal", "因果链", ledger.get("causal_chains", "")),
        ("timeline", "时间轴", ledger.get("timeline_events", "")),
        ("relationships", "关系动态", ledger.get("relationship_dynamics", "")),
        ("recent_full", "最近完整内容", clip_text(story["recent_full"], 1200, keep="tail")),
    ]
    return RecallPreview(
        chapter_number=chapter_number,
        sections=[{"key": k, "title": t, "text": v, "chars": len(v)} for k, t, v in sections if v and v.strip()],
        relevant_items=story.get("relevant_items") or [],
        stats=story.get("stats") or {},
    )
