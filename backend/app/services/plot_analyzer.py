"""章节分析（两段式）：A「叙事事实」必须成功，B「人物与标注」可以单独失败。

旧版一次调用要 17 类 JSON（评分 / 建议 / 情绪曲线等没人用），输出动辄五六千 token：被 Max Tokens 截断后
json-repair 补上括号就当成功落库，排在最后的连续性信号 / 故事时间整块丢失，还把上一次的正确结算清掉。现在：
- 只抽会影响后续章节的东西，分两次并行调用；输出带结尾哨兵 end，截断 / 缺摘要一律判失败，先用精简模式重试一次
- 分析调用关闭思考（预算留给输出），且不改外面共用的 AIService 实例
- 长章按段落分段抽取再合并（不再只看前 8000 字）；伏笔只认「未回收清单」的编号推进 / 回收，新坑才新建
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Iterable, Optional

from app.logger import get_logger
from app.services import chapter_analysis_schema as schema
from app.services.ai_service import AIService, last_stream_finish_reason, reset_stream_finish_reason

logger = get_logger(__name__)

SEGMENT_LIMIT = 12_000
SEGMENT_TARGET = 9_000
OPEN_PROMISE_LIMIT = 30
KNOWN_CHARACTER_LIMIT = 60


class AnalysisError(RuntimeError):
    """分析没有成功（截断 / 空返回 / 不是 JSON / 缺摘要 / 调用失败）；消息是给作者看的原因。"""


FACTS_PROMPT = """你是长篇网文的连续性编辑。读完下面这一章{segment_note}，把会影响后续章节的「已发生事实」记下来，严格输出 JSON。

【章节】第{chapter_number}章《{title}》
{context_block}
【正文】
{content}

---
记录规则：
- 只记正文明确写出的事，不推测、不补设定；人名优先用「已登记角色」里的正式名
- 回忆、梦境、幻象、别人讲的往事不是现在发生的：end_state / story_time / state_changes / relationships 只记现在这条线（回忆里出现的死人不算复活，往事里的地点、境界、关系也不算现在的）；往事写进 summary 或 events 时注明「回忆」，events 的 time 写成「回忆·十年前」这样
- 整章都是往事、没有回到现在：end_state 和 story_time 留空
- evidence 从正文逐字摘 6-30 字（必须能在原文里找到）
- 没有的项给空数组 []，不要编{compact_rule}

字段（按顺序输出）：
1. summary：{summary_limit} 字以内，本章发生了什么、结果如何（白话，不评价、不升华）
2. end_state：80 字以内，章末主要人物各在哪、处境如何
3. story_time：本章结束时的故事内时间（如“入宗第三年·深秋”），判断不了留空
4. locations：本章主要地点（最多 4 个）
5. characters：本章出场的人物 [{{"name", "change"}}]，change = 本章处境 / 心态 / 实力的变化（30 字内，没变化留空）
6. state_changes：硬性状态变化，只记明确写出的 [{{"who", "kind", "value", "change", "evidence"}}]
   - life：change = dead / missing / revived / survived，value 留空
   - location：value = 地点，change = arrived / left / current
   - realm：value = 变化后的境界 / 等级 / 身份地位，change = current
   - item：value = 关键物品（法宝 / 功法 / 丹药 / 信物 / 大额钱财），change = gained / lost / used
   - injury：value = 伤势，change = injured / recovered
   - goal：value = 新的当前目标，change = current
   - ability：value = 能力名，change = learned / mastered / used / lost / forgotten
7. promises：伏笔 / 承诺 / 悬念 / 冲突 [{{"action", "ref", "type", "title", "content", "owner", "target", "priority", "deadline_chapter", "evidence"}}]
   - 推进或重新提起「未回收清单」里的某条：action = advance，ref 填它的编号（如 P3）
   - 把清单里的某条彻底回收 / 解决：action = resolve，ref 填编号
   - 清单里没有的新坑：action = plant，ref 留空；同一个坑只写一次
   - type = foreshadow / promise / mystery / conflict；priority = low / medium / high / critical
   - deadline_chapter：新埋设且「本章计划叙事任务」给了计划回收章时填章号，否则 null
