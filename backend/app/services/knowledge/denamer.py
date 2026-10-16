"""去名：人名换成功能位占位（【主角】【导师】【对手·卷反派】…），给仿写注入用；纯规则，不调模型。

名单 = 人物功能谱（主角 / 盟友 / 对手）+ 拆书卡里出场最多的其余人物（【人物1】…）。
长名先替换（「林七七」不会被「林七」拆开）；不足 2 字的名字不替换，误伤太大。
拆书卡的出场人物里常混进职业 / 称号（如书名《牧龙师》里的「牧龙师」），所以出现在 protected 文本（书名）里的
高频名不替换；人物功能谱里明确的人物照常替换。
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional, Sequence

from app.services.book_dissect.v5_types import ChapterCard

EXTRA_NAME_LIMIT = 30
MIN_NAME_LEN = 2
_ROLE_SPLIT = re.compile(r"[/／、，,；;｜|（(]")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _role(value: Any, default: str) -> str:
    head = _ROLE_SPLIT.split(_clean(value), maxsplit=1)[0].strip()
    return head[:8] or default


def build_name_map(characters: Optional[dict], cards: Sequence[ChapterCard],
                   protected: Sequence[str] = ()) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: Counter[str] = Counter()

    def put(name: Any, label: str) -> None:
        text = _clean(name)
        if len(text) < MIN_NAME_LEN or text in mapping:
            return
        used[label] += 1
        mapping[text] = f"【{label}】" if used[label] == 1 else f"【{label}{used[label]}】"

    data = characters if isinstance(characters, dict) else {}
    protagonist = data.get("protagonist")
    if isinstance(protagonist, dict):
        put(protagonist.get("name"), "主角")
    for ally in data.get("allies") or []:
        if isinstance(ally, dict):
            put(ally.get("name"), _role(ally.get("function_role"), "配角"))
    for foe in data.get("antagonists") or []:
        if isinstance(foe, dict):
            tier = _role(foe.get("tier"), "")
            put(foe.get("name"), f"对手·{tier}" if tier else "对手")
    frequency = Counter(_clean(n) for card in cards for n in card.characters)
    extra = 0
    for name, _ in frequency.most_common():
        if extra >= EXTRA_NAME_LIMIT:
            break
        if len(name) >= MIN_NAME_LEN and name not in mapping and not any(name in text for text in protected if text):
            extra += 1
            put(name, f"人物{extra}")
    return mapping


class Denamer:
    """按名单替换；名单为空时原样返回。"""

    def __init__(self, mapping: dict[str, str]):
        self.mapping = dict(mapping)
        names = sorted(self.mapping, key=len, reverse=True)
        self._pattern = re.compile("|".join(re.escape(n) for n in names)) if names else None

    def __call__(self, text: Any) -> str:
        value = str(text or "")
        if not value or self._pattern is None:
            return value
        return self._pattern.sub(lambda m: self.mapping[m.group(0)], value)
