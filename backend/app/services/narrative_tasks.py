"""章纲叙事任务（chapter_outlines.narrative_tasks，纯函数）。

伏笔规划化：章纲展开时（能看到当前未回收承诺清单）为每章规划
- resolve：本章必须回收的旧承诺（promise_id + 怎么回收）
- advance：本章顺带推进 / 提一句的旧承诺（保温，防止长线伏笔几十章不露面）
- plant：本章要埋下的新伏笔（含计划多少章后回收）
写作时把任务明确写进「本章任务」；分析时把计划回收章交给分析模型填 deadline_chapter，
承诺清单据此按计划区间预警，而不是一律"5 章没提就掉线"。

同一份 JSON 里还有「读者线」（reader：三句短话，写法见 reader_lens）：
- waiting：读者带着什么期待读这一章；payoff：本章给读者的兑现；gap：信息差（谁被蒙在鼓里，保持还是揭开）
没有读者线的章纲不带 reader 键（解析结果与以前一致）。写作口吻三行都进本章任务（括号里是写法）；审校口吻不带 waiting
（它是背景，不是要核对的任务），另两行括号里换成判定口径；分析口吻不带读者线。
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Optional

TASK_KINDS: tuple[str, ...] = ("resolve", "advance", "plant")
READER_KEYS: tuple[str, ...] = ("waiting", "payoff", "gap")
READER_LABELS = {"waiting": "读者在等", "payoff": "本章兑现", "gap": "信息差"}
READER_LIMIT = 160
# 「本章兑现」可能是一次真兑现，也可能只是蓄势章把期待推近一步：前半句两种都适用，后半句只管真兑现（不逼着硬凑围观的人）
PAYOFF_HINT = "（落到具体的事上，不一句带过；是兑现就写出在场者的反应和主角实际拿到的东西）"
GAP_HINT = "（没揭开之前，不知情的人照着错的认知说话做事；本章揭开的话，看错的人要在场、有反应）"
# 审校口吻带的是判定口径，不是写法。信息差多半是「本章保持」：正文没写到那层不算没完成，否则批量写作会白白重写一次
PAYOFF_REVIEW_HINT = "（判定：正文里这件事确实发生了、不是一句话带过才算完成）"
GAP_REVIEW_HINT = "（判定：不知情的人在正文里提前知道了，或写明本章揭开却没揭开，才算没完成；正文没写到这层信息差算完成）"


def _empty() -> dict[str, Any]:
    return {kind: [] for kind in TASK_KINDS}


def _clip(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def parse_reader_line(raw: Any) -> dict[str, str]:
    """读者线：只留认识的、有内容的键。"""
    data = raw if isinstance(raw, dict) else {}
    return {key: text for key in READER_KEYS if (text := _clip(data.get(key), READER_LIMIT))}


def with_reader_line(raw: Any, reader: Any) -> Optional[str]:
    """把读者线写进章纲的叙事任务 JSON（伏笔任务原样保留）；整份都空了返回 None。"""
    tasks = parse_narrative_tasks(raw)
    tasks.pop("reader", None)
    line = parse_reader_line(reader)
    if line:
        tasks["reader"] = line
    return json.dumps(tasks, ensure_ascii=False) if has_tasks(tasks) else None


def parse_narrative_tasks(raw: Any) -> dict[str, Any]:
    """JSON 文本 / dict → 规整结构；坏数据一律退化为空任务。有读者线才带 reader 键。"""
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
    reader = parse_reader_line(data.get("reader"))
    if reader:
        out["reader"] = reader
    return out


def normalize_narrative_tasks(raw: Any, open_promises: Iterable[Any]) -> dict[str, Any]:
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
    return any(tasks[kind] for kind in TASK_KINDS) or bool(tasks.get("reader"))


def _reader_lines(reader: dict[str, str], *, for_review: bool) -> list[str]:
    lines = []
    if reader.get("waiting") and not for_review:
        lines.append(f"{READER_LABELS['waiting']}：{reader['waiting']}")
    if reader.get("payoff"):
        lines.append(f"- {READER_LABELS['payoff']}：{reader['payoff']}{PAYOFF_REVIEW_HINT if for_review else PAYOFF_HINT}")
    if reader.get("gap"):
        lines.append(f"- {READER_LABELS['gap']}：{reader['gap']}{GAP_REVIEW_HINT if for_review else GAP_HINT}")
    return lines


def render_narrative_tasks(raw: Any, chapter_number: int | None = None, *, for_analysis: bool = False,
                           for_review: bool = False) -> str:
    """写作口吻给正文「本章任务」；审校口吻（for_review）给章纲遵循度审校；分析口吻（for_analysis）给分析提示词（带计划回收章）。"""
    tasks = parse_narrative_tasks(raw)
    lines: list[str] = [] if for_analysis else _reader_lines(tasks.get("reader") or {}, for_review=for_review)
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