8. relationships：人物关系的明确变化 [{{"from", "to", "delta", "reason_type", "reason", "status", "evidence"}}]
   delta = -100~100 的整数；reason_type = rescue / betrayal / alliance / misunderstanding / confession / rivalry / respect / hostility / other；status = active / broken / past / complicated
9. knowledge：人物新知道的信息 [{{"who", "key", "content", "source", "secret"}}]；key = 10 字内的信息标签，source = witnessed / hearsay / deduced / document，secret = public / private / secret
10. events：1-5 个关键事件，按正文里的先后排列 [{{"title", "what", "cause", "effect", "decision", "type", "actors", "targets", "location", "time", "visibility", "importance", "evidence"}}]
    type = action / reveal / battle / meeting / departure / arrival / promise / mystery / conflict / death / other；有人死亡时 type = death、死者写进 targets；importance = 0~1
11. 最后一个字段固定写 "end": true

格式示例：
{example}

只输出 JSON 对象，不要 Markdown 代码块，不要解释。"""

COMPACT_RULE_FACTS = "\n- 精简模式：summary 120 字内；每个数组最多 3 条；evidence 15 字内；没把握的不写"

CAST_PROMPT = """你是小说编辑。读完下面这一章{segment_note}，做两件事，严格输出 JSON。

【章节】第{chapter_number}章《{title}》
{known_block}
【正文】
{content}

---
一、characters / organizations：本章出场、有名字的人物和组织（只写正文里有依据的信息，没提到的字段填 null）
- 人物 = 能说话、能行动的个体；宗门 / 门派 / 家族 / 帮会 / 堂殿阁院等机构一律放 organizations
- 已登记的只补本章新透露的信息
- 回忆 / 往事里的身份与归属写进 background；affiliations 只写人物现在的归属（往事里待过的组织不写进 affiliations）
- characters：[{{"name", "gender", "age", "role_type", "personality", "appearance", "speech_style", "background", "traits", "affiliations"}}]
  role_type = protagonist / major / supporting / minor；speech_style = 说话方式 / 口头禅（台词体现不出来填 null）；background = 一句话
  affiliations = [{{"org_name", "position", "change", "reason"}}]，change = joined / left / promoted / expelled / active
- organizations：[{{"name", "organization_type", "organization_purpose", "personality", "appearance", "location", "known_members", "traits", "background"}}]

二、annotations：正文里最值得标出来的 3-8 处 [{{"type", "title", "note", "quote", "importance"}}]
- type = hook（让读者想往下看的钩子）/ foreshadow（埋下或回收的伏笔）/ plot_point（关键转折）
- title 10 字内；note 40 字内说明为什么值得标；quote 从正文逐字复制 8-30 字；importance = 0~1{compact_rule}

最后一个字段固定写 "end": true

格式示例：
{example}

