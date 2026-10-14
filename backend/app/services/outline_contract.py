"""章纲契约：生成正文所依据的章纲字段，以及它们的指纹。

指纹只算有值的字段：以后给章纲加新字段（旧章纲为空）不会让所有旧指纹失效。
候选稿记录生成时的指纹（生成期间章纲被改 → 标记）；章节记录采用时的指纹（之后章纲被改 → 列表显示「章纲已改」）。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

OUTLINE_CONTRACT_FIELDS: tuple[str, ...] = (
    "title", "scene", "pov", "plot_points", "summary", "key_events", "characters_involved",
    "narrative_tasks", "target_word_count", "bridge_position", "position_constraints",
    "entry_state", "exit_state", "forbidden",
)


def forbidden_items(raw: Any) -> list[str]:
    """章纲禁止事项（JSON 列表文本）→ 去空的字符串列表。"""
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return [str(raw).strip()] if str(raw).strip() else []
    if isinstance(data, list):
        return [str(x).strip() for x in data if str(x).strip()]
    return [str(data).strip()] if str(data).strip() else []


def _normalized(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\r\n", "\n").strip()
    return value


def outline_fingerprint(outline: Any) -> Optional[str]:
    if outline is None:
        return None
    payload = {}
    for field in OUTLINE_CONTRACT_FIELDS:
        value = _normalized(getattr(outline, field, None))
        if value not in (None, ""):
            payload[field] = value
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
