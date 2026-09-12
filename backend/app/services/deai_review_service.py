"""去 AI 味诊断（sepia review 操作的中文化）：只诊断、不改稿。

每个 prompts/deai/review/*.md 一轮 LLM 调用（sepia 实测：让模型一次看完整个 rubric 会塌缩到一两个显眼维度、
漏掉其余），每轮返回带原文引证的 findings；本模块用 deai_anchor 逐条核实引证并落字符偏移（编造的引文
不计、不进计划），再按层（架构 → 篇章 → 措辞）排序生成修改计划。
结果由 api.chapters 落到 chapter_deai_reviews，并可作为重生成 deai 模式（补丁式改稿）的修改指令来源。
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Awaitable, Callable, Optional

from app.logger import get_logger
from app.services.deai_anchor import locate
from app.services.deai_metrics import compute_metrics, format_hints
from app.services.deai_rules import ReviewPass, detect_model_family, load_review_passes, load_text, model_prior
from app.services.generation_trace import begin_stage
from app.utils.json_cleaner import safe_parse_json

logger = get_logger(__name__)

_LAYER_ORDER = {"架构": 0, "篇章": 1, "措辞": 2}
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
DEFAULT_CONCURRENCY = 4  # 各轮互相独立，并行跑；限并发是照顾中转网关的速率限制

ProgressHook = Callable[[str, int], Any]


def pick_review_model(chapter_model: Optional[str], current_model: Optional[str]) -> Optional[str]:
    """诊断要画像的是"写这章的模型"（chapters.generated_by_model），不是当前设置里正在用来审的模型；没记录才退回当前。"""
    return (chapter_model or "").strip() or current_model


def route_for_layer(layer: str) -> str:
    """信号该走哪条修订路径：架构层（主题说破、因果太整齐、结尾三件套…）靠替换几个词修不掉，只能整章重写或回章纲；
    篇章 / 措辞层可以补丁式最小改动。"""
    return "rewrite" if layer == "架构" else "patch"


def is_actionable(finding: dict[str, Any]) -> bool:
    """能进修改计划的信号：报的是缺陷（非人类正向标记），且引证没有被核实为"原文里找不到"。

    语义与前端 isActionableDeaiFinding 一致：只有显式 verified=False 才排除（落库的旧报告没有这个键）；
    kind 缺失时用 review/04 的 fix="保留" 约定兜底识别正向标记。
    """
    kind = finding.get("kind")
    positive = kind == "positive" or (kind is None and (finding.get("fix") or "").strip() == "保留")
    return not positive and finding.get("verified") is not False


def content_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def build_pass_prompt(
    p: ReviewPass, *, content: str, title: str, genre: str, model_prior_text: str, local_hints: str = "",
) -> str:
    prior = f"\n\n【当前模型家族的已知倾向——当作重点排查线索，但仍需原文证据】\n{model_prior_text}" if model_prior_text else ""
    hints = (
        f"\n\n【本地统计提示——程序按词表和句长算出来的候选位置，只是排查线索：逐条判断，不成立就不报，也不要只报这些】\n{local_hints}"
        if local_hints else ""
    )
    return f"""你是一位研究 AI 生成小说特征的资深编辑，现在对下面这一章做「去 AI 味」诊断中的一轮：{p.title}。
只诊断，不改稿；只看这一轮的判据，不报其他问题。

【校准总纲】
{load_text("calibration.md")}

【本轮判据】
{p.body}{prior}{hints}

【章节】《{title}》（类型：{genre or "未设定"}）
{content}

