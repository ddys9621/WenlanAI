"""Plot analysis service for extracting chapter structure and narrative state."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.logger import get_logger
from app.services.ai_service import AIService

logger = get_logger(__name__)


class PlotAnalyzer:
    """Use LLM to analyze a chapter and extract structured narrative state."""

    ANALYSIS_PROMPT = """你是一位专业的小说编辑、剧情分析师和叙事状态审计员。请深度分析以下章节内容，并严格输出 JSON。

【章节信息】
- 章节：第{chapter_number}章
- 标题：{title}
- 字数：{word_count}字
{context_block}
【章节正文】
{content}

---

请完成以下分析任务：

### 1. Hooks
识别本章最能驱动读者继续阅读的钩子：
- type: suspense / emotion / conflict / revelation
- content: 钩子内容
- strength: 1-10
- position: opening / middle / ending
- keyword: 必须从原文逐字复制 8-25 字，能在正文中精确找到

### 2. Foreshadows
识别本章埋设或回收的伏笔：
- content
- type: planted / resolved
- strength: 1-10
- subtlety: 1-10
- reference_chapter: 若为回收伏笔，尽量指出对应章节号
- resolves_promise_id: 回收的是上方「未回收清单」里的哪一条就填它的编号（如 P3），清单里没有就留空，不要猜
- keyword: 必须从原文逐字复制 8-25 字

### 3. Conflict
- types: 人与人 / 人与己 / 人与环境 / 人与社会
- parties: 冲突双方
- level: 1-10
- description
- resolution_progress: 0.0-1.0

### 4. Emotional Arc
- primary_emotion
- intensity: 1-10
- curve
- secondary_emotions

### 5. Character States
对本章主要角色逐个分析：
- character_name
- state_before
- state_after
- psychological_change
- key_event
- relationship_changes: {{ "对方角色名": "变化描述" }}

### 6. Plot Points
列出 3-5 个关键剧情点：
- content
- type: revelation / conflict / resolution / transition
- importance: 0.0-1.0
- impact
- keyword: 必须从原文逐字复制 8-25 字

### 7. Scenes
- location
- atmosphere
- duration

### 8. Quality Scores
- pacing / engagement / coherence / overall: 1-10

### 9. Suggestions
给出 3-5 条具体建议。

### 10. Summary
输出 100-200 字章节摘要。

### 11. Causal Links
提取 1-5 条关键因果链，每条必须包含：
- cause
- event
- effect
- decision
- actor_names: 角色名数组
- target_names: 受影响角色名数组
- plot_line_hint: 若能判断属于哪条剧情线，写标题，否则留空
- importance: 0.0-1.0
- reversible: true / false
- evidence: 必须尽量引用原文关键短句

### 12. Narrative Promises
提取本章新增或推进的叙事承诺，类型仅允许：
- foreshadow / promise / mystery / conflict
每条包含：
- promise_type
- title
- content
- owner_character_name
- target_character_name
- plot_line_hint
- priority: low / medium / high / critical
- status: open / progressing / resolved / broken
- deadline_chapter: 新埋设且上方「本章计划叙事任务」给了计划回收章时填该章号，否则留空
- reference_chapter: 若是回收/解决旧承诺，尽量给出起始章节号
- resolves_title: 若能判断回收的是哪一个承诺，写标题，否则留空
- resolves_promise_id: 本章把「未回收清单」里的某条彻底回收 / 解决时填它的编号（如 P3），status 填 resolved
- advances_promise_id: 本章只是推进或重新提起清单里的某条（没解决）时填它的编号，status 填 progressing
- evidence
清单里的旧承诺被推进或回收时，务必用编号指认，不要另起一条同义的新承诺；清单外的新坑才新建。

### 13. Relationship Deltas
提取本章明确推动的人物关系变化：
- from_character_name
- to_character_name
- delta: -100 到 100 的整数
- reason_type: rescue / betrayal / alliance / misunderstanding / confession / rivalry / respect / hostility / other
- reason
- new_status: active / broken / past / complicated
- evidence

