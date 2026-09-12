"""去 AI 味诊断历史的聚合：勾选反馈 → 特征采纳率；最近 N 章高频特征 → 项目级先验。

两个闭环都不需要新表：
- 用户在「去 AI 味润色」里勾/不勾某条 finding 就是免费的标注，追加到 chapter_deai_reviews.result["feedback"]；
- 同一项目最近几章的诊断结果聚合出"这个模型在这本书里真的反复犯的"特征，注入下一章的写作提示词——
  这是直接中文、直接本题材、直接本模型的证据，比 models/<family>.prior.md 的英文基准形状迁移准得多。
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.deai_review_service import is_actionable

FEEDBACK_HISTORY_CAP = 10  # 同一份报告最多留最近几次勾选记录
PROJECT_PRIOR_MAX_CHAPTERS = 8  # 项目级先验看最近几章的诊断
PROJECT_PRIOR_TOP = 5
MIN_CHAPTERS = 2  # 至少在这么多章里出现才算"反复犯"
MIN_ACCEPTANCE = 0.34  # 采纳率低于此（且反馈样本够）的特征视为噪音，不进先验
MIN_FEEDBACK = 3  # 采纳率至少要有这么多次"被提供"才可信


def record_feedback(result: dict[str, Any], *, mode: str, selected: list[int], candidates: list[int], at: str) -> dict[str, Any]:
    """把一次勾选记录追加进 result["feedback"]，返回新 dict（JSON 列要整体重新赋值才会写库）。

    candidates：当时展示给用户可勾的 finding 下标；selected：用户最终勾着的（必须是 candidates 的子集）。
    """
    total = len(result.get("findings") or [])
    cand = sorted({i for i in candidates if isinstance(i, int) and 0 <= i < total})
    sel = sorted({i for i in selected if isinstance(i, int) and i in cand})
    entry = {"mode": mode, "selected": sel, "candidates": cand, "at": at}
    history = [e for e in (result.get("feedback") or []) if isinstance(e, dict)]
    history.append(entry)
    return {**result, "feedback": history[-FEEDBACK_HISTORY_CAP:]}


def feature_acceptance(results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """按特征名统计：被提供给用户几次（offered）、被勾着带入几次（selected）。没有反馈的报告不计。"""
    acc: dict[str, dict[str, int]] = {}
    for result in results:
        findings = result.get("findings") or []
        for entry in result.get("feedback") or []:
            selected = set(entry.get("selected") or [])
            for idx in entry.get("candidates") or []:
                if not isinstance(idx, int) or not 0 <= idx < len(findings):
                    continue
                feature = findings[idx].get("feature") or ""
                slot = acc.setdefault(feature, {"selected": 0, "offered": 0})
                slot["offered"] += 1
                if idx in selected:
                    slot["selected"] += 1
    return acc


def aggregate_project_findings(
    results: list[dict[str, Any]],
    *,
    min_chapters: int = MIN_CHAPTERS,
    top: int = PROJECT_PRIOR_TOP,
    min_acceptance: float = MIN_ACCEPTANCE,
    min_feedback: int = MIN_FEEDBACK,
) -> list[dict[str, Any]]:
    """每份 result 视为一章：按特征统计出现的章数（不是实例数），按章数降序取 top。

    只算 is_actionable 的信号；用户反复不勾（采纳率 < min_acceptance 且 offered ≥ min_feedback）的特征剔除。
    """
    acceptance = feature_acceptance(results)
    stats: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for result in results:
        seen: set[str] = set()
        for f in result.get("findings") or []:
            feature = (f.get("feature") or "").strip()
            if not feature or feature in seen or not is_actionable(f):
                continue
            seen.add(feature)
            slot = stats.setdefault(feature, {"feature": feature, "layer": f.get("layer") or "措辞", "chapters": 0, "example": f.get("evidence") or ""})
            slot["chapters"] += 1
    items = []
    for item in stats.values():
        if item["chapters"] < min_chapters:
            continue
        acc = acceptance.get(item["feature"])
        if acc and acc["offered"] >= min_feedback and acc["selected"] / acc["offered"] < min_acceptance:
            continue
        items.append(item)
    items.sort(key=lambda i: -i["chapters"])
    return items[:top]


def format_project_prior(items: list[dict[str, Any]], *, chapters_considered: int) -> str:
    if not items:
        return ""
    lines = [
        f"【本项目实测高频问题——最近 {chapters_considered} 章去 AI 味诊断里反复出现的信号，是这个模型在这本书里真的在犯的，优先避免】"
    ]
    for item in items:
        example = f"（例：“{item['example'][:30]}”）" if item.get("example") else ""
        lines.append(f"- {item['layer']}·{item['feature']}：{item['chapters']}/{chapters_considered} 章出现{example}")
    return "\n".join(lines)


async def load_recent_review_results(db: AsyncSession, project_id: str, *, max_chapters: int = PROJECT_PRIOR_MAX_CHAPTERS) -> list[dict[str, Any]]:
    """项目内每章最新一份诊断结果，按诊断时间倒序，最多 max_chapters 章。"""
    from app.models.chapter_deai_review import ChapterDeaiReview

    rows = (await db.execute(
        select(ChapterDeaiReview.chapter_id, ChapterDeaiReview.result)
        .where(ChapterDeaiReview.project_id == project_id)
        .order_by(ChapterDeaiReview.created_at.desc())
        .limit(max_chapters * 4)
    )).all()
    latest: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for chapter_id, result in rows:
        if chapter_id not in latest and isinstance(result, dict):
            latest[chapter_id] = result
        if len(latest) >= max_chapters:
            break
    return list(latest.values())


async def load_project_prior(db: AsyncSession, project_id: Optional[str]) -> str:
    """写作提示词用：项目级先验文本；没有足够诊断历史时返回空串。"""
    if not project_id:
        return ""
    results = await load_recent_review_results(db, project_id)
    return format_project_prior(aggregate_project_findings(results), chapters_considered=len(results))
