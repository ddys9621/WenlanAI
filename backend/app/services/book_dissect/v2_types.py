"""拆书 V2: 领域类型定义

定义 V2 流水线各阶段共享的 dataclass 与枚举。

业务层与持久层分离原则：
- 这里的 dataclass 是流水线内的"运行时数据结构"
- DB 持久化使用 SQLAlchemy 模型（app/models/book_dissect_*.py）
- 序列化进出 DB 时通过 to_dict / from_dict 转换

参见设计文档：agent-docs/features/book_dissect_v2_design.md §4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------

class V2Phase(str, Enum):
    """V2 流水线阶段。任务 BookDissectTask.extraction_phase 字段使用。"""

    SPLITTING = "splitting"          # 章节切分（V1 已有，复用）
    SCANNING = "scanning"            # 实体预扫描（纯正则）
    DICTIONARY = "dictionary"        # LLM 候选词分类
    EXTRACTING = "extracting"        # 逐章 LLM 抽取 ChapterFact
    AGGREGATING = "aggregating"      # 全书聚合
    SYNTHESIZING = "synthesizing"    # 网文专有产物（项目骨架 / 文风样本）
    DONE = "done"


class EntityType(str, Enum):
    """实体类型枚举。与 BookDissectEntity.entity_type 对应。"""

    PERSON = "person"
    LOCATION = "location"
    ITEM = "item"
    ORG = "org"
    CONCEPT = "concept"
    UNKNOWN = "unknown"
    REJECTED = "rejected"


class Importance(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RelationCategory(str, Enum):
    FAMILY = "family"
    INTIMATE = "intimate"
    HIERARCHICAL = "hierarchical"
    SOCIAL = "social"
    HOSTILE = "hostile"
    OTHER = "other"


class CandidateSource(str, Enum):
    """实体扫描器候选词的来源标记。"""

    NGRAM = "ngram"
    DIALOGUE = "dialogue"
    NAMING = "naming"
    SUFFIX = "suffix"
    TITLE = "title"


# ---------------------------------------------------------------------------
# 实体扫描产物
# ---------------------------------------------------------------------------

@dataclass
class EntityCandidate:
    """EntityScanner 产出的候选词。"""

    name: str
    frequency: int
    sources: list[str] = field(default_factory=list)        # CandidateSource 字符串集合
    sample_context: Optional[str] = None
    suggested_type: Optional[str] = None                    # 后缀规则给出的类型提示

    def add_source(self, src: str) -> None:
        if src not in self.sources:
            self.sources.append(src)


# ---------------------------------------------------------------------------
# 字典分类产物
# ---------------------------------------------------------------------------

@dataclass
class DictionaryEntry:
    """LLM 分类后的字典条目。"""

    name: str
    entity_type: str        # EntityType 字符串
    aliases: list[str] = field(default_factory=list)
    confidence: str = "medium"      # high / medium / low
    frequency: int = 0
    sources: list[str] = field(default_factory=list)
    sample_context: Optional[str] = None


# ---------------------------------------------------------------------------
# 章节抽取产物（ChapterFact）
# ---------------------------------------------------------------------------

@dataclass
class CharacterFact:
    name: str
    new_aliases: list[str] = field(default_factory=list)
    role_hint: Optional[str] = None         # protagonist / supporting / ...
    appearance: Optional[str] = None
    abilities_gained: list[str] = field(default_factory=list)
    locations_in_chapter: list[str] = field(default_factory=list)
    evidence: Optional[str] = None


@dataclass
class RelationFact:
    person_a: str
    person_b: str
    relation_type: str                      # 归一化前 LLM 原始输出
    evidence: Optional[str] = None


@dataclass
class LocationFact:
    name: str
    type: Optional[str] = None              # 城市 / 山 / 洞府 / ...
    parent: Optional[str] = None
    peers: list[str] = field(default_factory=list)
    role: Optional[str] = None              # setting / referenced / boundary
    description: Optional[str] = None
    evidence: Optional[str] = None


@dataclass
class EventFact:
    event_type: str                         # meet / depart / fight / breakthrough / death / … / other（LLM 原始输出）
    title: str
    description: Optional[str] = None
    actors: list[str] = field(default_factory=list)
    location: Optional[str] = None
    importance: str = "medium"              # Importance 字符串
    evidence: Optional[str] = None


@dataclass
class ItemFact:
    name: str
    type: Optional[str] = None              # 武器 / 丹药 / 功法 / 法宝 / ...
    owner: Optional[str] = None
    action: str = "mentioned"               # obtained / lost / used / forged / mentioned
    description: Optional[str] = None
    evidence: Optional[str] = None


@dataclass
class OrgFact:
    name: str
    action: str = "mentioned"               # introduced / joined / left / expanded / destroyed / mentioned
    description: Optional[str] = None
    members_mentioned: list[str] = field(default_factory=list)


@dataclass
class ConceptFact:
    name: str
    type: Optional[str] = None              # 境界 / 术语 / 世界规则
    description: Optional[str] = None
    evidence: Optional[str] = None


@dataclass
class ChapterFact:
    """单章 LLM 抽取产物。对应 DB 模型 BookDissectChapterFact.fact_json。"""

    chapter_number: int
    chapter_title: Optional[str] = None
    summary: Optional[str] = None
    characters: list[CharacterFact] = field(default_factory=list)
    relationships: list[RelationFact] = field(default_factory=list)
    locations: list[LocationFact] = field(default_factory=list)
    events: list[EventFact] = field(default_factory=list)
    item_events: list[ItemFact] = field(default_factory=list)
    org_events: list[OrgFact] = field(default_factory=list)
    new_concepts: list[ConceptFact] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 聚合产物（全书级）
# ---------------------------------------------------------------------------

@dataclass
class AliasGroup:
    """Union-Find 合并后的别名组。"""

    canonical: str
    members: list[str] = field(default_factory=list)


@dataclass
class EntityProfile:
    """全书聚合的实体档案（含跨章节统计）。"""

    canonical_name: str
    entity_type: str
    aliases: list[str] = field(default_factory=list)
    first_chapter: Optional[int] = None
    last_chapter: Optional[int] = None
    appearance_count: int = 0
    role_type: Optional[str] = None         # 仅 person
    parent_name: Optional[str] = None       # 地点 / 组织层级
    profile_extras: dict = field(default_factory=dict)      # 类型特定字段
