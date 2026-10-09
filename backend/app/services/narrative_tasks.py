"""章纲叙事任务（chapter_outlines.narrative_tasks，纯函数）。

伏笔规划化：章纲展开时（能看到当前未回收承诺清单）为每章规划
- resolve：本章必须回收的旧承诺（promise_id + 怎么回收）
- advance：本章顺带推进 / 提一句的旧承诺（保温，防止长线伏笔几十章不露面）
- plant：本章要埋下的新伏笔（含计划多少章后回收）
写作时把任务明确写进「本章任务」；分析时把计划回收章交给分析模型填 deadline_chapter，
承诺清单据此按计划区间预警，而不是一律"5 章没提就掉线"。
"""
from __future__ import annotations

import json
from typing import Any, Iterable

TASK_KINDS: tuple[str, ...] = ("resolve", "advance", "plant")


def _empty() -> dict[str, list[dict[str, Any]]]:
    return {kind: [] for kind in TASK_KINDS}


def _clip(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def parse_narrative_tasks(raw: Any) -> dict[str, list[dict[str, Any]]]:
    """JSON 文本 / dict → 规整结构；坏数据一律退化为空任务。"""
    data: Any = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return _empty()
    if not isinstance(data, dict):
        return _empty()
    out = _empty()
    for kind in ("resolve", "advance"):
        for item in data.get(kind) or []:
            if isinstance(item, dict) and (item.get("promise_id") or item.get("title")):
                out[kind].append({
                    "promise_id": str(item.get("promise_id") or "").strip() or None,
                    "title": _clip(item.get("title"), 60),
                    "how": _clip(item.get("how"), 120),
                })
    for item in data.get("plant") or []:
        if isinstance(item, dict) and (item.get("title") or item.get("content")):
            out["plant"].append({
                "title": _clip(item.get("title") or item.get("content"), 60),
                "content": _clip(item.get("content") or item.get("title"), 160),
                "payoff_after": _int(item.get("payoff_after")),
            })
    return out


def normalize_narrative_tasks(raw: Any, open_promises: Iterable[Any]) -> dict[str, list[dict[str, Any]]]:
    """展开结果入库前校正：resolve / advance 只保留确实还没回收的承诺，标题以承诺表为准。"""
    tasks = parse_narrative_tasks(raw)
    by_id = {str(getattr(p, "id", "")): p for p in open_promises or []}
    for kind in ("resolve", "advance"):
        kept = []
        for item in tasks[kind]:
            promise = by_id.get(item.get("promise_id") or "")
            if promise is None:
                continue
            kept.append({**item, "title": _clip(getattr(promise, "title", "") or item["title"], 60)})
        tasks[kind] = kept
    return tasks


def task_promise_ids(raw: Any) -> set[str]:
    tasks = parse_narrative_tasks(raw)
    return {item["promise_id"] for kind in ("resolve", "advance") for item in tasks[kind] if item.get("promise_id")}


def has_tasks(raw: Any) -> bool:
    tasks = parse_narrative_tasks(raw)
    return any(tasks[kind] for kind in TASK_KINDS)


def render_narrative_tasks(raw: Any, chapter_number: int | None = None, *, for_analysis: bool = False) -> str:
    """写作口吻（for_analysis=False）给正文「本章任务」；分析口吻给分析提示词（带计划回收章）。"""
    tasks = parse_narrative_tasks(raw)
    lines: list[str] = []
    for item in tasks["resolve"]:
        how = f"：{item['how']}" if item.get("how") else ""
        lines.append(f"- 必须回收「{item['title']}」{how}（写清楚真相 / 结果，让读者对上前文）")
    for item in tasks["advance"]:
        how = f"：{item['how']}" if item.get("how") else ""
        lines.append(f"- 推进 / 提一句「{item['title']}」{how}（只露一点新进展，不解决）")
    for item in tasks["plant"]:
        due = ""
        if item.get("payoff_after"):
            target = f"第{chapter_number + item['payoff_after']}章" if chapter_number else f"约{item['payoff_after']}章后"
            due = f"（计划回收章：{target}）" if for_analysis else f"（约 {item['payoff_after']} 章后回收，计划{target}）"
        lines.append(f"- 埋下「{item['title']}」：{item['content']}{due}（自然带出，不点破、不解释）")
    return "\n".join(lines)