【输出】只输出一个 JSON 对象，不要 Markdown 代码块、不要解释：
{{
  "findings": [
    {{"feature": "判据表里的特征名（原样）", "evidence": "原文短语（必须逐字引用，10–40 字）", "note": "为什么算信号，一句话", "fix": "怎么改，一句话，具体到这处原文", "severity": "high|medium|low"}}
  ],
  "na": ["本章没有判断场合的特征名，可写原因"],
  "advisories": ["仅提示类：反向过头、副线、单一地点等，一句一条"]
}}
没有引证就不要报；没有信号时 findings 给空数组。"""


def _normalize_finding(item: Any, *, content: str, kind: str) -> Optional[dict[str, Any]]:
    """规范化单条 finding，并把 evidence 在原文里落位：找到 → start/end + verified=True；找不到 → verified=False。

    模型编造引文是常态，"没有引证就不要报"只靠 prompt 管不住，这里机械核实一遍。
    """
    if not isinstance(item, dict):
        return None
    severity = str(item.get("severity") or "medium").strip().lower()
    if severity not in _SEVERITY_ORDER:
        severity = "medium"
    evidence = str(item.get("evidence") or "").strip()
    anchor = locate(content, evidence) if content and evidence else None
    return {
        "feature": str(item.get("feature") or "").strip(),
        "evidence": evidence,
        "note": str(item.get("note") or "").strip(),
        "fix": str(item.get("fix") or "").strip(),
        "severity": severity,
        "kind": kind,
        "start": anchor[0] if anchor else None,
        "end": anchor[1] if anchor else None,
        "verified": anchor is not None,
    }


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def parse_pass_output(raw: str, *, content: str = "", kind: str = "issue") -> dict[str, Any]:
    """解析一轮输出。content 为空时无法核实引证，所有 finding 都是 verified=False。"""
    data = safe_parse_json(raw or "", default=None, expected_type="object", log_prefix="[deai-review]")
    if not isinstance(data, dict):
        return {"findings": [], "na": [], "advisories": [], "error": "模型输出不是合法 JSON 对象"}
    findings = [
        f for f in (_normalize_finding(x, content=content, kind=kind) for x in data.get("findings") or [])
        if f and f["feature"]
    ]
    return {"findings": findings, "na": _str_list(data.get("na")), "advisories": _str_list(data.get("advisories"))}


def build_plan(passes: list[dict[str, Any]]) -> list[str]:
    """按层（架构 → 篇章 → 措辞）再按 severity 排序的修改计划，一条一行；只收 is_actionable 的信号。"""
    items = [
        (p.get("layer", "措辞"), f)
        for p in passes
        for f in p.get("findings") or []
        if is_actionable(f)
    ]
    items.sort(key=lambda lf: (_LAYER_ORDER.get(lf[0], 9), _SEVERITY_ORDER.get(lf[1].get("severity", "medium"), 9)))
    return [
        f"【{layer}】{f['feature']}：{f.get('fix') or '按判据修正'}（原文：“{f.get('evidence', '')}”）"
        for layer, f in items
    ]


async def _notify(on_progress: Optional[ProgressHook], message: str, percent: int) -> None:
    if on_progress is None:
        return
    hook_result = on_progress(message, percent)
    if isinstance(hook_result, Awaitable):
        await hook_result


async def run_deai_review(
    *,
    content: str,
    title: str,
    genre: str,
    model_name: Optional[str],
    ai_service: Any,
    on_progress: Optional[ProgressHook] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> dict[str, Any]:
    """各轮并行诊断（信号量限并发）；单轮解析失败只记 error 不中断。返回可直接落库 / 回前端的 dict。"""
    review_passes = load_review_passes()
    prior_text = model_prior(model_name)
    family = detect_model_family(model_name)
    total = max(len(review_passes), 1)
    metrics_report = compute_metrics(content)
    local_hints = format_hints(metrics_report)
    semaphore = asyncio.Semaphore(max(1, concurrency))
    done_count = 0

    await _notify(on_progress, f"并行诊断 {total} 轮…", 5)

    async def run_one(p: ReviewPass) -> dict[str, Any]:
        nonlocal done_count
        async with semaphore:
            stage = begin_stage(p.key, p.title)  # 绑定了任务追踪时每轮一个阶段；否则 no-op
            prompt = build_pass_prompt(
                p, content=content, title=title, genre=genre, model_prior_text=prior_text,
                local_hints=local_hints if p.layer == "措辞" else "",
            )
            try:
                # 流式累积调 LLM：单轮带整章正文常超 100s，非流式会被中转网关（Cloudflare 524）首字节超时掐断
                response = await ai_service.generate_text_stream_collect(
                    prompt=prompt, temperature=0.2, context=f"deai-review-{p.key}",
                )
                raw = response.get("content", "") if isinstance(response, dict) else str(response or "")
                parsed = parse_pass_output(raw, content=content, kind=p.kind)
            except Exception as exc:  # noqa: BLE001 - 单轮失败不拖垮整次诊断
                logger.warning("[deai-review] 轮次 %s 调用失败: %s", p.key, exc)
                parsed = {"findings": [], "na": [], "advisories": [], "error": str(exc)[:300]}
            stage.done(
                findings=len(parsed["findings"]),
                unverified=sum(1 for f in parsed["findings"] if not f.get("verified")),
                **({"error": parsed["error"]} if parsed.get("error") else {}),
            )
        done_count += 1
        await _notify(on_progress, f"完成 {p.title}（{done_count}/{total}）", int(5 + done_count / total * 90))
        return {"key": p.key, "title": p.title, "layer": p.layer, "kind": p.kind, **parsed}

    passes_out: list[dict[str, Any]] = list(await asyncio.gather(*(run_one(p) for p in review_passes)))

    flat = [
        {**f, "layer": p["layer"], "group": p["key"], "route": route_for_layer(p["layer"])}
        for p in passes_out
        for f in p["findings"]
    ]
    plan = build_plan(passes_out)
    advisories = [a for p in passes_out for a in p.get("advisories") or []]
    failed = [p["title"] for p in passes_out if p.get("error")]
    unverified = sum(1 for f in flat if f.get("kind", "issue") == "issue" and not f.get("verified"))
    by_layer = {layer: sum(1 for f in flat if f["layer"] == layer and is_actionable(f)) for layer in _LAYER_ORDER}
    family_note = (
        f"{family}（已按其实测倾向重点排查）" if family and prior_text
        else f"{family}（sepia 无先验表，只用通用判据）" if family
        else "未知（无先验表，只用通用判据）"
    )
    summary = (
        f"共 {len(plan)} 条待改信号（架构 {by_layer['架构']} / 篇章 {by_layer['篇章']} / 措辞 {by_layer['措辞']}），"
        f"{len(advisories)} 条提示"
        + (f"；{unverified} 条引证未在原文找到（已不计）" if unverified else "")
        + (f"；{len(failed)} 轮解析失败：{'、'.join(failed)}" if failed else "")
        + f"。模型家族：{family_note}。"
    )
    await _notify(on_progress, "汇总诊断结果", 97)
    return {
        "model_name": model_name or "",
        "model_family": family,
        "passes": passes_out,
        "findings": flat,
        "plan": plan,
        "advisories": advisories,
        "summary": summary,
        "metrics": metrics_report["metrics"],
    }
