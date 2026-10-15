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
# S2 剧情单元（对应卷纲里的「一件事」）
# ============================================================

TASK_MARK_ARC = "【任务：剧情单元】"

SYSTEM_ARC = """你是网文结构分析师。下面是一段连续章节的「拆书卡」（不是正文）。请从窗口第一章开始，识别已经自然闭合的「剧情单元」。
剧情单元 = 一件完整的事：有起因，经过里有阻碍、选择和代价，有阶段性的结果，结束时局面发生了变化。长短按事件大小定（通常 2-8 章），不要按固定章数机械切。
规则：
1. 单元必须从窗口第一章开始；多个单元首尾相接，不跳章、不重叠
2. 窗口尾部这件事还没有结果的，不要硬凑成单元，写进 carryover_reason
3. 「是否最终窗口」为「是」时，尽量给尾部一个合理收束，只有明显未完成的才保留
4. 只依据拆书卡，不引入卡里没有的内容；保留具体信息：人名、势力、地点、物品、冲突原因、结果、钩子
5. 主角靠什么推进就如实写（选择、智谋、关系、能力、代价……）；这件事里没用到特殊能力就不要硬写
6. 只输出一个 JSON 对象，不要解释、不要 Markdown；字符串里的引号用「」，禁止换行符"""

ARC_PROMPT = TASK_MARK_ARC + """
【窗口范围】第 {start}-{end} 章　【单元最大章数】{max_len}　【是否最终窗口】{is_final}

【兑现方式词表（payoff_type 只选一个）】
成长突破 / 智斗破局 / 反转揭示 / 真相揭秘 / 情感推进 / 关系转变 / 配角高光 / 打脸逆袭 / 以弱胜强 / 收获机缘 / 失去与代价 / 缓和过渡

【章内位置词表（chapter_roles 的值）】open(开启：起因 / 新麻烦) / advance(推进：阻碍、选择、代价) / turn(转折或兑现) / close(收束：结果与余波) / transition(过渡 / 缓和)

【输出 JSON 模板（字段名一字不差）】
{{"completed_arcs":[{{
 "start_chapter": {start},
 "end_chapter": 0,
 "title": "≤20 字短标题",
 "function": "这件事在全书中的作用：开局立足 / 引出主线 / 铺设危机 / 第一次正面冲突 / 成长突破 / 关系推进 / 揭开秘密 / 转换舞台 / 阶段收获 / 缓和过渡…按实际填",
 "boundary_reason": "为什么在此闭合",
 "story": "这件事的经过（自然段，80-200 字）：起因 → 经过（阻碍、选择、代价）→ 结果",
 "structure": "落到章：起因(第X章) -> 推进(第X-Y章) -> 转折/兑现(第Z章) -> 收束(第W章)",
 "approach": "主角靠什么推进 / 解决：选择、智谋、关系、能力、代价…；用了特殊能力就写清怎么用、受什么限制",
 "turn": "单元结束时局面怎样变化：处境 / 关系 / 实力 / 掌握的信息",
 "emotion_curve": "压抑点(章) / 拉扯点(章) / 高点(章) / 余韵(章)",
 "payoff": "这件事的高点是什么、怎么兑现；缓和过渡的单元写它承担的作用",
 "payoff_type": "词表之一",
 "character_changes": "重要角色的行动、立场、关系变化",
 "gains_costs": "收获（实力 / 资源 / 人脉 / 信息）与代价",
 "foreshadowing": "新埋伏笔 / 回收伏笔 / 信息差 / 抛给下一件事的困境",
 "chapter_roles": {{"{start}":"open"}},
 "tension_peak_chapter": {start}
}}],
"carryover_reason": "尾部未闭合的原因；没有写「无」"}}

【拆书卡窗口】
{cards_json}"""


# ============================================================
# S3 分卷 / 全书骨架 / 人物功能谱 / 写法手册
# 产物与作者自己的 总纲 → 卷纲（剧情单元 + 线索）→ 章纲 一一对应，方便对照着写
# ============================================================

TASK_MARK_VOLUME = "【任务：分卷】"
TASK_MARK_SKELETON = "【任务：全书骨架】"
TASK_MARK_CHARACTERS = "【任务：人物功能谱】"
TASK_MARK_METHODOLOGY = "【任务：写法手册】"

SYSTEM_SKELETON = """你是资深网文编辑兼写作教练。你只依据给出的结构化材料（剧情单元 / 分卷 / 拆书卡 / 统计）做归纳，不编造材料里没有的情节。
只输出一个 JSON 对象，不要解释、不要 Markdown；字符串里的引号用「」，禁止换行符。"""

VOLUME_PROMPT = TASK_MARK_VOLUME + """
下面是一本书按顺序编号的剧情单元列表（本块第 {first}-{last} 个，全书共 {total} 个；{is_final_note}）。
请把它们划分成「卷」：每卷是一个新的局面（新的舞台、对手层级或目标），有贯穿全卷的目标与冲突，卷末有高潮和把读者带进下一卷的钩子。通常 5-15 个单元一卷。
{open_volume_block}
规则：
1. 卷必须从本块第一个单元开始，首尾相接覆盖到最后一个单元，arc_start / arc_end 用单元编号
2. 本块不是最终块时，最后一卷若尚未收束标 status=open；最终块所有卷 status=closed
3. climax 写本卷高潮对应的单元编号与一句话
4. threads 写本卷推进的感情线 / 支线 / 伏笔，每条「名称：从哪推进到哪」；没有给 []

【输出 JSON 模板】
{{"volumes":[{{"title":"卷名","arc_start":{first},"arc_end":0,"summary":"本卷故事（自然段）","goal":"主角本卷的目标与核心冲突","climax":"#编号 一句话","ending_hook":"卷末钩子","threads":["感情线：从相识到并肩"],"growth":"主角本卷的成长与收获","status":"closed|open"}}]}}

【剧情单元】
{arc_lines}"""