### 14. Timeline Events
提取 1-5 个可写入全局时间轴的事件：
- event_type: action / reveal / battle / meeting / departure / arrival / promise / mystery / conflict / death / other
- title
- description
- location
- time_marker
- actor_names
- target_names
- plot_line_hints
- public_visibility: public / private / secret

### 15. Knowledge Changes
提取角色在本章新增获得的信息：
- character_name
- info_key
- content
- source: witnessed / hearsay / deduced / document
- confidence: 0.0-1.0
- secret_level: public / private / secret

### 16. Continuity Signals
为了做硬规则连续性审计，请额外提取以下结构化信号：

- life_state_changes: 仅在人物生死/失踪/复活被明确提及时填写
  - character_name
  - status: dead / missing / revived / survived
  - evidence

- ability_updates: 仅在人物明确学会、掌握、失去、忘记、使用某项能力时填写
  - character_name
  - ability_name
  - change: learned / mastered / used / lost / forgotten
  - evidence

- location_updates: 仅在人物明确抵达、离开、当前所处地点时填写
  - character_name
  - location
  - status: arrived / left / current
  - evidence

- realm_updates: 仅在人物境界 / 实力等级 / 身份地位明确变化或被点明时填写
  - character_name
  - realm: 变化后的境界 / 等级 / 地位（如“筑基初期”“外门执事”）
  - evidence

- item_updates: 仅在人物明确获得、失去、用掉关键物品（法宝 / 功法秘籍 / 丹药 / 信物 / 大额钱财）时填写
  - character_name
  - item
  - change: gained / lost / used
  - evidence

- injury_updates: 仅在人物明确受伤 / 中毒 / 痊愈时填写
  - character_name
  - injury: 伤势描述（如“左臂骨折”“经脉受损”）
  - status: injured / recovered
  - evidence

- goal_updates: 仅在人物明确立下或改变当前目标时填写
  - character_name
  - goal
  - evidence

### 17. Story Time
- story_time: 本章结束时的故事内时间（如“入宗第三年·深秋”“大比前三天”），无法判断留空

---

仅输出 JSON，不要输出 Markdown，不要输出解释文字。

