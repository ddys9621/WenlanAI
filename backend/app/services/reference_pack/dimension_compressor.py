"""参考包维度的三档预压缩：解析维度 JSON 后交给 v5_compressor 的专用算法。

- compress_dimension(json_text, dimension, level) → str：单个维度；空 / 坏 JSON / 未知维度返回空串
- compress_pack_to_db(pack) → {<dim>_<level>: text}：抽取完成时一次性写进参考包的 18 个预压缩字段
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.services.reference_pack.v5_compressor import LEVEL_CHAR_BUDGET, compress_v5

logger = logging.getLogger(__name__)

# 6 个预压缩维度（corpus 依赖动态 BM25，不预压缩），与 ReferencePack.DIMENSIONS_WITH_PRECOMPRESSION 对齐
COMPRESSIBLE_DIMENSIONS = (
    "methodology",
    "style",
    "structure",
    "synopsis",
    "bridges",
    "character_archive",
)

__all__ = ["COMPRESSIBLE_DIMENSIONS", "LEVEL_CHAR_BUDGET", "compress_dimension", "compress_pack_to_db"]


def compress_dimension(json_text: Optional[str], dimension: str, level: str) -> str:
    """三档压缩单个维度（≤ LEVEL_CHAR_BUDGET[level] 字符）。"""
    if not json_text or level not in LEVEL_CHAR_BUDGET:
        return ""
    try:
        data = json.loads(json_text) if isinstance(json_text, str) else json_text
    except (json.JSONDecodeError, TypeError):
        logger.warning("compress_dimension: %s 不是合法 JSON", dimension)
        return ""
    return compress_v5(dimension, data, level) if isinstance(data, dict) else ""


def compress_pack_to_db(pack: Any) -> dict[str, str]:
    """对参考包的 6 个 _json 字段一次性生成预压缩文本（6 维 × 3 档，空的不写）。"""
    result: dict[str, str] = {}
    for dim in COMPRESSIBLE_DIMENSIONS:
        json_text = getattr(pack, f"{dim}_json", None)
        if not json_text:
            continue
        for level in ("light", "medium", "deep"):
            text = compress_dimension(json_text, dim, level)
            if text:
                result[f"{dim}_{level}"] = text
    return result