SKELETON_PROMPT = TASK_MARK_SKELETON + """
根据下列分卷、客观统计与开头三章拆书卡，梳理这本书的全书骨架（相当于作者写书时的「总纲」）。可以出现原书专有名词（这是给作者看的结构分析，不是仿写产物）。

【分卷】
{volumes_json}

【客观统计】
{stats_brief}

【开头三章拆书卡】
{opening_cards}

【输出 JSON 模板】
{{"genre_tag":"题材标签","premise":"故事梗概（3-5 句）",
 "main_plot":"全书主线（自然段，300-600 字）：主角在什么处境下做了什么选择、别人怎样回应、结果如何、又引出什么，一直讲到结局或目前进度",
 "main_conflict":"贯穿全书的大矛盾 + 主角为何无法回避",
 "golden_finger":{{"what":"主角的特殊能力 / 核心优势","how_it_works":"怎么运作","limits":"限制与代价","evolution":["前期…","中期…","后期…"]}},
 "selling_points":["卖点 / 读者预期，一句一条"],
 "main_tropes":["主要套路 / 看点类型"],
 "growth_route":"主角的成长路线：实力 / 地位 / 心境的里程碑",
 "power_system":"力量体系 / 规则梳理（无则「无」）",
 "ultimate_goal":"主角的终极目标",
 "volumes":[],
 "high_points":[{{"volume":"所在卷","arcs":"#编号","setup":"铺垫","trigger":"转折或爆发的机制","result":"结果与变化"}}],
 "long_foreshadowing":[{{"setup":"埋在哪","payoff":"揭在哪","role":"作用"}}],
 "opening_strategy":"黄金三章怎么做的：第 1-3 章各干了什么、钩子在哪"}}
主角没有特殊能力时 golden_finger 直接写「无」，不要硬编；high_points ≤5 条、long_foreshadowing ≤8 条、selling_points ≤5 条；volumes 可原样返回或合并相邻卷。"""

CHARACTERS_PROMPT = TASK_MARK_CHARACTERS + """
根据分卷、各剧情单元的「角色与关系变化」以及角色出场频次，归纳这本书的人物功能谱：不是罗列人物，而是每个人物在结构里承担什么功能、作者怎么用他。

【分卷】
{volumes_json}

【角色出场频次（名字｜出场章数｜首末章）】
{character_freq}

【各单元角色与关系变化】
{arc_changes}

【输出 JSON 模板】
{{"protagonist":{{"name":"","persona":"人设三句话","advantage":"核心优势或特殊能力；没有写「无」","flaws_and_pressure":"缺陷与持续压力来源","growth_track":[{{"volume":"卷名","state":"该卷末的实力 / 身份 / 心态"}}]}},
 "allies":[{{"name":"","function_role":"导师 / 兄弟 / 红颜 / 工具人 / 见证者…","arc_span":"第X-Y章","technique":"作者怎么用这个人推剧情或衬主角"}}],
 "antagonists":[{{"name":"","tier":"小反派 / 卷反派 / 终极反派","conflict_nature":"","escalation":"如何递进","outcome":""}}],
 "function_slots":[{{"slot":"见证者 / 压力来源 / 误导者 / 秩序维护者 / 隐藏布局者…","how_used":""}}]}}
allies ≤8、antagonists ≤6、function_slots ≤6。"""

METHODOLOGY_PROMPT = TASK_MARK_METHODOLOGY + """
根据下列全书骨架、客观统计与开头三章拆书卡，反推这本书的写法手册。每一条都要有 evidence（引用章号或单元编号），writing_tips 是给作者写自己的书时可执行的建议（80-180 字）。

【全书骨架】
{skeleton_json}

【客观统计】
{stats_brief}

【开头三章拆书卡】
{opening_cards}

【输出 JSON 模板】
{{"opening_pattern":{{"pattern":"开篇怎么钩住读者","evidence":"","writing_tips":""}},
 "volume_rhythm":{{"pattern":"分卷节奏：每卷换什么局面、卷末高潮与钩子怎么做","evidence":"","writing_tips":""}},
 "unit_design":{{"pattern":"剧情单元怎么设计：一件事多长、起因-经过-结果怎么铺、怎么接到下一件事","evidence":"","writing_tips":""}},
 "tension_rhythm":{{"pattern":"张弛节奏：几章一压几章一放、紧张与缓和怎么交替、兑现方式怎么换着来","evidence":"","writing_tips":""}},
 "growth_progression":{{"pattern":"成长颗粒度：主角多久变强 / 变化一次、靠什么触发","evidence":"","writing_tips":""}},
 "advantage_usage":{{"pattern":"特殊能力 / 核心优势怎么用：出现频率、刻意不用的时候、限制与代价；没有特殊能力就写这本书靠什么推进","evidence":"","writing_tips":""}}}}"""


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
