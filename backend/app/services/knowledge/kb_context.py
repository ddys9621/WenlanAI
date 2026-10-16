"""仿写参考：按场景从项目的对标书里取去名版条目，组成提示词里独立的一节（设计稿 6.3–6.5）。

- 只注入去名版（denamed_body）；知识库是最低权威，开头固定写明边界与仿写方式
- 每条带 K 编号、条目名（不含原书人名）与对位理由；有回写的场景（分卷 / 细化卷纲 / 单元章纲）附 ref 字段说明
- 对位沿规划链往下传：卷（作者卷对标表 > 分卷时的引用 > 全书位置）→ 单元（细化时的引用 > 卷内位置）
  → 章（作者本次指定 > 章纲引用 > 单元内位置）
- 预算按场景：条目按顺序整条放，放不下的整条丢；第一条放不下就截断并注明
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter_outline import ChapterOutline
from app.models.knowledge import KbEntry, KbProjectLink, KbSource
from app.models.project import Project
from app.models.volume import Volume
from app.services.knowledge import kb_refs
from app.services.knowledge.alignment import (
    Span, align_chapter, align_unit, align_volume, coverage, excerpt_kinds, role_for,
)
from app.services.generation_trace import trace_reference
from app.services.knowledge.entry_types import entry_label
from app.services.knowledge.kb_refs import KbRef

SCENE_BUDGET = {
    "worldview": 2500, "characters": 2500, "story_outline": 4000, "volume_skeleton": 3000,
    "volume_detail": 4000, "unit_outline": 3000, "chapter": 2500,
}
STYLE_BUDGET = 1000
EXCERPT_LIMIT = 300
TRUNCATED = "…（已截断）"
ACTIVE_MODES = ("follow", "borrow", "style")
MODE_LABEL = {"follow": "跟写结构", "borrow": "借鉴节奏", "style": "只学文风", "off": "关闭"}
MODE_RULE = {
    "follow": "仿写方式：跟写结构——单元数、每个单元的作用 / 章数 / 强弱 / 兑现方式尽量与对标一致（可差 1 个），内容全部按本书设定重写。",
    "borrow": "仿写方式：借鉴节奏——参考它的节奏、强弱交替和兑现方式，按本书需要增减调整。",
    "style": "仿写方式：只学文风——只参考语感与写法，情节和结构按本书来。",
}
HEADER = "【仿写参考（知识库 · 最低权威）】"
BOUNDARY = (
    "以下来自知识库《{title}》，是最低权威的参考，不是本书设定：学节奏、因果结构、人物功能和爽点机制；"
    "人名、地名、专有设定和具体桥段必须换成本书的；不复制原句；与本书设定或作者要求冲突时以本书为准。"
)
REF_TARGET = {"volume_skeleton": "每一卷", "volume_detail": "每个剧情单元", "unit_outline": "每一章"}
REF_INSTRUCTION = "输出里{what}多一个字段 \"ref\"：它对标上面【仿写参考】里的哪一条（填编号，如 \"K2\"）；没有对标就填 \"\"。"
ROLE_LABEL = {"open": "开启", "advance": "推进", "turn": "转折", "close": "收束", "transition": "过渡"}
EXCERPT_KIND_LABEL = {
    "opening": "开场", "dialogue": "对白", "action": "动作", "payoff": "兑现", "ending_hook": "章末钩子",
    "description": "描写",
}


@dataclass
class KbContext:
    scene: str
    mode: str = "off"
    source_id: str = ""
    source_title: str = ""
    text: str = ""
    style: str = ""
    refs: dict[str, KbRef] = field(default_factory=dict)
    ref_instruction: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.text and not self.style

    def trace_items(self) -> list[dict[str, str]]:
        items = [{"title": f"{r.key} {r.label}", "detail": r.reason} for r in self.refs.values()]
        if self.style:
            items.append({"title": "参考文风", "detail": f"《{self.source_title}》"})
        return items


@dataclass
class _Item:
    entry: KbEntry
    text: str
    reason: str
    span_index: Optional[int] = None


def _take(block: str, remaining: int, first: bool) -> Optional[str]:
    if len(block) + 2 <= remaining:
        return block
    if first:
        return block[: max(remaining - len(TRUNCATED) - 2, 0)] + TRUNCATED
    return None


def fit_blocks(blocks: list[str], budget: int) -> list[str]:
    out: list[str] = []
    remaining = budget
    for block in blocks:
        taken = _take(block, remaining, not out)
        if taken is not None:
            out.append(taken)
            remaining -= len(taken) + 2
    return out


def _data(entry: KbEntry) -> dict[str, Any]:
    try:
        value = json.loads(entry.data_json or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _range(entry: KbEntry) -> str:
    if entry.chapter_start is None:
        return ""
    if entry.chapter_end in (None, entry.chapter_start):
        return f"第{entry.chapter_start}章"
    return f"第{entry.chapter_start}-{entry.chapter_end}章"


def _prompt_label(entry: KbEntry) -> str:
    kind = entry.entry_type
    if kind == "volume":
        return f"原书第{entry.volume_index}卷（{_range(entry)}）"
    if kind == "arc":
        return f"原书剧情单元#{entry.arc_index}（{_range(entry)}）"
    if kind == "chapter":
        return f"原书第{entry.chapter_start}章"
    if kind == "excerpt":
        label = EXCERPT_KIND_LABEL.get(str(_data(entry).get("kind") or ""), "片段")
        return f"原书片段（{label}" + (f"，第{entry.chapter_start}章）" if entry.chapter_start else "）")
    return f"原书{entry_label(kind)}"


def _display_label(source_title: str, entry: KbEntry) -> str:
    span = _range(entry) if entry.entry_type in ("volume", "arc") else ""
    return f"《{source_title}》{entry.title}" + (f"（{span}）" if span else "")


def _head(text: str, stop: str) -> str:
    lines: list[str] = []
    for line in (text or "").splitlines():
        if line.startswith(stop):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _volume_head(text: str) -> str:
    lines: list[str] = []
    for line in (text or "").splitlines():
        lines.append(line)
        if line.startswith("## 单元序列"):
            break
    return "\n".join(lines).strip()


def _first_sentence(text: str, limit: int = 80) -> str:
    return re.split(r"(?<=[。！？!?])", " ".join(text.split()), maxsplit=1)[0][:limit]


def _line_value(text: str, prefix: str) -> str:
    return next((line[len(prefix):].strip() for line in (text or "").splitlines() if line.startswith(prefix)), "")


def _beat(entry: KbEntry) -> str:
    data = _data(entry)
    role = ROLE_LABEL.get(str(data.get("arc_role") or ""), "推进")
    tags = "/".join(str(t) for t in data.get("function_tags") or []) or "—"
    hook = str(data.get("ending_hook_type") or "无")
    hook = "无钩子" if hook == "无" else hook
    outline = _first_sentence(_line_value(entry.denamed_body, "- 章纲："))
    return (f"单元第{data.get('unit_pos') or '?'}/{data.get('unit_len') or '?'}章（{role}）［{tags}］"
            f"{data.get('pace') or '中'}·张力{data.get('tension') or 3}·{hook}：{outline}")


def _excerpt_text(entry: KbEntry) -> str:
    body = entry.denamed_body or ""
    text = body.split("\n", 1)[1].strip() if body.startswith("#") and "\n" in body else body.strip()
    return text[:EXCERPT_LIMIT]


def _volume_map(link: KbProjectLink) -> dict[str, int]:
    try:
        raw = json.loads(link.volume_map or "{}")
    except (TypeError, ValueError):
        return {}
    out: dict[str, int] = {}
    for key, value in (raw.items() if isinstance(raw, dict) else []):
        try:
            out[str(int(key))] = int(value)
        except (TypeError, ValueError):
            continue
    return out


class _Book:
    def __init__(self, db: AsyncSession, source: KbSource):
        self.db, self.source = db, source
        self._cache: dict[str, list[KbEntry]] = {}

    async def of_type(self, entry_type: str) -> list[KbEntry]:
        if entry_type not in self._cache:
            self._cache[entry_type] = list((await self.db.execute(
                select(KbEntry).where(KbEntry.source_id == self.source.id, KbEntry.entry_type == entry_type)
                .order_by(KbEntry.sort_order)
            )).scalars().all())
        return self._cache[entry_type]

    async def first(self, entry_type: str) -> Optional[KbEntry]:
        rows = await self.of_type(entry_type)
        return rows[0] if rows else None

    async def covered(self) -> tuple[int, int]:
        chapters = [Span(e.chapter_start, e.chapter_start, e.chapter_start) for e in await self.of_type("chapter")
                    if e.chapter_start]
        if not chapters:
            chapters = [Span(e.arc_index or 0, e.chapter_start, e.chapter_end or e.chapter_start)
                        for e in await self.of_type("arc") if e.chapter_start]
        return coverage(chapters, self.source.chapter_count or 0)

    def owns(self, entry: Optional[KbEntry], entry_type: str) -> bool:
        return entry is not None and entry.entry_type == entry_type and entry.source_id == self.source.id


async def _project_total(db: AsyncSession, project_id: str) -> int:
    project = await db.get(Project, project_id)
    last_end = (await db.execute(select(func.max(Volume.chapter_end)).where(Volume.project_id == project_id))).scalar()
    last_outline = (await db.execute(
        select(func.max(ChapterOutline.chapter_number)).where(ChapterOutline.project_id == project_id)
    )).scalar()
    return max(int(getattr(project, "chapter_count", 0) or 0), int(last_end or 0), int(last_outline or 0), 1)


async def _ref_volume(db: AsyncSession, project_id: str, link: KbProjectLink, book: _Book,
                      volume: Volume) -> tuple[Optional[KbEntry], str]:
    entries = [e for e in await book.of_type("volume") if e.volume_index and e.chapter_start and e.chapter_end]
    if not entries:
        return None, ""
    spans = [Span(e.volume_index, e.chapter_start, e.chapter_end) for e in entries]
    mapped = _volume_map(link).get(str(volume.volume_number))
    cited_entry = await kb_refs.cited_entry(db, project_id, "volume", volume.id)
    cited = cited_entry.volume_index if book.owns(cited_entry, "volume") else None
    span = align_volume(volume.chapter_start, volume.chapter_end, await _project_total(db, project_id), spans,
                        covered=await book.covered(), mapped=mapped, cited=cited)
    if span is None:
        return None, ""
    reason = "作者指定的卷对标" if mapped == span.index else "分卷时的对标" if cited == span.index else "全书相对位置相近"
    return next(e for e in entries if e.volume_index == span.index), reason


async def _ref_arc(db: AsyncSession, project_id: str, link: KbProjectLink, book: _Book, volume: Volume,
                   unit: dict) -> tuple[Optional[KbEntry], str]:
    cited = await kb_refs.cited_entry(db, project_id, "unit", f"{volume.id}:{unit.get('index')}")
    if book.owns(cited, "arc"):
        return cited, "细化卷纲时的对标"
    arcs = [a for a in await book.of_type("arc") if a.arc_index and a.chapter_start and a.chapter_end]
    ref_volume, volume_reason = await _ref_volume(db, project_id, link, book, volume)
    pool = [a for a in arcs if ref_volume is not None and a.volume_index == ref_volume.volume_index]
    start, end = int(unit["chapter_start"]), int(unit["chapter_end"])
    if pool:
        vol_span = Span(ref_volume.volume_index, ref_volume.chapter_start, ref_volume.chapter_end)
        span = align_unit(start, end, volume.chapter_start, volume.chapter_end,
                          [Span(a.arc_index, a.chapter_start, a.chapter_end) for a in pool], vol_span)
        reason = f"卷内位置相近（对标原书第{ref_volume.volume_index}卷：{volume_reason}）"
    else:
        pool = arcs
        span = align_unit(start, end, 1, await _project_total(db, project_id),
                          [Span(a.arc_index, a.chapter_start, a.chapter_end) for a in pool], None)
        reason = "全书相对位置相近"
    if span is None:
        return None, ""
    return next(a for a in pool if a.arc_index == span.index), reason


async def _outline_position(db: AsyncSession, outline: Any) -> tuple[Optional[Volume], Optional[dict], int, int]:
    from app.services.volume_context import fetch_volume_context

    vctx = await fetch_volume_context(db, outline)
    if vctx is None or vctx.unit is None:
        return None, None, 0, 0
    return await db.get(Volume, vctx.volume_id), vctx.unit, vctx.index, vctx.size


async def _ref_chapter(db: AsyncSession, project_id: str, link: KbProjectLink, book: _Book, outline: Any,
                       kb_chapter: Optional[int]) -> tuple[Optional[KbEntry], str]:
    chapters = [c for c in await book.of_type("chapter") if c.chapter_start]
    if kb_chapter:
        picked = next((c for c in chapters if c.chapter_start == kb_chapter), None)
        if picked is not None:
            return picked, "作者本次指定"
    if outline is None or not chapters:
        return None, ""
    cited = await kb_refs.cited_entry(db, project_id, "chapter_outline", outline.id)
    if book.owns(cited, "chapter"):
        return cited, "章纲对标"
    volume, unit, pos, size = await _outline_position(db, outline)
    if volume is not None and unit is not None:
        arc, _reason = await _ref_arc(db, project_id, link, book, volume, unit)
        members = [c for c in chapters if arc is not None and c.arc_index == arc.arc_index]
        k = align_chapter(pos, size, len(members))
        if k:
            return members[k - 1], f"单元内位置相近（本单元第{pos}/{size}章 ↔ 原书单元#{arc.arc_index}第{k}/{len(members)}章）"
    number = int(getattr(outline, "chapter_number", 0) or 0)
    span = align_volume(number, number, await _project_total(db, project_id),
                        [Span(c.chapter_start, c.chapter_start, c.chapter_start) for c in chapters],
                        covered=await book.covered())
    picked = next((c for c in chapters if span is not None and c.chapter_start == span.index), None)
    return (picked, "全书相对位置相近") if picked is not None else (None, "")


async def _excerpt(book: _Book, role: Optional[str]) -> Optional[_Item]:
    excerpts = await book.of_type("excerpt")
    for kind in excerpt_kinds(role):
        for entry in excerpts:
            if _data(entry).get("kind") == kind:
                return _Item(entry, _excerpt_text(entry), f"同类片段（{EXCERPT_KIND_LABEL.get(kind, kind)}）",
                             entry.chapter_start)
    return None


async def _global_items(book: _Book, types: tuple[str, ...], reason: str) -> list[_Item]:
    items = []
    for entry_type in types:
        entry = await book.first(entry_type)
        if entry is not None:
            items.append(_Item(entry, entry.denamed_body, reason))
    return items


async def _scene_items(db: AsyncSession, project_id: str, scene: str, link: KbProjectLink, book: _Book, *,
                       volume: Optional[Volume], unit: Optional[dict], outline: Any,
                       kb_chapter: Optional[int]) -> tuple[list[_Item], list[str], str]:
    """返回（条目，放在条目前的说明行，正文要用的章内位置）。"""
    if scene == "worldview":
        return await _global_items(book, ("synopsis",), "全书设定参考（力量体系 / 金手指 / 卖点）"), [], ""
    if scene == "characters":
        return await _global_items(book, ("characters",), "人物功能位参考"), [], ""
    if scene == "story_outline":
        return await _global_items(book, ("synopsis", "methodology", "structure"), "全书结构参考"), [], ""
    if scene == "volume_skeleton":
        items = [_Item(e, _volume_head(e.denamed_body), "原书分卷结构", e.volume_index) for e in await book.of_type("volume")]
        return items, [], ""
    if scene == "volume_detail" and volume is not None:
        ref_volume, reason = await _ref_volume(db, project_id, link, book, volume)
        if ref_volume is None:
            return [], [], ""
        arcs = [a for a in await book.of_type("arc") if a.volume_index == ref_volume.volume_index]
        items = [_Item(a, _head(a.denamed_body, "## 节拍"), f"原书第{ref_volume.volume_index}卷第{k}个单元", a.arc_index)
                 for k, a in enumerate(arcs, 1)]
        intro = [f"对标：原书第{ref_volume.volume_index}卷（{reason}）", _volume_head(ref_volume.denamed_body)]
        return items, intro, ""
    if scene == "unit_outline" and volume is not None and unit is not None:
        arc, reason = await _ref_arc(db, project_id, link, book, volume, unit)
        if arc is None:
            return [], [], ""
        members = [c for c in await book.of_type("chapter") if c.arc_index == arc.arc_index]
        items = [_Item(arc, _head(arc.denamed_body, "## 节拍"), reason, arc.arc_index)]
        items += [_Item(c, _beat(c), f"原书单元#{arc.arc_index}第{k}/{len(members)}章", c.chapter_start)
                  for k, c in enumerate(members, 1)]
        return items, [], ""
    if scene == "chapter":
        picked, reason = await _ref_chapter(db, project_id, link, book, outline, kb_chapter)
        role = str(_data(picked).get("arc_role") or "") if picked is not None else ""
        if not role and outline is not None:
            _v, _u, pos, size = await _outline_position(db, outline)
            role = role_for(pos, size) if size else ""
        items = [] if picked is None or link.mode == "style" else [_Item(picked, picked.denamed_body, reason, picked.chapter_start)]
        excerpt = await _excerpt(book, role)
        return items + ([excerpt] if excerpt is not None else []), [], role
    return [], [], ""


async def _resolve_link(db: AsyncSession, project_id: str, source_id: Optional[str], mode: Optional[str],
                        user_id: Optional[str]) -> Optional[KbProjectLink]:
    """项目的对标关联；向导建项目前还没有项目，用向导里选的来源（必须属于该用户）临时拼一条，不入库。"""
    if not source_id:
        return await db.get(KbProjectLink, project_id) if project_id else None
    source = await db.get(KbSource, source_id)
    if source is None or source.user_id != user_id:
        return None
    return KbProjectLink(project_id=project_id or "", source_id=source_id, mode=mode if mode in MODE_LABEL else "borrow")


async def build_kb_context(db: AsyncSession, project_id: str, scene: str, *, volume: Optional[Volume] = None,
                           unit: Optional[dict] = None, outline: Any = None, kb_chapter: Optional[int] = None,
                           source_id: Optional[str] = None, mode: Optional[str] = None,
                           user_id: Optional[str] = None) -> KbContext:
    ctx = KbContext(scene=scene)
    link = await _resolve_link(db, project_id, source_id, mode, user_id)
    if link is None or link.mode not in ACTIVE_MODES or (link.mode == "style" and scene != "chapter"):
        return ctx
    source = await db.get(KbSource, link.source_id)
    if source is None:
        return ctx
    ctx.mode, ctx.source_id, ctx.source_title = link.mode, source.id, source.title
    book = _Book(db, source)
    items, intro, _role = await _scene_items(db, project_id, scene, link, book, volume=volume, unit=unit,
                                             outline=outline, kb_chapter=kb_chapter)
    if scene == "chapter":
        style = await book.first("style")
        if style is not None and style.denamed_body:
            ctx.style = f"【参考文风（知识库《{source.title}》）】\n{style.denamed_body[:STYLE_BUDGET]}"
    if not items:
        return ctx
    head = "\n".join([HEADER, BOUNDARY.format(title=source.title), MODE_RULE[link.mode], *[i for i in intro if i]])
    remaining = SCENE_BUDGET.get(scene, 2500) - len(head)
    blocks: list[str] = []
    for item in items:
        key = f"K{len(ctx.refs) + 1}"
        block = _take(f"【{key}｜{_prompt_label(item.entry)}｜对位：{item.reason}】\n{item.text}", remaining, not blocks)
        if block is None:
            continue
        blocks.append(block)
        remaining -= len(block) + 2
        ctx.refs[key] = KbRef(
            key=key, entry_id=item.entry.id, entry_revision=item.entry.revision or 1, source_id=source.id,
            entry_type=item.entry.entry_type, label=_display_label(source.title, item.entry),
            prompt_label=_prompt_label(item.entry), reason=item.reason, span_index=item.span_index,
        )
    ctx.text = "\n\n".join([head, *blocks])
    if scene in REF_TARGET:
        ctx.ref_instruction = REF_INSTRUCTION.format(what=REF_TARGET[scene])
    return ctx


async def traced_kb_context(db: AsyncSession, project_id: str, scene: str, **kwargs: Any) -> KbContext:
    """生成入口用：组装后把用到的条目报给过程面板（「参考了什么」）。"""
    ctx = await build_kb_context(db, project_id, scene, **kwargs)
    if not ctx.is_empty:
        trace_reference("knowledge", f"仿写参考《{ctx.source_title}》·{MODE_LABEL.get(ctx.mode, ctx.mode)}", ctx.trace_items())
    return ctx
