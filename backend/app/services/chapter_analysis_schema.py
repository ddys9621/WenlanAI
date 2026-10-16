"""章节分析两段式输出的解析、校验、分段合并，以及转成结算服务认的格式（纯函数，无 DB / 无 LLM）。

- 分析 A「叙事事实」：摘要 / 章末状态 / 故事时间 / 地点 / 出场人物 / 硬性状态变化 / 伏笔动作 / 关系 / 已知信息 / 关键事件
- 分析 B「人物与标注」：人物与组织档案（含归属变化）、正文标注引句
- parse_model_json：去代码块 → 严格解析 → 失败才用 json-repair 修，返回 (对象, 是否修过)
- looks_truncated：finish_reason=length，或修过且缺结尾哨兵 end —— 截断的结果一律不落库
- facts_to_settlement：叙事事实 → narrative_state_service / chapter_consistency_service 认的 analysis 字典
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional

try:
    from json_repair import repair_json as _repair_json
except ImportError:  # pragma: no cover - 依赖缺失时只剩严格解析
    _repair_json = None

STATE_CHANGES: dict[str, frozenset[str]] = {
    "life": frozenset({"dead", "missing", "revived", "survived"}),
    "location": frozenset({"arrived", "left", "current"}),
    "realm": frozenset({"current"}),
    "item": frozenset({"gained", "lost", "used"}),
    "injury": frozenset({"injured", "recovered"}),
    "goal": frozenset({"current"}),
    "ability": frozenset({"learned", "mastered", "used", "lost", "forgotten"}),
}
DEFAULT_CHANGE = {"realm": "current", "goal": "current", "location": "current"}
KIND_SYNONYMS = {
    "life_state": "life", "生死": "life", "location_state": "location", "位置": "location", "地点": "location",
    "境界": "realm", "等级": "realm", "身份": "realm", "物品": "item", "道具": "item", "伤势": "injury",
    "伤": "injury", "目标": "goal", "能力": "ability", "技能": "ability",
}
CHANGE_SYNONYMS = {
    "死亡": "dead", "死了": "dead", "身亡": "dead", "失踪": "missing", "复活": "revived", "生还": "survived",
    "幸存": "survived", "alive": "survived", "抵达": "arrived", "到达": "arrived", "离开": "left", "当前": "current",
    "所在": "current", "获得": "gained", "得到": "gained", "失去": "lost", "丢失": "lost", "使用": "used",
    "用掉": "used", "受伤": "injured", "痊愈": "recovered", "康复": "recovered", "学会": "learned", "掌握": "mastered",
    "遗忘": "forgotten", "忘记": "forgotten",
}
PROMISE_ACTIONS = ("plant", "advance", "resolve")
ACTION_SYNONYMS = {
    "埋下": "plant", "新埋": "plant", "埋设": "plant", "open": "plant", "推进": "advance", "提起": "advance",
    "progressing": "advance", "回收": "resolve", "解决": "resolve", "resolved": "resolve",
}
PROMISE_TYPES = frozenset({"foreshadow", "promise", "mystery", "conflict"})
PRIORITIES = frozenset({"low", "medium", "high", "critical"})
REASON_TYPES = frozenset({
    "rescue", "betrayal", "alliance", "misunderstanding", "confession", "rivalry", "respect", "hostility", "other",
})
RELATION_STATUSES = frozenset({"active", "broken", "past", "complicated"})
KNOWLEDGE_SOURCES = frozenset({"witnessed", "hearsay", "deduced", "document"})
VISIBILITY = frozenset({"public", "private", "secret"})
EVENT_TYPES = frozenset({
    "action", "reveal", "battle", "meeting", "departure", "arrival", "promise", "mystery", "conflict", "death", "other",
})
ANNOTATION_TYPES = ("hook", "foreshadow", "plot_point")
ANNOTATION_SYNONYMS = {"turn": "plot_point", "key": "plot_point", "转折": "plot_point", "情节点": "plot_point",
                       "钩子": "hook", "伏笔": "foreshadow"}
MIN_QUOTE_CHARS = 4

LIMITS = {
    "summary": 500, "end_state": 300, "story_time": 60, "locations": 6, "characters": 30, "state_changes": 40,
    "promises": 15, "relationships": 12, "knowledge": 12, "events": 8, "annotations": 10,
    "cast_characters": 30, "cast_organizations": 20,
}

FACTS_EXAMPLE = """{
  "summary": "林尘在慕家大堂被当众退婚，立下三年之约后离开慕家",
  "end_state": "林尘独自离开慕家，连夜赶往青峰山；慕雪留在慕家",
  "story_time": "入宗前一年·深秋",
  "locations": ["慕家大堂"],
  "characters": [{"name": "林尘", "change": "从隐忍转为决绝"}],
  "state_changes": [{"who": "林尘", "kind": "location", "value": "青峰山", "change": "arrived", "evidence": "林尘踏上青峰山"}],
  "promises": [{"action": "plant", "ref": "", "type": "promise", "title": "三年之约", "content": "林尘立誓三年后上门讨回公道",
                "owner": "林尘", "target": "慕雪", "priority": "critical", "deadline_chapter": null, "evidence": "三年之后"}],
  "relationships": [{"from": "林尘", "to": "慕雪", "delta": -40, "reason_type": "hostility", "reason": "当众退婚",
                     "status": "complicated", "evidence": "退了这门亲事"}],
  "knowledge": [{"who": "林尘", "key": "慕家态度", "content": "慕家公开切割婚约", "source": "witnessed", "secret": "public"}],
  "events": [{"title": "当众退婚", "what": "慕雪当众退婚", "cause": "林尘修为尽失", "effect": "两家决裂", "decision": "林尘立下三年之约",
              "type": "conflict", "actors": ["慕雪"], "targets": ["林尘"], "location": "慕家大堂", "time": "当日",
              "visibility": "public", "importance": 0.9, "evidence": "今日我便退了这门亲事"}],
  "end": true
}"""

CAST_EXAMPLE = """{
  "characters": [{"name": "慕雪", "gender": "女", "age": "十六岁", "role_type": "major", "personality": "高傲",
                  "appearance": null, "speech_style": "说话带刺，爱用反问", "background": "慕家大小姐，当众退婚",
                  "traits": ["高傲"], "affiliations": [{"org_name": "慕家", "position": "大小姐", "change": "active", "reason": null}]}],
  "organizations": [{"name": "慕家", "organization_type": "家族", "organization_purpose": null, "personality": "势利",
                     "appearance": null, "location": "青阳城", "known_members": ["慕雪"], "traits": [], "background": "退婚的一方"}],
  "annotations": [{"type": "hook", "title": "三年之约", "note": "全书主线起点", "quote": "三年之后，我必上门", "importance": 0.9}],
  "end": true
}"""


# ---------------- 基础清洗 ----------------

def _text(value: Any, limit: int) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    text = " ".join(str(value).split())
    if text.lower() in ("null", "none"):
        return ""
    return text[:limit]


def _key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _names(value: Any, limit: int = 8) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[、，,;；\s]+", value)
    out: list[str] = []
    for item in _list(value):
        name = _text(item, 30)
        if name and name not in out:
            out.append(name)
    return out[:limit]


def _float01(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _int(value: Any) -> Optional[int]:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number


def _enum(value: Any, allowed: Iterable[str], default: str, synonyms: Optional[dict[str, str]] = None) -> str:
    raw = _text(value, 30)
    mapped = (synonyms or {}).get(raw, raw).lower()
    return mapped if mapped in allowed else default


# ---------------- 解析 / 截断判断 ----------------

def _strip_fence(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    return re.sub(r"\s*```$", "", cleaned).strip()


def parse_model_json(text: str) -> tuple[Optional[dict], bool]:
    """返回 (对象, 是否修过)。严格解析失败才走 json-repair；拿不到对象返回 (None, True)。"""
    cleaned = _strip_fence(text)
    start = cleaned.find("{")
    if start < 0:
        return None, True
    body = cleaned[start:]
    end = body.rfind("}")
    candidate = re.sub(r",(\s*[}\]])", r"\1", body[: end + 1] if end >= 0 else body)
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj, False
    except (json.JSONDecodeError, ValueError):
        pass
    if _repair_json is None:
        return None, True
    try:
        repaired = _repair_json(body, return_objects=True)
    except Exception:  # noqa: BLE001 - 修不了就当解析失败
        return None, True
    return (repaired if isinstance(repaired, dict) else None), True


def looks_truncated(obj: Optional[dict], repaired: bool, finish_reason: Optional[str]) -> bool:
    """被 Max Tokens 截断：上游明说 length，或者靠修补才解析出来且缺结尾哨兵 end。"""
    if finish_reason == "length" or not isinstance(obj, dict):
        return True
    return bool(repaired) and obj.get("end") is not True


# ---------------- 分析 A：叙事事实 ----------------

def _state_change(item: Any) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    who = _text(item.get("who") or item.get("character_name") or item.get("name"), 30)
    kind = _text(item.get("kind") or item.get("type"), 20)
    kind = KIND_SYNONYMS.get(kind, kind.lower())
    if not who or kind not in STATE_CHANGES:
        return None
    raw_change = _text(item.get("change") or item.get("status"), 20)
    change = CHANGE_SYNONYMS.get(raw_change, raw_change.lower()) or DEFAULT_CHANGE.get(kind, "")
    if change not in STATE_CHANGES[kind]:
        return None
    value = _text(item.get("value"), 60)
    if kind != "life" and not value:
        return None
    return {"who": who, "kind": kind, "value": value if kind != "life" else "", "change": change,
            "evidence": _text(item.get("evidence"), 80)}


def _promise(item: Any) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    ref = _text(item.get("ref") or item.get("promise_ref"), 20).upper()
    raw_action = _text(item.get("action"), 20)
    action = ACTION_SYNONYMS.get(raw_action, raw_action.lower())
    if action not in PROMISE_ACTIONS:
        action = "advance" if ref else "plant"
    title = _text(item.get("title"), 40)
    content = _text(item.get("content"), 200)
    if action == "plant":
        if not (title or content):
            return None
        title, content, ref = title or content[:20], content or title, ""
    elif not (ref or title):
        return None
    return {
        "action": action, "ref": ref,
        "type": _enum(item.get("type") or item.get("promise_type"), PROMISE_TYPES, "foreshadow"),
        "title": title, "content": content,
        "owner": _text(item.get("owner"), 30), "target": _text(item.get("target"), 30),
        "priority": _enum(item.get("priority"), PRIORITIES, "medium"),
        "deadline_chapter": (lambda n: n if n and n > 0 else None)(_int(item.get("deadline_chapter"))),
        "evidence": _text(item.get("evidence"), 80),
        "promise_id": None,
    }


def _relationship(item: Any) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    a, b = _text(item.get("from"), 30), _text(item.get("to"), 30)
    delta = _int(item.get("delta"))
    if not a or not b or a == b or not delta:
        return None
    return {
        "from": a, "to": b, "delta": max(-100, min(100, delta)),
        "reason_type": _enum(item.get("reason_type"), REASON_TYPES, "other"),
        "reason": _text(item.get("reason"), 120),
        "status": _enum(item.get("status"), RELATION_STATUSES, ""),
        "evidence": _text(item.get("evidence"), 80),
    }


def _knowledge(item: Any) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    who, content = _text(item.get("who"), 30), _text(item.get("content"), 160)
    if not who or not content:
        return None
    return {
        "who": who, "key": _text(item.get("key"), 40) or content[:12], "content": content,
        "source": _enum(item.get("source"), KNOWLEDGE_SOURCES, "witnessed"),
        "secret": _enum(item.get("secret"), VISIBILITY, "private"),
        "confidence": _float01(item.get("confidence"), 1.0),
    }


def _event(item: Any) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    title, what = _text(item.get("title"), 40), _text(item.get("what") or item.get("description"), 200)
    if not (title or what):
        return None
    return {
        "title": title or what[:20], "what": what or title,
        "cause": _text(item.get("cause"), 120), "effect": _text(item.get("effect"), 120),
        "decision": _text(item.get("decision"), 120),
        "type": _enum(item.get("type"), EVENT_TYPES, "other"),
        "actors": _names(item.get("actors")), "targets": _names(item.get("targets")),
        "location": _text(item.get("location"), 60), "time": _text(item.get("time"), 60),
        "visibility": _enum(item.get("visibility"), VISIBILITY, "public"),
        "importance": _float01(item.get("importance"), 0.5),
        "evidence": _text(item.get("evidence"), 80),
    }


def _collect(items: Any, parse, limit: int) -> list[dict]:
    out = [parsed for parsed in (parse(item) for item in _list(items)) if parsed]
    return out[:limit]


def normalize_facts(raw: Any) -> dict:
    data = raw if isinstance(raw, dict) else {}
    characters: list[dict] = []
    seen: set[str] = set()
    for item in _list(data.get("characters")):
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name") or item.get("character_name"), 30)
        if name and name not in seen:
            seen.add(name)
            characters.append({"name": name, "change": _text(item.get("change"), 80)})
    locations: list[str] = []
    for item in _list(data.get("locations")):
        loc = _text(item, 40)
        if loc and loc not in locations:
            locations.append(loc)
    return {
        "summary": _text(data.get("summary"), LIMITS["summary"]),
        "end_state": _text(data.get("end_state"), LIMITS["end_state"]),
        "story_time": _text(data.get("story_time"), LIMITS["story_time"]),
        "locations": locations[: LIMITS["locations"]],
        "characters": characters[: LIMITS["characters"]],
        "state_changes": _collect(data.get("state_changes"), _state_change, LIMITS["state_changes"]),
        "promises": _collect(data.get("promises"), _promise, LIMITS["promises"]),
        "relationships": _collect(data.get("relationships"), _relationship, LIMITS["relationships"]),
        "knowledge": _collect(data.get("knowledge"), _knowledge, LIMITS["knowledge"]),
        "events": _collect(data.get("events"), _event, LIMITS["events"]),
    }


def facts_complete(facts: dict) -> bool:
    return bool((facts or {}).get("summary"))


def map_promise_refs(facts: dict, mapping: dict[str, str]) -> None:
    """模型回填的短编号（P1…）→ 真实 id；清单外的编号置空（宁可不动也不能错关别的伏笔）。"""
    real_ids = set(mapping.values())
    for item in facts.get("promises") or []:
        if item.get("action") == "plant":
            item["promise_id"] = None
            continue
        ref = (item.get("ref") or "").upper()
        item["promise_id"] = mapping.get(ref) or (item.get("ref") if item.get("ref") in real_ids else None)


def facts_to_settlement(facts: dict) -> dict:
    """叙事事实 → 结算服务认的 analysis 字典（键名沿用旧版，结算 / 审计逻辑不用改）。"""
    signals: dict[str, list[dict]] = {
        "life_state_changes": [], "ability_updates": [], "location_updates": [], "realm_updates": [],
        "item_updates": [], "injury_updates": [], "goal_updates": [],
    }
    for s in facts.get("state_changes") or []:
        who, value, change, evidence = s["who"], s["value"], s["change"], s.get("evidence", "")
        kind = s["kind"]
        if kind == "life":
            signals["life_state_changes"].append({"character_name": who, "status": change, "evidence": evidence})
        elif kind == "ability":
            signals["ability_updates"].append({"character_name": who, "ability_name": value, "change": change, "evidence": evidence})
        elif kind == "location":
            signals["location_updates"].append({"character_name": who, "location": value, "status": change, "evidence": evidence})
        elif kind == "realm":
            signals["realm_updates"].append({"character_name": who, "realm": value, "evidence": evidence})
        elif kind == "item":
            signals["item_updates"].append({"character_name": who, "item": value, "change": change, "evidence": evidence})
        elif kind == "injury":
            signals["injury_updates"].append({"character_name": who, "injury": value, "status": change, "evidence": evidence})
        elif kind == "goal":
            signals["goal_updates"].append({"character_name": who, "goal": value, "evidence": evidence})

    promises = []
    for p in facts.get("promises") or []:
        status = {"plant": "open", "advance": "progressing", "resolve": "resolved"}[p["action"]]
        promises.append({
            "action": p["action"], "promise_type": p["type"], "title": p["title"], "content": p["content"],
            "owner_character_name": p["owner"], "target_character_name": p["target"], "priority": p["priority"],
            "status": status, "deadline_chapter": p["deadline_chapter"] if p["action"] == "plant" else None,
            "evidence": p["evidence"],
            "resolves_promise_id": p.get("promise_id") if p["action"] == "resolve" else None,
            "advances_promise_id": p.get("promise_id") if p["action"] == "advance" else None,
        })

    events = facts.get("events") or []
    return {
        "summary": facts.get("summary", ""),
        "end_state": facts.get("end_state", ""),
        "story_time": facts.get("story_time", ""),
        "continuity_signals": signals,
        "narrative_promises": promises,
        "timeline_events": [{
            "event_type": e["type"], "title": e["title"], "description": e["what"], "location": e["location"],
            "time_marker": e["time"], "actor_names": e["actors"], "target_names": e["targets"],
            "public_visibility": e["visibility"], "evidence": e["evidence"],
        } for e in events],
        "causal_links": [{
            "cause": e["cause"], "event": e["what"], "effect": e["effect"], "decision": e["decision"],
            "actor_names": e["actors"], "target_names": e["targets"], "importance": e["importance"],
            "reversible": False, "evidence": e["evidence"],
        } for e in events if e["cause"] or e["effect"]],
        "relationship_deltas": [{
            "from_character_name": r["from"], "to_character_name": r["to"], "delta": r["delta"],
            "reason_type": r["reason_type"], "reason": r["reason"], "new_status": r["status"], "evidence": r["evidence"],
        } for r in facts.get("relationships") or []],
        "knowledge_changes": [{
            "character_name": k["who"], "info_key": k["key"], "content": k["content"], "source": k["source"],
            "confidence": k["confidence"], "secret_level": k["secret"],
        } for k in facts.get("knowledge") or []],
        "character_states": [{"character_name": c["name"], "state_after": c["change"]} for c in facts.get("characters") or []],
        "scenes": [{"location": loc} for loc in facts.get("locations") or []],
    }


# ---------------- 分析 B：人物与标注 ----------------

_CAST_CHARACTER_KEYS = ("gender", "age", "role_type", "personality", "appearance", "speech_style", "background")
_CAST_ORG_KEYS = ("organization_type", "organization_purpose", "personality", "appearance", "location", "background")


def _cast_character(item: Any) -> Optional[dict]:
    if not isinstance(item, dict) or not _text(item.get("name"), 30):
        return None
    out: dict[str, Any] = {"name": _text(item.get("name"), 30)}
    for key in _CAST_CHARACTER_KEYS:
        value = _text(item.get(key), 200)
        out[key] = value or None
    out["traits"] = [t for t in (_text(x, 20) for x in _list(item.get("traits"))) if t][:8]
    affiliations = []
    for aff in _list(item.get("affiliations")):
        if isinstance(aff, dict) and _text(aff.get("org_name"), 40):
            affiliations.append({
                "org_name": _text(aff.get("org_name"), 40), "position": _text(aff.get("position"), 30) or None,
                "change": _enum(aff.get("change"), ("joined", "left", "promoted", "expelled", "active"), "active"),
                "reason": _text(aff.get("reason"), 80) or None,
            })
    out["affiliations"] = affiliations[:6]
    return out


def _cast_org(item: Any) -> Optional[dict]:
    if not isinstance(item, dict) or not _text(item.get("name"), 40):
        return None
    out: dict[str, Any] = {"name": _text(item.get("name"), 40)}
    for key in _CAST_ORG_KEYS:
        value = _text(item.get(key), 200)
        out[key] = value or None
    out["known_members"] = _names(item.get("known_members"), 20)
    out["traits"] = [t for t in (_text(x, 20) for x in _list(item.get("traits"))) if t][:8]
    return out


def _annotation(item: Any) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    raw_type = _text(item.get("type"), 20)
    kind = ANNOTATION_SYNONYMS.get(raw_type, raw_type.lower())
    quote = str(item.get("quote") or "").strip()[:80]
    if kind not in ANNOTATION_TYPES or len(quote) < MIN_QUOTE_CHARS:
        return None
    return {
        "type": kind, "title": _text(item.get("title"), 20) or quote[:10], "note": _text(item.get("note"), 80),
        "quote": quote, "importance": _float01(item.get("importance"), 0.6),
    }


def normalize_cast(raw: Any) -> dict:
    data = raw if isinstance(raw, dict) else {}
    return {
        "characters": _collect(data.get("characters"), _cast_character, LIMITS["cast_characters"]),
        "organizations": _collect(data.get("organizations"), _cast_org, LIMITS["cast_organizations"]),
        "annotations": _collect(data.get("annotations"), _annotation, LIMITS["annotations"]),
    }


# ---------------- 长章分块与合并 ----------------

def split_for_analysis(text: str, limit: int = 12_000, target: int = 9_000) -> list[str]:
    """不超过 limit 的章整章分析；更长的在段落边界切成约 target 字的段（单段过长才硬切）。"""
    text = text or ""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in text.split("\n"):
        while len(paragraph) > limit:
            if current:
                parts.append("\n".join(current))
                current, size = [], 0
            parts.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        add = len(paragraph) + (1 if current else 0)
        if current and size + add > target:
            parts.append("\n".join(current))
            current, size, add = [], 0, len(paragraph)
        current.append(paragraph)
        size += add
    if current:
        parts.append("\n".join(current))
    return parts


def _dedupe(items: Iterable[dict]) -> list[dict]:
    out, seen = [], set()
    for item in items:
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if marker not in seen:
            seen.add(marker)
            out.append(item)
    return out


def merge_facts(parts: list[dict]) -> dict:
    """长章分段抽取的结果合并：摘要拼接、章末状态 / 故事时间取最后给出的、人物按名合并、同名新坑只记一次、同编号回收压过推进。"""
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return parts[0] if parts else normalize_facts({})
    merged = normalize_facts({})
    merged["summary"] = " ".join(p["summary"] for p in parts if p.get("summary"))[: LIMITS["summary"]]
    for key in ("end_state", "story_time"):
        merged[key] = next((p[key] for p in reversed(parts) if p.get(key)), "")
    for p in parts:
        for loc in p.get("locations") or []:
            if loc not in merged["locations"]:
                merged["locations"].append(loc)
    by_name: dict[str, dict] = {}
    for p in parts:
        for c in p.get("characters") or []:
            if c["name"] not in by_name:
                by_name[c["name"]] = dict(c)
                merged["characters"].append(by_name[c["name"]])
            elif c.get("change"):
                prev = by_name[c["name"]]
                prev["change"] = f"{prev['change']}；{c['change']}"[:80] if prev.get("change") else c["change"]
    promises: list[dict] = []
    index: dict[tuple, int] = {}
    rank = {"advance": 1, "resolve": 2}
    for p in parts:
        for item in p.get("promises") or []:
            key = ("plant", _key(item["title"])) if item["action"] == "plant" else ("ref", item["ref"] or _key(item["title"]))
            if key not in index:
                index[key] = len(promises)
                promises.append(item)
            elif item["action"] != "plant" and rank.get(item["action"], 0) > rank.get(promises[index[key]]["action"], 0):
                promises[index[key]] = item
    merged["promises"] = promises[: LIMITS["promises"]]
    for key in ("state_changes", "relationships", "knowledge"):
        merged[key] = _dedupe(x for p in parts for x in p.get(key) or [])[: LIMITS[key]]
    events = [e for p in parts for e in p.get("events") or []]
    if len(events) > LIMITS["events"]:
        keep = sorted(range(len(events)), key=lambda i: -events[i]["importance"])[: LIMITS["events"]]
        events = [events[i] for i in sorted(keep)]
    merged["events"] = events
    return merged


def merge_cast(parts: list[dict]) -> dict:
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return parts[0] if parts else normalize_cast({})
    out = normalize_cast({})
    for key, limit in (("characters", LIMITS["cast_characters"]), ("organizations", LIMITS["cast_organizations"])):
        by_name: dict[str, dict] = {}
        for p in parts:
            for item in p.get(key) or []:
                prev = by_name.get(item["name"])
                if prev is None:
                    by_name[item["name"]] = dict(item)
                    out[key].append(by_name[item["name"]])
                    continue
                for field, value in item.items():
                    if value and not prev.get(field):
                        prev[field] = value
        out[key] = out[key][:limit]
    out["annotations"] = [a for p in parts for a in p.get("annotations") or []][: LIMITS["annotations"]]
    return out