JSON 结构如下：
{{
  "summary": "章节摘要",
  "hooks": [
    {{
      "type": "suspense",
      "content": "钩子内容",
      "strength": 8,
      "position": "ending",
      "keyword": "原文关键短句"
    }}
  ],
  "foreshadows": [
    {{
      "content": "伏笔内容",
      "type": "planted",
      "strength": 7,
      "subtlety": 8,
      "reference_chapter": null,
      "resolves_promise_id": "",
      "keyword": "原文关键短句"
    }}
  ],
  "conflict": {{
    "types": ["人与人"],
    "parties": ["甲", "乙"],
    "level": 8,
    "description": "冲突说明",
    "resolution_progress": 0.2
  }},
  "emotional_arc": {{
    "primary_emotion": "愤怒",
    "intensity": 8,
    "curve": "压抑→爆发→坚定",
    "secondary_emotions": ["屈辱", "决绝"]
  }},
  "character_states": [
    {{
      "character_name": "林尘",
      "state_before": "隐忍",
      "state_after": "决绝",
      "psychological_change": "心态变化",
      "key_event": "触发事件",
      "relationship_changes": {{"慕雪": "关系恶化"}}
    }}
  ],
  "plot_points": [
    {{
      "content": "剧情点",
      "type": "conflict",
      "importance": 0.9,
      "impact": "推动主线",
      "keyword": "原文关键短句"
    }}
  ],
  "scenes": [
    {{
      "location": "慕家大堂",
      "atmosphere": "压抑",
      "duration": "短"
    }}
  ],
  "pacing": "varied",
  "dialogue_ratio": 0.4,
  "description_ratio": 0.3,
  "scores": {{
    "pacing": 8,
    "engagement": 9,
    "coherence": 8,
    "overall": 8.5
  }},
  "plot_stage": "发展",
  "suggestions": ["建议1", "建议2"],
  "causal_links": [
    {{
      "cause": "因",
      "event": "事",
      "effect": "果",
      "decision": "决",
      "actor_names": ["林尘"],
      "target_names": ["慕雪"],
      "plot_line_hint": "主线逆袭",
      "importance": 0.9,
      "reversible": false,
      "evidence": "原文关键短句"
    }}
  ],
  "narrative_promises": [
    {{
      "promise_type": "promise",
      "title": "三年之约",
      "content": "林尘立下三年之约",
      "owner_character_name": "林尘",
      "target_character_name": "慕雪",
      "plot_line_hint": "主线逆袭",
      "priority": "critical",
      "status": "open",
      "deadline_chapter": null,
      "reference_chapter": null,
      "resolves_title": "",
      "resolves_promise_id": "",
      "advances_promise_id": "",
      "evidence": "原文关键短句"
    }}
  ],
  "relationship_deltas": [
    {{
      "from_character_name": "林尘",
      "to_character_name": "慕雪",
      "delta": -40,
      "reason_type": "hostility",
      "reason": "当众退婚导致关系恶化",
      "new_status": "complicated",
      "evidence": "原文关键短句"
    }}
  ],
  "timeline_events": [
    {{
      "event_type": "promise",
      "title": "三年之约成立",
      "description": "林尘在退婚羞辱后立下三年之约",
      "location": "慕家大堂",
      "time_marker": "当日",
      "actor_names": ["林尘"],
      "target_names": ["慕雪"],
      "plot_line_hints": ["主线逆袭"],
      "public_visibility": "public"
    }}
  ],
  "knowledge_changes": [
    {{
      "character_name": "林尘",
      "info_key": "mu_family_attitude",
      "content": "慕家彻底看不起自己并公开切割婚约",
      "source": "witnessed",
      "confidence": 1.0,
      "secret_level": "private"
    }}
  ],
  "continuity_signals": {{
    "life_state_changes": [
      {{
        "character_name": "林长老",
        "status": "dead",
        "evidence": "原文关键短句"
      }}
    ],
    "ability_updates": [
      {{
        "character_name": "林尘",
        "ability_name": "御风步",
        "change": "learned",
        "evidence": "原文关键短句"
      }}
    ],
    "location_updates": [
      {{
        "character_name": "林尘",
        "location": "青峰山",
        "status": "current",
        "evidence": "原文关键短句"
      }}
    ],
    "realm_updates": [
      {{"character_name": "林尘", "realm": "炼气五层", "evidence": "原文关键短句"}}
    ],
    "item_updates": [
      {{"character_name": "林尘", "item": "玄铁剑", "change": "gained", "evidence": "原文关键短句"}}
    ],
    "injury_updates": [
      {{"character_name": "林尘", "injury": "左臂骨折", "status": "injured", "evidence": "原文关键短句"}}
    ],
    "goal_updates": [
      {{"character_name": "林尘", "goal": "三个月内进入内门", "evidence": "原文关键短句"}}
    ]
  }},
  "story_time": "入宗第三年·深秋"
}}
"""

    # 未回收清单最多列多少条（按优先级 / 计划回收章 / 最近活跃排序后截取）
    OPEN_PROMISE_LIMIT = 30
    CONTINUITY_SIGNAL_KEYS: tuple[str, ...] = (
        "life_state_changes", "ability_updates", "location_updates",
        "realm_updates", "item_updates", "injury_updates", "goal_updates",
    )

    ENTITY_EXTRACTION_PROMPT = """你是一个小说实体提取器。从以下章节正文中提取所有出场的**人物**和**组织/机构/势力**。

## 第{chapter_number}章: {title}

{content}

## 关键分类规则（严格遵守）

