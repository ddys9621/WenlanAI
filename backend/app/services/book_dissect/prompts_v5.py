"""拆书 V5 prompt 模板。

约定：每个 user prompt 首行是 `【任务：xxx】` 标记（TASK_MARK_*），单测用它给 mock LLM 路由。
所有 prompt 只要求输出 JSON 对象，不要 Markdown；字符串里的引号一律用「」。
"""
from __future__ import annotations

# ============================================================
# S1 拆书卡
# ============================================================

TASK_MARK_CARD = "【任务：拆书卡】"

SYSTEM_CARD = """你是资深网文拆书编辑。任务：阅读给定的一批连续章节正文，为每一章产出一张「拆书卡」JSON。
规则：
1. 只输出一个 JSON 对象 {"cards":[...]}，不要解释、不要 Markdown 代码块、不要前后空白
2. 每章一张卡，chapter_number 必须用输入里的真实章号，一章都不能漏、不能多
3. 只写正文里确实发生的内容，不虚构；人名用正文中最规范的称呼，「已知角色」里有的优先复用
4. 字符串值里出现引号一律用「」，禁止英文双引号；禁止换行符
5. 章纲要具体（谁在哪做了什么、为什么、结果如何、章末停在哪），不写空泛评价
6. function_tags / pace / ending_hook_type 只能从给出的词表里选"""

CARD_PROMPT = TASK_MARK_CARD + """
{known_characters_block}{prior_outlines_block}
【功能标签词表（function_tags 只从这里选，可多选）】
开局立足 / 日常代入 / 信息差铺垫 / 危机铺垫 / 拉扯试探 / 爽点兑现 / 打脸 / 升级突破 / 战斗 / 善后收获 / 转场换地图 / 信息揭露 / 伏笔埋设 / 伏笔回收 / 情感推进 / 支线推进 / 过渡

【章末钩子类型词表】悬念 / 危机 / 反转 / 新谜团 / 信息揭露 / 期待 / 无

【输出 JSON 模板（字段名一字不差）】
{{"cards":[{{
 "chapter_number": 12,
 "title": "章节名",
 "outline": "章纲 300-500 字：起因→人物行动→冲突推进→关键信息→章末停在哪。写具体因果，不写评价",
 "function_tags": ["危机铺垫","拉扯试探"],
 "pace": "快|中|慢",
 "tension": 3,
 "emotion_tone": "情绪基调短语链，如：压抑+期待",
 "ending_hook_type": "词表之一",
 "ending_hook_text": "章末制造钩子的那 1-2 句原文，≤60 字；无钩子填空字符串",
 "payoff_points": ["本章兑现的爽点/反转/情感高点，一句一条；没有给 []"],
 "highlights": ["金句 / 梗 / 爆点 / 读者会截图的设计，1-4 条，可原文短句"],
 "characters": ["本章出场角色规范名（只写名字）"],
 "protagonist_delta": "主角本章的实力/身份/处境/认知/关系变化，无变化写「无」",
 "new_settings": ["本章首次出现的设定要素，格式「名称：一句话」；没有给 []"]
}}]}}

【本批章节正文】共 {count} 章，边界标记为 === 第 N 章 标题 ===
{full_text}"""


# ============================================================
# S2 情节单元
# ============================================================

TASK_MARK_ARC = "【任务：情节单元】"

SYSTEM_ARC = """你是网文结构分析师。下面是一段连续章节的「拆书卡」（不是正文）。请从窗口第一章开始，识别已经自然闭合的「情节单元」。
情节单元 = 一个相对完整的最小情节弧：有触发、有推进/加压、有转折或兑现、有阶段性结果。通常 2-8 章，不要按固定章数机械切。
规则：
1. 单元必须从窗口第一章开始；多个单元首尾相接，不跳章、不重叠
2. 窗口尾部仍在铺垫/对抗中、还没有阶段性结果的，不要硬凑成单元，写进 carryover_reason
3. 「是否最终窗口」为「是」时，尽量给尾部一个合理收束，只有明显未完成的才保留
4. 只依据拆书卡，不引入卡里没有的内容；保留具体信息：人名、势力、地点、法宝、冲突原因、结果、钩子
5. 只输出一个 JSON 对象，不要解释、不要 Markdown；字符串里的引号用「」，禁止换行符"""

