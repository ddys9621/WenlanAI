"""知识库条目类型：类型 → (显示名, 层, 排序基数)。

层：index 导读 / fact 事实（保留原名、带章号）/ method 方法（可迁移）/ style 文风。
排序基数让一本书的条目按「导读 → 全书 → 方法 → 文风 → 片段 → 分卷 → 剧情单元 → 章卡」排列，同类再按序号。
"""
from __future__ import annotations

ENTRY_TYPES: dict[str, tuple[str, str, int]] = {
    "guide": ("导读", "index", 0),
    "synopsis": ("全书骨架", "fact", 10),
    "characters": ("人物功能谱", "method", 20),
    "methodology": ("写法手册", "method", 30),
    "structure": ("结构统计", "method", 40),
    "style": ("文风", "style", 50),
    "excerpt": ("典型片段", "style", 100),
    "volume": ("分卷", "fact", 1_000),
    "arc": ("剧情单元", "fact", 100_000),
    "chapter": ("章卡", "fact", 1_000_000),
}


def entry_label(entry_type: str) -> str:
    return ENTRY_TYPES.get(entry_type, (entry_type, "fact", 0))[0]


def entry_layer(entry_type: str) -> str:
    return ENTRY_TYPES.get(entry_type, (entry_type, "fact", 0))[1]


def entry_sort_order(entry_type: str, index: int = 0) -> int:
    return ENTRY_TYPES.get(entry_type, (entry_type, "fact", 9_000_000))[2] + index
