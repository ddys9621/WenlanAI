"""故事大纲（StoryOutline.content）核心字段解析。JSON 与纯文本两种格式。"""
from __future__ import annotations

import json
from typing import Any

_KEYS_STR = ("premise", "main_plot", "golden_finger", "power_system", "ultimate_goal", "opening_hook")
_KEYS_LIST = ("selling_points", "main_tropes")


def parse_story_outline_fields(content: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {k: "" for k in _KEYS_STR}
    result.update({k: [] for k in _KEYS_LIST})
    if not content:
        return result
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        result["premise"] = content
        return result
    if not isinstance(data, dict):
        result["premise"] = content
        return result
    for k in _KEYS_STR:
        result[k] = str(data.get(k) or "")
    for k in _KEYS_LIST:
        v = data.get(k) or []
        result[k] = list(v) if isinstance(v, list) else [str(v)]
    return result
