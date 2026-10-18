"""作者可改的提示词模板（project_prompts）：变量写成 {英文名}，只替换登记过的名字。

不用 str.format：作者写的 {主角}、示例里的 JSON 花括号都要原样保留，写错一个括号也不该让生成报错。
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

_VARIABLE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def render_vars(template: str, values: Mapping[str, Any]) -> str:
    return _VARIABLE.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template or "")


def template_variables(template: str) -> list[str]:
    return list(dict.fromkeys(_VARIABLE.findall(template or "")))


def unknown_variables(template: str, allowed: Iterable[str]) -> list[str]:
    known = set(allowed)
    return [name for name in template_variables(template) if name not in known]