ARC_PROMPT = TASK_MARK_ARC + """
【窗口范围】第 {start}-{end} 章　【单元最大章数】{max_len}　【是否最终窗口】{is_final}

【兑现方式词表（payoff_type 只选一个）】
打脸 / 扮猪吃虎 / 收获机缘 / 反差揭底 / 护人 / 绝境反杀 / 以弱胜强 / 反转揭示 / 情感兑现 / 规则破局 / 无强爽点

【章内位置词表（chapter_roles 的值）】intro(代入/信息差) / build(拉扯/加压) / payoff(兑现) / aftermath(善后/开启下一目标) / transition(过渡)

【输出 JSON 模板（字段名一字不差）】
{{"completed_arcs":[{{
 "start_chapter": {start},
 "end_chapter": 0,
 "title": "≤20 字短标题",
 "function": "该单元在全书中的功能：开局立足/危机铺垫/第一次爽点/打脸装逼/升级突破/资源争夺/支线开启/伏笔埋设/信息揭露/阶段收获/转场换地图…按实际填",
 "boundary_reason": "为什么在此闭合",
 "structure": "触发(第X章) -> 推进/加压(第X-Y章) -> 转折/兑现(第Z章) -> 收束或新困境(第W章)",
 "protagonist_chain": "目标 -> 判断 -> 行动 -> 阻碍 -> 调整 -> 结果",
 "emotion_curve": "压抑点(章) / 拉扯点(章) / 爆发点(章) / 余韵(章)",
 "payoff": "核心爽点或张力点是什么、怎么兑现；无强爽点时写它承担的功能",
 "payoff_type": "词表之一",
 "golden_finger_usage": "金手指/核心优势在本单元怎么用；无则「无」",
 "character_changes": "重要角色的行动、立场、关系变化",
 "gains_costs": "收获（实力/资源/人脉/信息）与代价",
 "foreshadowing": "新埋伏笔 / 回收伏笔 / 信息差 / 抛给下一单元的困境",
 "chapter_roles": {{"{start}":"intro"}},
 "tension_peak_chapter": {start}
}}],
"carryover_reason": "尾部未闭合的原因；没有写「无」"}}

【拆书卡窗口】
{cards_json}"""


# ============================================================
# S3 阶段划分 / 全书骨架 / 人物功能谱 / 写法手册
# ============================================================

TASK_MARK_STAGE = "【任务：阶段划分】"
TASK_MARK_SKELETON = "【任务：全书骨架】"
TASK_MARK_CHARACTERS = "【任务：人物功能谱】"
TASK_MARK_METHODOLOGY = "【任务：写法手册】"

SYSTEM_SKELETON = """你是资深网文编辑兼写作教练。你只依据给出的结构化材料（情节单元 / 阶段 / 拆书卡 / 统计）做归纳，不编造材料里没有的情节。
只输出一个 JSON 对象，不要解释、不要 Markdown；字符串里的引号用「」，禁止换行符。"""

STAGE_PROMPT = TASK_MARK_STAGE + """
下面是一本书按顺序编号的情节单元列表（本块第 {first}-{last} 个，全书共 {total} 个；{is_final_note}）。
请把它们划分成「阶段」（相当于卷 / 大副本）：每个阶段有一个贯穿的核心矛盾与主角目标，通常 5-15 个单元。
{open_stage_block}
规则：
1. 阶段必须从本块第一个单元开始，首尾相接覆盖到最后一个单元，arc_start / arc_end 用单元编号
2. 本块不是最终块时，最后一个阶段若尚未收束标 status=open；最终块所有阶段 status=closed
3. signature_arc 写成名战 / 巅峰战对应的单元编号与一句话

【输出 JSON 模板】
{{"stages":[{{"title":"阶段名","arc_start":{first},"arc_end":0,"core_conflict":"","protagonist_goal":"","key_upgrades":"实力/地位/资源的关键提升","signature_arc":"#编号 一句话","ending_hook":"阶段末悬念","status":"closed|open"}}]}}

【情节单元】
{arc_lines}"""

SKELETON_PROMPT = TASK_MARK_SKELETON + """
根据下列阶段划分、客观统计与开头三章拆书卡，梳理这本书的全书骨架。可以出现原书专有名词（这是给作者看的结构分析，不是仿写产物）。

【阶段划分】
{stages_json}

【客观统计】
{stats_brief}

【开头三章拆书卡】
{opening_cards}

【输出 JSON 模板】
{{"genre_tag":"题材标签","one_line_premise":"一句话讲清这是什么故事","main_conflict":"贯穿全书的大矛盾 + 主角为何无法回避",
 "golden_finger":{{"what":"金手指是什么","how_it_works":"怎么运作","evolution":["前期…","中期…","后期…"]}},
 "stages":[],
 "top_payoffs":[{{"stage":"所在阶段","arcs":"#编号","buildup":"压抑铺垫","trigger":"爆发/转折机制","reward":"收获与成长"}}],
 "growth_system":"主角从弱到强的路径：境界/资源/地位里程碑",
 "power_system":"力量体系/规则梳理（无则「无」）",
 "long_foreshadowing":[{{"setup":"埋在哪","payoff":"揭在哪","role":"作用"}}],
 "reading_promise":"卖点 / 读者预期：爽点类型、密度、情绪回报",
 "opening_strategy":"黄金三章怎么做的：第 1-3 章各干了什么、钩子在哪"}}
top_payoffs ≤5 条、long_foreshadowing ≤8 条；stages 可原样返回或合并相邻阶段。"""

