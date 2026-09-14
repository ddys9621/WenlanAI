"""拆书 V5 领域类型：拆书卡（ChapterCard）与情节单元（StoryArc）。

LLM 输出一律经 from_llm 归一化：枚举落词表、数值夹范围、字符串截长、列表去空去重。
持久化：ChapterCard → book_dissect_chapter_facts.fact_json；StoryArc → book_dissect_story_arcs.arc_json。
设计：agent-docs/features/book_dissect_v5_design.md §2
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

FUNCTION_TAGS = (
    "开局立足", "日常代入", "信息差铺垫", "危机铺垫", "拉扯试探", "爽点兑现", "打脸",
    "升级突破", "战斗", "善后收获", "转场换地图", "信息揭露", "伏笔埋设", "伏笔回收",
    "情感推进", "支线推进", "过渡",
)
HOOK_TYPES = ("悬念", "危机", "反转", "新谜团", "信息揭露", "期待", "无")
PACES = ("快", "中", "慢")
PAYOFF_TYPES = (
    "打脸", "扮猪吃虎", "收获机缘", "反差揭底", "护人", "绝境反杀", "以弱胜强",
    "反转揭示", "情感兑现", "规则破局", "无强爽点",
)
CHAPTER_ROLES = ("intro", "build", "payoff", "aftermath", "transition")

OUTLINE_MAX = 800
HOOK_TEXT_MAX = 60
SHORT_MAX = 200
LONG_MAX = 1200
LIST_MAX_ITEMS = 12


def _s(value: Any, limit: int) -> str:
    text = " ".join(str(value).split()) if value is not None else ""
    return text[:limit]


def _str_list(value: Any, *, limit: int = SHORT_MAX, max_items: int = LIST_MAX_ITEMS) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _s(item, limit)
        if text and text not in out:
            out.append(text)
        if len(out) >= max_items:
            break
    return out


def _int_in(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _enum(value: Any, vocab: tuple[str, ...], default: str, *, fuzzy: bool = True) -> str:
    """精确命中优先；fuzzy 时再取第一个作为子串出现在文本里的词表项；再否则 default。

    单字词表（如 pace 快/中/慢）必须 fuzzy=False：「极快」「不快」子串命中会得出错误档位。
    """
    text = _s(value, 40)
    if text in vocab:
        return text
    if fuzzy:
        for v in vocab:
            if v != "无" and v in text:
                return v
    return default


def _tags(value: Any) -> list[str]:
    out: list[str] = []
    for raw in _str_list(value, limit=40, max_items=20):
        hit = raw if raw in FUNCTION_TAGS else next((t for t in FUNCTION_TAGS if t in raw), None)
        if hit and hit not in out:
            out.append(hit)
    return out


@dataclass
class ChapterCard:
    chapter_number: int
    title: str = ""
    outline: str = ""
    function_tags: list[str] = field(default_factory=list)
    pace: str = "中"
    tension: int = 3
    emotion_tone: str = ""
    ending_hook_type: str = "无"
    ending_hook_text: str = ""
    payoff_points: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    characters: list[str] = field(default_factory=list)
    protagonist_delta: str = "无"
    new_settings: list[str] = field(default_factory=list)
    word_count: int = 0
    truncated_input: bool = False

    def has_content(self) -> bool:
        return bool(self.outline.strip())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChapterCard":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_llm(cls, item: dict[str, Any], *, chapter_number: int, title: str,
                 word_count: int, truncated: bool) -> "ChapterCard":
        return cls(
            chapter_number=chapter_number,
            title=_s(item.get("title"), 160) or title,
            outline=_s(item.get("outline"), OUTLINE_MAX),
            function_tags=_tags(item.get("function_tags")),
            pace=_enum(item.get("pace"), PACES, "中", fuzzy=False),
            tension=_int_in(item.get("tension"), 1, 5, 3),
            emotion_tone=_s(item.get("emotion_tone"), 80),
            ending_hook_type=_enum(item.get("ending_hook_type"), HOOK_TYPES, "无"),
            ending_hook_text=_s(item.get("ending_hook_text"), HOOK_TEXT_MAX),
            payoff_points=_str_list(item.get("payoff_points"), limit=120, max_items=6),
            highlights=_str_list(item.get("highlights"), limit=120, max_items=6),
            characters=_str_list(item.get("characters"), limit=30, max_items=30),
            protagonist_delta=_s(item.get("protagonist_delta"), SHORT_MAX) or "无",
            new_settings=_str_list(item.get("new_settings"), limit=120, max_items=10),
            word_count=word_count,
            truncated_input=truncated,
        )


def normalize_chapter_roles(roles: Any, chapters: list[int], peak: Optional[int]) -> dict[str, str]:
    """保留 LLM 给的合法位置值，缺失的按规则补：1 章=payoff；2 章=build+payoff；
    ≥3 章：峰值章（无则取中间偏后）payoff，峰值前第一章 intro、其余 build，峰值后全部 aftermath。"""
    keys = [str(c) for c in chapters]
    given: dict[str, str] = {}
    if isinstance(roles, dict):
        given = {str(k).strip(): str(v).strip() for k, v in roles.items()
                 if str(k).strip() in keys and str(v).strip() in CHAPTER_ROLES}
    n = len(keys)
    if n == 0:
        return {}
    if n == 1:
        default = {keys[0]: "payoff"}
    elif n == 2:
        default = {keys[0]: "build", keys[1]: "payoff"}
    else:
        peak_key = str(peak) if peak is not None and str(peak) in keys else keys[(n - 1) * 2 // 3]
        pk = keys.index(peak_key)
        default = {}
        for i, k in enumerate(keys):
            if i == pk:
                default[k] = "payoff"
            elif i < pk:
                default[k] = "intro" if i == 0 else "build"
            else:
                default[k] = "aftermath"
    return {k: given.get(k, default[k]) for k in keys}


@dataclass
class StoryArc:
    arc_index: int = 0
    start_chapter: int = 0
    end_chapter: int = 0
    title: str = ""
    function: str = ""
    boundary_reason: str = ""
    structure: str = ""
    protagonist_chain: str = ""
    emotion_curve: str = ""
    payoff: str = ""
    payoff_type: str = "无强爽点"
    golden_finger_usage: str = "无"
    character_changes: str = ""
    gains_costs: str = ""
    foreshadowing: str = ""
    chapter_roles: dict[str, str] = field(default_factory=dict)
    tension_peak_chapter: Optional[int] = None
    origin: str = "llm"                      # llm / fallback

    @property
    def chapters(self) -> list[int]:
        if self.chapter_roles:
            return sorted(int(k) for k in self.chapter_roles)
        return list(range(self.start_chapter, self.end_chapter + 1))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StoryArc":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_llm(cls, item: dict[str, Any], *, chapters: list[int]) -> "StoryArc":
        """chapters 由调用方按窗口位置算好（采样模式下章号不连续也能用）。"""
        peak_raw = _int_in(item.get("tension_peak_chapter"), min(chapters), max(chapters), -1)
        peak = peak_raw if peak_raw in chapters else None
        return cls(
            start_chapter=chapters[0],
            end_chapter=chapters[-1],
            title=_s(item.get("title"), 60) or f"第{chapters[0]}-{chapters[-1]}章",
            function=_s(item.get("function"), SHORT_MAX),
            boundary_reason=_s(item.get("boundary_reason"), SHORT_MAX),
            structure=_s(item.get("structure"), LONG_MAX),
            protagonist_chain=_s(item.get("protagonist_chain"), LONG_MAX),
            emotion_curve=_s(item.get("emotion_curve"), SHORT_MAX * 2),
            payoff=_s(item.get("payoff"), SHORT_MAX * 2),
            payoff_type=_enum(item.get("payoff_type"), PAYOFF_TYPES, "无强爽点"),
            golden_finger_usage=_s(item.get("golden_finger_usage"), SHORT_MAX) or "无",
            character_changes=_s(item.get("character_changes"), SHORT_MAX * 2),
            gains_costs=_s(item.get("gains_costs"), SHORT_MAX * 2),
            foreshadowing=_s(item.get("foreshadowing"), SHORT_MAX * 2),
            chapter_roles=normalize_chapter_roles(item.get("chapter_roles"), chapters, peak),
            tension_peak_chapter=peak,
            origin="llm",
        )
