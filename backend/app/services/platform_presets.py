"""平台预设（纯数据）：不同平台的单章字数、章末钩子默认值与正文写法差异。

- 起点（付费）：单章 3000-4000，设定自洽，章末断章拉订阅；兑现章允许"爽完即收"
- 番茄 / 七猫（免费）：单章 2000-2500，开头三行进冲突，章末必须有钩子（靠钩子留人）
- 晋江（女频）：情感线为主，人物关系与潜台词，章末停在情绪 / 关系变化点
写法提示进正文 system 提示词；字数只作为新建项目 / 未指定时的默认值，不覆盖用户显式设置。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PlatformPreset:
    key: str
    name: str
    chapter_words: int
    block: str


PLATFORM_PRESETS: dict[str, PlatformPreset] = {
    "qidian": PlatformPreset(
        key="qidian", name="起点（付费连载）", chapter_words=3500,
        block=(
            "【平台写法：起点付费连载】\n"
            "- 单章 3000-4000 字，一章完成一个小目标；章末给读者\"必须看下一章\"的理由（付费章靠断章拉订阅）\n"
            "- 可以有稍长的叙述交代设定，但单段不超过 5 行；爽点要有铺垫、有旁人反应、有实际收获\n"
            "- 升级体系、数值、境界前后严格一致，读者会较真"
        ),
    ),
    "fanqie": PlatformPreset(
        key="fanqie", name="番茄（免费阅读）", chapter_words=2200,
        block=(
            "【平台写法：番茄免费阅读】\n"
            "- 单章 2000-2500 字，开头三行内就要有冲突或悬念，节奏比付费文更快\n"
            "- 段落更短（一两句一段）、对话更多，少设定说明，信息用对话和动作带出\n"
            "- 每章结尾都要有钩子（免费平台靠章末钩子留人），爽点直给、密度高"
        ),
    ),
    "jinjiang": PlatformPreset(
        key="jinjiang", name="晋江（女频）", chapter_words=3000,
        block=(
            "【平台写法：晋江女频】\n"
            "- 情感线是主线：人物关系的细微变化、对话里的潜台词比打斗更重要\n"
            "- 人物立体，配角有自己的动机；文笔可以细腻一点，但仍是白话，不堆辞藻\n"
            "- 感情推进有逻辑，误会必须有信息差支撑；章末停在情绪或关系的变化点"
        ),
    ),
    "qimao": PlatformPreset(
        key="qimao", name="七猫（免费阅读）", chapter_words=2500,
        block=(
            "【平台写法：七猫免费阅读】\n"
            "- 单章 2000-3000 字，节奏快、爽点直给，开篇三行进冲突\n"
            "- 语言通俗，段落短，对话推动剧情；少写景、少大段心理独白\n"
            "- 章末必须留钩子"
        ),
    ),
}


def resolve_platform(key: Optional[str]) -> Optional[PlatformPreset]:
    return PLATFORM_PRESETS.get((key or "").strip().lower())


def platform_block(key: Optional[str]) -> str:
    preset = resolve_platform(key)
    return preset.block if preset else ""


def default_chapter_words(key: Optional[str], fallback: int = 3000) -> int:
    preset = resolve_platform(key)
    return preset.chapter_words if preset else fallback


def normalize_longform_settings(data: dict) -> dict:
    """新建项目时的长篇设置（向导 / 创建接口共用）：只收合法的平台预设。"""
    platform = (data.get("platform_preset") or "").strip().lower()
    return {"platform_preset": platform} if platform in PLATFORM_PRESETS else {}
