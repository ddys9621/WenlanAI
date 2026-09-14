"""灵感语料检索（V5 薄封装）。

V3.1.3 的「摘要 BM25 + 实体 1-hop 关系扩展」随实体图谱（V2-V4 抽取核心）一并删除。
本模块只保留对外名字 ``ImitationCorpusRetriever / CorpusHit / format_corpus_prompt / tokenize / BM25``，
底层全部委托 ``book_dissect.chapter_card_retriever``（BM25 over 拆书卡）。

CorpusHit.summary 即拆书卡章纲（老包无章纲时为老引擎摘要）；expansion_path 恒为 None（无关系扩展）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.book_dissect.chapter_card_retriever import (  # noqa: F401 —— 对外保留旧名字
    BM25,
    BM25_B,
    BM25_K1,
    MIN_SCORE_FLOOR,
    CardHit,
    ChapterCardRetriever,
    format_card_hits,
    tokenize,
)


@dataclass
class CorpusHit:
    """检索命中的单条语料（旧字段名保持不变）。"""

    task_id: str
    chapter_number: int
    chapter_title: str
    summary: str
    score: float
    hit_type: str = "direct"                    # direct / fallback
    expansion_path: Optional[list[str]] = None  # 兼容旧字段；V5 无关系扩展，恒为 None
    function_tags: list[str] = field(default_factory=list)
    payoff_points: list[str] = field(default_factory=list)
    ending_hook_text: str = ""

    @classmethod
    def from_card_hit(cls, hit: CardHit) -> "CorpusHit":
        return cls(
            task_id=hit.task_id, chapter_number=hit.chapter_number, chapter_title=hit.chapter_title,
            summary=hit.outline, score=hit.score, hit_type=hit.hit_type,
            function_tags=list(hit.function_tags), payoff_points=list(hit.payoff_points),
            ending_hook_text=hit.ending_hook_text,
        )

    def to_card_hit(self) -> CardHit:
        return CardHit(
            task_id=self.task_id, chapter_number=self.chapter_number, chapter_title=self.chapter_title,
            outline=self.summary, function_tags=list(self.function_tags), payoff_points=list(self.payoff_points),
            ending_hook_text=self.ending_hook_text, score=self.score, hit_type=self.hit_type,
        )


class ImitationCorpusRetriever:
    """灵感语料检索：委托 ChapterCardRetriever，返回 CorpusHit（summary = 拆书卡章纲）。"""

    def __init__(self, retriever: Optional[ChapterCardRetriever] = None) -> None:
        self._retriever = retriever or ChapterCardRetriever()

    async def retrieve(
        self,
        db: AsyncSession,
        *,
        task_ids: list[str],
        user_intent: str,
        top_k: int,
        allow_fallback: bool = True,
        boost_tags: Iterable[str] = (),
    ) -> list[CorpusHit]:
        """Args:
            task_ids: 涉及的拆书任务 ID 列表
            user_intent: 检索锚文本（作者意图 / 章纲 / 桥段目标等）
            top_k: 最终返回条数
            allow_fallback: 命中不足时是否按章节序补最早的卡；prompt 注入场景应传 False
        """
        hits = await self._retriever.retrieve(
            db, task_ids=task_ids, query=user_intent, top_k=top_k,
            boost_tags=boost_tags, allow_fallback=allow_fallback,
        )
        return [CorpusHit.from_card_hit(h) for h in hits]


def format_corpus_prompt(hits: list[CorpusHit], *, title_map: dict[str, str], chars_per_item: int) -> str:
    """把 hits 格式化为 prompt 片段（同 chapter_card_retriever.format_card_hits）。"""
    return format_card_hits([h.to_card_hit() for h in hits], title_map=title_map, chars_per_item=chars_per_item)
