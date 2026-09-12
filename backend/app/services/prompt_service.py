"""提示词管理服务"""
from typing import Dict, Optional


# 章节正文两个模板（CHAPTER_GENERATION / CHAPTER_GENERATION_WITH_CONTEXT）共用的开头人设。
CHAPTER_WRITER_PERSONA = (
    "你是一个在起点、番茄这类平台写了几百万字的网文老作者，习惯日更，写出来的东西读者在手机上刷着看不费劲。"
    "下面是这本书的设定和本章要写的东西：设定、章纲、剧情卡是硬约束，文风按「叙事与文风要求」来。照着写这一章："
)

# 章节正文两个模板共用的文风段（创作要求第 5 条，编号由模板加）。用 str.format 填充，只允许出现
# {narrative_perspective} / {perspective_boundary_clause} 两个占位符，其余花括号要写成 {{ }}。
# 顺序刻意排成：形态（段落 / 对话）→ 口吻 → 用词 → 结尾 → 样张。形态是读者第一眼能看出"像不像网文"的东西，放最前。
# 其他正文入口（章节重生成等）用 PromptService.render_chapter_style_rules 拿填好视角的版本。
CHAPTER_STYLE_RULES = """**叙事与文风要求：网文大白话（重点，和章纲同等重要）**：
   - 用【{narrative_perspective}】视角稳稳讲故事，不来回切视角（细则见上方「叙事视角指导」）
   {perspective_boundary_clause}
   - 类型基调按上方「类型特色指导」里的爽点和雷区来
   - 读者是在手机上刷着看的，读起来要像起点、番茄上的连载，不是文学散文，也不是作文

   **段落和对话（形态是第一眼的事，先把这几条做到）：**
   - 一段最多三句，多数段落不超过 60 字；一句话单独成段随时可以用，关键的动作、转折、反应更要单独成段
   - 对话每人一段，说话人的动作跟他的话放在同一段；全章对话占四到六成，剧情尽量靠人说话、做事往前推，不靠叙述交代
   - 说话标记用"说、道"就行，或者干脆不写，让上下文说明谁在说；不要轮着换"低声道、沉声道、淡淡道"
   - 环境描写一处最多两句，写完马上回到人身上；开头不要"时间+地点+天气+外貌"的建立镜头，直接进入正在发生的事
   - 短句为主，这是网文的底子；但要长短参差，短句里隔几句夹一句长的。别连续三句一样长（全是十来个字的碎句也算），也别连着长句、工整排比——句长整齐才是机器味

   **叙述口吻（叙述就是主角在心里说话）：**
   - 第三人称也要贴着主角的嘴走：他怎么想、怎么骂、怎么吐槽，叙述就用他那套词。"他心里一沉。这事儿不对。"是网文；"他心中泛起一丝不安"不是
   - 主角的内心话直接写出来，不加引号、不加"他想"，一句成段：「行吧。」「等等，不对。」「这货怕是有毛病。」
   - 情绪先写他做了什么，再直接点名"他慌了""她有点烦"；胸口发紧、冷汗、心跳这类身体渲染一章最多留一两处
   - 描写以"人做了什么 / 看到了什么 / 听到了什么 / 说了什么"为主；数字、境界、价钱、还剩几天，直接说出来，不藏在形容词后面
   - 不跳出来总结道理、升华主题，不写议论文和鸡汤；"信念、命运、本质、真理"这类大词不用
   - 主角的大愿望、人生使命不说破，用动作带：不写"他决心保护村民"，写"他看了眼村子的方向，把刀重新别回腰上"

   **用词（书面词换成嘴上会说的；成群出现才算问题，偶尔一个不用管）：**
   - 随即 / 旋即 / 径自 → 然后 / 马上 / 直接
   - 俨然 / 宛如 / 恍若 / 犹如 → 像 / 跟……一样
   - 些许 / 几分 / 颇为 / 甚是 / 略显 → 有点 / 挺 / 特别
   - 须臾 / 刹那间 / 霎时 → 一下子 / 眨眼 / 立马
   - 眸 / 眼眸 / 唇角 / 指尖 / 发丝 → 眼 / 嘴角 / 手指 / 头发
   - 氤氲 / 斑驳 / 静谧 / 寂寥 / 黯淡 → 不用，直接写看见的东西
   - 心底蔓延 / 涌起 / 泛起 / 弥漫 → 心里一沉 / 一紧 / 不是滋味 / 有点慌

   **章节结尾：**
   - 停在一个具体的动作、一句话或一个声音上，最好是钩子：新人物进门、坏消息到了、有人话说了半句
   - 不写"他知道，未来……"的预告，不写"道心坚定""一往无前""无论前方有多少艰难险阻"式的升华，不用排比总结心理变化
   - 不走"主角想明白了 → 自己做了选择 → 接受了"三件套；事情可以只解决一半，宁可早收一拍

   **样张（只学段落形态和口气；里面的人名、情节、道具一个都不许出现在正文里，视角按本书设定）：**
   改前——文学腔，别这么写：
   夜色如墨。林川伫立在门前，寒风裹挟着雪粒拍打在他的脸上，心中涌起一股难以名状的复杂情绪。三年了，他终于回到了这个曾让他饱受屈辱的地方。他缓缓握紧拳头，指节泛白，仿佛在无声地宣誓着什么。
   改后——网文腔，要这么写：
   林川在门口站了一会儿，没进去。
   三年了。门上那道裂口还在，当年他被人踹出来的时候撞的。
   他伸手摸了摸，笑了一下。
   行，路还认得就行。
   “谁啊？”里面有人喊，“大晚上的，不进来就滚。”
   是老张。嗓门比三年前还大。
   林川没吭声，抬脚把门踹开了。
   句子对照（左边的写法换成右边的）：
   「他的心中涌起一股难以名状的情绪」→「他心里有点不是滋味」
   「她缓缓抬起头，眸中闪过一丝复杂」→「她抬头看了他一眼，没说话」
   「他随即转身，径自离去」→「他转身就走」
   「一种莫名的不安在心底蔓延」→「不对。这事儿有问题。」
   「众人皆是一惊，面面相觑」→「一屋子人全愣了」
   「他深吸一口气，眼神逐渐坚定」→「他想了想。去。」"""

# 章节正文的收尾：先复述一遍网文形态（模型落笔前最后读到的东西），再给输出格式指令。
# apply_style_to_prompt 会把项目风格插到这段前面，所以它必须是模板的最后一段。
CHAPTER_OUTPUT_INSTRUCTION = "请直接输出章节正文内容，不要包含章节标题和其他说明文字。"
CHAPTER_CLOSING = (
    "落笔前再看一眼：段落短、对话多、叙述用主角的口气、环境两句带过、书面词换成嘴上的词、结尾停在钩子上。\n\n"
    + CHAPTER_OUTPUT_INSTRUCTION
)


class WritingStyleManager:
    """写作风格管理器"""
    
    # 预设风格配置
    # 预设是叠在正文文风段（网文大白话）之上的口味微调，不能反过来把叙述拉回文学腔：
    # 段落短、对话多、叙述用主角口吻这几条各预设都不动，只调用词味道、情绪篇幅、画面密度。
    # 改这里的内容后，database._init_global_writing_styles 会按 preset_id 同步已落库的全局预设。
    PRESET_STYLES = {
        "natural": {
            "name": "自然流畅",
            "description": "像普通人讲事儿一样自然，不刻意修饰，有生活气息",
            "prompt_content": """
**自然流畅风格要求：**
- 用简单朴实的词叙述，不堆形容词，不用华丽辞藻
- 像跟朋友讲事儿一样往下说，该交代就交代，不刻意营造氛围
- 短句为主，长短错开，不排比
- 让读者读得顺，别让人觉得在"看文学作品"
"""
        },
        "classical": {
            "name": "古风韵味",
            "description": "古风味放在对话、称谓和物件里，叙述仍是白话短段",
            "prompt_content": """
**古风韵味风格要求：**
- 古风味放在对话和称谓里：对话半文半白，"在下 / 姑娘 / 前辈 / 奴婢 / 妾身"这类称呼按身份和时代来，不出现现代词
- 叙述仍是白话短段，不写骈文，不堆四字词和"之乎者也"
- 物件、吃穿、礼数用当时的东西写具体（茶盏、灯油、请安的规矩），韵味从这里出来，不靠形容词
- 诗词、典故只能从人物嘴里说出来，且要符合世界观，一章最多一处
"""
        },
        "modern": {
            "name": "现代简约",
            "description": "简洁明快的现代口语，直接表达，信息密度高",
            "prompt_content": """
**现代简约风格要求：**
- 语言简洁直接，直达重点，用现代口语
- 短句短段，节奏明快，信息密度高
- 环境和过渡一句带过，情节推得快
- 对话干脆，不寒暄
"""
        },
        "poetic": {
            "name": "情感细腻",
            "description": "情绪戏写足篇幅，但情绪写在动作和对话里，不靠景物和身体渲染",
            "prompt_content": """
**情感细腻风格要求：**
- 情绪戏多给篇幅：一次心动或一次崩溃可以写足一整场，但仍然是短段、有对话
- 情绪写在动作和话里（杯子放下了又端起来、话说了半句停住），该点名就直接点名（"他慌了""她不想见他"），不用胸口发紧、心跳加速这类身体渲染堆
- 主角的内心话直接写出来，一句成段，用嘴上会说的词
- 天气就是天气，景物不替人物说心情
"""
        },
        "concise": {
            "name": "精炼利落",
            "description": "惜字如金的简练风格，每句话都有用",
            "prompt_content": """
**精炼利落风格要求：**
- 每句话都要有作用，多余的描写和过渡直接删
- 多用动词，少用形容词和副词
- 对话干脆利落，不拖泥带水
- 环境点到为止，一处一句
- 用最少的字说最多的事
"""
        },
        "vivid": {
            "name": "画面感强",
            "description": "画面靠具体的动作和东西撑起来，一处一种感官",
            "prompt_content": """
**画面感强风格要求：**
- 画面靠具体的动作和东西：谁站在哪儿、手里拿着什么、往哪儿走，写清楚
- 一处只写一种感官，先写看到的和听到的，气味少用
- 比喻用日常的东西打（"像被人从背后踹了一脚"），不用文学化的意象
- 人物表情、动作写具体（"他嘴角抽了一下"），不写"神色复杂"这类概括
"""
        }
    }
    
    @classmethod
    def get_preset_style(cls, preset_id: str) -> Optional[Dict[str, str]]:
        """获取预设风格配置"""
        return cls.PRESET_STYLES.get(preset_id)
    
    @classmethod
    def get_all_presets(cls) -> Dict[str, Dict[str, str]]:
        """获取所有预设风格"""
        return cls.PRESET_STYLES
    
    @staticmethod
    def apply_style_to_prompt(base_prompt: str, style_content: str) -> str:
        """
        将写作风格应用到基础提示词中
        
        Args:
            base_prompt: 基础提示词
            style_content: 风格要求内容
            
        Returns:
            组合后的提示词
        """
        # 风格要求插在收尾段之前：既保持"落笔前复述 + 输出指令"是模型最后读到的内容，也避免尾句重复出现
        if base_prompt.endswith(CHAPTER_CLOSING):
            base_prompt = base_prompt[: -len(CHAPTER_CLOSING)].rstrip()
        return f"{base_prompt}\n\n{style_content}\n\n{CHAPTER_CLOSING}"


