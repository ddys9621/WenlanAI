"""V4.4 K5 三档预压缩 generator（通用算法）。

设计目标：
- 把 ReferencePack 的 6 维 _json 字段（methodology / style / structure /
  archetypes / worldbuilding / synopsis）按 light/medium/deep 三档生成精炼文本
- light: ~130 chars（仅核心要点）→ 适用于 S 档模型 + 边缘场景
- medium: ~400 chars（要点+精简 tips）→ 适用于 M/L 档模型 + 主流场景
- deep: ~1000 chars（完整子模式 + 完整 tips）→ 适用于 XL 档模型 + 章节正文

通用算法（基于观察 6 维 JSON 共同结构）：
- 顶层 dict 含若干"子模式 key"（如 golden_finger_pattern / opening_hook_pattern）
- 每个子模式是 dict，含若干字段 + writing_tips（核心建议，80-180 字）
- light 取每个 writing_tips 第一句
- medium 取每个子模式核心字段 + tips 截短
- deep 完整展开

调用方式：
- compress_dimension(json_text, dimension, level) → str
- 或：DimensionCompressor.compress_pack(pack) → 24 字段批量生成

性能：
- 纯字符串处理 + 简单字典遍历，几毫秒级
- 可选缓存到 ReferencePack 的 24 个预压缩字段
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 6 个支持预压缩的维度（corpus 不预压缩，依赖动态 BM25），与 ReferencePack.DIMENSIONS_WITH_PRECOMPRESSION 对齐
# V5：archetypes / worldbuilding 随实体图谱抽取一并删除
COMPRESSIBLE_DIMENSIONS = (
    "methodology",
    "style",
    "structure",
    "synopsis",
    "bridges",
    "character_archive",
)

# 三档配额（字符数，比 token 大约 1.5 倍）
LEVEL_CHAR_BUDGET = {
    "light": 300,   # ≤200 token，留些缓冲
    "medium": 900,  # ≤600 token
    "deep": 2200,   # ≤1500 token
}

# 子模式 key 中文化映射（让压缩输出更可读）
HUMANIZE_KEY = {
    # methodology
    "golden_finger_pattern": "金手指",
    "opening_hook_pattern": "开篇钩",
    "facepunch_rhythm": "打脸节奏",
    "power_progression": "升级路线",
    "highlight_density": "爽点密度",
    # structure
    "opening_pattern": "开篇模式",
    "midpoint_conflict_escalation": "中段冲突升级",
    "ending_hook_pattern": "章末钩",
    # archetypes
    "protagonist_archetype": "主角塑造",
    "supporting_archetype": "配角塑造",
    "antagonist_archetype": "反派塑造",
    # worldbuilding
    "era_design": "时代设计",
    "location_hierarchy": "地点层级",
    "rule_balance": "规则平衡",
    "atmosphere_building": "氛围营造",
    # synopsis
    "genre": "类型",
    "premise": "核心设定",
    "golden_finger": "金手指设定",
    "power_system": "力量体系",
    "world_type": "世界类型",
    # style 较特殊（无子模式，直接 prompt_content）
    "prompt_content": "文风指令",
    "name": "风格名",
    "traits": "特征",
    "description": "描述",
    # V4.1 bridges
    "bridge_types": "桥段类型分布",
    "rhythm_stats": "节奏指标",
    "golden_finger_diversity": "金手指多样性",
    "total_bridges_detected": "桥段总数",
    "standard_bridges": "标准桥段数",
    "variant_bridges": "变体桥段数",
    # V4.1 character_archive
    "protagonist_archetypes": "主角范式",
    "antagonist_progression": "反派演进",
    "support_character_techniques": "配角手法",
}


# V5 有专用算法的维度；methodology 形状与 V3 相同，V5 包也走通用算法
V5_SPECIALIZED_DIMENSIONS = ("bridges", "synopsis", "style", "character_archive", "structure")


def compress_dimension(
    json_text: Optional[str], dimension: str, level: str, *, pipeline_version: int = 2,
) -> str:
    """三档压缩单个维度。

    Args:
        json_text: ReferencePack.<dim>_json 字段原值（JSON 字符串或 None）
        dimension: 维度名（必须在 COMPRESSIBLE_DIMENSIONS 中）
        level: 'light' | 'medium' | 'deep'
        pipeline_version: 参考包流水线版本；≥5 且维度有专用算法时走 v5_compressor，否则通用算法

    Returns:
        压缩后的可读文本（≤ LEVEL_CHAR_BUDGET[level] 字符）。
        空输入 / 无效 JSON → 空串。
    """
    if not json_text:
        return ""
    if level not in LEVEL_CHAR_BUDGET:
        logger.warning(f"compress_dimension: 未知 level={level}")
        return ""
    try:
        data = json.loads(json_text) if isinstance(json_text, str) else json_text
    except (json.JSONDecodeError, TypeError):
        # 不是有效 JSON → 按纯文本截断
        return _truncate_plain(str(json_text), LEVEL_CHAR_BUDGET[level])
    if not data:
        return ""

    if pipeline_version >= 5 and dimension in V5_SPECIALIZED_DIMENSIONS and isinstance(data, dict):
        from app.services.reference_pack.v5_compressor import compress_v5
        return compress_v5(dimension, data, level)

    # style 维度特殊：通常是单个 dict 含 prompt_content（无子模式层级）
    if dimension == "style":
        return _compress_style_dim(data, level)

    # 其他维度：统一走通用算法
    if isinstance(data, dict):
        return _compress_generic_dim(data, level, dimension)
    if isinstance(data, list):
        return _compress_list_dim(data, level)
    return _truncate_plain(str(data), LEVEL_CHAR_BUDGET[level])


# ============================================================
# 私有：通用压缩算法
# ============================================================


def _compress_generic_dim(data: dict, level: str, dimension: str) -> str:
    """通用算法：每个子模式按 level 抽取不同详细度。"""
    budget = LEVEL_CHAR_BUDGET[level]
    lines: list[str] = []

    for sub_key, sub_val in data.items():
        if not isinstance(sub_val, dict):
            # 顶层标量字段（如 synopsis 的 genre/premise 字符串）
            line = _format_scalar_field(sub_key, sub_val, level)
            if line:
                lines.append(line)
            continue

        sub_label = HUMANIZE_KEY.get(sub_key, sub_key)

        if level == "light":
            # 只取 writing_tips 第一句
            tip = sub_val.get("writing_tips", "")
            if tip:
                first = _first_sentence(str(tip))
                lines.append(f"- {sub_label}：{first}")
            elif sub_val:
                # 没 tips 取第一个有内容的字段
                for v in sub_val.values():
                    if isinstance(v, (str, int, float)) and str(v).strip():
                        lines.append(f"- {sub_label}：{str(v)[:60]}")
                        break

        elif level == "medium":
            # 核心 1-2 个字段 + tips 截短到 100 字符
            key_fields = _extract_key_fields(sub_val, max_count=2, max_len=80)
            tip = str(sub_val.get("writing_tips", ""))[:120]
            block = f"【{sub_label}】"
            if key_fields:
                block += " " + " / ".join(key_fields)
            if tip:
                block += f"\n  ▸ {tip}"
            lines.append(block)

        elif level == "deep":
            # 全部子字段 + 完整 tips
            block_lines = [f"【{sub_label}】"]
            for k, v in sub_val.items():
                if k == "writing_tips":
                    continue
                formatted = _format_field(k, v, max_len=200)
                if formatted:
                    block_lines.append(f"  {formatted}")
            tip = sub_val.get("writing_tips", "")
            if tip:
                block_lines.append(f"  ▸ 建议: {str(tip)[:300]}")
            lines.append("\n".join(block_lines))

    # 拼接 + 全局预算控制
    text = "\n".join(lines)
    if len(text) > budget:
        text = text[:budget].rsplit("\n", 1)[0] + "\n…（截断）"
    return text


def _compress_style_dim(data: Any, level: str) -> str:
    """style 维度特殊算法（数据结构往往是 {name, prompt_content, description, traits}）。"""
    budget = LEVEL_CHAR_BUDGET[level]
    if not isinstance(data, dict):
        return _truncate_plain(str(data), budget)
    name = data.get("name", "")
    prompt_content = str(data.get("prompt_content", ""))
    description = str(data.get("description", ""))
    traits = data.get("traits", [])

    if level == "light":
        # 仅 name + description 第一句
        if description:
            text = f"风格：{name} — {_first_sentence(description)}"
        else:
            text = f"风格：{name or '未知'}"
    elif level == "medium":
        parts = [f"【风格名】{name}"] if name else []
        if description:
            parts.append(f"【描述】{description[:200]}")
        if isinstance(traits, list) and traits:
            parts.append(f"【特征】{', '.join(str(t)[:30] for t in traits[:5])}")
        if prompt_content:
            parts.append(f"【核心指令】{prompt_content[:300]}")
        text = "\n".join(parts)
    else:  # deep
        parts = []
        if name:
            parts.append(f"【风格名】{name}")
        if description:
            parts.append(f"【描述】{description[:400]}")
        if isinstance(traits, list) and traits:
            parts.append(f"【特征】{', '.join(str(t) for t in traits)}")
        if prompt_content:
            parts.append(f"【完整文风指令】\n{prompt_content[:1200]}")
        text = "\n".join(parts)

    if len(text) > budget:
        text = text[:budget] + "…（截断）"
    return text


def _compress_list_dim(data: list, level: str) -> str:
    """list 类型维度（少见，如某些 bridges 数据）。"""
    budget = LEVEL_CHAR_BUDGET[level]
    if not data:
        return ""
    take_count = {"light": 3, "medium": 6, "deep": 12}.get(level, 6)
    lines = []
    for idx, item in enumerate(data[:take_count]):
        if isinstance(item, dict):
            title = item.get("title") or item.get("name") or f"项目 {idx+1}"
            summary = item.get("summary") or item.get("description") or ""
            lines.append(f"{idx+1}. {title}: {str(summary)[:120]}")
        else:
            lines.append(f"{idx+1}. {str(item)[:80]}")
    text = "\n".join(lines)
    if len(text) > budget:
        text = text[:budget] + "…（截断）"
    return text


# ============================================================
# 辅助函数
# ============================================================


def _first_sentence(text: str, max_chars: int = 80) -> str:
    """取第一句（按中文句号/感叹号/问号分隔），上限 80 字符。"""
    if not text:
        return ""
    parts = re.split(r"[。！？.!?]\s*", text.strip(), maxsplit=1)
    first = parts[0].strip()
    if len(first) > max_chars:
        return first[:max_chars] + "…"
    return first


def _extract_key_fields(d: dict, max_count: int, max_len: int) -> list[str]:
    """从子模式 dict 中抽出最多 max_count 个非 writing_tips 字段，每个 ≤ max_len 字符。"""
    out: list[str] = []
    skip_keys = {"writing_tips", "case"}  # case 字段太长，medium 档不要
    for k, v in d.items():
        if k in skip_keys:
            continue
        if isinstance(v, (str, int, float)) and str(v).strip():
            label = HUMANIZE_KEY.get(k, k)
            out.append(f"{label}={str(v)[:max_len]}")
        elif isinstance(v, list) and v:
            label = HUMANIZE_KEY.get(k, k)
            out.append(f"{label}=[{', '.join(str(x)[:20] for x in v[:3])}]")
        if len(out) >= max_count:
            break
    return out


def _format_field(key: str, value: Any, max_len: int) -> str:
    """deep 档单字段格式化。"""
    label = HUMANIZE_KEY.get(key, key)
    if isinstance(value, (str, int, float)):
        s = str(value).strip()
        if not s or s.lower() == "null":
            return ""
        return f"{label}: {s[:max_len]}"
    if isinstance(value, list) and value:
        return f"{label}: {', '.join(str(x)[:40] for x in value[:6])}"
    if isinstance(value, dict) and value:
        # 嵌套 dict 简短展开
        sub_parts = [f"{k}={str(v)[:40]}" for k, v in list(value.items())[:3]]
        return f"{label}: {{{', '.join(sub_parts)}}}"
    return ""


def _format_scalar_field(key: str, value: Any, level: str) -> str:
    """顶层标量字段（如 synopsis 的 genre/premise 直接是字符串）。"""
    if not value:
        return ""
    label = HUMANIZE_KEY.get(key, key)
    max_len = {"light": 60, "medium": 150, "deep": 400}.get(level, 150)
    if isinstance(value, (str, int, float)):
        s = str(value).strip()
        return f"- {label}：{s[:max_len]}" if s else ""
    if isinstance(value, list):
        return f"- {label}：{', '.join(str(x)[:30] for x in value[:5])}"
    return ""


def _truncate_plain(text: str, budget: int) -> str:
    """非 JSON 输入的兜底截断。"""
    if len(text) <= budget:
        return text
    return text[:budget] + "…（截断）"


# ============================================================
# ReferencePack 批量预压缩（可选 - 写到 DB 的 24 个字段）
# ============================================================


def compress_pack_to_db(pack: Any) -> dict[str, str]:
    """对 ReferencePack 的 6 个 _json 字段一次性生成 18 个预压缩字符串。

    Args:
        pack: ReferencePack ORM 对象

    Returns:
        {field_name: text} dict，含 methodology_light/medium/deep 等 18 字段
        （6 维 × 3 档，corpus 不参与）

    用法（可选 - 让已有拆书数据享受高质量预压缩）：
        from app.services.reference_pack.dimension_compressor import compress_pack_to_db
        updates = compress_pack_to_db(pack)
        for field, text in updates.items():
            setattr(pack, field, text)
        await db.commit()
    """
    result: dict[str, str] = {}
    pipeline_version = int(getattr(pack, "pipeline_version", None) or 2)
    for dim in COMPRESSIBLE_DIMENSIONS:
        json_text = getattr(pack, f"{dim}_json", None)
        if not json_text:
            continue
        for level in ("light", "medium", "deep"):
            text = compress_dimension(json_text, dim, level, pipeline_version=pipeline_version)
            if text:
                result[f"{dim}_{level}"] = text
    return result
