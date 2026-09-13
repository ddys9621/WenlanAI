"""V3 R5 一键仿写服务

职责（仿写专用上层）：
1. 加载 [项目状态 + 作者意图 + 已挂载/勾选的参考包] 三类输入
2. 拼装 system_prompt + user_prompt（文风注入 system，结构/方法论/角色塑造/世界观/语料注入 user）
3. 提供同步 preview（dry-run）与 SSE 流式生成两种入口

参考资料组装能力（强度档位 / 维度过滤 / 5 维 + corpus 拼装）已抽到 ``reference_pack_injector``，
本模块通过 ``self.injector`` 委托复用，避免与其他生成场景双源维护。

对外 API（向下兼容）：
- ``ImitationService.resolve_packs / resolve_dimensions / resolve_strength``：代理给 injector
- ``ImitationService.assemble_prompt``：仿写主入口（流式生成由 api/imitation.make_imitation_runner 走通用后台任务）
- 本模块顶层 ``StrengthProfile`` / ``_ResolvedPack`` 仍可 import（re-export 自 injector）

参见：
- 设计文档：@/agent-docs/features/book_dissect_v3_imitation_design.md §5
- R2 抽取设计：@/agent-docs/features/dissect_to_creation_pipeline.md §4
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.chapter import Chapter
from app.models.chapter_outline import ChapterOutline
from app.models.character import Character
from app.models.project import Project
from app.services.ai_service import AIService
# 重新导出：测试与下游代码继续从本模块 import 这些符号
from app.services.reference_pack_injector import (  # noqa: F401  re-export
    ReferenceBlock,
    ReferencePackInjector,
    StrengthProfile,
    _ResolvedPack,
    _dedup_keep_order,
    _safe_json,
    _serialize_dimension,
    _serialize_style,
    _truncate,
)

logger = get_logger(__name__)


def _tail_truncate(text: str, limit: int) -> str:
    """尾部截选：保留末尾 limit 字符（续写场景下，结尾比开头重要得多）。"""
    if not text:
        return ""
    text = text.strip()
    if limit <= 0 or len(text) <= limit:
        return text
    return "…" + text[-limit:].lstrip()


# ============================================================
# 数据载体（仿写专用：项目当前状态快照）
# ============================================================


@dataclass
class _ProjectContext:
    """项目当前状态快照（轻量；不含 RAG 历史）。"""

    project: Project
    main_characters: List[Character] = field(default_factory=list)
    target_chapter: Optional[Chapter] = None
    target_outline: Optional[ChapterOutline] = None
    recent_chapters: List[Chapter] = field(default_factory=list)


# ============================================================
# 主服务类
# ============================================================


class ImitationService:
    """一键仿写：依赖注入 AIService（来自 get_user_ai_service）。"""

    # 类常量便于测试 monkeypatch
    DEFAULT_DIMENSION_FALLBACK: tuple[str, ...] = ("methodology", "style", "corpus")
    RECENT_CHAPTERS_FOR_CONTEXT: int = 3
    RECENT_CHAPTER_CHARS_TRUNCATE: int = 1500
    MAIN_CHARACTERS_LIMIT: int = 6
    # 目标章节"已写正文"结尾截选长度（续写衔接的关键上下文）
    CURRENT_CHAPTER_TAIL_CHARS: int = 2000
    # 关联剧情卡注入上限
    LINKED_PLOT_CARDS_LIMIT: int = 5
    LINKED_PLOT_CARD_CHARS: int = 160

    def __init__(self, ai_service: AIService):
        self.ai_service = ai_service
        # 参考资料组装统一委托给 injector（R2 抽出，跨场景共享）
        self.injector = ReferencePackInjector(ai_service)

    # ----------------------------------------------------------------
    # 输入归一化：代理给 injector（保留方法签名以兼容下游调用）
    # ----------------------------------------------------------------

    async def resolve_packs(
        self,
        db: AsyncSession,
        project_id: str,
        pack_ids: Optional[List[str]],
    ) -> List[_ResolvedPack]:
        return await self.injector.resolve_packs(db, project_id, pack_ids)

    def resolve_dimensions(
        self,
        packs: List[_ResolvedPack],
        explicit: Optional[List[str]],
    ) -> List[str]:
        return self.injector.resolve_dimensions(
            packs, explicit, fallback=self.DEFAULT_DIMENSION_FALLBACK
        )

    def resolve_strength(
        self,
        packs: List[_ResolvedPack],
        explicit: Optional[str],
    ) -> str:
        return self.injector.resolve_strength(packs, explicit)

    # ----------------------------------------------------------------
    # 项目上下文加载（轻量）
    # ----------------------------------------------------------------

    async def load_project_context(
        self,
        db: AsyncSession,
        project_id: str,
        target_chapter_id: Optional[str],
    ) -> _ProjectContext:
        """加载项目快照：项目本体 + 主角 + 当前章节大纲 + 最近 3 章（裁剪）。

        刻意避开 build_smart_chapter_context 的向量库依赖：
        - 测试场景下不需要 memory_service
        - R5 V1 只取最近章节，足够 LLM 维持人物设定 / 风格延续
        """
        proj_result = await db.execute(select(Project).where(Project.id == project_id))
        project = proj_result.scalar_one_or_none()
        if not project:
            raise ValueError(f"项目不存在：{project_id}")

        # 主角（role_type=protagonist 优先；不足时补 supporting）
        char_result = await db.execute(
            select(Character)
            .where(Character.project_id == project_id)
            .where(Character.is_organization.is_(False))
        )
        all_chars = list(char_result.scalars().all())
        # 排序：protagonist > major > supporting > minor > 其他
        rank = {"protagonist": 0, "major": 1, "supporting": 2, "minor": 3}
        all_chars.sort(key=lambda c: rank.get((c.role_type or "minor").lower(), 99))
        main_chars = all_chars[: self.MAIN_CHARACTERS_LIMIT]

        target_chapter: Optional[Chapter] = None
        target_outline: Optional[ChapterOutline] = None
        recent_chapters: List[Chapter] = []

        if target_chapter_id:
            ch_result = await db.execute(
                select(Chapter).where(Chapter.id == target_chapter_id)
            )
            target_chapter = ch_result.scalar_one_or_none()
            if target_chapter and target_chapter.project_id != project_id:
                # 安全护栏：API 层应已校验，这里再兜一道
                raise ValueError("目标章节不属于当前项目")
            if target_chapter and target_chapter.chapter_outline_id:
                ol_result = await db.execute(
                    select(ChapterOutline).where(
                        ChapterOutline.id == target_chapter.chapter_outline_id
                    )
                )
                target_outline = ol_result.scalar_one_or_none()

        # 最近 N 章：以 target_chapter.chapter_number 为锚；无锚则取最大序号往前数
        if target_chapter:
            anchor = target_chapter.chapter_number
            recent_q = (
                select(Chapter)
                .where(Chapter.project_id == project_id)
                .where(Chapter.chapter_number < anchor)
                .where(Chapter.content.isnot(None))
                .where(Chapter.content != "")
                .order_by(Chapter.chapter_number.desc())
                .limit(self.RECENT_CHAPTERS_FOR_CONTEXT)
            )
        else:
            recent_q = (
                select(Chapter)
                .where(Chapter.project_id == project_id)
                .where(Chapter.content.isnot(None))
                .where(Chapter.content != "")
                .order_by(Chapter.chapter_number.desc())
                .limit(self.RECENT_CHAPTERS_FOR_CONTEXT)
            )
        recent_result = await db.execute(recent_q)
        recent_chapters = list(reversed(recent_result.scalars().all()))  # 升序

        return _ProjectContext(
            project=project,
            main_characters=main_chars,
            target_chapter=target_chapter,
            target_outline=target_outline,
            recent_chapters=recent_chapters,
        )

    # ----------------------------------------------------------------
    # Prompt 拼装
    # ----------------------------------------------------------------

    def _format_project_state(self, ctx: _ProjectContext) -> str:
        """[项目当前状态] 区块，自然语言描述。"""
        proj = ctx.project
        lines: List[str] = []
        lines.append(f"小说标题：《{proj.title}》")
        if proj.theme:
            lines.append(f"主题：{proj.theme}")
        if proj.genre:
            lines.append(f"题材：{proj.genre}")
        if proj.narrative_perspective:
            lines.append(f"叙事视角：{proj.narrative_perspective}")
        world_bits = []
        if proj.world_time_period:
            world_bits.append(f"时代：{proj.world_time_period}")
        if proj.world_location:
            world_bits.append(f"地点：{proj.world_location}")
        if proj.world_atmosphere:
            world_bits.append(f"氛围：{proj.world_atmosphere}")
        if world_bits:
            lines.append("世界观：" + "；".join(world_bits))
        if proj.world_rules:
            rules_short = _truncate(proj.world_rules, 600)
            lines.append(f"世界规则：{rules_short}")

        # 主角
        if ctx.main_characters:
            char_lines = ["主要角色（用户已设定，仿写时必须遵守这些角色身份/性格）："]
            for c in ctx.main_characters:
                bits = [c.name]
                if c.role_type:
                    bits.append(f"({c.role_type})")
                detail = []
                if c.gender:
                    detail.append(c.gender)
                if c.age:
                    detail.append(c.age)
                if c.personality:
                    detail.append(_truncate(c.personality, 80))
                if detail:
                    bits.append("，" + "/".join(detail))
                char_lines.append("- " + "".join(bits))
            lines.append("\n".join(char_lines))

        # 当前章节大纲
        if ctx.target_chapter:
            ch = ctx.target_chapter
            lines.append(f"\n本次仿写目标章节：第{ch.chapter_number}章《{ch.title}》")
            outline_text = ""
            if ctx.target_outline:
                outline_text = (
                    ctx.target_outline.plot_points
                    or ctx.target_outline.summary
                    or ""
                )
            elif ch.summary:
                outline_text = ch.summary
            if outline_text:
                lines.append(f"章纲：{_truncate(outline_text, 1000)}")

            # 本章已写正文（结尾截选）：草稿会被"追加"到编辑器，
            # 不给已写内容会导致模型从章纲开头重写、追加后情节重复
            existing = (ch.content or "").strip()
            if existing:
                tail = _tail_truncate(existing, self.CURRENT_CHAPTER_TAIL_CHARS)
                lines.append(
                    "【本章已写内容 · 结尾截选】\n"
                    "（本次生成的草稿将追加在这段文字之后，必须从其结尾自然续写，"
                    "严禁重写/复述已发生的情节与对话）\n"
                    f"{tail}"
                )

        # 最近 3 章（结尾截选：续写承接看的是上一章怎么收尾，而非怎么开头）
        if ctx.recent_chapters:
            recent_lines = ["最近章节（结尾截选）："]
            for ch in ctx.recent_chapters:
                content = _tail_truncate(
                    ch.content or "", self.RECENT_CHAPTER_CHARS_TRUNCATE
                )
                recent_lines.append(
                    f"--- 第{ch.chapter_number}章《{ch.title}》结尾 ---\n{content}"
                )
            lines.append("\n".join(recent_lines))

        return "\n\n".join(lines)

    def _format_user_intent(self, user_intent: str) -> str:
        return f"[作者本次创作意图]\n{user_intent.strip()}"

    # ----------------------------------------------------------------
    # 对外：拼装 / 流式
    # ----------------------------------------------------------------

    async def assemble_prompt(
        self,
        db: AsyncSession,
        project_id: str,
        *,
        user_intent: str,
        target_chapter_id: Optional[str],
        pack_ids: Optional[List[str]],
        dimensions: Optional[List[str]],
        strength: Optional[str],
        target_word_count: int,
        style_id: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """拼装完整 prompt 并返回元数据（供 API 层包装为响应或喂给 AIService）。

        user_id 可选：提供时会额外注入长期记忆（伏笔/角色状态/情节点）与
        叙事状态（因果链/承诺/关系/时间线），保证仿写不破坏长篇连续性；
        省略时跳过（测试/无向量库环境自动降级）。

        Returns:
            {
              "system_prompt": str,
              "user_prompt": str,
              "used_packs": List[{pack_id, source_book_title, dimensions: [...]}],
              "used_dimensions": List[str],
              "strength": str,
              "target_word_count": int,
              "project_context_chars": int,
              "reference_chars": int,
            }
        """
        ctx = await self.load_project_context(db, project_id, target_chapter_id)

        # ====== 参考包组装：统一走 injector.build_reference_block ======
        # 修复点：此前仿写自维护一套只认 5 手法+corpus 的拼装，
        # synopsis/entities/relations/events/bridges/character_archive 被静默丢弃，
        # 而 used_dimensions 仍谎报"已启用"。改走统一入口后：
        # 1) 12 个维度全部可消费；2) used_dimensions 只含实际产出段落的维度。
        block = await self.injector.build_reference_block(
            db,
            project_id,
            scene="imitate_chapter",
            dimensions=dimensions,
            strength=strength,
            pack_ids=pack_ids,
            anchor_query=user_intent,
            fallback_dimensions=self.DEFAULT_DIMENSION_FALLBACK,
        )
        used_dimensions = block.used_dimensions
        used_strength = block.used_strength
        ref_sections: List[str] = list(block.user_sections)

        # ====== System Prompt ======
        base_system = (
            "你是一位专业的中文小说写手。你将基于 [作者本次创作意图] 完成一段章节草稿。\n"
            "硬性纪律：\n"
            "1) 严格遵守 [项目当前状态] 中给出的角色身份/性格/世界观/章纲，不得随意改动\n"
            "2) [参考方法论/结构手法/角色塑造/世界观/原书案例] 仅作『如何写』的方法参考，"
            "禁止照抄原书的具体人名/地名/情节/台词\n"
            "3) 输出体感：保持中文小说叙事节奏，避免分点列举式\n"
            "4) 字数控制：在目标字数 ±15% 区间内，结构完整\n"
            "5) 仅输出小说正文，不要输出任何解释、标题、章节号、Markdown 标记或元注释\n"
            "6) 若提供了【本章已写内容】：你的输出是它的直接续写，"
            "必须从其结尾无缝衔接，严禁重复、复述或改写已写段落"
        )
        if block.system_segment:
            base_system = (
                base_system
                + "\n\n[文风参考（影响语气/句式而非具体内容）]\n"
                + block.system_segment
            )

        # 项目内已有的写作风格叠加（与参考包文风互不冲突，叠加在更后面优先级更高）
        # 修复点：按项目所有权过滤（全局预设 project_id IS NULL / 本项目自定义），
        # 防止通过 style_id 读到其他项目的自定义文风内容
        if style_id:
            try:
                from app.models.writing_style import WritingStyle

                ws_result = await db.execute(
                    select(WritingStyle).where(
                        WritingStyle.id == style_id,
                        or_(
                            WritingStyle.project_id.is_(None),
                            WritingStyle.project_id == project_id,
                        ),
                    )
                )
                ws = ws_result.scalar_one_or_none()
                if ws and ws.prompt_content:
                    base_system = (
                        base_system
                        + "\n\n[项目内自定义文风（优先级最高）]\n"
                        + ws.prompt_content
                    )
                elif ws is None:
                    logger.warning(
                        "[V3-R5] style_id=%s 不存在或不属于项目 %s，已忽略",
                        style_id, project_id,
                    )
            except Exception as e:  # pragma: no cover - 防御性兜底
                logger.warning("[V3-R5] 项目文风加载失败，已忽略：%s", e)

        # ====== 业务上下文块（剧情卡 / 桥段位置 / 长期记忆） ======
        cards_block = await self._build_linked_cards_block(db, ctx)
        bridge_block = await self._build_bridge_constraint_block(
            db, project_id, ctx, target_word_count
        )
        memory_block = await self._build_memory_state_block(
            db, project_id, ctx, user_id, user_intent
        )

        # ====== User Prompt ======
        project_state = self._format_project_state(ctx)
        intent_block = self._format_user_intent(user_intent)
        word_block = (
            f"[字数要求]\n请输出约 {target_word_count} 字的小说正文（允许 ±15%）。"
        )

        user_prompt_parts = [
            "[项目当前状态]",
            project_state,
            intent_block,
        ]
        if cards_block:
            user_prompt_parts.append(cards_block)
        if bridge_block:
            user_prompt_parts.append(bridge_block)
        if memory_block:
            user_prompt_parts.append(memory_block)
        if ref_sections:
            user_prompt_parts.extend(ref_sections)
        user_prompt_parts.append(word_block)
        user_prompt_parts.append(
            "请直接输出小说正文（不要任何前言/标题/分隔线/解释）："
        )
        user_prompt = "\n\n".join(user_prompt_parts)

        return {
            "system_prompt": base_system,
            "user_prompt": user_prompt,
            "used_packs": block.used_packs,
            "used_dimensions": used_dimensions,
            "strength": used_strength,
            "target_word_count": target_word_count,
            "project_context_chars": len(project_state),
            "reference_chars": sum(len(s) for s in ref_sections),
        }

    # ----------------------------------------------------------------
    # 业务上下文块构建（剧情卡 / 桥段约束 / 长期记忆）
    # ----------------------------------------------------------------

    async def _build_linked_cards_block(
        self, db: AsyncSession, ctx: _ProjectContext
    ) -> str:
        """目标章纲关联的剧情卡片（与普通正文生成对齐）。"""
        if ctx.target_outline is None:
            return ""
        try:
            from app.models.plot_card import PlotCard
            from app.models.plot_card_chapter_outline_link import (
                PlotCardChapterOutlineLink,
            )

            rows = await db.execute(
                select(PlotCard)
                .join(
                    PlotCardChapterOutlineLink,
                    PlotCard.id == PlotCardChapterOutlineLink.plot_card_id,
                )
                .where(
                    PlotCardChapterOutlineLink.chapter_outline_id
                    == ctx.target_outline.id
                )
                .order_by(PlotCardChapterOutlineLink.created_at)
            )
            cards = list(rows.scalars().all())[: self.LINKED_PLOT_CARDS_LIMIT]
            if not cards:
                return ""
            lines = [
                f"- 【{c.card_type or '剧情'}】{c.title}："
                f"{_truncate(c.content or '', self.LINKED_PLOT_CARD_CHARS)}"
                for c in cards
            ]
            return "[本章关联剧情卡片（草稿应体现这些设计）]\n" + "\n".join(lines)
        except Exception as e:  # pragma: no cover - 防御性降级
            logger.warning("[V3-R5] 剧情卡注入失败（已跳过）：%s", e)
            return ""

    async def _build_bridge_constraint_block(
        self,
        db: AsyncSession,
        project_id: str,
        ctx: _ProjectContext,
        target_word_count: int,
    ) -> str:
        """K2 桥段位置约束：目标章纲绑定桥段时注入 C1/C2/C3/C4 位置纪律。

        修复点：此前仿写完全无桥段感——C3 该"装到底不留钩子"的章节
        可能被写成留悬念，C1 代入章可能被写成大结算。
        """
        outline = ctx.target_outline
        if outline is None or not getattr(outline, "bridge_id", None):
            return ""
        try:
            from app.services.reference_pack import (
                build_v4_bridge_constraint_only,
                fetch_bridge_context,
            )

            bridge_ctx = await fetch_bridge_context(db, outline)
            if not bridge_ctx:
                return ""
            return await build_v4_bridge_constraint_only(
                db,
                project_id,
                scene="chapter_content",
                bridge_position=getattr(outline, "bridge_position", None),
                bridge_context=bridge_ctx,
                chapter_outline_id=outline.id,
                target_word_count=target_word_count,
            )
        except Exception as e:  # pragma: no cover - 防御性降级
            logger.warning("[V3-R5] 桥段约束注入失败（已跳过）：%s", e)
            return ""

    async def _build_memory_state_block(
        self,
        db: AsyncSession,
        project_id: str,
        ctx: _ProjectContext,
        user_id: Optional[str],
        user_intent: str,
    ) -> str:
        """长期记忆 + 叙事状态（伏笔/角色状态/因果/承诺/关系/时间线）。

        仅当 user_id 提供且目标章节明确时启用；任一子服务失败都单独降级，
        不阻塞仿写主流程（测试/无向量库环境自然跳过）。
        """
        if not user_id or ctx.target_chapter is None:
            return ""

        chapter_number = ctx.target_chapter.chapter_number
        outline_query = ""
        if ctx.target_outline is not None:
            outline_query = (
                ctx.target_outline.plot_points or ctx.target_outline.summary or ""
            )
        query_text = (outline_query or ctx.target_chapter.summary or user_intent or "")[:500]

        parts: List[str] = []

        # 1) 向量记忆：伏笔 / 角色状态 / 情节点 / 语义相关
        try:
            from app.services.memory_service import memory_service

            mem = await memory_service.build_context_for_generation(
                user_id=user_id,
                project_id=project_id,
                current_chapter=chapter_number,
                chapter_outline=query_text,
                character_names=[c.name for c in ctx.main_characters] or None,
            )
            for key in ("foreshadows", "character_states", "plot_points", "relevant_memories"):
                v = (mem or {}).get(key) or ""
                if isinstance(v, str) and v.strip():
                    parts.append(v.strip())
        except Exception as e:
            logger.warning("[V3-R5] 记忆上下文加载失败（已跳过）：%s", e)

        # 2) 叙事状态：因果链 / 承诺 / 关系动态 / 时间线 / POV 已知信息 / 阵营
        try:
            from app.services.narrative_state_service import narrative_state_service

            state = await narrative_state_service.build_generation_context(
                db=db,
                project_id=project_id,
                current_chapter=chapter_number,
                pov_character_name=(
                    getattr(ctx.target_outline, "pov", None)
                    if ctx.target_outline is not None
                    else None
                ),
            )
            for v in (state or {}).values():
                if isinstance(v, str) and v.strip():
                    parts.append(v.strip())
        except Exception as e:
            logger.warning("[V3-R5] 叙事状态加载失败（已跳过）：%s", e)

        if not parts:
            return ""
        joined = _truncate("\n\n".join(parts), 4000)
        return (
            "[长期记忆与叙事状态（硬约束：已死角色不得复活；能力/位置/关系/未回收伏笔以此为准）]\n"
            + joined
        )


# ============================================================
# 工具函数（V3.1.3 前的 token 工具；其他通用工具已搬到 reference_pack_injector）
# ============================================================


_STOPWORDS = {
    "的", "了", "和", "与", "及", "以", "但是", "因为", "所以", "如果", "可以",
    "需要", "一个", "一些", "我们", "他们", "她们", "这个", "那个",
    "the", "a", "an", "of", "and", "or", "to", "in", "is", "for", "on",
}


def _tokenize_keywords(text: str) -> List[str]:
    """轻量中文分词：按 2-4 字 n-gram 切片 + 英文单词。"""
    if not text:
        return []
    out: List[str] = []
    # 英文/数字单词
    out.extend(re.findall(r"[A-Za-z0-9]+", text))
    # 中文按 2-gram 取片段（足够覆盖关键词命中）
    cn = re.findall(r"[\u4e00-\u9fff]+", text)
    for seg in cn:
        if len(seg) < 2:
            continue
        for i in range(len(seg) - 1):
            tok = seg[i : i + 2]
            out.append(tok)
    out = [w.lower() for w in out if w.lower() not in _STOPWORDS]
    return _dedup_keep_order(out)


def _score_text(text: str, keywords: List[str]) -> int:
    if not text or not keywords:
        return 0
    low = text.lower()
    return sum(1 for k in keywords if k and k in low)
