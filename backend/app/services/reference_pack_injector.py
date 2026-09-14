"""V3 R5+ 通用拆书参考资料注入服务（Reference Pack Injector）

职责：
1. 加载项目挂载的参考包，按强度档位组装 5 维度 + corpus 的可注入文本块
2. 对外提供两种粒度的 API：
   - 高层：``build_reference_block(...)`` 一次性返回 ReferenceBlock（含 user_segment / system_segment）
   - 低层：``resolve_packs / resolve_dimensions / resolve_strength``（细粒度，供 imitation_service 复用）
3. **本服务不关心 prompt 拼装上下文**（项目状态 / 作者意图等由调用方负责），保持纯净以便接入：
   故事大纲 / 章纲 / 章节正文 / 场景 / 章节重生成 / 角色 / 关系 / 世界观 / 灵感 等所有生成场景。

历史背景：
- 本模块从 ``imitation_service.py`` 中抽出（V3 R5 一键仿写）。原模块依旧持有"项目状态 +
  作者意图"等仿写专用逻辑，同时通过实例委托复用本模块的资料组装能力。
- ``imitation_service`` 的对外 API（``ImitationService.resolve_*`` / ``assemble_prompt``）
  保持 100% 兼容，下游 R3-R7 各场景按需直接调用本模块。

设计文档：@/agent-docs/features/dissect_to_creation_pipeline.md §4
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.project_reference_pack import ProjectReferencePack
from app.models.reference_pack import ReferencePack
from app.services.ai_service import AIService
from app.services.generation_trace import trace_reference
from app.services.imitation_corpus import (
    ImitationCorpusRetriever,
    format_corpus_prompt,
)
from app.services.reference_pack.policy_tables import V5_DIMENSIONS
from app.services.reference_pack.v5_compressor import compress_v5

logger = get_logger(__name__)


# ============================================================
# 强度配置（与 imitation_service 历史行为完全一致）
# ============================================================


@dataclass(frozen=True)
class StrengthProfile:
    """强度→各维度的预算（字符上限/语料 top-k）。

    字段命名贴 ReferencePack 的 JSON 维度，便于裁剪函数直接索引。
    V5 包各维度直接复用 v5_compressor 的三档文本（light/medium/deep 与 name 对齐），
    这里的 *_chars 只约束老包（pipeline_version < 5）的通用序列化。
    """

    name: str  # light / medium / deep
    methodology_chars: int
    structure_chars: int
    style_chars: int
    synopsis_chars: int
    corpus_top_k: int
    corpus_chars_per_item: int  # 每条语料摘要上限
    bridges_chars: int = 900
    character_archive_chars: int = 900

    @classmethod
    def for_strength(cls, strength: str) -> "StrengthProfile":
        s = (strength or "medium").lower()
        if s == "light":
            return cls(
                name="light", methodology_chars=600, structure_chars=600, style_chars=400, synopsis_chars=400,
                corpus_top_k=1, corpus_chars_per_item=300, bridges_chars=400, character_archive_chars=400,
            )
        if s == "deep":
            return cls(
                name="deep", methodology_chars=3500, structure_chars=3500, style_chars=1200, synopsis_chars=1000,
                corpus_top_k=3, corpus_chars_per_item=600, bridges_chars=1800, character_archive_chars=1800,
            )
        return cls(
            name="medium", methodology_chars=1500, structure_chars=1500, style_chars=800, synopsis_chars=700,
            corpus_top_k=2, corpus_chars_per_item=450, bridges_chars=900, character_archive_chars=900,
        )


# ============================================================
# 数据载体
# ============================================================


@dataclass
class _ResolvedPack:
    """挂载关系 + 参考包合并后的"本次实际使用快照"。"""

    pack_id: str
    source_book_title: str
    task_id: str
    methodology: Optional[Dict[str, Any]]
    style: Optional[Dict[str, Any]]
    structure: Optional[Dict[str, Any]]
    generated_dimensions: List[str]
    default_dimensions: List[str]  # 来自挂载关联
    default_strength: str  # 来自挂载关联
    synopsis: Optional[Dict[str, Any]] = None
    bridges: Optional[Dict[str, Any]] = None
    character_archive: Optional[Dict[str, Any]] = None
    # 2 = V2-V4 老包（各维度走通用序列化）；5 = V5（走 v5_compressor）
    pipeline_version: int = 2

    @property
    def is_v5(self) -> bool:
        return self.pipeline_version >= 5

@dataclass
class ReferenceBlock:
    """一次组装的可注入参考资料块。

    - ``user_segment`` / ``system_segment``：开箱即用的 prompt 片段（已 join）
    - ``user_sections``：各维度未 join 的细粒度列表（供调用方按需自行排版/计字数）
    - ``used_*`` / ``debug_meta``：供前端展示或日志统计
    """

    user_segment: str
    system_segment: str
    user_sections: List[str] = field(default_factory=list)
    used_packs: List[Dict[str, Any]] = field(default_factory=list)
    used_dimensions: List[str] = field(default_factory=list)
    used_strength: str = "medium"
    debug_meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.user_segment and not self.system_segment


def trace_reference_block(block: "ReferenceBlock", *, scene: str) -> None:
    """把本次实际生效的参考包上报给过程追踪（前端弹窗"参考了什么"面板）；没绑定追踪时 no-op。"""
    if block.is_empty:
        return
    trace_reference(
        "reference_pack",
        "拆书参考包",
        [
            {"title": f"《{p['source_book_title']}》", "detail": "、".join(p["dimensions"]) or "—"}
            for p in block.used_packs
        ],
        scene=scene,
        strength=block.used_strength,
        dimensions=list(block.used_dimensions),
        chars=len(block.user_segment) + len(block.system_segment),
    )


# ============================================================
# 工具函数（搬自 imitation_service；imitation_service 通过 re-export 保留）
# ============================================================


def _safe_json(raw: Optional[str], default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        logger.warning("[Injector] JSON 解析失败，已退回默认值：%r", raw[:80] if raw else None)
        return default


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    text = text.strip()
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _dedup_keep_order(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _serialize_dimension(data: Dict[str, Any]) -> str:
    """把 5 个 tab 的 dict 序列化成 LLM 可读自然文本。

    通用策略：
    - 若 dict 里含 prompt_content / content / text / summary 字段 → 优先取
    - 否则 fallback 为对 dict 进行可读化（key: value 折行）
    """
    if not isinstance(data, dict):
        return _truncate(str(data), 2000)
    for key in ("prompt_content", "content", "text", "markdown", "summary"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    lines: List[str] = []
    for k, v in data.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float)):
            lines.append(f"{k}: {v}")
        elif isinstance(v, list):
            preview = "; ".join(str(x) for x in v[:8])
            lines.append(f"{k}: {preview}")
        elif isinstance(v, dict):
            sub = "; ".join(f"{kk}={vv}" for kk, vv in list(v.items())[:6])
            lines.append(f"{k}: {sub}")
    return "\n".join(lines)


def _serialize_style(style: Dict[str, Any]) -> str:
    """style tab 的特化处理：prompt_content 优先，其次 traits/句式特征。"""
    if not isinstance(style, dict):
        return _truncate(str(style), 1000)
    if isinstance(style.get("prompt_content"), str) and style["prompt_content"].strip():
        return style["prompt_content"].strip()
    parts: List[str] = []
    if isinstance(style.get("name"), str):
        parts.append(f"风格：{style['name']}")
    if isinstance(style.get("description"), str):
        parts.append(f"描述：{style['description']}")
    traits = style.get("traits") or style.get("features")
    if isinstance(traits, list):
        parts.append("特征：" + "；".join(str(t) for t in traits[:8]))
    return "\n".join(parts)


# ============================================================
# 主服务：ReferencePackInjector
# ============================================================


class ReferencePackInjector:
    """统一的拆书参考资料注入服务。所有生成场景共享。

    使用模式：
    1. **高层（推荐给 R3-R7 各场景）**：
       ``await injector.build_reference_block(db, project_id, scene=...)``
       一次拿到 ReferenceBlock（可直接拼到 prompt）。
    2. **低层（imitation_service 用）**：
       分步调用 ``resolve_packs / resolve_dimensions / resolve_strength``
       自行决定如何拼装。

    线程/连接模型：实例本身无状态，可全局复用；DB session 由调用方传入。
    """

    # 当用户未给 explicit、且 pack 的 default_dimensions 也为空时的兜底维度
    # V3.2：默认包含 synopsis，让新拆任务自动获得 Story Bible 层全局引导；
    # 老 pack 没生成 synopsis 时由 valid 过滤自动跳过，向后兼容。
    DEFAULT_DIMENSION_FALLBACK: Tuple[str, ...] = (
        "synopsis", "methodology", "style", "corpus"
    )

    def __init__(self, ai_service: Optional[AIService] = None):
        # ai_service 可选：当前 corpus retriever 不依赖；保留为参数以便未来向量库升级
        self.ai_service = ai_service

    # ----------------------------------------------------------------
    # 输入归一化：参考包 / 维度 / 强度
    # ----------------------------------------------------------------

    async def resolve_packs(
        self,
        db: AsyncSession,
        project_id: str,
        pack_ids: Optional[List[str]],
    ) -> List[_ResolvedPack]:
        """加载本项目挂载的参考包，按 pack_ids 过滤；返回就绪的快照列表。

        - pack_ids 为 None/空 → 取项目所有挂载
        - pack_ids 显式给出 → 必须每个都在挂载列表内（任一不在则抛 ValueError）
        - 状态 generating/failed 的 pack 自动剔除（partial 允许，由维度并集裁掉空 tab）
        """
        result = await db.execute(
            select(ProjectReferencePack, ReferencePack)
            .join(ReferencePack, ProjectReferencePack.pack_id == ReferencePack.id)
            .where(ProjectReferencePack.project_id == project_id)
        )
        rows = result.all()
        attached_map: Dict[str, Tuple[ProjectReferencePack, ReferencePack]] = {
            pack.id: (link, pack) for link, pack in rows
        }

        if pack_ids is not None:
            requested = [pid for pid in pack_ids if pid]
            if not requested:
                raise ValueError("pack_ids 为空，请至少选择一个参考包")
            unknown = [pid for pid in requested if pid not in attached_map]
            if unknown:
                raise ValueError(f"以下参考包未挂载到项目，无法使用：{unknown}")
            iter_ids = requested
        else:
            if not attached_map:
                raise ValueError("项目未挂载任何参考包，无法使用一键仿写")
            iter_ids = list(attached_map.keys())

        resolved: List[_ResolvedPack] = []
        for pid in iter_ids:
            link, pack = attached_map[pid]
            if pack.status not in ("ready", "partial"):
                logger.info(
                    "[Injector] 跳过未就绪参考包 pack=%s status=%s", pid, pack.status
                )
                continue
            resolved.append(
                _ResolvedPack(
                    pack_id=pack.id,
                    source_book_title=pack.source_book_title,
                    task_id=pack.task_id,
                    methodology=_safe_json(pack.methodology_json, None),
                    style=_safe_json(pack.style_json, None),
                    structure=_safe_json(pack.structure_json, None),
                    synopsis=_safe_json(pack.synopsis_json, None),
                    bridges=_safe_json(pack.bridges_json, None),
                    character_archive=_safe_json(pack.character_archive_json, None),
                    generated_dimensions=_safe_json(pack.generated_dimensions, []) or [],
                    default_dimensions=_safe_json(link.default_dimensions, []) or [],
                    default_strength=link.default_strength or "medium",
                    pipeline_version=int(getattr(pack, "pipeline_version", None) or 2),
                )
            )

        if not resolved:
            raise ValueError("所选参考包均未就绪（generating/failed），请稍后再试或重新生成")
        return resolved

    def resolve_dimensions(
        self,
        packs: List[_ResolvedPack],
        explicit: Optional[List[str]],
        fallback: Optional[Tuple[str, ...]] = None,
    ) -> List[str]:
        """归一化最终生效的维度清单。

        - explicit 显式 → 仅保留"至少在一个 pack 中已生成"或 == 'corpus'
        - explicit 省略 → 取所选 pack 的 default_dimensions 取并集；空则用 fallback；
          fallback 也无效则兜底到 ['corpus']
        """
        generated_union: set[str] = set()
        for p in packs:
            generated_union.update(p.generated_dimensions or [])
        # corpus 永远可用（拆书卡 / 章节事实表，未挂载到 generated_dimensions）；
        # 已删除的维度（archetypes / worldbuilding / entities / relations / events）即使老包 generated 里有也不再生效
        valid = (generated_union & set(V5_DIMENSIONS)) | {"corpus"}

        if explicit is not None:
            chosen = [d for d in explicit if d in valid]
            if not chosen:
                chosen = ["corpus"]
            return _dedup_keep_order(chosen)

        merged: List[str] = []
        for p in packs:
            for d in p.default_dimensions:
                merged.append(d)
        merged = [d for d in merged if d in valid]
        if not merged:
            fb = fallback if fallback is not None else self.DEFAULT_DIMENSION_FALLBACK
            merged = [d for d in fb if d in valid]
        if not merged:
            merged = ["corpus"]
        return _dedup_keep_order(merged)

    def resolve_strength(
        self,
        packs: List[_ResolvedPack],
        explicit: Optional[str],
    ) -> str:
        """归一化最终强度。显式给定优先；否则取所选 pack 中最深者。"""
        if explicit:
            return explicit
        rank = {"light": 0, "medium": 1, "deep": 2}
        max_rank = -1
        winner = "medium"
        for p in packs:
            r = rank.get(p.default_strength, 1)
            if r > max_rank:
                max_rank = r
                winner = p.default_strength
        return winner or "medium"

    # ----------------------------------------------------------------
    # 维度组装（6 维 + corpus）
    # V5 包：各维度直接复用 v5_compressor 的三档文本（与装配单 / 预压缩字段同一套格式）
    # 老包（pipeline_version < 5）：保留原通用序列化，保证存量参考包继续可用
    # ----------------------------------------------------------------

    def _format_v5_sections(
        self, packs: List[_ResolvedPack], *, attr: str, section_title: str, profile: StrengthProfile,
    ) -> str:
        """V5 包某维度的合并段落：每本书一段 compress_v5 文本。"""
        bodies: List[str] = []
        for p in packs:
            data = getattr(p, attr, None)
            if not p.is_v5 or not isinstance(data, dict):
                continue
            text = compress_v5(attr, data, profile.name)
            if text:
                bodies.append(f"《{p.source_book_title}》：\n{text}")
        if not bodies:
            return ""
        return f"[{section_title}]\n" + "\n\n".join(bodies)

    def _legacy_packs(self, packs: List[_ResolvedPack]) -> List[_ResolvedPack]:
        return [p for p in packs if not p.is_v5]

    def _format_methodology(
        self, packs: List[_ResolvedPack], profile: StrengthProfile
    ) -> str:
        """写法手册：金手指/钩子/打脸/升级/爽点（V3 五键形状，新老包同一格式）。"""
        return self._format_dimension_section(
            packs,
            attr="methodology",
            section_title="参考方法论（原书写作手法，作为参考而非复刻）",
            chars_budget=profile.methodology_chars,
        )

    def _format_structure(
        self, packs: List[_ResolvedPack], profile: StrengthProfile
    ) -> str:
        v5 = self._format_v5_sections(
            packs, attr="structure", profile=profile,
            section_title="参考结构统计（原书节奏 / 章末钩子 / 爽点密度 / 张力曲线，仅作节奏参考）",
        )
        legacy = self._format_dimension_section(
            self._legacy_packs(packs),
            attr="structure",
            section_title="参考结构手法（开篇钩 / 中段冲突 / 结尾钩）",
            chars_budget=profile.structure_chars,
        )
        return "\n\n".join(x for x in (v5, legacy) if x)

    def _format_bridges(
        self, packs: List[_ResolvedPack], profile: StrengthProfile
    ) -> str:
        """桥段库：V5 情节单元（结构 / 行动链 / 爽点）；老包沿用 V4.1 桥段类型分布的抽象描述。"""
        v5 = self._format_v5_sections(
            packs, attr="bridges", profile=profile,
            section_title="参考情节单元（原书桥段的结构 / 行动链 / 兑现方式，学写法不复刻具体情节）",
        )
        bodies: List[str] = []
        for p in self._legacy_packs(packs):
            data = p.bridges
            if not isinstance(data, dict):
                continue
            lines: List[str] = []
            total = data.get("total_bridges_detected")
            if total is not None:
                lines.append(f"- 全书识别桥段：{total} 个")
            bridge_types = data.get("bridge_types") or []
            if isinstance(bridge_types, list) and bridge_types:
                type_bits = [
                    f"{bt.get('type', '?')}×{bt.get('count', '?')}" for bt in bridge_types[:6] if isinstance(bt, dict)
                ]
                if type_bits:
                    lines.append(f"- 桥段类型分布：{', '.join(type_bits)}")
            if lines:
                bodies.append(_truncate(f"《{p.source_book_title}》：\n" + "\n".join(lines), profile.bridges_chars))
        legacy = (
            "[参考桥段范本（原书桥段的类型/节奏，仅作结构参考，禁止复刻具体情节）]\n" + "\n\n".join(bodies)
            if bodies else ""
        )
        return "\n\n".join(x for x in (v5, legacy) if x)

    def _format_character_archive(
        self, packs: List[_ResolvedPack], profile: StrengthProfile
    ) -> str:
        """人物功能谱：V5 主角 / 盟友 / 反派 / 功能位；老包沿用 V4.1 角色档案的手法抽取。"""
        v5 = self._format_v5_sections(
            packs, attr="character_archive", profile=profile,
            section_title="参考人物功能谱（原书每个人物在结构里承担什么功能、作者怎么用，禁止照搬原书角色）",
        )
        SECTION_MAP = (
            ("protagonist_archetypes", "主角塑造"),
            ("antagonist_progression", "反派递进"),
            ("support_character_techniques", "配角手法"),
        )
        bodies: List[str] = []
        for p in self._legacy_packs(packs):
            data = p.character_archive
            if not isinstance(data, dict):
                continue
            lines: List[str] = []
            for key, label in SECTION_MAP:
                for item in (data.get(key) or [])[:2]:
                    if not isinstance(item, dict):
                        continue
                    bits = [
                        f"{k}={str(v).strip()}" for k, v in item.items()
                        if isinstance(v, str) and v.strip() and k != "name"
                    ][:3]
                    if bits:
                        lines.append(f"- 【{label}】{'；'.join(bits)}")
            if lines:
                bodies.append(_truncate(f"《{p.source_book_title}》：\n" + "\n".join(lines), profile.character_archive_chars))
        legacy = (
            "[参考角色档案手法（如何引出/递进/赋予功能，仅作塑造方法参考，禁止照搬原书角色）]\n" + "\n\n".join(bodies)
            if bodies else ""
        )
        return "\n\n".join(x for x in (v5, legacy) if x)

    def _format_synopsis(
        self, packs: List[_ResolvedPack], profile: StrengthProfile
    ) -> str:
        """全书骨架：V5 骨架（题材 / 一句话 / 大矛盾 / 金手指 / 阶段 / 爽点 / 成长体系）；老包沿用 V3.2 类型骨架。

        Hierarchical RAG 最佳实践：Story Bible 放最前，让 LLM 先看到全局再看具体手法。
        """
        v5 = self._format_v5_sections(
            packs, attr="synopsis", profile=profile,
            section_title="参考全书骨架（原书的题材 / 前提 / 大矛盾 / 阶段 / 成长体系，仅供方向参考）",
        )
        LABEL_MAP = (
            ("genre_tag", "题材"),
            ("core_premise", "故事前提"),
            ("golden_finger_concept", "金手指"),
            ("power_system_overview", "力量体系"),
            ("central_conflict", "核心冲突"),
            ("ultimate_goal", "终极目标"),
            ("selling_points", "卖点"),
            ("target_audience_signals", "目标受众"),
        )
        bodies: List[str] = []
        for p in self._legacy_packs(packs):
            if not p.synopsis:
                continue
            lines: List[str] = []
            for key, label in LABEL_MAP:
                v = p.synopsis.get(key)
                if not v:
                    continue
                v_text = " / ".join(str(x).strip() for x in v if x) if isinstance(v, list) else str(v).strip()
                if v_text:
                    lines.append(f"- {label}：{v_text}")
            if lines:
                bodies.append(_truncate(f"《{p.source_book_title}》：\n" + "\n".join(lines), profile.synopsis_chars))
        legacy = (
            "[参考故事类型骨架（仅供方向参考，禁止复刻原书具体人名/地名/物品名）]\n" + "\n\n".join(bodies)
            if bodies else ""
        )
        return "\n\n".join(x for x in (v5, legacy) if x)

    def _format_dimension_section(
        self,
        packs: List[_ResolvedPack],
        *,
        attr: str,
        section_title: str,
        chars_budget: int,
    ) -> str:
        """通用：从多 pack 取同一个维度并合并。"""
        bodies: List[str] = []
        for p in packs:
            data = getattr(p, attr, None)
            if not data:
                continue
            text = _serialize_dimension(data)
            text = _truncate(text, chars_budget)
            bodies.append(f"《{p.source_book_title}》：\n{text}")
        if not bodies:
            return ""
        joined = "\n\n".join(bodies)
        return f"[{section_title}]\n{joined}"

    async def _format_corpus(
        self,
        db: AsyncSession,
        packs: List[_ResolvedPack],
        anchor_query: str,
        profile: StrengthProfile,
    ) -> str:
        """灵感语料：BM25 + 1-hop 关系扩展（V3.1.3）。

        anchor_query 为检索锚点（如作者本次意图、当前章纲、剧情卡内容等）。
        没有 anchor 则跳过——corpus 是定向检索，无锚点没意义。
        """
        if not anchor_query or not anchor_query.strip():
            return ""
        task_ids = [p.task_id for p in packs]
        if not task_ids:
            return ""

        retriever = ImitationCorpusRetriever()
        # allow_fallback=False：检索无相关命中时返回空，
        # 不再按章节序强塞最早章节（无关内容只会干扰生成）
        hits = await retriever.retrieve(
            db=db,
            task_ids=task_ids,
            user_intent=anchor_query,
            top_k=profile.corpus_top_k,
            allow_fallback=False,
        )
        if not hits:
            return ""

        title_map = {p.task_id: p.source_book_title for p in packs}
        return format_corpus_prompt(
            hits,
            title_map=title_map,
            chars_per_item=profile.corpus_chars_per_item,
        )

    def _format_style_system_prompt(
        self,
        packs: List[_ResolvedPack],
        profile: StrengthProfile,
    ) -> str:
        """文风维度注入到 system prompt（影响 tone/句式而非具体内容）。

        V5 包：v5_compressor 三档（含量化指标 / 例句）；老包：prompt_content 优先的通用序列化。
        """
        bodies: List[str] = []
        for p in packs:
            if not p.style:
                continue
            if p.is_v5:
                text = compress_v5("style", p.style, profile.name)
            else:
                text = _truncate(_serialize_style(p.style), profile.style_chars)
            if not text:
                continue
            bodies.append(f"参考《{p.source_book_title}》的文风指引：\n{text}")
        if not bodies:
            return ""
        return "\n\n".join(bodies)

    # ----------------------------------------------------------------
    # 高层 API：一次组装完整 ReferenceBlock
    # ----------------------------------------------------------------

    async def build_reference_block(
        self,
        db: AsyncSession,
        project_id: str,
        *,
        scene: str = "generic",
        dimensions: Optional[List[str]] = None,
        strength: Optional[str] = None,
        pack_ids: Optional[List[str]] = None,
        anchor_query: Optional[str] = None,
        fallback_dimensions: Optional[Tuple[str, ...]] = None,
    ) -> ReferenceBlock:
        """组装可注入的参考资料块。

        Args:
            scene: 场景标识（"story_outline" / "chapter_outline" / "chapter_content" / ...），
                仅用于日志/telemetry，不影响行为。
            dimensions: 显式覆盖维度列表；None 则取已挂载 packs 的 default_dimensions 并集。
            strength: 显式覆盖强度；None 则取所选 pack 中最深者。
            pack_ids: 显式覆盖参考包列表；None 则取项目所有挂载的 ready/partial pack。
            anchor_query: 用于 corpus 检索的查询锚点（章纲/正文场景必传，否则 corpus 维度跳过）。
            fallback_dimensions: 当 default_dimensions 也为空时的兜底；不传用类常量。

        如项目未挂载参考包或 pack_ids 全部未就绪，会抛 ValueError；
        调用方按需 try/except 转化为"跳过参考"的优雅降级。
        """
        # P2-2：粗粒度耗时统计（分段记录，便于后续发现瓶颈）
        t_start = time.perf_counter()

        packs = await self.resolve_packs(db, project_id, pack_ids)
        t_packs = time.perf_counter()

        used_dimensions = self.resolve_dimensions(packs, dimensions, fallback_dimensions)
        used_strength = self.resolve_strength(packs, strength)
        profile = StrengthProfile.for_strength(used_strength)

        # ---- user_segment ----
        # 拼装顺序遵循 Hierarchical RAG 最佳实践：全书骨架（粗）→ 写法手册 / 结构统计（中）→
        # 情节单元 / 人物功能谱（中）→ 拆书卡（细）。
        # produced_dimensions 记录"实际产出非空段落"的维度，
        # 保证 used_dimensions 对前端/日志如实（选了但内容为空的维度不再谎报）。
        ref_sections: List[str] = []
        produced_dimensions: List[str] = []

        def _emit(dim: str, text: str) -> None:
            if text:
                ref_sections.append(text)
                produced_dimensions.append(dim)

        if "synopsis" in used_dimensions:
            _emit("synopsis", self._format_synopsis(packs, profile))
        if "methodology" in used_dimensions:
            _emit("methodology", self._format_methodology(packs, profile))
        if "structure" in used_dimensions:
            _emit("structure", self._format_structure(packs, profile))
        if "bridges" in used_dimensions:
            _emit("bridges", self._format_bridges(packs, profile))
        if "character_archive" in used_dimensions:
            _emit("character_archive", self._format_character_archive(packs, profile))
        t_5dim = time.perf_counter()

        if "corpus" in used_dimensions:
            _emit(
                "corpus",
                await self._format_corpus(db, packs, anchor_query or "", profile),
            )
        t_corpus = time.perf_counter()

        user_segment = "\n\n".join(ref_sections)

        # ---- system_segment（仅 style）----
        system_segment = ""
        if "style" in used_dimensions:
            system_segment = self._format_style_system_prompt(packs, profile)
            if system_segment:
                produced_dimensions.append("style")

        # used_dimensions 收敛为"实际产出"的维度（如实反馈）
        used_dimensions = _dedup_keep_order(produced_dimensions)

        # ---- meta ----
        used_packs_meta = self._build_used_packs_meta(packs, used_dimensions)
        t_end = time.perf_counter()

        # 分段耗时（毫秒）：packs 加载 / 5 维组装 / corpus 检索 / 总耗时
        ms_packs = int((t_packs - t_start) * 1000)
        ms_5dim = int((t_5dim - t_packs) * 1000)
        ms_corpus = int((t_corpus - t_5dim) * 1000)
        ms_total = int((t_end - t_start) * 1000)

        debug_meta = {
            "scene": scene,
            "pack_count": len(packs),
            "user_segment_chars": len(user_segment),
            "system_segment_chars": len(system_segment),
            "section_count": len(ref_sections),
            # P2-2 性能统计（便于前端展示或日志分析）
            "timings_ms": {
                "packs": ms_packs,
                "dims_5": ms_5dim,
                "corpus": ms_corpus,
                "total": ms_total,
            },
        }
        logger.info(
            "[Injector] scene=%s project=%s strength=%s dims=%s "
            "user=%d sys=%d | timings packs=%dms dims=%dms corpus=%dms total=%dms",
            scene,
            project_id,
            used_strength,
            used_dimensions,
            len(user_segment),
            len(system_segment),
            ms_packs,
            ms_5dim,
            ms_corpus,
            ms_total,
        )
        # 超阈值告警（协助尽早发现未来性能问题）
        if ms_total > 1500:
            logger.warning(
                "[Injector] 组装耗时较高 scene=%s total=%dms packs=%d dims=%s "
                "（建议检查 corpus 检索/DB 连接/pack 挂载量）",
                scene, ms_total, len(packs), used_dimensions,
            )

        block = ReferenceBlock(
            user_segment=user_segment,
            system_segment=system_segment,
            user_sections=ref_sections,
            used_packs=used_packs_meta,
            used_dimensions=used_dimensions,
            used_strength=used_strength,
            debug_meta=debug_meta,
        )
        trace_reference_block(block, scene=scene)
        return block

    @staticmethod
    def _build_used_packs_meta(
        packs: List[_ResolvedPack], used_dimensions: List[str]
    ) -> List[Dict[str, Any]]:
        """生成 used_packs 元数据：每个 pack 在本次实际生效的维度。"""
        out: List[Dict[str, Any]] = []
        for p in packs:
            pack_dims = [
                d for d in used_dimensions
                if d == "corpus" or getattr(p, d, None)
            ]
            out.append(
                {
                    "pack_id": p.pack_id,
                    "source_book_title": p.source_book_title,
                    "dimensions": _dedup_keep_order(pack_dims),
                }
            )
        return out
