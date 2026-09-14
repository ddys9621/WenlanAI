"""拆书 V5：拆书卡检索（BM25 over 拆书卡 + 桥段位置功能标签加权）。

替代 V3.1.3 的「摘要 BM25 + 实体 1-hop 扩展」：实体图谱随 V2-V4 抽取核心一并删除，
拆书卡本身已带功能标签 / 章末钩子 / 爽点，检索直接落在这些字段上，不再做实体扩展。

文档文本 = outline（无则 summary 兼容老包）+ function_tags + ending_hook_text + payoff_points。
boost_tags 命中任一功能标签 → 分数 ×TAG_BOOST（桥段位置 → 标签映射见 BRIDGE_POSITION_TAGS）。
设计：agent-docs/features/book_dissect_v5_design.md §5
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book_dissect_chapter_fact import BookDissectChapterFact

# BM25 经典参数
BM25_K1 = 1.5
BM25_B = 0.75
# 分数下界：低于此值的卡不会被返回（即使凑不满 top-k）
MIN_SCORE_FLOOR = 0.01
# 功能标签命中加权
TAG_BOOST = 1.3

# 桥段位置 → 该位置典型的功能标签（v5_types.FUNCTION_TAGS 子集）
BRIDGE_POSITION_TAGS: dict[str, tuple[str, ...]] = {
    "intro":     ("开局立足", "日常代入", "信息差铺垫", "转场换地图", "伏笔埋设"),
    "build":     ("危机铺垫", "拉扯试探", "信息差铺垫", "支线推进", "情感推进"),
    "payoff":    ("爽点兑现", "打脸", "升级突破", "战斗", "伏笔回收", "信息揭露"),
    "aftermath": ("善后收获", "过渡", "情感推进", "转场换地图"),
}

_STOPWORDS = {
    "的", "了", "和", "与", "及", "以", "但是", "因为", "所以", "如果", "可以",
    "需要", "一个", "一些", "我们", "他们", "她们", "这个", "那个",
    "the", "a", "an", "of", "and", "or", "to", "in", "is", "for", "on",
}


def tokenize(text: str) -> list[str]:
    """轻量中文分词：汉字按 2-gram 切片 + 英文 / 数字单词，过滤停用词。"""
    if not text:
        return []
    out: list[str] = []
    out.extend(re.findall(r"[A-Za-z0-9]+", text))
    for seg in re.findall(r"[\u4e00-\u9fff]+", text):
        for i in range(len(seg) - 1):
            out.append(seg[i: i + 2])
    return [w.lower() for w in out if w.lower() not in _STOPWORDS]


class BM25:
    """最小化 Okapi BM25：score(D,Q) = Σ IDF(q) · f(q,D)(k1+1) / (f(q,D) + k1(1 - b + b·|D|/avgdl))。"""

    def __init__(self, tokenized_docs: list[list[str]], k1: float = BM25_K1, b: float = BM25_B) -> None:
        self.k1, self.b = k1, b
        self.n_docs = len(tokenized_docs)
        self.doc_lens = [len(d) for d in tokenized_docs]
        self.avg_dl = (sum(self.doc_lens) / self.n_docs) if self.n_docs else 0.0
        df: dict[str, int] = {}
        self.tfs: list[dict[str, int]] = []
        for doc in tokenized_docs:
            tf: dict[str, int] = {}
            for w in doc:
                tf[w] = tf.get(w, 0) + 1
            self.tfs.append(tf)
            for w in tf:
                df[w] = df.get(w, 0) + 1
        self.idf = {w: math.log((self.n_docs - cnt + 0.5) / (cnt + 0.5) + 1.0) for w, cnt in df.items()}

    def score(self, doc_idx: int, query_tokens: Iterable[str]) -> float:
        if self.n_docs == 0 or self.avg_dl == 0:
            return 0.0
        tf, dl = self.tfs[doc_idx], self.doc_lens[doc_idx]
        s = 0.0
        for q in query_tokens:
            f = tf.get(q)
            if not f:
                continue
            denom = f + self.k1 * (1 - self.b + self.b * dl / self.avg_dl)
            s += self.idf.get(q, 0.0) * (f * (self.k1 + 1)) / denom
        return s

    def rank(self, query_tokens: list[str]) -> list[tuple[int, float]]:
        """返回 [(doc_idx, score), ...] 按分数倒序。"""
        if not query_tokens or self.n_docs == 0:
            return []
        scores = [(i, self.score(i, query_tokens)) for i in range(self.n_docs)]
        scores.sort(key=lambda x: -x[1])
        return scores


@dataclass
class CardHit:
    task_id: str
    chapter_number: int
    chapter_title: str
    outline: str
    function_tags: list[str] = field(default_factory=list)
    payoff_points: list[str] = field(default_factory=list)
    ending_hook_text: str = ""
    score: float = 0.0
    boosted: bool = False
    hit_type: str = "direct"                  # direct / fallback


@dataclass
class _CardDoc:
    task_id: str
    chapter_number: int
    chapter_title: str
    outline: str
    function_tags: list[str]
    payoff_points: list[str]
    ending_hook_text: str
    tokens: list[str]

    def to_hit(self, score: float, *, boosted: bool = False, hit_type: str = "direct") -> CardHit:
        return CardHit(
            task_id=self.task_id, chapter_number=self.chapter_number, chapter_title=self.chapter_title,
            outline=self.outline, function_tags=list(self.function_tags), payoff_points=list(self.payoff_points),
            ending_hook_text=self.ending_hook_text, score=round(score, 4), boosted=boosted, hit_type=hit_type,
        )


class ChapterCardRetriever:
    """BM25 over 拆书卡。

    用法：
        hits = await ChapterCardRetriever().retrieve(
            db, task_ids=[pack.task_id], query="林七第一次拜师", top_k=3,
            boost_tags=BRIDGE_POSITION_TAGS.get(bridge_position, ()),
        )
    """

    async def retrieve(
        self,
        db: AsyncSession,
        *,
        task_ids: list[str],
        query: str,
        top_k: int,
        boost_tags: Iterable[str] = (),
        allow_fallback: bool = False,
    ) -> list[CardHit]:
        """按 query 检索拆书卡，返回 ≤ top_k 条，按加权分倒序。

        allow_fallback=True 时命中不足 top_k 会按 (task_id, chapter_number) 顺序补最早的卡
        （hit_type="fallback"，score=0）；prompt 注入场景应保持 False——无关卡只会干扰生成。
        """
        if not task_ids or top_k <= 0:
            return []
        docs = await self._load_cards(db, task_ids)
        if not docs:
            return []
        query_tokens = _dedup_keep_order(tokenize(query or ""))
        hits: list[CardHit] = []
        if query_tokens:
            boost = set(boost_tags)
            bm25 = BM25([d.tokens for d in docs])
            scored: list[tuple[float, bool, _CardDoc]] = []
            for idx, doc in enumerate(docs):
                raw = bm25.score(idx, query_tokens)
                if raw < MIN_SCORE_FLOOR:
                    continue
                boosted = bool(boost) and any(t in boost for t in doc.function_tags)
                scored.append((raw * TAG_BOOST if boosted else raw, boosted, doc))
            scored.sort(key=lambda x: (-x[0], x[2].task_id, x[2].chapter_number))
            hits = [doc.to_hit(score, boosted=boosted) for score, boosted, doc in scored[:top_k]]
        if allow_fallback and len(hits) < top_k:
            picked = {(h.task_id, h.chapter_number) for h in hits}
            leftover = sorted(
                (d for d in docs if (d.task_id, d.chapter_number) not in picked),
                key=lambda d: (d.task_id, d.chapter_number),
            )
            hits.extend(d.to_hit(0.0, hit_type="fallback") for d in leftover[: top_k - len(hits)])
        return hits

    async def _load_cards(self, db: AsyncSession, task_ids: list[str]) -> list[_CardDoc]:
        rows = (await db.execute(
            select(
                BookDissectChapterFact.task_id, BookDissectChapterFact.chapter_number,
                BookDissectChapterFact.chapter_title, BookDissectChapterFact.fact_json, BookDissectChapterFact.summary,
            ).where(BookDissectChapterFact.task_id.in_(task_ids))
        )).all()
        docs: list[_CardDoc] = []
        for task_id, number, title, fact_json, summary in rows:
            card = _parse_card(fact_json)
            outline = " ".join(str(card.get("outline") or summary or "").split())
            if not outline:
                continue
            tags = _str_list(card.get("function_tags"))
            payoffs = _str_list(card.get("payoff_points"))
            hook = " ".join(str(card.get("ending_hook_text") or "").split())
            docs.append(_CardDoc(
                task_id=task_id, chapter_number=number, chapter_title=title or str(card.get("title") or ""),
                outline=outline, function_tags=tags, payoff_points=payoffs, ending_hook_text=hook,
                tokens=tokenize(" ".join([outline, *tags, hook, *payoffs])),
            ))
        return docs


DEFAULT_CORPUS_HEADER = "[原书相关拆书卡（仅作节奏 / 结构参考，禁止照抄原书人名与情节）]"


def format_card_hits(
    hits: list[CardHit],
    *,
    title_map: dict[str, str],
    chars_per_item: int,
    header: str = DEFAULT_CORPUS_HEADER,
) -> str:
    """把命中的拆书卡格式化为 prompt 片段：一卡一条，章纲按 chars_per_item 截断，爽点 / 章末钩另起一行。"""
    if not hits:
        return ""
    lines: list[str] = []
    for h in hits:
        book = title_map.get(h.task_id, "原书")
        tags = f"［{' / '.join(h.function_tags)}］" if h.function_tags else ""
        tag = "（按章节序兜底）" if h.hit_type == "fallback" else ""
        lines.append(f"- 《{book}》第{h.chapter_number}章《{h.chapter_title}》{tags}{tag}：{_truncate(h.outline, chars_per_item)}")
        extras = []
        if h.payoff_points:
            extras.append(f"爽点：{'；'.join(h.payoff_points[:3])}")
        if h.ending_hook_text:
            extras.append(f"章末钩：{h.ending_hook_text}")
        if extras:
            lines.append("  " + "｜".join(extras))
    body = "\n".join(lines)
    return f"{header}\n{body}" if header else body


def _parse_card(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [" ".join(str(x).split()) for x in value if x is not None and str(x).strip()]


def _dedup_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _truncate(text: str, cap: int) -> str:
    if not text or len(text) <= cap:
        return text or ""
    return text[: max(cap - 1, 0)] + "…"