CHARACTERS_PROMPT = TASK_MARK_CHARACTERS + """
根据阶段划分、各情节单元的「角色与关系变化」以及角色出场频次，归纳这本书的人物功能谱：不是罗列人物，而是每个人物在结构里承担什么功能、作者怎么用他。

【阶段划分】
{stages_json}

【角色出场频次（名字｜出场章数｜首末章）】
{character_freq}

【各单元角色与关系变化】
{arc_changes}

【输出 JSON 模板】
{{"protagonist":{{"name":"","persona":"人设三句话","golden_finger":"","flaws_and_pressure":"缺陷与持续压力来源","growth_track":[{{"stage":"阶段名","state":"该阶段末的实力/身份/心态"}}]}},
 "allies":[{{"name":"","function_role":"导师/兄弟/红颜/工具人/见证者…","arc_span":"第X-Y章","technique":"作者怎么用这个人推剧情或衬主角"}}],
 "antagonists":[{{"name":"","tier":"小反派/阶段反派/终极反派","conflict_nature":"","escalation":"如何递进","outcome":""}}],
 "function_slots":[{{"slot":"见证者/压力来源/误导者/秩序维护者/隐藏布局者…","how_used":""}}]}}
allies ≤8、antagonists ≤6、function_slots ≤6。"""

METHODOLOGY_PROMPT = TASK_MARK_METHODOLOGY + """
根据下列全书骨架、客观统计与开头三章拆书卡，反推这本书的写法手册。每一条都要有 evidence（引用章号或单元编号），writing_tips 是给作者的可执行建议（80-180 字）。

【全书骨架】
{skeleton_json}

【客观统计】
{stats_brief}

【开头三章拆书卡】
{opening_cards}

【输出 JSON 模板】
{{"golden_finger_pattern":{{"pattern":"金手指的使用模式","evidence":"","writing_tips":""}},
 "opening_hook_pattern":{{"pattern":"开篇怎么钩住读者","evidence":"","writing_tips":""}},
 "facepunch_rhythm":{{"pattern":"压抑→兑现的节奏（几章一压、几章一放）","evidence":"","writing_tips":""}},
 "power_progression":{{"pattern":"升级颗粒度与触发方式","evidence":"","writing_tips":""}},
 "highlight_density":{{"pattern":"爽点密度与章末钩子习惯","evidence":"","writing_tips":""}}}}"""


# ============================================================
# S4 文风定性 / 例句
# ============================================================

TASK_MARK_STYLE = "【任务：文风定性】"
TASK_MARK_EXCERPT = "【任务：文风例句】"

SYSTEM_STYLE = """你是资深网文编辑。只依据给出的正文样本与客观统计描述作者笔法，不评价内容好坏。
只输出一个 JSON 对象，不要解释、不要 Markdown；字符串里的引号用「」，禁止换行符。"""

STYLE_PROMPT = TASK_MARK_STYLE + """
下面是同一本书若干章的正文样本（各章开头与中段）与全书客观统计。请提炼作者的写作风格，生成一段可直接作为 LLM 写作指令使用的「文风提示词」。

【客观统计】
{metrics_brief}

【正文样本】
{samples}

【输出 JSON 模板】
{{"name":"风格名（≤8 字）","description":"风格一句话描述",
 "prompt_content":"可直接注入写作 prompt 的文风指令，300-600 字：句式节奏 / 段落长度 / 对话与叙述比例 / 叙述视角与贴近程度 / 描写层次 / 情绪表达方式 / 用词习惯（举 3-5 个原文用词或句式例子）",
 "traits":["特征短语 4-8 条"],
 "dialogue_style":"对话风格：标签用法、长短、潜台词",
 "narration_habits":"叙述习惯：视角、内心独白、镜头感",
 "avoid_list":["该作者明显不用的写法 2-5 条"]}}"""

EXCERPT_PROMPT = TASK_MARK_EXCERPT + """
从下面这一章正文里**原样摘出** 2 段最能代表作者笔法的片段，每段 150-300 字，一个字都不能改、不能拼接不相邻的句子。
本章类型提示：{kind_hint}。kind 从 opening / dialogue / action / payoff / ending_hook / description 里选。

【输出 JSON 模板】
{{"excerpts":[{{"kind":"payoff","text":"原文片段"}}]}}

【第{chapter_number}章正文】
{chapter_text}"""