只输出 JSON 对象，不要 Markdown 代码块，不要解释。"""

COMPACT_RULE_CAST = "\n- 精简模式：只写本章新出场或有新信息的人物 / 组织，每个字段 20 字内；annotations 最多 3 条"


class PlotAnalyzer:
    OPEN_PROMISE_LIMIT = OPEN_PROMISE_LIMIT

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    # ---------------- 调用模型 ----------------

    def _service(self) -> Any:
        """分析不需要思考：真实 AIService 开了思考就复制一份关掉（批量流水线里正文生成还在用原实例）。"""
        svc = self.ai_service
        if isinstance(svc, AIService) and getattr(svc, "reasoning_enabled", False):
            svc = copy.copy(svc)
            svc.reasoning_enabled = False
        return svc

    def _model_kwargs(self) -> dict[str, Any]:
        """配了分析模型（设置 → 分析模型）就走它。"""
        model = getattr(self.ai_service, "analysis_model", None)
        return {"model": model} if isinstance(model, str) and model.strip() else {}

    async def _call(self, svc: Any, prompt: str, temperature: float) -> tuple[str, Optional[str]]:
        reset_stream_finish_reason()
        chunks: list[str] = []
        try:
            async for chunk in svc.generate_text_stream(prompt=prompt, temperature=temperature, **self._model_kwargs()):
                if chunk:
                    chunks.append(chunk)
        except Exception as exc:  # noqa: BLE001 - 鉴权 / 网关 / 网络错误统一转成可读原因
            raise AnalysisError(f"调用模型失败：{exc}") from exc
        return "".join(chunks), last_stream_finish_reason()

    def _reason_text(self, reason: Optional[str], label: str) -> str:
        if reason == "truncated":
            max_tokens = getattr(self.ai_service, "default_max_tokens", None)
            current = f"（当前 {max_tokens}）" if isinstance(max_tokens, int) else ""
            return (f"{label}的输出被 Max Tokens 截断{current}，精简重试后仍没写完："
                    f"请在「设置」里调大 Max Tokens，或给分析换一个不带思考过程的模型")
        if reason == "empty":
            return f"{label}时模型没有返回任何内容（可能是思考过程耗尽了 Max Tokens，或接口异常）"
        if reason == "incomplete":
            return f"{label}的结果缺少本章摘要"
        return f"{label}时模型返回的不是可解析的 JSON"

    async def _structured(
        self,
        label: str,
        build_prompt: Callable[[bool], str],
        normalize: Callable[[Any], dict],
        complete: Callable[[dict], bool],
        temperature: float,
    ) -> dict:
        """先按正常模式调用，截断 / 解析失败 / 不完整就用精简模式再来一次；两次都不行抛 AnalysisError。"""
        svc = self._service()
        reason: Optional[str] = None
        for compact in (False, True):
            text, finish = await self._call(svc, build_prompt(compact), temperature)
            if not text.strip():
                reason = "empty"
                continue
            obj, repaired = schema.parse_model_json(text)
            if obj is None:
                reason = "truncated" if finish == "length" else "invalid"
                continue
            if schema.looks_truncated(obj, repaired, finish):
                reason = "truncated"
                logger.warning("⚠️ %s输出被截断（finish_reason=%s，修补=%s），%s", label, finish, repaired,
                               "改用精简模式重试" if not compact else "放弃")
                continue
            result = normalize(obj)
            if not complete(result):
                reason = "incomplete"
                continue
            return result
        raise AnalysisError(self._reason_text(reason, label))

    # ---------------- 提示词素材 ----------------

    @classmethod
    def build_open_promise_block(cls, open_promises: Optional[Iterable[Any]]) -> tuple[str, dict[str, str]]:
        """把未回收承诺渲染成带短编号（P1…）的清单，返回 (文本, 短编号 → 真实 id)。"""
        items = list(open_promises or [])[: cls.OPEN_PROMISE_LIMIT]
        if not items:
            return "", {}
        lines = ["【未回收清单：本章推进或回收了其中某条，必须用它的编号】"]
        mapping: dict[str, str] = {}
        for index, item in enumerate(items, start=1):
            short_id = f"P{index}"
            mapping[short_id] = str(getattr(item, "id", "") or "")
            deadline = getattr(item, "deadline_chapter", None)
            plan = f"，计划第{deadline}章前回收" if deadline else ""
            lines.append(
                f"- {short_id} [{getattr(item, 'promise_type', '') or 'promise'}/{getattr(item, 'priority', '') or 'medium'}] "
                f"{getattr(item, 'title', '')}（第{getattr(item, 'source_chapter_number', '?')}章起{plan}）："
                f"{str(getattr(item, 'content', '') or '')[:40]}"
            )
        return "\n".join(lines), mapping

    @staticmethod
    def _known_names(known_characters: Optional[Iterable[str]]) -> str:
        return "、".join(n for n in list(known_characters or [])[:KNOWN_CHARACTER_LIMIT] if n)

    @staticmethod
    def _carry_over(parts: list[dict]) -> str:
        summaries = "；".join(p["summary"] for p in parts if p.get("summary"))
        end_state = parts[-1].get("end_state") or ""
        planted = "、".join(p["title"] for part in parts for p in part.get("promises") or [] if p["action"] == "plant")
        lines = ["【本章前面几段已记下（只记新内容，不要重复）】", f"- 摘要：{summaries}"]
        if end_state:
            lines.append(f"- 上一段结尾：{end_state}")
        if planted:
            lines.append(f"- 已记下的新坑：{planted}")
        return "\n".join(lines)

    # ---------------- 分析 A：叙事事实 ----------------

    async def analyze_facts(
        self,
        *,
        chapter_number: int,
        title: str,
        content: str,
        open_promises: Optional[Iterable[Any]] = None,
        planned_tasks: str = "",
        known_characters: Optional[Iterable[str]] = None,
    ) -> dict:
        """返回规整后的叙事事实（伏笔编号已映射回真实 id）；失败抛 AnalysisError。"""
        promise_block, mapping = self.build_open_promise_block(open_promises)
        base_context = [promise_block] if promise_block else []
        if planned_tasks and planned_tasks.strip():
            base_context.append(f"【本章计划叙事任务（章纲）】\n{planned_tasks.strip()}")
        names = self._known_names(known_characters)
        if names:
            base_context.append(f"【已登记角色正式名（人名优先用这些）】\n{names}")

        segments = schema.split_for_analysis(content or "", limit=SEGMENT_LIMIT, target=SEGMENT_TARGET)
        multi = len(segments) > 1
        parts: list[dict] = []
        for index, segment in enumerate(segments, start=1):
            context = base_context + ([self._carry_over(parts)] if parts else [])
            note = f"（第{index}/{len(segments)}段）" if multi else ""

            def build(compact: bool, segment: str = segment, context: list[str] = context, note: str = note) -> str:
                return FACTS_PROMPT.format(
                    chapter_number=chapter_number, title=title or "", segment_note=note,
                    context_block="\n\n".join(context) + ("\n" if context else ""), content=segment,
                    summary_limit=120 if (multi or compact) else 200,
                    compact_rule=COMPACT_RULE_FACTS if compact else "", example=schema.FACTS_EXAMPLE,
                )

            parts.append(await self._structured("分析叙事事实", build, schema.normalize_facts, schema.facts_complete, 0.2))

        facts = schema.merge_facts(parts)
        schema.map_promise_refs(facts, mapping)
        logger.info(
            "✅ 第%s章叙事事实：%s段 状态变化=%s 伏笔动作=%s 事件=%s 关系=%s",
            chapter_number, len(segments), len(facts["state_changes"]), len(facts["promises"]),
            len(facts["events"]), len(facts["relationships"]),
        )
        return facts

    # ---------------- 分析 B：人物与标注 ----------------

    async def extract_cast(
        self,
        *,
        chapter_number: int,
        title: str,
        content: str,
        known_characters: Optional[Iterable[str]] = None,
    ) -> dict:
        """返回 {characters, organizations, annotations}；失败抛 AnalysisError（调用方可降级，不影响叙事事实）。"""
        names = self._known_names(known_characters)
        known_block = f"【已登记角色 / 组织】\n{names}\n" if names else ""
        segments = schema.split_for_analysis(content or "", limit=SEGMENT_LIMIT, target=SEGMENT_TARGET)
        multi = len(segments) > 1
        parts: list[dict] = []
        for index, segment in enumerate(segments, start=1):
            note = f"（第{index}/{len(segments)}段）" if multi else ""

            def build(compact: bool, segment: str = segment, note: str = note) -> str:
                return CAST_PROMPT.format(
                    chapter_number=chapter_number, title=title or "", segment_note=note, known_block=known_block,
                    content=segment, compact_rule=COMPACT_RULE_CAST if compact else "", example=schema.CAST_EXAMPLE,
                )

            parts.append(await self._structured("抽取人物与标注", build, schema.normalize_cast, lambda _c: True, 0.2))
        cast = schema.merge_cast(parts)
        logger.info(
            "✅ 第%s章人物与标注：%s个人物 %s个组织 %s处标注",
            chapter_number, len(cast["characters"]), len(cast["organizations"]), len(cast["annotations"]),
        )
        return cast
