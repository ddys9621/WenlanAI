"""去 AI 味规则加载器（sepia 三层法中文化：叙事架构 → 篇章推进 → 中文措辞）。

规则全部是 backend/app/prompts/deai/ 下的 markdown，改规则不改代码：
- calibration.md     总纲（校准 + 护栏），写 / 改 / 审三处都注入
- write.md           生成时注入正文提示词的三层规则
- refactor.md        去 AI 味改稿协议（重生成 deai 模式）
- review/NN_*.md     诊断：每个文件一轮 LLM 调用（首行 "# 标题"，"层：架构|篇章|措辞" 一行，可选 "种类：正向"，其余为判据）
- models/<family>.prior.md 模型家族叙事层先验（按用户 settings.llm_model 识别；没有表的家族不注入）。
  带 .prior 后缀是因为裸的 claude.md 在 Windows（大小写不敏感）会被 AI 编码工具当成 CLAUDE.md 指令文件自动加载。

文件内容 lru_cache 常驻，改完规则重启服务生效。PyInstaller 打包时该目录须作为 datas 显式带上（见 mumuai.spec）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.logger import get_logger

logger = get_logger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts" / "deai"

# 模型名（小写）→ 家族。顺序即优先级；"o1 / o3-mini / openai/o4" 这类 OpenAI 推理模型要求 o 后紧跟数字，
# 且前面是开头或分隔符，避免 moonshot / doubao 之类误配。
# 识别家族 ≠ 有先验表：先验只来自 models/<family>.prior.md 是否存在（sepia 原则：StoryScope 没测过、厂商没公开写作指南的家族
# 不猜——Grok / Qwen / GLM / 豆包 目前都没有表，识别出来只为了在报告里如实写"无先验表"，用户有自己的观察可自建文件）
_FAMILY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("claude", re.compile(r"claude")),
    ("gpt", re.compile(r"gpt|(?:^|[/:\-_ ])o[1-9](?:$|[^a-z0-9])")),
    ("gemini", re.compile(r"gemini")),
    ("deepseek", re.compile(r"deepseek")),
    ("kimi", re.compile(r"kimi|moonshot")),
    ("grok", re.compile(r"grok")),
    ("qwen", re.compile(r"qwen|qwq")),
    ("glm", re.compile(r"glm|zhipu")),
    ("doubao", re.compile(r"doubao")),
)

WRITE_HEADER = (
    "【去 AI 味规则（sepia 三层法，依据 StoryScope 等对人类 / AI 小说的实测差异）】\n"
    "这块只负责去掉机器腔，不改文体：段落形态、对话占比、叙述口吻、章内节奏一律以上方「叙事与文风要求」（网文大白话）为准，"
    "本块与之冲突时让路；措辞层的规则照用。与章纲、剧情卡、项目风格冲突时同样以后者为先。"
)


def detect_model_family(model_name: str | None) -> str | None:
    name = (model_name or "").strip().lower()
    if not name:
        return None
    for family, pattern in _FAMILY_PATTERNS:
        if pattern.search(name):
            return family
    return None


@lru_cache(maxsize=None)
def load_text(rel: str) -> str:
    """读 PROMPTS_DIR 下的规则文件（相对路径）；缺文件返回空串并告警，不抛。"""
    path = PROMPTS_DIR / rel
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.warning("去 AI 味规则文件不存在，已跳过: %s", path)
        return ""


def model_prior(model_name: str | None) -> str:
    """该模型家族的叙事层先验；家族未识别或没有 models/<family>.prior.md（无实测表）都返回空串，不告警。"""
    family = detect_model_family(model_name)
    if not family or not (PROMPTS_DIR / "models" / f"{family}.prior.md").is_file():
        return ""
    return load_text(f"models/{family}.prior.md")


def _join(*parts: str) -> str:
    return "\n\n".join(p for p in parts if p)


ROTATION_PICKS_PER_SECTION = 2  # 架构、篇章各主推几条；措辞层规则是禁忌性的，常开不轮换
_SECTION_RE = re.compile(r"^## [一二三四五六七八九十]+、([^（(\s]+)", re.M)  # 标题后的括注（最先决定…）不算名字
_ITEM_RE = re.compile(r"^\d+\.\s+(.+?)\s*$", re.M)
_SECTION_LAYER = {"叙事架构": "架构", "篇章推进": "篇章"}


def _write_sections() -> dict[str, list[str]]:
    """write.md 的 `## 一、叙事架构` / `## 二、篇章推进` 两段里的编号条目（逐字）。"""
    text = load_text("write.md")
    heads = list(_SECTION_RE.finditer(text))
    sections: dict[str, list[str]] = {}
    for i, head in enumerate(heads):
        layer = _SECTION_LAYER.get(head.group(1))
        if layer is None:
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        sections[layer] = _ITEM_RE.findall(text[head.end():end])
    return sections


def rotation_items(chapter_number: int, picks: int = ROTATION_PICKS_PER_SECTION) -> list[tuple[str, str]]:
    """按章节号确定性抽取"本章主推"条目：架构、篇章各 picks 条，相邻章节不同。

    calibration.md 要求"每章只挑 3–5 招、和前几章换着用"——只靠模型自觉记不住前几章用了什么，这里用章节号做种子，
    把"换着用"变成事实。主推是重点提示，不替代全量规则（禁忌类条目仍然全在）。
    """
    import random

    rng = random.Random(f"deai-rotation-{chapter_number}")
    out: list[tuple[str, str]] = []
    for layer, items in _write_sections().items():
        if items:
            out.extend((layer, item) for item in rng.sample(items, k=min(picks, len(items))))
    return out


def build_rotation_block(chapter_number: int | None) -> str:
    if chapter_number is None:
        return ""
    items = rotation_items(chapter_number)
    if not items:
        return ""
    return "【本章主推（按章轮换，重点用这几招；其余条目仍需遵守）】\n" + "\n".join(f"- {layer}：{text}" for layer, text in items)


def build_write_block(model_name: str | None, chapter_number: int | None = None, project_prior: str = "") -> str:
    """章节 / 场景生成提示词里的去 AI 味块：总纲 + 三层生成规则 + 本章主推（有章节号时）+ 模型家族先验 + 项目级先验。

    project_prior 来自 deai_history.load_project_prior（本项目最近几章诊断的高频信号），最具体所以放最后、离正文最近。
    """
    return _join(
        WRITE_HEADER, load_text("calibration.md"), load_text("write.md"),
        build_rotation_block(chapter_number), model_prior(model_name), project_prior,
    )


def build_refactor_protocol(model_name: str | None) -> str:
    """重生成 deai 模式的改稿协议：总纲 + 最小改动协议 + 当前模型家族先验。"""
    return _join(load_text("calibration.md"), load_text("refactor.md"), model_prior(model_name))


@dataclass(frozen=True)
class ReviewPass:
    key: str
    title: str
    layer: str
    body: str
    kind: str = "issue"  # issue：报缺陷；positive：报"已具备的人类标记"（头部 "种类：正向"），不进修改计划


_LAYER_RE = re.compile(r"^层[：:]\s*(\S+)\s*$")
_KIND_RE = re.compile(r"^种类[：:]\s*(\S+)\s*$")
_KIND_ALIASES = {"正向": "positive", "positive": "positive", "缺陷": "issue", "issue": "issue"}


def load_review_passes() -> list[ReviewPass]:
    """review/*.md 按文件名排序，每个文件一轮诊断；下划线开头的文件不算轮次。

    头部（首个非空正文行之前）可含：`# 标题`、`层：架构|篇章|措辞`、`种类：正向|缺陷`（默认缺陷）。
    """
    passes: list[ReviewPass] = []
    for path in sorted((PROMPTS_DIR / "review").glob("*.md")):
        if path.name.startswith("_"):
            continue
        title, layer, kind, body_lines, in_header = path.stem, "措辞", "issue", [], True
        for line in load_text(f"review/{path.name}").splitlines():
            stripped = line.strip()
            if in_header:
                if not stripped:
                    continue
                if stripped.startswith("# "):
                    title = stripped[2:].strip()
                    continue
                layer_match = _LAYER_RE.match(stripped)
                if layer_match:
                    layer = layer_match.group(1)
                    continue
                kind_match = _KIND_RE.match(stripped)
                if kind_match:
                    kind = _KIND_ALIASES.get(kind_match.group(1).lower(), "issue")
                    continue
                in_header = False
            body_lines.append(line)
        passes.append(ReviewPass(key=path.stem, title=title, layer=layer, body="\n".join(body_lines).strip(), kind=kind))
    return passes