**characters（人物）**= 有血有肉的自然人，能说话、能行动的个体。
示例：林尘、慕雪、许长老、张三

**organizations（组织）**= 机构、团体、建筑、部门、地方势力，不是个体自然人。
包含但不限于：
- 宗门/门派：青云宗、太一仙宗
- 宗门下属机构/部门：外门、内门、戒律堂、藏经阁、执法殿、丹药阁
- 家族/氏族：慕家、林家、王氏
- 势力/帮会：黑风盗、天机阁
- 建筑/场所（如果作为势力单位出现）：演武场、议事大殿

**绝对禁止**：把宗门、门派、堂、殿、阁、院、门、家族、帮、盟、会等放入 characters。
如果一个名字以"宗/派/门/堂/殿/阁/院/府/家/帮/盟/会/楼/馆/谷/洞"结尾，它几乎一定是 organization。

## 其他提取规则
- 只提取正文中**明确出现名字**的实体，不要推测
- 每个字段**只填本章正文中有明确依据的信息**，没有提到的字段填 null
- 严格输出 JSON，不要任何其他文字

## 输出格式
```json
{{
  "characters": [
    {{
      "name": "角色名",
      "gender": "男/女/未知",
      "age": "年龄或年龄段，如'十六岁'、'中年'，无法判断填null",
      "role_type": "protagonist/major/supporting/minor 之一",
      "personality": "性格特征，如'沉稳冷静'，本章无法判断填null",
      "appearance": "外貌描写，如'身穿白袍，剑眉星目'，本章无描写填null",
      "speech_style": "说话方式 / 口头禅 / 称呼习惯，如'嘴硬爱吐槽，口头禅“行吧”'，本章台词体现不出来填null",
      "background": "一句话背景，如'青云宗外门弟子，被退婚'",
      "traits": ["特征标签1", "特征标签2"],
      "affiliations": [
        {{
          "org_name": "所属组织名（必须与 organizations 中的 name 一致）",
          "position": "职位，如'外门弟子'、'长老'、'帮主'，无法判断填null",
          "change": "joined/left/promoted/expelled/active 之一",
          "reason": "变化原因，如'通过考核晋升'、'因叛变被逐'、'主动退出宗门'，无变化或无法判断填null"
        }}
      ]
    }}
  ],
  "organizations": [
    {{
      "name": "组织名",
      "organization_type": "类型，如'宗门'、'家族'、'商会'、'势力'，无法判断填null",
      "organization_purpose": "组织宗旨或性质，一句话，无法判断填null",
      "personality": "组织风格/氛围，如'纪律严明'、'唯利是图'，无法判断填null",
      "appearance": "外在特征，如'统一白袍、佩剑'，无描写填null",
      "location": "所在地点，如'青云山'，无法判断填null",
      "known_members": ["本章明确提到的成员名字"],
      "traits": ["特征标签1", "特征标签2"],
      "background": "一句话描述其在本章的作用"
    }}
  ]
}}
```"""

    def __init__(self, ai_service: AIService):
        self.ai_service = ai_service
        logger.info("✅ PlotAnalyzer initialized")

    def _model_kwargs(self) -> Dict[str, Any]:
        """配了分析模型（设置 → 分析模型）就走它：分析 / 抽取占每章一半调用量，用便宜快模型即可。"""
        model = getattr(self.ai_service, "analysis_model", None)
        return {"model": model} if isinstance(model, str) and model.strip() else {}

    @classmethod
    def build_open_promise_block(cls, open_promises: Optional[List[Any]]) -> tuple[str, Dict[str, str]]:
        """把未回收承诺渲染成带短编号（P1…）的清单，返回 (文本, 短编号 → 真实 id)。"""
        if not open_promises:
            return "", {}
        lines = ["【当前未回收的伏笔 / 承诺（本章推进或回收了其中某条，必须回填它的编号）】"]
        mapping: Dict[str, str] = {}
        for index, item in enumerate(list(open_promises)[: cls.OPEN_PROMISE_LIMIT], start=1):
            short_id = f"P{index}"
            mapping[short_id] = str(getattr(item, "id", "") or "")
            deadline = getattr(item, "deadline_chapter", None)
            plan = f"，计划第{deadline}章前回收" if deadline else ""
            lines.append(
                f"- {short_id} [{getattr(item, 'promise_type', '') or 'promise'}/{getattr(item, 'priority', '') or 'medium'}] "
                f"{getattr(item, 'title', '')}（第{getattr(item, 'source_chapter_number', '?')}章起{plan}）："
                f"{str(getattr(item, 'content', '') or '')[:60]}"
            )
        return "\n".join(lines), mapping

    @staticmethod
    def _map_promise_ids(result: Dict[str, Any], mapping: Dict[str, str]) -> None:
        """模型回填的短编号 → 真实 id；清单外的编号一律置空（宁可新建也不能错关别的伏笔）。"""
        real_ids = set(mapping.values())
        for section in ("narrative_promises", "foreshadows"):
            for item in result.get(section) or []:
                if not isinstance(item, dict):
                    continue
                for key in ("resolves_promise_id", "advances_promise_id"):
                    raw = str(item.get(key) or "").strip()
                    if not raw:
                        item[key] = None
                    elif raw.upper() in mapping:
                        item[key] = mapping[raw.upper()]
                    else:
                        item[key] = raw if raw in real_ids else None

    async def extract_entities(
        self,
        chapter_number: int,
        title: str,
        content: str,
    ) -> Optional[Dict[str, Any]]:
        """Extract characters and organizations from chapter text (lightweight, parallel-safe)."""
        try:
            logger.info("👥 开始提取第%s章实体...", chapter_number)
            extraction_content = content[:6000] if len(content) > 6000 else content
            prompt = self.ENTITY_EXTRACTION_PROMPT.format(
                chapter_number=chapter_number,
                title=title,
                content=extraction_content,
            )

            chunks: list[str] = []
            async for chunk in self.ai_service.generate_text_stream(
                prompt=prompt,
                temperature=0.1,
                **self._model_kwargs(),
            ):
                chunks.append(chunk)

            response_text = "".join(chunks)
            if not response_text:
                logger.warning("⚠️ 实体提取返回为空")
                return None

            from app.utils.json_cleaner import safe_parse_json
            result = safe_parse_json(response_text, default=None)
            if not result:
                logger.warning("⚠️ 实体提取JSON解析失败")
                return None

            chars = result.get("characters", [])
            orgs = result.get("organizations", [])
            logger.info("✅ 第%s章实体提取完成: %s个人物, %s个组织", chapter_number, len(chars), len(orgs))
            return result
        except Exception as exc:
            logger.error("⚠️ 实体提取异常(非致命): %s", exc)
            return None

    async def analyze_chapter(
        self,
        chapter_number: int,
        title: str,
        content: str,
        word_count: int,
        open_promises: Optional[List[Any]] = None,
        planned_tasks: str = "",
        known_characters: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Analyze one chapter and return normalized JSON payload.

        open_promises：本章之前仍未回收的承诺（ORM 或同形对象）。带短编号进提示词，模型回收 / 推进时回填编号，
        这里映射回真实 id——narrative_state_service 据此精确关闭，不再按标题模糊猜。
        planned_tasks：本章章纲计划的叙事任务（要埋 / 要回收什么，计划回收章），供模型填 deadline_chapter。
        known_characters：已登记角色正式名，减少别名导致的建档重复与状态错挂。
        """
        try:
            logger.info("📳 开始分析第%s章: %s", chapter_number, title)
            analysis_content = content[:8000] if len(content) > 8000 else content
            promise_block, mapping = self.build_open_promise_block(open_promises)
            context_parts = [promise_block]
            if planned_tasks and planned_tasks.strip():
                context_parts.append(f"【本章计划叙事任务（章纲）】\n{planned_tasks.strip()}")
            if known_characters:
                names = "、".join(n for n in known_characters[:60] if n)
                if names:
                    context_parts.append(f"【已登记角色正式名（输出人名优先用这些）】\n{names}")
            context_block = "\n\n".join(p for p in context_parts if p)
            prompt = self.ANALYSIS_PROMPT.format(
                chapter_number=chapter_number,
                title=title,
                word_count=word_count,
                content=analysis_content,
                context_block=f"\n{context_block}\n" if context_block else "",
            )

            logger.info("  调用 AI 分析(内容长度: %s字, 流式模式)...", len(analysis_content))
            chunks: list[str] = []
            async for chunk in self.ai_service.generate_text_stream(
                prompt=prompt,
                temperature=0.3,
                **self._model_kwargs(),
            ):
                chunks.append(chunk)

            response_text = "".join(chunks)
            if not response_text:
                logger.error("❌ AI 返回为空")
                return None

            analysis_result = self._parse_analysis_response(response_text)
            if not analysis_result:
                logger.error("❌ 分析结果解析失败")
                return None
            self._map_promise_ids(analysis_result, mapping)

            logger.info(
                "✅ 第%s章分析完成: hooks=%s foreshadows=%s plot_points=%s causal=%s promises=%s",
                chapter_number,
                len(analysis_result.get("hooks", [])),
                len(analysis_result.get("foreshadows", [])),
                len(analysis_result.get("plot_points", [])),
                len(analysis_result.get("causal_links", [])),
                len(analysis_result.get("narrative_promises", [])),
            )
            return analysis_result
        except Exception as exc:
            logger.error("❌ 章节分析异常: %s", exc)
            return None

    def _parse_analysis_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse and normalize LLM JSON output."""
        from app.utils.json_cleaner import safe_parse_json

        result = safe_parse_json(
            response,
            default=None,
            expected_type="object",
            log_prefix="[章节分析]",
        )
        if result is None:
            return None

        result.setdefault("summary", "")
        result.setdefault("hooks", [])
        result.setdefault("foreshadows", [])
        result.setdefault("conflict", {})
        result.setdefault("emotional_arc", {})
        result.setdefault("character_states", [])
        result.setdefault("plot_points", [])
        result.setdefault("scenes", [])
        result.setdefault("pacing", "moderate")
        result.setdefault("dialogue_ratio", 0.0)
        result.setdefault("description_ratio", 0.0)
        result.setdefault("scores", {})
        result.setdefault("plot_stage", "发展")
        result.setdefault("suggestions", [])
        result.setdefault("causal_links", [])
        result.setdefault("narrative_promises", [])
        result.setdefault("relationship_deltas", [])
        result.setdefault("timeline_events", [])
        result.setdefault("knowledge_changes", [])
        signals = result.get("continuity_signals")
        if not isinstance(signals, dict):
            signals = {}
            result["continuity_signals"] = signals
        for key in self.CONTINUITY_SIGNAL_KEYS:
            if not isinstance(signals.get(key), list):
                signals[key] = []
        if not isinstance(result.get("story_time"), str):
            result["story_time"] = ""

        for field in ("pacing", "engagement", "coherence", "overall"):
            result["scores"].setdefault(field, 0)

        return result

    def extract_memories_from_analysis(
        self,
        analysis: Dict[str, Any],
        chapter_id: str,
        chapter_number: int,
        chapter_content: str = "",
        chapter_title: str = "",
    ) -> List[Dict[str, Any]]:
        """Extract searchable memory fragments from analysis result."""
        memories: List[Dict[str, Any]] = []

        try:
            chapter_summary = ""
            if analysis.get("summary"):
                chapter_summary = analysis["summary"]
            elif analysis.get("plot_points"):
                plot_summaries = [item.get("content", "") for item in analysis["plot_points"][:3]]
                chapter_summary = "；".join([item for item in plot_summaries if item])
            elif chapter_content:
                chapter_summary = chapter_content[:300] + ("..." if len(chapter_content) > 300 else "")

            if chapter_summary:
                memories.append(
                    {
                        "type": "chapter_summary",
                        "content": chapter_summary,
                        "title": f"第{chapter_number}章《{chapter_title}》摘要",
                        "metadata": {
                            "chapter_id": chapter_id,
                            "chapter_number": chapter_number,
                            "importance_score": 0.6,
                            "tags": ["摘要", "章节概览", chapter_title],
                            "is_foreshadow": 0,
                            "text_position": 0,
                            "text_length": len(chapter_summary),
                        },
                    }
                )

            for hook in analysis.get("hooks", []):
                if int(hook.get("strength", 0) or 0) < 6:
                    continue

                keyword = hook.get("keyword", "")
                position, length = self._find_text_position(chapter_content, keyword)
                memories.append(
                    {
                        "type": "hook",
                        "content": f"[{hook.get('type', 'unknown')}] {hook.get('content', '')}",
                        "title": f"{hook.get('type', 'hook')} - {hook.get('position', '')}",
                        "metadata": {
                            "chapter_id": chapter_id,
                            "chapter_number": chapter_number,
                            "importance_score": min(float(hook.get("strength", 5) or 5) / 10.0, 1.0),
                            "tags": [hook.get("type", "hook"), hook.get("position", "")],
                            "is_foreshadow": 0,
                            "keyword": keyword,
                            "text_position": position,
                            "text_length": length,
                            "strength": hook.get("strength", 5),
                            "position_desc": hook.get("position", ""),
                        },
                    }
                )

            for foreshadow in analysis.get("foreshadows", []):
                is_planted = foreshadow.get("type") == "planted"
                keyword = foreshadow.get("keyword", "")
                position, length = self._find_text_position(chapter_content, keyword)
                memories.append(
                    {
                        "type": "foreshadow",
                        "content": foreshadow.get("content", ""),
                        "title": "埋下伏笔" if is_planted else "回收伏笔",
                        "metadata": {
                            "chapter_id": chapter_id,
                            "chapter_number": chapter_number,
                            "importance_score": min(float(foreshadow.get("strength", 5) or 5) / 10.0, 1.0),
                            "tags": ["伏笔", foreshadow.get("type", "planted")],
                            "is_foreshadow": 1 if is_planted else 2,
                            "reference_chapter": foreshadow.get("reference_chapter"),
                            "keyword": keyword,
                            "text_position": position,
                            "text_length": length,
                            "foreshadow_type": foreshadow.get("type", "planted"),
                            "strength": foreshadow.get("strength", 5),
                        },
                    }
                )

            for plot_point in analysis.get("plot_points", []):
                if float(plot_point.get("importance", 0) or 0) < 0.6:
                    continue

                keyword = plot_point.get("keyword", "")
                position, length = self._find_text_position(chapter_content, keyword)
                memories.append(
                    {
                        "type": "plot_point",
                        "content": f"{plot_point.get('content', '')}。影响: {plot_point.get('impact', '')}",
                        "title": f"剧情点 - {plot_point.get('type', 'unknown')}",
                        "metadata": {
                            "chapter_id": chapter_id,
                            "chapter_number": chapter_number,
                            "importance_score": float(plot_point.get("importance", 0.5) or 0.5),
                            "tags": ["剧情点", plot_point.get("type", "unknown")],
                            "is_foreshadow": 0,
                            "keyword": keyword,
                            "text_position": position,
                            "text_length": length,
                        },
                    }
                )

            for char_state in analysis.get("character_states", []):
                char_name = char_state.get("character_name", "未知角色")
                memories.append(
                    {
                        "type": "character_event",
                        "content": (
                            f"{char_name}的状态变化: {char_state.get('state_before', '')} → "
                            f"{char_state.get('state_after', '')}。{char_state.get('psychological_change', '')}"
                        ),
                        "title": f"{char_name}的变化",
                        "metadata": {
                            "chapter_id": chapter_id,
                            "chapter_number": chapter_number,
                            "importance_score": 0.7,
                            "tags": ["角色", char_name, "状态变化"],
                            "related_characters": [char_name],
                            "is_foreshadow": 0,
                        },
                    }
                )

            conflict = analysis.get("conflict", {}) or {}
            if int(conflict.get("level", 0) or 0) >= 7:
                memories.append(
                    {
                        "type": "plot_point",
                        "content": f"重要冲突: {conflict.get('description', '')}",
                        "title": f"冲突 - 强度{conflict.get('level', 0)}",
                        "metadata": {
                            "chapter_id": chapter_id,
                            "chapter_number": chapter_number,
                            "importance_score": min(float(conflict.get("level", 5) or 5) / 10.0, 1.0),
                            "tags": ["冲突"] + [str(item) for item in (conflict.get("types", []) or [])],
                            "is_foreshadow": 0,
                        },
                    }
                )

            logger.info("📝 从分析中提取 %s 条记忆", len(memories))
            return memories
        except Exception as exc:
            logger.error("❌ 提取记忆失败: %s", exc)
            return []

    def _find_text_position(self, full_text: str, keyword: str) -> tuple[int, int]:
        """Find keyword position in chapter text."""
        if not keyword or not full_text:
            return (-1, 0)

        try:
            position = full_text.find(keyword)
            if position != -1:
                return (position, len(keyword))

            clean_keyword = re.sub(r"[，。！？、；：\"'（）《》【】]", "", keyword)
            clean_text = re.sub(r"[，。！？、；：\"'（）《》【】]", "", full_text)
            position = clean_text.find(clean_keyword)
            if position != -1:
                return (position, len(clean_keyword))

            if len(keyword) > 10:
                partial = keyword[: min(15, len(keyword))]
                position = full_text.find(partial)
                if position != -1:
                    return (position, len(partial))

            return (-1, 0)
        except Exception as exc:
            logger.error("查找位置失败: %s", exc)
            return (-1, 0)

    def generate_analysis_summary(self, analysis: Dict[str, Any]) -> str:
        """Generate a compact human-readable report."""
        try:
            scores = analysis.get("scores", {}) or {}
            hooks = analysis.get("hooks", []) or []
            foreshadows = analysis.get("foreshadows", []) or []
            causal_links = analysis.get("causal_links", []) or []
            promises = analysis.get("narrative_promises", []) or []

            lines = ["=== 章节分析报告 ===", ""]
            lines.append("【整体评分】")
            lines.append(f"  整体质量: {scores.get('overall', 'N/A')}/10")
            lines.append(f"  节奏把控: {scores.get('pacing', 'N/A')}/10")
            lines.append(f"  吸引力: {scores.get('engagement', 'N/A')}/10")
            lines.append(f"  连贯性: {scores.get('coherence', 'N/A')}/10")
            lines.append("")

            lines.append(f"【剧情阶段】{analysis.get('plot_stage', '未知')}")
            lines.append(f"【钩子数量】{len(hooks)}")
            lines.append(f"【伏笔数量】埋下 {sum(1 for item in foreshadows if item.get('type') == 'planted')} / 回收 {sum(1 for item in foreshadows if item.get('type') == 'resolved')}")
            lines.append(f"【因果链】{len(causal_links)}")
            lines.append(f"【叙事承诺】{len(promises)}")
            lines.append("")

            suggestions = analysis.get("suggestions", []) or []
            if suggestions:
                lines.append("【改进建议】")
                for index, suggestion in enumerate(suggestions, start=1):
                    lines.append(f"  {index}. {suggestion}")

            return "\n".join(lines)
        except Exception as exc:
            logger.error("❌ 生成分析摘要失败: %s", exc)
            return "分析摘要生成失败"


_plot_analyzer_instance: Optional[PlotAnalyzer] = None