class PromptService:
    """提示词模板管理"""
    
    # 世界构建提示词
    WORLD_BUILDING = """你是一位资深的世界观设计师。请根据以下信息构建一个完整的小说世界观：

书名：{title}
主题：{theme}
类型：{genre}

请生成包含以下内容的世界构建框架：

1. **时间背景**：具体的时代设定、时间流逝特点、重要历史事件
2. **地理位置**：主要地点描述、地理环境特征、空间布局
3. **氛围基调**：整体氛围感觉、情感色彩、视觉风格
4. **世界规则**：基本运行法则、特殊设定、社会规则和禁忌、权力结构

要求：
- 与主题高度契合
- 设定要合理自洽
- 为故事发展提供支撑
- 具有独特性和吸引力

**重要格式要求：**
1. 只返回纯JSON格式，不要包含任何markdown标记、代码块标记或其他说明文字
2. 不要在JSON字符串值中使用中文引号（""''），请使用英文引号或直接省略引号
3. 专有名词和强调内容可以使用【】或《》标记，不要用引号

请严格按照以下JSON格式返回（每个字段为200-300字的文本描述）：
{{
  "time_period": "时间背景的详细描述，包括时代设定、时间特点、历史事件",
  "location": "地理位置的详细描述，包括主要地点、环境特征、空间布局",
  "atmosphere": "氛围基调的详细描述，包括整体氛围、情感色彩、视觉风格",
  "rules": "世界规则的详细描述，包括运行法则、特殊设定、社会规则、权力结构"
}}

再次强调：
1. 只返回纯JSON对象，不要有```json```这样的标记
2. 文本中不要使用中文引号（""），使用【】或《》代替
3. 不要有任何额外的文字说明"""

    # 批量角色生成提示词
    CHARACTERS_BATCH_GENERATION = """你是一位专业的角色设定师。请根据以下世界观和要求，生成{count}个立体丰满的角色和组织：

世界观信息：
- 时间背景：{time_period}
- 地理位置：{location}
- 氛围基调：{atmosphere}
- 世界规则：{rules}

主题：{theme}
类型：{genre}
特殊要求：{requirements}

【数量要求 - 必须严格遵守】
请精确生成{count}个实体，不多不少。数组中必须包含且仅包含{count}个对象。

实体类型分配：
- 至少1个主角（protagonist）
- 多个配角（supporting）
- 可以包含反派（antagonist）
- 可以包含1-2个**高影响力的重要组织**（势力等级应在70-95之间）

要求：
- 角色要符合世界观设定
- 性格和背景要有深度
- 角色之间要有关系网络
- 组织要有存在的合理性
- 所有实体要为故事服务

**重要格式要求：**
1. 只返回纯JSON数组格式，不要包含任何markdown标记、代码块标记或其他说明文字
2. 不要在JSON字符串值中使用中文引号（""''），请使用英文引号或【】《》标记
3. 专有名词和强调内容使用【】或《》，不要用引号

请严格按照以下JSON数组格式返回（每个角色为数组中的一个对象）：
[
  {{
    "name": "角色姓名",
    "age": 25,
    "gender": "男/女/其他",
    "is_organization": false,
    "role_type": "protagonist/supporting/antagonist",
    "personality": "性格特点的详细描述（100-200字），包括核心性格、优缺点、特殊习惯",
    "background": "背景故事的详细描述（100-200字），包括家庭背景、成长经历、重要转折",
    "appearance": "外貌描述（50-100字），包括身高、体型、面容、着装风格",
    "traits": ["特长1", "特长2", "特长3"],
    "relationships_array": [
      {{
        "target_character_name": "已生成的角色名称",
        "relationship_type": "关系类型（必须从以下选择：父亲/母亲/兄弟/姐妹/子女/配偶/恋人/师父/徒弟/朋友/同学/邻居/知己/上司/下属/同事/合作伙伴/敌人/仇人/竞争对手/宿敌）",
        "intimacy_level": 75,
        "description": "关系描述"
      }}
    ],
    "organization_memberships": [
      {{
        "organization_name": "已生成的组织名称",
        "position": "职位",
        "rank": 5,
        "loyalty": 80
      }}
    ]
  }},
  {{
    "name": "组织名称",
    "is_organization": true,
    "role_type": "supporting",
    "personality": "组织特性描述（100-200字），包括运作方式、核心理念、行事风格",
    "background": "组织背景（100-200字），包括建立历史、发展历程、重要事件",
    "appearance": "组织外在表现（50-100字），如总部位置、标志性建筑等",
    "organization_type": "组织类型",
    "organization_purpose": "组织目的",
    "organization_members": ["成员1", "成员2"],
    "power_level": 85,
    "location": "组织所在地或主要活动区域",
    "motto": "组织格言、口号或宗旨",
    "color": "组织代表颜色（如：深红色、金色、黑色等）",
    "traits": []
  }}
]

**组织生成要求（重要）：**
- 组织必须是对故事有重大影响的势力
- power_level应在70-95之间（高影响力组织）
- 不要生成无关紧要的小组织或普通社团
- 组织应该是推动剧情发展的关键力量
- 可以是正派势力、中立势力或反派势力，但一定要有存在感

**关系类型（必须从以下列表中精确选择一个，禁止自定义）：**
- 家族：父亲、母亲、兄弟、姐妹、子女、配偶、恋人
- 社交：师父、徒弟、朋友、同学、邻居、知己
- 职业：上司、下属、同事、合作伙伴
- 敌对：敌人、仇人、竞争对手、宿敌

**重要说明：**
1. **数量控制**：数组中必须精确包含{count}个对象，不能多也不能少
2. **关系约束**：relationships_array只能引用本批次中已经出现的角色名称
3. **组织约束**：organization_memberships只能引用本批次中is_organization=true的实体名称
4. **禁止幻觉**：不要引用任何不存在的角色或组织，如果没有可引用的就留空数组[]
5. intimacy_level是-100到100的整数（负值表示敌对仇恨关系），loyalty是0-100的整数
6. 角色之间要形成合理的关系网络

**示例说明**：
- 如果生成了角色A、组织B、角色C，则角色A的organization_memberships只能是[组织B]，不能是其他组织
- 如果角色A在数组第一位，它的relationships_array必须为空[]，因为还没有其他角色
- 如果角色C在数组第三位，它的relationships_array可以引用角色A，但不能引用不存在的角色D

再次强调：
1. 只返回纯JSON数组，不要有```json```这样的标记
2. 数组中必须精确包含{count}个对象
3. 不要引用任何本批次中不存在的角色或组织名称
4. 文本描述中不要使用中文引号（""），改用【】或《》"""

    # 修炼 / 感悟场景的写法，只给有修炼体系的类型（玄幻 / 仙侠 / 修仙）注入；原先放在正文文风段里对所有类型生效
    _CULTIVATION_SCENE_RULE = (
        "- 修炼/感悟场景：写他此刻在干什么、周围有什么动静（外面的声音、光线变了、有人路过），"
        "身体感受最多一两处（“腿麻了”就够，不要连着写发热、发麻、出汗、心跳）；"
        "感悟用白话点到为止（“他隐约觉得，自己抓到了点什么”“脑子里一片空白，像被什么点了一下”），"
        "不写“与天地融为一体 / 触及大道本源 / 领悟了xxx的真谛 / 天地运行的奥秘 / 万物生灭的根源”这类总结式大词，"
        "也不写“他明白了xxx的本质”"
    )

    # 类型引导字典 - 根据不同小说类型提供专业化指导
    # 设计参考：起点、番茄、晋江三大网文平台的题材定位 + 编辑选稿的"读者期待清单"
    # 每条 guide 包含三层：核心爽点、必备元素、常见雷区
    GENRE_GUIDES = {
        # ===== 玄幻类 =====
        "玄幻": f"""【玄幻文核心要素】
- 力量体系：独特的修炼/战斗体系（斗气、魔法、血脉等），等级划分清晰，每级有明确战力差
- 金手指设定：主角的核心优势（系统、重生、血脉觉醒、神级传承等），爽点设计要合理且持续进化
- 势力格局：大陆/位面的势力分布（宗门、王国、神域），主角从底层向顶层逆袭的清晰路线
- 热血战斗：战斗场面要有燃点（招式描写、状态切换、嘶吼怒喝），以弱胜强的逆袭时刻是关键爽点
- 后宫/兄弟：重要配角的定位与作用，情感线服务于成长线，禁止抢戏喧宾夺主
{_CULTIVATION_SCENE_RULE}
- ⚠️ 雷区：等级体系混乱、金手指外挂感太强（一键秒杀失去爽感）、配角刻板化""",

        "奇幻": """【奇幻文核心要素】
- 西式世界观：种族多样（精灵、矮人、兽人、龙族）、魔法学院/教会/王国/魔王军体系明确
- 魔法体系：法术分类（元素/神圣/暗黑/召唤），施法代价（魔力/咏唱/材料），打破规则需要铺垫
- 主角定位：勇者/法师/盗贼/骑士等典型职业，技能成长路径要符合职业逻辑
- 冒险节奏：地下城/迷宫/远征/讨伐魔王，每段冒险有明确目标和奖励
- 神话原型：可借鉴北欧/凯尔特/亚瑟王/克苏鲁等神话元素，但要重构融入自己的体系
- ⚠️ 雷区：魔法体系自相矛盾、世界观西化但人物对话现代化、套用游戏术语过多""",

        "武侠": """【武侠文核心要素】
- 江湖世界：门派（少林/武当/丐帮等）、世家、绿林、官府四股势力的恩怨纠葛
- 武功体系：内功心法（运气、经脉、内息）+ 外功招式（拳法/剑法/掌法），招式命名要有诗意意境
- 侠义精神：主角行事符合"为国为民"或"快意恩仇"的侠者准则，侠之大者要有担当
- 江湖恩怨：师门血仇、武林秘籍争夺、家国大义等经典冲突线
- 人物对话：用半文半白的"江湖口吻"，少用现代词汇，多用"在下/兄台/姑娘/前辈"等称呼；江湖味只放在对话和招式名里，叙述仍是白话短段
- ⚠️ 雷区：武功描写空洞（只说"一招打飞"无招式细节）、对白现代化、缺少江湖味""",

        "仙侠": f"""【仙侠文核心要素】
- 仙凡之别：仙界/人界/魔界/妖界的等级森严，主角跨越界限的剧情张力
- 修仙境界：清晰阶梯（如练气→筑基→金丹→元婴→化神→渡劫→大乘→飞升），突破节点是关键爽点
- 情劫执念：仙侠的核心张力来自"情"与"道"的冲突（爱情/亲情/友情成劫数）
- 大道之争：寻找天道、争夺机缘、改写命数，主角的道心和执念推动剧情
- 氛围：云海/仙山/灵兽/法宝一两句带出来就行，别停下来写景，仙气靠人物怎么用它、怎么议论它带出来
{_CULTIVATION_SCENE_RULE}
- ⚠️ 雷区：境界设定混乱、情劫描写矫揉造作、纯打怪升级失去仙侠韵味""",

        "修仙": f"""【修仙文核心要素】
- 境界体系：设计清晰的修炼等级（如炼气→筑基→金丹→元婴→化神），主角的突破节点是关键爽点
- 机缘法则：功法、丹药、法宝、秘境等资源的获取方式，机缘是推动剧情的重要动力
- 宗门势力：宗门、世家、散修的势力格局，主角的势力归属与成长路径
- 战力规则：不同境界的战力差距，越级战斗的条件与代价（血脉/秘宝/牺牲）
- 大道之争：修仙的终极目标（长生、飞升、证道），主角的道心与执念
{_CULTIVATION_SCENE_RULE}
- ⚠️ 雷区：境界乱跳、机缘过于轻易、缺少修炼细节（功法名/经脉走向/灵气运转）""",

        # ===== 都市类 =====
        "都市": """【都市文核心要素】
- 金手指设定：主角的核心优势（重生记忆/系统/异能/超脑），要与都市背景自然融合
- 爽点节奏：打脸、逆袭、装X的节奏安排要密集（推荐每章至少 1 个小爽点 + 每 5 章 1 个大爽点）
- 社会关系：家族、公司、圈层的权力结构清晰（豪门/商界/政界/娱乐圈），主角地位变化要有跨度
- 情感纠葛：感情线设计（追妻火葬场、扮猪吃虎被女主发现、多女主好感度），情感冲突服务于爽感
- 现实融合：都市背景与金手指要合理融合（不要让超能力破坏都市规则），保留一定的现实感
- ⚠️ 雷区：装X过度失去节制（变成纯爽文）、金手指开外挂痕迹太重、缺少都市生活细节""",

        "现实": """【现实文核心要素】
- 真实质感：聚焦真实社会议题（职场/教育/医疗/创业/婚姻），细节要经得起推敲
- 人物群像：不止主角，要有立体的配角群（同事/家人/邻居/对手），每个人都有自己的逻辑
- 困境与突破：主角面对的不是开金手指，而是真实的资源约束、人情世故、道德两难
- 情感真实：感情发展遵循现实节奏，不空降CP，不夸张戏剧化
- 时代背景：可以融入真实的时代特征（行业变迁、政策影响、社会热点）
- ⚠️ 雷区：爽文化（突然开外挂）、悬浮（脱离实际工作流程）、说教（强行升华主题）""",

        # ===== 历史/军事类 =====
        "历史": """【历史文核心要素】
- 时代细节：朝代背景的衣食住行、官制礼仪、文化习俗要考据准确（错一处即出戏）
- 主角定位：穿越者/重生者/原生人，要明确知识储备和能改变历史的边界
- 朝堂权谋：皇权/相权/外戚/宦官/世家的多方博弈，主角参与权谋要有手腕和退路
- 民生百态：上至朝堂，下至市井，要呈现完整的社会切片
- 关键人物：与真实历史人物互动时，性格要符合史料记载或合理推演
- ⚠️ 雷区：用现代词（"OK/同志/朕表示"）、官职错乱、用现代价值观评判古人""",

        "军事": """【军事文核心要素】
- 战术真实：行军/侦察/伏击/合围/突破等战术细节要符合军事逻辑（避免"主角光环式胜利"）
- 武器装备：武器型号、口径、射程、弹道、操作步骤要准确（写到具体装备就要查证）
- 铁血氛围：战友情、生死兄弟、训练吃苦、流血牺牲的硬汉风格
- 战争代价：胜利要有代价（伤亡、失误、心理创伤），不要写成"无伤通关游戏"
- 命令链与服从：军队的等级制度、服从天职、违命代价要严肃刻画
- ⚠️ 雷区：把士兵当杂兵堆人头、武器参数瞎编、忽视后勤补给和情报""",

        # ===== 二次元/游戏/体育 =====
        "游戏": """【游戏文核心要素】
- 游戏系统：技能/装备/属性/经验/副本/任务/公会，所有系统要逻辑自洽且服务于成长
- 副本/任务：每个副本/任务要有清晰的入场条件、流程节点、通关奖励
- 公会/团战：多人协作的策略安排、职业分工（坦克/输出/治疗/控制）
- 现实vs游戏：主角在现实和游戏中的双线生活，两条线的相互影响
- 装备/技能描写：参数化呈现（如：暴击+30%/冷却-2s），让读者一眼看懂强度
- ⚠️ 雷区：系统设定混乱、技能描述模糊（"释放了一招大招"）、缺少策略博弈感""",

        "体育": """【体育文核心要素】
- 训练成长：从基本功到高阶技巧的清晰成长曲线，每次突破要有具体的训练量和方法
- 比赛悬念：每场比赛要有明确对手、战术博弈、关键转折点（绝杀/逆转/伤退）
- 竞技精神：尊重对手、永不放弃、团队荣誉，主角的体育道德要立得住
- 技术细节：项目专属术语和动作描写要准确（篮球的pick&roll/足球的越位/拳击的组合拳）
- 队友/对手：每个重要配角要有自己的技术特点和成长线，不当背景板
- ⚠️ 雷区：靠系统/异能代替训练（失去体育文核心）、比赛流水账无张力、对手脸谱化""",

        # ===== 科幻类 =====
        "科幻": """【科幻文核心要素】
- 科技设定：核心科幻设定（人工智能/星际航行/基因改造/虚拟现实/平行宇宙等）要内在自洽
- 软硬抉择：硬科幻重物理逻辑（公式/参数/理论），软科幻重人文思辨（伦理/社会/文明）
- 未来想象：科技对人类生活的具体改变（衣食住行/工作/情感/政治）
- 冲突核心：技术 vs 伦理、人类 vs AI、文明 vs 文明、个体 vs 体制
- 推演严谨：从已知科学推导未来，避免"魔法即科技"的设定
- ⚠️ 雷区：把魔法套个科技壳（"灵气"改名"能量"无本质区别）、科技解释纯堆砌术语""",

        # ===== 悬疑/灵异 =====
        "悬疑": """【悬疑文核心要素】
- 核心谜题：贯穿全书的核心悬念（凶手/真相/动机），层层剥茧的揭示节奏
- 线索布局：明线（表层故事）与暗线（真相伏笔）的交织，伏笔的埋设与回收
- 反转设计：关键节点的反转安排（凶手身份反转/动机反转/事件性质反转），颠覆读者预期
- 节奏控制：紧张（追查/对峙）与舒缓（推理/调查）交替，悬念的维持与释放
- 逻辑严密：推理过程的合理性，禁止"主角光环式破案"和"无证据下定论"
- ⚠️ 雷区：靠巧合推动剧情、关键线索藏到最后才告诉读者（不公平推理）、凶手动机苍白""",

        "灵异": """【灵异文核心要素】
- 诡异感：靠具体的不对劲（灯闪了一下、门自己关了、数人头少了一个），一处一两句就够，不铺形容词、不堆气味
- 规则诡异：用清晰的规则约束超自然现象（如"半夜不能照镜子""鬼不过桥"），违反就有代价
- 未知恐惧：恐惧来自"不知道是什么"，过早揭示真相会失去张力
- 主角弱小：主角不要太强（不然没紧张感），保持"普通人面对超自然"的代入感
- 真相揭示：背后要有合理的"灵异规则"或"民俗根源"，不能纯靠"它就是这样"
- ⚠️ 雷区：靠 jump scare（突然惊吓）堆砌恐惧、规则随意修改、主角无敌失去恐惧感""",

        # ===== 二次元 =====
        "二次元": """【二次元文核心要素】
- 萌系/燃系/治愈/恋爱：明确作品基调（轻松日常/热血战斗/温暖治愈/校园恋爱）
- 角色萌点：每个角色要有鲜明的萌属性（傲娇/天然呆/腹黑/三无/病娇/中二）
- 番剧感：剧情节奏接近 12-24 集番剧（每"集"有起承转合，季末有大高潮）
- 宅文化梗：可适度使用 ACGN 圈内梗（注意要让非宅读者也能看懂）
- 关系网：青梅竹马、后宫、社团、班级、家族等典型关系结构
- ⚠️ 雷区：堆砌生硬的日漫梗、人物纸片化（只有萌属性没有性格）、对白过于轻佻""",

        # ===== 言情类 =====
        "言情": """【言情文核心要素】
- 人设魅力：男女主的人设吸引力（颜值/能力/反差萌），性格互补或碰撞产生化学反应
- 情感递进：从相识→暧昧→相爱→危机→和解的清晰节奏，每步都要有"心动瞬间"
- 虐恋/甜宠：明确基调（甜宠为主撒糖，虐恋为主虐心），虐点和甜点的合理交替
- 误会与和解：情感冲突的设计要合理（误会有依据，和解有诚意），避免"为虐而虐"
- 配角作用：情敌（白月光/朱砂痣）、闺蜜、家人等配角要服务于主线情感，不能喧宾夺主
- ⚠️ 雷区：男主"霸总油腻"、女主"白莲花圣母"、情感线靠误会硬撑、撒糖过度甜到齁""",

        "现言": """【现言文核心要素】
- 现代背景：聚焦都市/职场/校园/娱乐圈/豪门等真实可感的现代场景
- 类型化人设：霸道总裁、青梅竹马、契约婚姻、追妻火葬场等经典 CP 模式
- 撩点设计：日常生活中的撩点（捡发夹/雨中借伞/醋意吃飞醋/突然壁咚），细节决定吸引力
- 现实困境：职场矛盾、家族阻挠、第三者插足、阶层差距等现代化的情感障碍
- 都市质感：服装/餐厅/工作细节要符合现实（避免"霸总写法"的悬浮感）
- ⚠️ 雷区：霸总油腻 PUA、女主玛丽苏圣母、人物悬浮（豪门生活完全脱离实际）""",

        "古言": """【古言文核心要素】
- 古代背景：朝代设定（架空或真实）的衣食住行、礼仪规矩、官制等要考据
- 经典模式：宫斗（后宫争宠/嫔妃斗智）、宅斗（嫡庶之争/妯娌内斗）、权谋（朝堂博弈+爱情）
- 嫡庶礼仪：清晰呈现古代家族的尊卑秩序、规矩讲究，违礼有代价
- 婉转表达：对话半文半白，"奴婢/妾身/小生/在下"等称谓要正确；叙述仍是白话短段，不写骈文
- 隐忍智慧：女主用智谋而非蛮力解决问题（请安/赏赐/分寸把握），符合古代闺阁逻辑
- ⚠️ 雷区：现代价值观穿越（女主突然女权觉醒）、用现代词、礼仪混乱""",
    }

    # 视角引导字典 - 根据不同叙事视角提供针对性写作技巧
    # 参考：业界经典《小说创作教程》《故事》(Robert McKee) + 网文平台编辑规范
    PERSPECTIVE_GUIDES = {
        "第一人称": """【第一人称视角写作技巧】
- **主语规则**：以"我"作为叙述主语，所有事件都从"我"的眼睛、耳朵、感受出发
- **信息边界（最重要）**：只能写"我"亲身经历、亲眼所见、亲耳听到、亲口问到的内容
  - ❌ 严禁写其他角色的心理活动（除非通过"我"的观察推测，需用"似乎/像是/我猜"等模糊词）
  - ❌ 严禁写"我"不在场的事件（除非通过他人转述、信件、回忆等合理途径告知）
  - ❌ 严禁全知视角描写（"与此同时，远方的某某正在……"是绝对禁忌）
- **内心独白丰富**：充分利用第一人称的优势，多写"我"的真实想法、感受、犹豫、吐槽
- **代入感强化**：用"我"的语言习惯说话，性格、文化、年龄要在叙述语言上体现
- **观察式描写**：描写其他角色时要带"我"的主观判断（"他看起来有些紧张""这家伙明显在撒谎"）""",

        "第三人称": """【第三人称视角写作技巧】
- **主语规则**：用角色名字或"他/她"作主语，禁止用"我"叙述
- **视角焦点（紧密第三人称）**：默认跟随主角的视角，主角不在场就不写该场景
  - 可以写主角的心理活动、感受、想法
  - 其他角色的心理只能通过主角的观察推测，不能直接揭示
- **POV 切换规则**：如需切换视角到其他角色（多 POV 写法），必须以"章节"或"明确分隔符（如 ※※※）"为界，禁止在同一段落内跳跃视角
- **避免视角污染**：在 A 视角章节里，禁止写 A 不知道的信息（典型错误：A 房间里独处时，突然描述 B 在隔壁的心理活动）
- **客观与主观平衡**：可以适度跳出做简短的环境/背景交代，但主体叙述要回到角色视角""",

        "全知视角": """【全知视角写作技巧】
- **叙述者权限**：叙述者无所不知，可以自由切换不同角色的视角、心理、感受
- **适用题材**：大群像史诗、长河式作品、多线并行的宏大叙事
- **切换技巧**：视角切换要有清晰的过渡（章节/段落分隔/明确的引导句），避免读者迷失
- **保持焦点**：虽然全知，但每个场景仍要有"叙述焦点"，不要在一个段落里跳遍所有人
- **叙述者声调**：可以有叙述者的态度和评论，但用白话（如"老张当时没当回事"），不写"命运正在悄悄改变"这种预告腔
- **避免散漫**：全知视角最大的陷阱是失焦，每一章仍要有明确的主线和情感锚点
- ⚠️ 注意：本视角下「信息边界」规则不严格适用，但仍要避免「读者已知信息再次冗余交代」""",
    }

    # 视角别名归一化（兼容数据库可能存的英文值或简写）
    PERSPECTIVE_ALIASES = {
        "first_person": "第一人称",
        "first-person": "第一人称",
        "1st": "第一人称",
        "我": "第一人称",
        "third_person": "第三人称",
        "third-person": "第三人称",
        "3rd": "第三人称",
        "他": "第三人称",
        "她": "第三人称",
        "omniscient": "全知视角",
        "上帝视角": "全知视角",
        "上帝": "全知视角",
        "全知": "全知视角",
    }

    # 类型别名归一化（处理同义/英文/简写）
    GENRE_ALIASES = {
        "scifi": "科幻", "sci-fi": "科幻", "science_fiction": "科幻",
        "fantasy": "奇幻", "xuanhuan": "玄幻", "xianxia": "仙侠",
        "wuxia": "武侠", "urban": "都市", "modern": "现实",
        "history": "历史", "military": "军事", "game": "游戏",
        "sports": "体育", "mystery": "悬疑", "horror": "灵异",
        "supernatural": "灵异", "acg": "二次元", "anime": "二次元",
        "romance": "言情", "modern_romance": "现言", "ancient_romance": "古言",
        "cultivation": "修仙", "immortal": "修仙",
    }

    # 通用类型引导（fallback）
    GENERIC_GENRE_GUIDE = """【通用创作要素】
- 核心冲突：设计贯穿全书的主要矛盾，确保张力持续
- 人物成长：主角需要有清晰的成长弧线，内外兼修
- 节奏把控：起伏交替，高潮与缓和合理安排
- 情感共鸣：让读者与主角产生情感连接"""

    # 通用视角引导（fallback）
    GENERIC_PERSPECTIVE_GUIDE = """【通用视角写作要求】
- 在叙述时保持视角一致性，不要在不同视角间频繁切换
- 视角内只描写该视角能感知到的信息，避免视角越界
- 心理描写要符合所选视角的权限范围"""

    # 向导大纲生成提示词（网文风格优化版 v2 - 去重）
    COMPLETE_OUTLINE_GENERATION = """# 角色设定
你是一位资深网文策划，专注于【{genre}】类型，擅长设计金手指、提炼卖点、把握爽点节奏。

# 任务说明
请根据以下信息，生成一份**网文大纲**——让读者一眼就知道"这本书爽在哪里"。

## 基本信息
| 项目 | 内容 |
|------|------|
| 书名 | {title} |
| 类型 | {genre} |
| 主题 | {theme} |
| 视角 | {narrative_perspective} |
| 规模 | 约{chapter_count}章，{target_words}字 |

## 背景参考
- 初始想法：{description}
- 时代背景：{time_period}
- 主要场景：{location}
- 氛围基调：{atmosphere}
- 世界规则：{rules}

{protagonists_info}

## 其他角色参考
{characters_info}

{genre_guide}

{mcp_references}

## 其他要求
{requirements}

# 网文大纲7要素

请围绕以下7个核心要素构思（注意：主角信息已在上方提供，大纲中不重复输出）：

### 1. 故事梗概 (premise)
- 用5-8句话概括整个故事
- 突出：主角开局处境 + 金手指获得 + 核心冲突 + 逆袭方向

### 2. 金手指 (golden_finger)
- 主角的核心优势是什么？（系统/重生/传承/血脉/异能）
- 金手指要有成长性，能支撑整本书的升级

### 3. 核心卖点 (selling_points)
- 这本书最吸引读者的是什么？
- 常见卖点：扮猪吃虎、打脸装逼、废材逆袭、复仇爽文、甜宠撒糖

### 4. 升级路线 (power_system)
- 主角如何变强？（境界/实力/地位/财富）
- 要有清晰的等级划分，让读者有追更动力

### 5. 主要套路 (main_tropes)
- 会用到哪些经典桥段？
- 如：宗门大比、夺宝、退婚打脸、身份揭露、以弱胜强

### 6. 终极目标 (ultimate_goal)
- 最终主角会达到什么成就？
- 如：成为最强者、复仇成功、后宫圆满、真相大白

### 7. 开篇钩子 (opening_hook)
- 第一章如何抓住读者？
- 如：主角被当众羞辱、获得神秘传承、发现惊天秘密

# 类型示例

## 修仙/玄幻类示例
```json
{{
  "premise": "萧炎曾是天才少年，却因斗气消失沦为废物，未婚妻当众退婚。绝望之际，戒指中的药老苏醒，传他逆天功法【焚决】。从此他白天装废物，夜晚疯狂修炼，只等三年之约打脸所有看不起他的人。",
  "golden_finger": "药老传承 + 可吞噬异火进化的焚决功法",
  "selling_points": ["废材逆袭", "扮猪吃虎", "打脸退婚流"],
  "power_system": "斗者→斗师→斗灵→斗王→斗皇→斗宗→斗尊→斗圣→斗帝",
  "main_tropes": ["退婚打脸", "宗门大比", "夺取异火", "以弱胜强", "身份揭露"],
  "ultimate_goal": "成为斗帝，迎娶萧薰儿，为母报仇",
  "opening_hook": "萧炎被未婚妻纳兰嫣然当众退婚，从天才跌落废物"
}}
```

## 都市类示例
```json
{{
  "premise": "陈平入赘三年，受尽冷眼。妻子提出离婚那天，他接到电话：爷爷去世，万亿家产归他继承。从今天起，曾经看不起他的人，都要跪着求他。",
  "golden_finger": "隐藏首富身份 + 顶级商业帝国继承权",
  "selling_points": ["赘婿逆袭", "身份反转", "打脸装逼"],
  "power_system": "赘婿→身份暴露→商界新贵→幕后大佬→顶级财阀",
  "main_tropes": ["身份反转", "商战碾压", "前妻后悔", "豪门争斗", "打脸装逼"],
  "ultimate_goal": "成为商界传奇，让所有看不起他的人跪着道歉",
  "opening_hook": "离婚协议书摆在面前，一通神秘电话改变一切"
}}
```

# 输出格式

直接返回JSON对象，不要有任何其他文字：

{{
  "premise": "故事梗概（5-8句话，突出开局+金手指+核心冲突）",
  "golden_finger": "金手指设定（主角的核心优势，要具体明确）",
  "selling_points": ["卖点1", "卖点2", "卖点3"],
  "power_system": "升级路线（用→连接各阶段）",
  "main_tropes": ["套路1", "套路2", "套路3"],
  "ultimate_goal": "终极目标（主角最终会达成什么成就）",
  "opening_hook": "开篇钩子（第一章如何吸引读者继续看）"
}}

**格式要求**：
- 纯JSON，无markdown标记
- 不要输出 title、theme、tone、protagonists（这些信息已在项目设置和角色模块中）
- 专有名词用【】标记
- 直接以{{开始}}结束"""
    

    # 章节完整创作提示词（开头人设 / 第 5 条文风段 / 收尾段与下面带上下文的模板共用，见模块顶部常量）
    CHAPTER_GENERATION = CHAPTER_WRITER_PERSONA + """

项目信息：
- 书名：{title}
- 主题：{theme}
- 类型：{genre}
- 叙事视角：{narrative_perspective}

{perspective_guide}
{genre_guide}
世界观：
- 时间背景：{time_period}
- 地理位置：{location}
- 氛围基调：{atmosphere}
- 世界规则：{rules}

角色信息：
{characters_info}

本章信息：
- 章节序号：第{chapter_number}章
- 章节标题：{chapter_title}
- 章节大纲：{chapter_outline}

创作要求（必须严格遵守）：
1. **严格遵循章节大纲（最高优先级）**：
   - 必须完整呈现大纲中的所有剧情要点
   - 不得省略或跳过大纲中的任何关键事件
   - 不得添加与大纲矛盾的新情节
   - 按照大纲规划的顺序展开情节

2. **剧情连贯性**：
   - 保持与前后章节的连贯性
   - 注意时间线和因果关系
   - 结尾可以留一个具体的悬念或未完成的动作（但不要预告未来、总结主题）

3. **角色一致性**：
   - 严格符合角色性格设定
   - 角色行为必须符合其背景和动机

4. **世界观一致性**：
   - 体现世界观特色
   - 遵守世界规则

5. """ + CHAPTER_STYLE_RULES + """

{deai_block}

6. **字数要求（严格控制）**：
   - **目标字数**：{target_word_count}字
   - **允许范围**：{min_word_count}至{max_word_count}字之间
   - **硬性要求**：
     - 正文字数必须控制在上述范围内，不得明显超出上限
     - 当接近{max_word_count}字时，必须尽快收尾，不要继续展开新情节
     - 如果篇幅不足以详细展开所有大纲事件，优先采取以下策略：
       * 压缩环境描写和过渡性叙述，对话和冲突优先保留
       * 使用简洁叙述概括次要桥段
       * 保留核心冲突、转折和结局的完整性
     - 禁止为了凑字数而重复描写或添加无关内容

**重要提醒：**
- 章节大纲和剧情卡片是创作的核心依据，必须严格遵循
- 不要自由发挥添加无关情节
- 所有创作都应围绕预设的大纲和卡片展开
- 在有限字数内完整呈现大纲要点是首要任务

---

【参考资料 - 用于保持剧情连贯】

以下内容用于帮助你了解故事背景和前文情节，剧情发展、角色状态、伏笔线索，保持与前文的连贯性和一致性。

全书大纲：
{outlines_context}

{linked_cards_section}

---

""" + CHAPTER_CLOSING

    # 章节完整创作提示词（带前置章节上下文和记忆增强）
    CHAPTER_GENERATION_WITH_CONTEXT = CHAPTER_WRITER_PERSONA + """

项目信息：
- 书名：{title}
- 主题：{theme}
- 类型：{genre}
- 叙事视角：{narrative_perspective}

{perspective_guide}
{genre_guide}
世界观：
- 时间背景：{time_period}
- 地理位置：{location}
- 氛围基调：{atmosphere}
- 世界规则：{rules}

角色信息：
{characters_info}

本章信息：
- 章节序号：第{chapter_number}章
- 章节标题：{chapter_title}
- 章节大纲：{chapter_outline}

创作要求（必须严格遵守）：
1. **严格遵循章节大纲（最高优先级）**：
   - 必须完整呈现大纲中的所有剧情要点
   - 不得省略或跳过大纲中的任何关键事件
   - 不得添加与大纲矛盾的新情节
   - 按照大纲规划的顺序展开情节

2. **剧情连贯性（第二优先级）**：
   - 必须承接前面章节的剧情发展
   - 注意角色状态、情节进展、时间线的连续性
   - 不能出现与前文矛盾的内容
   - 自然过渡，避免突兀的跳跃
   - 开头自然衔接上一章结尾
   - 结尾可以留一个具体的悬念或未完成的动作（但不要预告未来、总结主题）

3. **角色一致性**：
   - 严格符合角色性格设定
   - 延续角色在前文中的成长和变化
   - 保持角色关系的连贯性
   - 角色行为必须符合其发展轨迹

4. **世界观一致性**：
   - 体现世界观特色
   - 遵守世界规则
   - 与关键剧情保持一致

5. """ + CHAPTER_STYLE_RULES + """

{deai_block}

6. **字数要求（严格控制）**：
   - **目标字数**：{target_word_count}字
   - **允许范围**：{min_word_count}至{max_word_count}字之间
   - **硬性要求**：
     - 正文字数必须控制在上述范围内，不得明显超出上限
     - 当接近{max_word_count}字时，必须尽快收尾，不要继续展开新情节
     - 如果篇幅不足以详细展开所有大纲事件，优先采取以下策略：
       * 压缩环境描写和过渡性叙述，对话和冲突优先保留
       * 使用简洁叙述概括次要桥段
       * 保留核心冲突、转折和结局的完整性
     - 禁止为了凑字数而重复描写或添加无关内容

7. **记忆系统使用指南**：
   - **最近章节记忆**：保持情节连贯，注意角色状态和剧情发展
   - **语义相关记忆**：参考相似情节的处理方式
   - **未完结伏笔**：适当时机可以回收伏笔，制造呼应效果
   - **角色状态记忆**：确保角色行为符合其发展轨迹
   - **重要情节点**：与关键剧情保持一致
   - **叙事承诺/因果链**：不要遗忘已立下的约定、未解决谜团和关键因果后果
   {perspective_boundary_clause}

**重要提醒：**
- 章节大纲和剧情卡片是创作的核心依据，必须严格遵循
- 不要自由发挥添加无关情节
- 所有创作都应围绕预设的大纲和卡片展开
- 在遵循大纲和卡片的基础上，保持与前文的连贯性
- 在有限字数内完整呈现大纲要点是首要任务

---

【参考资料 - 用于保持剧情连贯】

以下内容用于帮助你了解故事背景和前文情节，其中的剧情发展、角色状态、伏笔线索，保持与前文的连贯性和一致性。

全书大纲：
{outlines_context}

【已完成的前置章节内容】
{previous_content}

【🧠 智能记忆系统 - 重要参考】
以下是从故事记忆库中检索到的相关信息，请在创作时适当参考和呼应：

{memory_context}

{linked_cards_section}

---

""" + CHAPTER_CLOSING


    # 单个角色生成提示词
    SINGLE_CHARACTER_GENERATION = """你是一位专业的角色设定师。请根据以下信息创建一个立体饱满的小说角色。

{project_context}

{user_input}

请生成一个完整的角色卡片，包含以下所有信息：

1. **基本信息**：
   - 姓名：如果用户未提供，请生成一个符合世界观的名字
   - 年龄：具体数字或年龄段
   - 性别：男/女/其他

2. **外貌特征**（100-150字）：
   - 身高体型、面容特征、着装风格
   - 要符合角色定位和世界观设定

3. **性格特点**（150-200字）：
   - 核心性格特质（至少3个）
   - 优点和缺点
   - 特殊习惯或癖好
   - 性格要有复杂性和矛盾性

4. **背景故事**（200-300字）：
   - 家庭背景
   - 成长经历
   - 重要转折事件
   - 如何与项目主题关联
   - 融入用户提供的背景设定

5. **人际关系**：
   - 与现有角色的关系（如果有）
   - 重要的人际纽带
   - 社会地位和人脉

6. **特殊能力/特长**：
   - 擅长的领域
   - 特殊技能或知识
   - 符合世界观设定

**重要格式要求：**
1. 只返回纯JSON格式，不要包含任何markdown标记、代码块标记或其他说明文字
2. 不要在JSON字符串值中使用中文引号（""''），改用【】或《》
3. 文本描述中的专有名词使用【】标记

请严格按照以下JSON格式返回：
{{
  "name": "角色姓名",
  "age": "年龄",
  "gender": "性别",
  "appearance": "外貌描述（100-150字）",
  "personality": "性格特点（150-200字）",
  "background": "背景故事（200-300字）",
  "traits": ["特长1", "特长2", "特长3"],
  
  "relationships_text": "人际关系的文字描述（用于显示）",
  
  "relationships": [
    {{
      "target_character_name": "已存在的角色名称",
      "relationship_type": "关系类型（必须从以下选择：父亲/母亲/兄弟/姐妹/子女/配偶/恋人/师父/徒弟/朋友/同学/邻居/知己/上司/下属/同事/合作伙伴/敌人/仇人/竞争对手/宿敌）",
      "intimacy_level": 75,
      "description": "这段关系的详细描述",
      "started_at": "关系开始的故事时间点（可选）"
    }}
  ],
  
  "organization_memberships": [
    {{
      "organization_name": "已存在的组织名称",
      "position": "职位名称",
      "rank": 8,
      "loyalty": 80,
      "joined_at": "加入时间（可选）",
      "status": "active"
    }}
  ]
}}

**关系类型（必须从以下列表中精确选择一个，禁止自定义）：**
- 家族关系：父亲、母亲、兄弟、姐妹、子女、配偶、恋人
- 社交关系：师父、徒弟、朋友、同学、邻居、知己
- 职业关系：上司、下属、同事、合作伙伴
- 敌对关系：敌人、仇人、竞争对手、宿敌

**重要说明：**
1. relationships数组：只包含与上面列出的已存在角色的关系，通过target_character_name匹配
2. organization_memberships数组：只包含与上面列出的已存在组织的关系
3. intimacy_level是-100到100的整数（负值表示敌对、仇恨等关系），loyalty是0-100的整数
4. 如果没有关系或组织，对应数组为空[]
5. relationships_text是自然语言描述，用于展示给用户看

**角色设定要求：**
- 角色要符合项目的世界观和主题
- 如果是主角，要有明确的成长空间和目标动机
- 如果是反派，要有合理的动机，不能脸谱化
- 配角要有独特性，不能是工具人
- 所有设定要为故事服务

再次强调：
1. 只返回纯JSON对象，不要有```json```这样的标记
2. 文本中不要使用中文引号（""），改用【】或《》
3. 不要有任何额外的文字说明"""

    # 单个组织生成提示词
    SINGLE_ORGANIZATION_GENERATION = """你是一位专业的组织设定师。请根据以下信息创建一个完整的组织/势力设定。

{project_context}

{user_input}

请生成一个完整的组织设定，包含以下所有信息：

1. **基本信息**：
   - 组织名称：如果用户未提供，请生成一个符合世界观的名称
   - 组织类型：如帮派、公司、门派、学院、政府机构、宗教组织等
   - 成立时间：具体时间或时间段

2. **组织特性**（150-200字）：
   - 组织的核心理念和行事风格
   - 组织文化和价值观
   - 运作方式和管理模式
   - 特殊传统或规矩

3. **组织背景**（200-300字）：
   - 建立历史和起源
   - 发展历程和重要事件
   - 目前的地位和影响力
   - 如何与项目主题关联
   - 融入用户提供的背景设定

4. **外在表现**（100-150字）：
   - 总部或主要据点位置
   - 标志性建筑或场所
   - 组织标志、徽章、制服等
   - 可辨识的外在特征

5. **组织目的/宗旨**：
   - 明确的组织目标
   - 长期愿景
   - 行动准则

6. **势力等级**：
   - 在世界中的影响力（0-100）
   - 综合实力评估

7. **所在地点**：
   - 主要活动区域
   - 势力范围

**重要格式要求：**
1. 只返回纯JSON格式，不要包含任何markdown标记、代码块标记或其他说明文字
2. 不要在JSON字符串值中使用中文引号（""''），改用【】或《》
3. 文本描述中的专有名词使用【】标记

请严格按照以下JSON格式返回：
{{
  "name": "组织名称",
  "is_organization": true,
  "organization_type": "组织类型",
  "personality": "组织特性（150-200字）",
  "background": "组织背景（200-300字）",
  "appearance": "外在表现（100-150字）",
  "organization_purpose": "组织目的和宗旨",
  "power_level": 75,
  "location": "所在地点",
  "motto": "组织格言或口号",
  "traits": ["特征1", "特征2", "特征3"],
  "color": "组织代表颜色（如：深红色、金色、黑色等）",
  "organization_members": ["重要成员1", "重要成员2", "重要成员3"]
}}

**组织设定要求：**
- 组织要符合项目的世界观和主题
- 目标和行动要合理，不能过于理想化或脸谱化
- 要有存在的必要性，能推动故事发展
- 内部要有层级和结构
- 与其他势力要有互动关系

**说明**：
1. power_level是0-100的整数，表示组织在世界中的影响力
2. organization_members是组织内重要成员的名字列表（如果已有角色，可以关联）
3. 所有文本描述要详细具体，避免空泛

再次强调：
1. 只返回纯JSON对象，不要有```json```这样的标记
2. 文本中不要使用中文引号（""），改用【】或《》
3. 不要有任何额外的文字说明"""

    @staticmethod
    def format_prompt(template: str, **kwargs) -> str:
        """
        格式化提示词模板
        
        Args:
            template: 提示词模板
            **kwargs: 模板参数
            
        Returns:
            格式化后的提示词
        """
        try:
            return template.format(**kwargs)
        except KeyError as e:
            raise ValueError(f"缺少必需的参数: {e}")

    # ============ 类型/视角提示词注入辅助方法 ============

    @classmethod
    def _normalize_genre_token(cls, token: str) -> str:
        """将单个类型 token 归一化为字典 key（处理别名/英文/简写）"""
        if not token:
            return ""
        token = token.strip().lower()
        return cls.GENRE_ALIASES.get(token, token)

    @classmethod
    def _split_genre_tokens(cls, genre: str) -> list:
        """
        将类型字符串拆分为 token 列表，支持多种分隔符
        例如："玄幻、修仙" / "玄幻,都市" / "玄幻 修仙" / "fantasy/scifi"
        """
        if not genre:
            return []
        # 统一分隔符为单个空格，再拆分
        normalized = (
            genre.replace("、", " ")
            .replace(",", " ")
            .replace("，", " ")
            .replace("/", " ")
            .replace("|", " ")
            .replace("+", " ")
        )
        return [t.strip() for t in normalized.split() if t.strip()]

    @classmethod
    def _resolve_genre_guide(cls, genre: str) -> str:
        """
        根据类型字符串解析对应的类型引导（支持多选合并）

        匹配逻辑：
        1. 先按分隔符拆分多选类型
        2. 每个 token 经过别名归一化
        3. 用 token 与 GENRE_GUIDES 的 key 做双向 in 匹配（兼容"修仙文"匹配"修仙"）
        4. 命中多个时合并输出（去重保序）

        Args:
            genre: 原始类型字符串，可能是单值或用、,，/| 拼接的多选

        Returns:
            完整的 "## 类型特色指导\n..." Markdown 段落
        """
        if not genre:
            return f"## 类型特色指导\n{cls.GENERIC_GENRE_GUIDE}\n"

        tokens = cls._split_genre_tokens(genre)
        matched_keys = []  # 保序去重

        for token in tokens:
            normalized = cls._normalize_genre_token(token)
            for key in cls.GENRE_GUIDES.keys():
                if (key in normalized or normalized in key) and key not in matched_keys:
                    matched_keys.append(key)
                    break  # 同一 token 只匹配一个 key

        if not matched_keys:
            return f"## 类型特色指导\n{cls.GENERIC_GENRE_GUIDE}\n"

        if len(matched_keys) == 1:
            return f"## 类型特色指导\n{cls.GENRE_GUIDES[matched_keys[0]]}\n"

        # 多类型合并：加入跨类型协调提示
        merged_parts = [cls.GENRE_GUIDES[k] for k in matched_keys]
        joined_names = "、".join(matched_keys)
        return (
            f"## 类型特色指导（跨类型融合：{joined_names}）\n"
            f"本作品融合多种类型，请在保持各类型核心爽点的同时注意协调，避免设定冲突。\n\n"
            + "\n\n".join(merged_parts)
            + "\n"
        )

    @classmethod
    def _resolve_perspective_guide(cls, perspective: str) -> str:
        """
        根据视角字符串解析对应的视角引导

        匹配逻辑：
        1. 视角别名归一化（first_person → 第一人称）
        2. 在 PERSPECTIVE_GUIDES 中查找精确匹配
        3. 未命中则用模糊匹配（兼容"第一人称视角"匹配"第一人称"）
        4. 仍未命中则使用通用 fallback

        Returns:
            完整的 "## 叙事视角指导\n..." Markdown 段落
        """
        if not perspective:
            return f"## 叙事视角指导\n{cls.GENERIC_PERSPECTIVE_GUIDE}\n"

        normalized = perspective.strip()
        # 别名归一化
        normalized = cls.PERSPECTIVE_ALIASES.get(normalized.lower(), normalized)

        # 精确匹配
        guide = cls.PERSPECTIVE_GUIDES.get(normalized)
        if guide:
            return f"## 叙事视角指导\n{guide}\n"

        # 模糊匹配
        for key, value in cls.PERSPECTIVE_GUIDES.items():
            if key in normalized or normalized in key:
                return f"## 叙事视角指导\n{value}\n"

        return f"## 叙事视角指导\n{cls.GENERIC_PERSPECTIVE_GUIDE}\n"

    @classmethod
    def _build_perspective_boundary_clause(cls, perspective: str) -> str:
        """
        根据视角生成"信息边界"约束子句
        - 全知视角：放宽，仅提示叙述焦点
        - 其他视角：严格信息边界
        """
        if not perspective:
            return "- **视角信息边界**：POV 角色只能使用其已知信息，禁止全知视角污染"

        normalized = cls.PERSPECTIVE_ALIASES.get(perspective.strip().lower(), perspective.strip())
        if "全知" in normalized or "omniscient" in normalized.lower():
            return "- **叙述焦点控制**：本作品采用全知视角，可跳跃多角色心理，但单段落内应保持一个叙述焦点，避免读者迷失"

        if "第一人称" in normalized or "first" in normalized.lower():
            return (
                "- **第一人称信息边界（严格）**：所有内容必须经'我'的感官或合理转述获取；"
                "禁止描写'我'不在场的事件、其他角色的内心独白、远方同时发生的场景"
            )

        return (
            "- **第三人称视角边界**：默认跟随主角，不写主角不知道的信息；"
            "如需切换 POV 必须使用章节或明确分隔符（如 ※※※），禁止段落内跳跃视角"
        )

    @classmethod
    def render_chapter_style_rules(cls, narrative_perspective: str) -> str:
        """把正文共用的文风段（CHAPTER_STYLE_RULES）填好视角占位符，供章节重生成等正文入口复用。

        单独使用时没有正文模板里的「叙事视角指导 / 类型特色指导」两节，把指向它们的交叉引用去掉。
        """
        perspective = (narrative_perspective or "").strip() or "第三人称"
        text = CHAPTER_STYLE_RULES.format(
            narrative_perspective=perspective,
            perspective_boundary_clause=cls._build_perspective_boundary_clause(perspective),
        ).replace("（细则见上方「叙事视角指导」）", "")
        return "\n".join(line for line in text.splitlines() if "类型特色指导" not in line)

    @staticmethod
    def apply_project_generation_prompt(base_prompt: str, generation_prompt: str = "") -> str:
        """追加项目级最终提示词微调。"""
        prompt_text = (generation_prompt or "").strip()
        if not prompt_text:
            return base_prompt

        return f"""{base_prompt}

【用户最终提示词微调】
以下内容来自项目世界设定页，会作为最终提交给 AI 的补充要求，优先级高于通用写作偏好；如果与本任务的输出格式要求冲突，仍必须遵守本任务的格式要求。

{prompt_text}"""
    
    @classmethod
    def get_world_building_prompt(cls, title: str, theme: str, genre: str = "") -> str:
        """获取世界构建提示词"""
        return cls.format_prompt(
            cls.WORLD_BUILDING,
            title=title,
            theme=theme,
            genre=genre or "通用类型"
        )
    
    @classmethod
    def get_characters_batch_prompt(cls, count: int, time_period: str, location: str,
                                   atmosphere: str, rules: str, theme: str,
                                   genre: str = "", requirements: str = "") -> str:
        """获取批量角色生成提示词"""
        return cls.format_prompt(
            cls.CHARACTERS_BATCH_GENERATION,
            count=count,
            time_period=time_period,
            location=location,
            atmosphere=atmosphere,
            rules=rules,
            theme=theme,
            genre=genre or "通用类型",
            requirements=requirements or "无特殊要求"
        )
    
    @classmethod
    def get_complete_outline_prompt(cls, title: str, theme: str, genre: str,
                                   chapter_count: int, narrative_perspective: str,
                                   target_words: int, time_period: str, location: str,
                                   atmosphere: str, rules: str, characters_info: str,
                                   description: str = "",
                                   protagonists_info: str = "",
                                   requirements: str = "",
                                   mcp_references: str = "") -> str:
        """获取向导大纲生成提示词（支持MCP增强、类型适配和主角绑定）"""
        # 格式化MCP参考资料
        mcp_text = ""
        if mcp_references:
            mcp_text = "## MCP参考资料\n"
            mcp_text += "以下是搜索到的参考资料，可用于设计情节：\n\n"
            mcp_text += mcp_references
            mcp_text += "\n"

        # 格式化主角信息（强制约束）
        protagonists_text = ""
        if protagonists_info:
            protagonists_text = """## 📌 主角设定（必须使用）
以下是用户已创建的主角，生成大纲时**必须严格使用**：

""" + protagonists_info + """

⚠️ **强制要求**：
- protagonists 数组中的 name 必须使用上述主角姓名，不可自行创造！
- personality 和 initial_status 必须基于上述设定，可适当扩展但不可矛盾！
"""
        else:
            protagonists_text = """## 📌 主角设定
用户尚未创建主角，请根据类型和主题自行设计合适的主角。
"""

        # 根据类型选择对应的引导内容（支持多选类型合并）
        genre_guide = cls._resolve_genre_guide(genre or "")

        return cls.format_prompt(
            cls.COMPLETE_OUTLINE_GENERATION,
            title=title,
            theme=theme,
            genre=genre or "通用",
            chapter_count=chapter_count,
            narrative_perspective=narrative_perspective or "第三人称",
            target_words=target_words,
            description=description or "用户未提供初始想法",
            time_period=time_period or "未设定",
            location=location or "未设定",
            atmosphere=atmosphere or "未设定",
            rules=rules or "未设定",
            protagonists_info=protagonists_text,
            characters_info=characters_info or "暂无其他角色",
            genre_guide=genre_guide,
            mcp_references=mcp_text,
            requirements=requirements or "无特殊要求"
        )
    
    @classmethod
    def get_chapter_generation_prompt(cls, title: str, theme: str, genre: str,
                                      narrative_perspective: str, time_period: str,
                                      location: str, atmosphere: str, rules: str,
                                      characters_info: str, outlines_context: str,
                                      chapter_number: int, chapter_title: str,
                                      chapter_outline: str, style_content: str = "",
                                      target_word_count: int = 3000,
                                      memory_context: dict = None,
                                      linked_cards_context: str = "",
                                      mcp_references: str = "",
                                      deai_block: str = "") -> str:
        """
        获取章节完整创作提示词
        
        Args:
            style_content: 写作风格要求内容，如果提供则会追加到提示词中
            target_word_count: 目标字数，默认3000字
            memory_context: 记忆上下文（可选）
            mcp_references: MCP工具搜索的参考资料（可选）
            deai_block: 去 AI 味规则块（deai_rules.build_write_block），插在文风要求之后、字数要求之前
        """
        # 从配置读取字数控制参数
        from app.config import settings
        soft_range = settings.chapter_word_soft_range

        # 计算字数范围
        min_word_count = int(target_word_count * (1 - soft_range))
        max_word_count = int(target_word_count * (1 + soft_range))
        
        # 格式化记忆上下文
        memory_text = ""
        if memory_context:
            memory_text = "\n【🧠 智能记忆系统 - 重要参考】\n"
            memory_text += memory_context.get('recent_context', '')
            memory_text += "\n" + memory_context.get('relevant_memories', '')
            memory_text += "\n" + memory_context.get('foreshadows', '')
            memory_text += "\n" + memory_context.get('character_states', '')
            memory_text += "\n" + memory_context.get('plot_points', '')
            memory_text += "\n" + memory_context.get('causal_chains', '')
            memory_text += "\n" + memory_context.get('narrative_promises', '')
            memory_text += "\n" + memory_context.get('relationship_dynamics', '')
            memory_text += "\n" + memory_context.get('timeline_events', '')
            memory_text += "\n" + memory_context.get('pov_known_info', '')
            memory_text += "\n" + memory_context.get('affiliation_dynamics', '')
        
        # 格式化MCP参考资料
        mcp_text = ""
        if mcp_references:
            mcp_text = "\n【📚 MCP工具搜索 - 参考资料】\n"
            mcp_text += "以下是通过MCP工具搜索到的相关参考资料，可用于丰富情节和细节：\n\n"
            mcp_text += mcp_references
            mcp_text += "\n"
        
        # 格式化剧情卡片段落
        linked_cards_section = ""
        if linked_cards_context:
            linked_cards_section = f"""
【📇 剧情卡片素材 - 必须严格遵循】
以下是本章预先设计的剧情卡片，这些是创作的核心依据，必须在章节内容中体现：

{linked_cards_context}

**强制要求：**
1. **必须使用所有卡片内容** - 每个卡片中的情节、场景、冲突都必须在章节中出现
2. **严格遵循卡片设定** - 不得改变卡片中的核心情节、场景描述或冲突设定
3. **保持卡片顺序** - 按照卡片列出的顺序展开情节（除非逻辑上需要调整）
4. **完整呈现内容** - 不得省略或跳过任何卡片中的关键元素
5. **可以扩展细节** - 在不改变核心设定的前提下，可以添加对话、心理描写、环境细节等
6. **禁止自由发挥** - 不要添加与卡片内容无关或矛盾的新情节

**检查清单（创作完成后自查）：**
- ✓ 每个卡片的核心内容都已体现
- ✓ 卡片中的场景、角色、事件都已出现
- ✓ 没有与卡片设定矛盾的内容
- ✓ 卡片之间的逻辑连接自然流畅
"""
        
        # 解析类型/视角指导（章节级注入）
        genre_guide = cls._resolve_genre_guide(genre or "")
        perspective_guide = cls._resolve_perspective_guide(narrative_perspective or "")
        perspective_boundary_clause = cls._build_perspective_boundary_clause(narrative_perspective or "")

        base_prompt = cls.format_prompt(
            cls.CHAPTER_GENERATION,
            title=title,
            theme=theme,
            genre=genre,
            narrative_perspective=narrative_perspective,
            perspective_guide=perspective_guide,
            genre_guide=genre_guide,
            perspective_boundary_clause=perspective_boundary_clause,
            time_period=time_period,
            location=location,
            atmosphere=atmosphere,
            rules=rules,
            characters_info=characters_info,
            outlines_context=outlines_context,
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            chapter_outline=chapter_outline,
            target_word_count=target_word_count,
            min_word_count=min_word_count,
            max_word_count=max_word_count,
            linked_cards_section=linked_cards_section,
            deai_block=deai_block or ""
        )
        
        # 插入记忆上下文和MCP参考资料
        insert_text = ""
        if memory_text:
            insert_text += memory_text
        if mcp_text:
            insert_text += mcp_text
        
        if insert_text:
            base_prompt = base_prompt.replace(
                "本章信息：",
                insert_text + "\n\n本章信息："
            )
        
        # 如果有风格要求，应用到提示词中
        if style_content:
            return WritingStyleManager.apply_style_to_prompt(base_prompt, style_content)
        
        return base_prompt
    
    @classmethod
    def get_chapter_generation_with_context_prompt(cls, title: str, theme: str, genre: str,
                                                   narrative_perspective: str, time_period: str,
                                                   location: str, atmosphere: str, rules: str,
                                                   characters_info: str, outlines_context: str,
                                                   previous_content: str, chapter_number: int,
                                                   chapter_title: str, chapter_outline: str,
                                                   style_content: str = "",
                                                   target_word_count: int = 3000,
                                                   memory_context: dict = None,
                                                   linked_cards_context: str = "",
                                                   mcp_references: str = "",
                                                   deai_block: str = "") -> str:
        """
        获取章节完整创作提示词（带前置章节上下文和记忆增强）
        
        Args:
            style_content: 写作风格要求内容，如果提供则会追加到提示词中
            target_word_count: 目标字数，默认3000字
            memory_context: 记忆上下文（可选）
            mcp_references: MCP工具搜索的参考资料（可选）
            deai_block: 去 AI 味规则块（deai_rules.build_write_block），插在文风要求之后、字数要求之前
        """
        # 从配置读取字数控制参数
        from app.config import settings
        soft_range = settings.chapter_word_soft_range

        # 计算字数范围
        min_word_count = int(target_word_count * (1 - soft_range))
        max_word_count = int(target_word_count * (1 + soft_range))

        # 格式化记忆上下文
        memory_text = ""
        if memory_context:
            memory_text = memory_context.get('recent_context', '')
            memory_text += "\n" + memory_context.get('relevant_memories', '')
            memory_text += "\n" + memory_context.get('foreshadows', '')
            memory_text += "\n" + memory_context.get('character_states', '')
            memory_text += "\n" + memory_context.get('plot_points', '')
            memory_text += "\n" + memory_context.get('causal_chains', '')
            memory_text += "\n" + memory_context.get('narrative_promises', '')
            memory_text += "\n" + memory_context.get('relationship_dynamics', '')
            memory_text += "\n" + memory_context.get('timeline_events', '')
            memory_text += "\n" + memory_context.get('pov_known_info', '')
            memory_text += "\n" + memory_context.get('affiliation_dynamics', '')
        else:
            memory_text = "暂无相关记忆"
        
        # 格式化MCP参考资料
        if mcp_references:
            memory_text += "\n\n【📚 MCP工具搜索 - 参考资料】\n"
            memory_text += "以下是通过MCP工具搜索到的相关参考资料，可用于丰富情节和细节：\n\n"
            memory_text += mcp_references
        
        # 格式化剧情卡片段落
        linked_cards_section = ""
        if linked_cards_context:
            linked_cards_section = f"""
【📇 剧情卡片素材 - 必须严格遵循】
以下是本章预先设计的剧情卡片，这些是创作的核心依据，必须在章节内容中体现：

{linked_cards_context}

**强制要求：**
1. **必须使用所有卡片内容** - 每个卡片中的情节、场景、冲突都必须在章节中出现
2. **严格遵循卡片设定** - 不得改变卡片中的核心情节、场景描述或冲突设定
3. **保持卡片顺序** - 按照卡片列出的顺序展开情节（除非逻辑上需要调整）
4. **完整呈现内容** - 不得省略或跳过任何卡片中的关键元素
5. **可以扩展细节** - 在不改变核心设定的前提下，可以添加对话、心理描写、环境细节等
6. **禁止自由发挥** - 不要添加与卡片内容无关或矛盾的新情节

**检查清单（创作完成后自查）：**
- ✓ 每个卡片的核心内容都已体现
- ✓ 卡片中的场景、角色、事件都已出现
- ✓ 没有与卡片设定矛盾的内容
- ✓ 卡片之间的逻辑连接自然流畅
"""
        
        # 解析类型/视角指导（章节级注入）
        genre_guide = cls._resolve_genre_guide(genre or "")
        perspective_guide = cls._resolve_perspective_guide(narrative_perspective or "")
        perspective_boundary_clause = cls._build_perspective_boundary_clause(narrative_perspective or "")

        base_prompt = cls.format_prompt(
            cls.CHAPTER_GENERATION_WITH_CONTEXT,
            title=title,
            theme=theme,
            genre=genre,
            narrative_perspective=narrative_perspective,
            perspective_guide=perspective_guide,
            genre_guide=genre_guide,
            perspective_boundary_clause=perspective_boundary_clause,
            time_period=time_period,
            location=location,
            atmosphere=atmosphere,
            rules=rules,
            characters_info=characters_info,
            outlines_context=outlines_context,
            previous_content=previous_content,
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            chapter_outline=chapter_outline,
            target_word_count=target_word_count,
            min_word_count=min_word_count,
            max_word_count=max_word_count,
            memory_context=memory_text,
            linked_cards_section=linked_cards_section,
            deai_block=deai_block or ""
        )
        
        # 如果有风格要求，应用到提示词中
        if style_content:
            return WritingStyleManager.apply_style_to_prompt(base_prompt, style_content)
        
        return base_prompt
    

    @classmethod
    def get_single_character_prompt(cls, project_context: str, user_input: str) -> str:
        """获取单个角色生成提示词"""
        return cls.format_prompt(
            cls.SINGLE_CHARACTER_GENERATION,
            project_context=project_context,
            user_input=user_input
        )
    
    @classmethod
    def get_single_organization_prompt(cls, project_context: str, user_input: str) -> str:
        """获取单个组织生成提示词"""
        return cls.format_prompt(
            cls.SINGLE_ORGANIZATION_GENERATION,
            project_context=project_context,
            user_input=user_input
        )


# 创建全局提示词服务实例
prompt_service = PromptService()
