"""剧情相关的 Prompt 模板"""
from typing import Dict, Any, Optional, List

# 主线节点数按书长缩放：约每 20 章一个节点（≈ 一个 10-30 章的剧情单元），夹在 [5, 16]
CHAPTERS_PER_MAIN_BEAT = 20
MIN_MAIN_BEATS = 5
MAX_MAIN_BEATS = 16
# 开篇节点（觉醒 / 金手指到手 / 第一次打脸）篇幅上限：网文前 30 章定生死，开篇不能拖
OPENING_BEAT_MAX_CHAPTERS = 12


def suggested_beat_count(chapters: Optional[int]) -> tuple[int, int]:
    """全书章数 → 建议主线节点数区间 (lo, hi)。未知章数沿用旧的 5-8。"""
    if not chapters or chapters <= 0:
        return MIN_MAIN_BEATS, 8
    target = round(chapters / CHAPTERS_PER_MAIN_BEAT)
    clamp = lambda v: max(MIN_MAIN_BEATS, min(MAX_MAIN_BEATS, v))  # noqa: E731
    lo, hi = clamp(target - 1), clamp(max(target + 2, 8))
    return (hi, hi) if lo > hi else (lo, hi)


class PlotPromptTemplates:
    """剧情 Prompt 模板管理器"""

    # 类型化剧情结构模板 - 网文风格
    GENRE_PLOT_STRUCTURES = {
        "修仙": {
            "name": "修仙升级流",
            "description": "以境界突破为核心驱动，机缘与打脸交替的爽文节奏",
            "arcs": ["入门筑基", "宗门立足", "区域争霸", "大陆风云", "飞升之战"],
            "arc_description": "每个大阶段代表一个势力层级的征服，完成后进入更高层次的世界",
            "beat_cycle": ["机缘发现", "势力冲突", "境界突破", "打脸收尾", "新敌浮现"],
            "beat_types": {
                "treasure_discovery": "机缘发现 - 发现功法、丹药、法宝、秘境等修炼资源",
                "power_up": "境界突破 - 修为提升的关键时刻，战力飞跃",
                "face_slap": "打脸时刻 - 碾压曾经轻视主角的人，旁观者震惊",
                "enemy_reveal": "强敌浮现 - 更高层次的对手出现，形成新压力",
                "sect_conflict": "宗门纷争 - 势力之间的资源争夺、地位之争",
                "secret_revealed": "身世揭秘 - 主角血脉、传承、身份的秘密揭露",
                "alliance": "结盟借势 - 获得强者认可、拜师、加入势力",
                "trial": "试炼历练 - 秘境探索、宗门大比、生死历练",
                "cliff_hanger": "悬念钩子 - 为下一阶段埋下伏笔"
            },
            "rhythm_guide": """【修仙文节奏要点】
- 每5-8章安排一次小突破或小打脸
- 每15-20章安排一次境界大突破或大打脸
- 每30-50章完成一个地图/势力层级的循环
- 敌人升级路线：杂鱼→内门弟子→核心弟子→长老→掌门→更高势力
- 机缘密度：保持主角始终有"下一个目标"可追求
- 打脸铺垫：对方越嚣张，打脸越爽"""
        },
        "玄幻": {
            "name": "玄幻热血流",
            "description": "以战斗升级为核心，热血对决与势力扩张交织",
            "arcs": ["觉醒崛起", "势力成形", "区域称霸", "大陆争锋", "位面征战"],
            "arc_description": "从个人成长到势力建立，最终成为顶级强者",
            "beat_cycle": ["实力展示", "强敌挑战", "苦战突破", "碾压收割", "更强者现"],
            "beat_types": {
                "awakening": "觉醒时刻 - 血脉觉醒、系统激活、天赋显现",
                "battle_victory": "战斗胜利 - 关键战斗的胜利，以弱胜强",
                "power_up": "实力突破 - 等级提升、技能领悟、装备升级",
                "face_slap": "打脸震慑 - 碾压对手，震惊全场",
                "team_building": "团队组建 - 收服小弟、建立势力",
                "treasure_hunt": "夺宝争锋 - 争夺资源、抢夺机缘",
                "enemy_boss": "BOSS战 - 与阶段性大BOSS的决战",
                "new_realm": "新世界 - 进入更高层次的世界/位面",
                "cliff_hanger": "悬念钩子 - 埋下伏笔"
            },
            "rhythm_guide": """【玄幻文节奏要点】
- 战斗密度高，每3-5章至少一场战斗
- 以弱胜强是核心爽点，要铺垫实力差距
- 每10-15章一次重要战斗胜利
- 势力扩张与个人实力提升并行
- 热血燃点：绝境反杀、守护同伴、突破极限"""
        },
        "都市": {
            "name": "都市逆袭流",
            "description": "以打脸装逼为核心，社会层级逐步突破",
            "arcs": ["逆袭起步", "圈层突破", "行业称霸", "顶级博弈", "人生巅峰"],
            "arc_description": "从底层逆袭到顶层，每个阶段征服一个社会圈层",
            "beat_cycle": ["被轻视", "展示实力", "打脸震惊", "收获资源", "新对手现"],
            "beat_types": {
                "underestimated": "被轻视 - 被人看不起、嘲讽、刁难",
                "identity_hide": "扮猪吃虎 - 隐藏身份实力，低调行事",
                "skill_reveal": "实力展示 - 关键时刻亮出真本事",
                "face_slap": "打脸时刻 - 反杀打脸，旁观者震惊",
                "resource_gain": "资源获取 - 获得金钱、人脉、地位",
                "beauty_encounter": "红颜助力 - 与女主的情感互动",
                "level_up": "层级跃升 - 进入更高的社会圈层",
                "old_enemy": "旧敌重逢 - 与过去的仇人再次对决",
                "new_challenge": "新挑战 - 更强大的对手或更大的目标",
                "cliff_hanger": "悬念钩子 - 埋下伏笔"
            },
            "rhythm_guide": """【都市文节奏要点】
- 打脸是核心爽点，每5-10章一次打脸
- 铺垫越足打脸越爽：对方要够嚣张、够得意
- 旁观者反应是关键：震惊、后悔、巴结
- 每15-20章完成一个圈层的征服
- 女主线穿插其中，不要喧宾夺主
- 金手指使用要克制，保持悬念"""
        },
        "悬疑": {
            "name": "悬疑推理流",
            "description": "以谜题解密为核心，层层反转揭示真相",
            "arcs": ["案件初现", "深入调查", "假相揭露", "真凶浮现", "真相大白"],
            "arc_description": "从表面现象到深层真相，每次揭露都带来新的谜团",
            "beat_cycle": ["悬念设置", "线索发现", "推理分析", "误导陷阱", "反转揭示"],
            "beat_types": {
                "mystery_hook": "悬念钩子 - 设置核心谜题，引发好奇",
                "clue_discovery": "线索发现 - 发现关键证据或信息",
                "deduction": "推理分析 - 主角的推理过程展示",
                "red_herring": "误导陷阱 - 故意误导读者的假线索",
                "suspect_reveal": "嫌疑人 - 新的嫌疑人浮出水面",
                "twist": "情节反转 - 出乎意料的发展",
                "truth_partial": "部分真相 - 揭露部分真相，留更大悬念",
                "danger": "危机时刻 - 主角陷入危险",
                "final_reveal": "真相大白 - 最终真相的揭示",
                "cliff_hanger": "悬念钩子 - 新的谜团"
            },
            "rhythm_guide": """【悬疑文节奏要点】
- 每章结尾必须有钩子，维持悬念
- 线索要公平：读者能看到但想不到
- 每10-15章一次中反转
- 每30-50章一次大反转
- 误导要自然，不能刻意欺骗读者
- 推理过程要合理，避免开挂式破案"""
        },
        "言情": {
            "name": "言情甜虐流",
            "description": "以情感发展为核心，甜蜜与虐心交替",
            "arcs": ["初遇心动", "暧昧试探", "确认心意", "误会分离", "重逢圆满"],
            "arc_description": "从相遇到相爱，经历波折最终在一起",
            "beat_cycle": ["甜蜜互动", "心意萌动", "误会产生", "虐心时刻", "和解升温"],
            "beat_types": {
                "first_meet": "初遇心动 - 男女主的第一次相遇",
                "sweet_moment": "甜蜜时刻 - 暧昧互动、心动瞬间",
                "jealousy": "吃醋时刻 - 因第三者产生的醋意",
                "confession": "表白告白 - 心意的表达",
                "misunderstanding": "误会产生 - 因误解产生隔阂",
                "heartbreak": "虐心时刻 - 分离、背叛、伤害",
                "sacrifice": "牺牲守护 - 为对方付出、保护",
                "reconciliation": "和解重逢 - 误会解开、重归于好",
                "intimacy": "亲密升级 - 关系更进一步",
                "happy_ending": "圆满结局 - 最终在一起"
            },
            "rhythm_guide": """【言情文节奏要点】
- 甜虐比例根据定位：甜宠7:3，虐恋3:7
- 每3-5章安排一个甜蜜/心动时刻
- 虐心要有意义，不能为虐而虐
- 误会要合理，不能智商下线
- 配角（情敌、闺蜜）适度出场
- BE还是HE要有前兆，不要突然转向"""
        }
    }

    # 网文通用节奏引导
    WEBNOVEL_RHYTHM_GUIDE = """
## 网文节奏设计核心原则

### 1. 爽点密度
网文的核心是"爽"，爽点必须密集：
- **小爽点**：每2-3章一个（小胜利、小打脸、小收获）
- **中爽点**：每10-15章一个（重要战斗胜利、关键突破）
- **大爽点**：每30-50章一个（境界飞跃、大仇得报、真相揭露）

### 2. 钩子设计
每个节点结尾必须有钩子：
- **悬念钩子**：留下未解之谜
- **危机钩子**：主角陷入困境
- **期待钩子**：预告即将到来的好事/大战
- **反转钩子**：出乎意料的发展

### 3. 冲突升级规律
敌人和挑战必须持续升级：
- 小喽啰 → 中层管理 → 高层 → 幕后BOSS → 更大势力
- 每打败一个层级，立刻引出更高层级的敌人
- 不要让主角长时间没有对手

### 4. 打脸三要素
打脸是网文最核心的爽点：
1. **铺垫**：对方足够嚣张、看不起主角、威胁主角
2. **反转**：主角展示真正实力，碾压对手
3. **震惊**：旁观者的反应（震惊、后悔、巴结、跪舔）

### 5. 黄金结构
每个小循环遵循：
**期待 → 阻碍 → 努力 → 突破 → 收获 → 新期待**
"""

    @staticmethod
    def get_plot_card_prompt(
        project_data: Dict[str, Any],
        outline_content: Optional[str] = None,
        card_type: str = "plot",
        extend_from: Optional[str] = None,
        custom_prompt: Optional[str] = None
    ) -> str:
        """生成剧情卡片的 Prompt"""
        
        card_type_descriptions = {
            "plot": "剧情事件卡片，描述具体的故事情节和事件",
            "character": "角色卡片，描述角色的行为、对话和心理活动",
            "scene": "场景卡片，描述具体的环境、氛围和场景设置",
            "conflict": "冲突卡片，描述矛盾冲突的产生、发展和解决"
        }
        
        base_prompt = f"""
# 剧情卡片生成任务

## 项目信息
- **项目标题**: {project_data.get('title', '未命名项目')}
- **小说类型**: {project_data.get('genre', '通用')}
- **主题**: {project_data.get('theme', '待定')}

## 卡片类型
**{card_type}**: {card_type_descriptions.get(card_type, '通用剧情卡片')}

## 生成要求
请生成 3-5 个具体的剧情卡片，每个卡片包含：

### 卡片结构
1. **标题**: 简洁明确的卡片名称（10-20字）
2. **内容**: 详细描述（100-300字）
   - 具体的情节内容或场景描述
   - 涉及的角色和行为
   - 情感氛围和关键细节
   - 与整体故事的关联

### 内容要求
- 确保与故事大纲和主题保持一致
- 每个卡片都应该是独立且完整的情节单元
- 卡片之间可以有逻辑关联但不强制连续
- 为后续章节写作提供具体的素材支撑
- **如果基于章纲生成**：严格围绕指定章节的具体事件，避免跨章内容
- **如果基于大纲生成**：覆盖故事不同发展阶段，保持整体连贯性
"""
        
        if outline_content:
            base_prompt += f"\n## 参考大纲\n{outline_content}\n"
            
            # 检测是否包含章纲详情（通过关键词判断）
            has_chapter_details = ("【章纲详情】" in outline_content or 
                                 "第" in outline_content and "章：" in outline_content)
            
            if has_chapter_details:
                # 基于章纲生成的强约束
                base_prompt += """
## 章纲生成约束
**重要**：上述参考大纲中包含具体章节信息，请严格按以下要求生成剧情卡片：

### 生成范围限制
- **只描述该章节中应该发生的具体事件**，不要涉及其他章节的内容
- 优先覆盖章纲中提到的关键事件（key events）和剧情要点（plot points）
- 避免引入与该章节无关的新角色、新设定或与大纲矛盾的情节

### 内容标注要求
- 每个卡片的内容开头建议注明：**【对应章节】第X章：章节标题**
- 确保卡片内容与章节的核心冲突、关键转折点紧密相关
- 如果章纲中提到具体角色行为，优先将其转化为对应的剧情卡片

### 避免事项
- 不要生成跨章节的宏观情节描述
- 不要创造与章纲矛盾的新情节线
- 避免过于抽象的概念性描述，要具体到可执行的场景和事件
"""
            else:
                # 仅基于故事大纲的相对宽松约束
                base_prompt += """
## 大纲生成指导
基于上述故事大纲，请生成能够支撑整体故事发展的关键剧情卡片：

### 覆盖建议
- 尽量覆盖故事的不同发展阶段（开端、发展、高潮、结局）
- 每个卡片可在内容中简要说明属于故事的哪个阶段
- 确保卡片之间有一定的逻辑关联，但保持相对独立

### 内容深度
- 可以是具体的场景事件，也可以是关键的情节转折
- 为后续章节划分和详细展开预留空间
"""
        
        if extend_from:
            base_prompt += f"\n## 延伸基础\n基于以下内容进行延伸创作：\n{extend_from}\n"
        
        if custom_prompt:
            base_prompt += f"\n## 特殊要求\n{custom_prompt}\n"
        
        base_prompt += """
## 输出格式
请按以下JSON格式输出：

**重要**：字段名使用英文，但所有文字内容（标题、描述、标签等）必须使用简体中文撰写！

```json
[
    {
        "title": "卡片标题",
        "content": "详细内容描述",
        "card_type": "plot/character/scene/conflict",
        "tags": ["标签1", "标签2"]
    }
]
```
"""
        
        return base_prompt.strip()
    
    @classmethod
    def get_plot_line_prompt(
        cls,
        project_data: Dict[str, Any],
        outline_content: Optional[str] = None,
        plot_cards: Optional[List[Dict]] = None,
        line_type: str = "main",
        custom_prompt: Optional[str] = None,
        count: int = 3,
        historical_context: Optional[str] = None,
        previous_line_summary: Optional[Dict[str, Any]] = None,
        sequence_index: Optional[int] = None
    ) -> str:
        """生成剧情线的 Prompt（网文风格优化版）"""

        line_type_descriptions = {
            "main": "主线剧情，推动故事核心发展的主要情节线",
            "sub": "支线剧情，丰富故事内容的次要情节线",
            "character": "角色线，专注于某个角色成长和发展的情节线"
        }

        # 获取类型对应的剧情结构模板
        genre = project_data.get('genre', '通用')
        genre_structure = None
        for key in cls.GENRE_PLOT_STRUCTURES:
            if key in genre or genre in key:
                genre_structure = cls.GENRE_PLOT_STRUCTURES[key]
                break

        # 主线且已知全书章数：estimated_chapters 固定为全书章数，描述按全书体量规划
        chapter_count = project_data.get('chapter_count')
        main_with_length = line_type == "main" and isinstance(chapter_count, int) and chapter_count > 0
        length_row = f"\n| 全书章数 | {chapter_count} 章 |" if main_with_length else ""

        base_prompt = f"""
# 剧情线生成任务

## 项目信息
| 项目 | 内容 |
|------|------|
| 书名 | {project_data.get('title', '未命名项目')} |
| 类型 | {genre} |
| 主题 | {project_data.get('theme', '待定')} |
| 背景 | {project_data.get('world_time_period', '现代')} · {project_data.get('world_location', '待定')} |{length_row}

## 剧情线类型
**{line_type}**: {line_type_descriptions.get(line_type, '通用剧情线')}"""

        if main_with_length:
            base_prompt += f"""

## 全书体量
主线贯穿全书共 {chapter_count} 章。描述必须按这个体量规划：开局（前 ~10 章内金手指到手 / 第一次冲突）→ 若干个卷 / 地图阶段（每阶段换更高层级的对手与舞台）→ 终局。写清每个阶段主角的境界 / 地位变化与对手层级，不要按短篇的体量去写。"""

        # 添加类型化结构引导
        if genre_structure:
            base_prompt += f"""

## 【{genre}】剧情结构指南
**模式**: {genre_structure['name']}
**特点**: {genre_structure['description']}

### 推荐的大阶段划分
{' → '.join(genre_structure['arcs'])}

### 每个阶段的节奏循环
{' → '.join(genre_structure['beat_cycle'])}

{genre_structure['rhythm_guide']}"""
        
        # 添加历史背景信息
        if historical_context:
            base_prompt += f"""

## 历史剧情线背景
以下是项目中已有的剧情线，请参考这些内容保持剧情连贯性：
{historical_context}"""
        
        # 添加上一条剧情线信息
        if previous_line_summary:
            base_prompt += f"""

## 上一条剧情线（必须承接）
**标题**: {previous_line_summary.get('title', '未知')}
**描述**: {previous_line_summary.get('description', '暂无描述')}

**重要要求**: 新生成的剧情线必须在情节上承接上述剧情线，确保：
1. 延续上一条剧情线的悬念和冲突
2. 保持角色动机和行为的一致性
3. 推进整体故事发展，不能出现逻辑断层
4. 可以引入新的冲突，但要基于前面的铺垫"""
        
        # 添加序列信息
        sequence_info = ""
        if sequence_index is not None:
            sequence_info = f"（当前生成第 {sequence_index} 条）"
        
        base_prompt += f"""

## 生成要求{sequence_info}
请生成 {count} 条剧情线，每条剧情线包含：

### 剧情线结构
1. **标题**: 剧情线名称（10-30字），要有网文感、吸引力

2. **描述**: 剧情线整体方向概述（300-600字）
   - 这条剧情线的**核心爽点/虐点/燃点**是什么
   - 主要涉及的角色和冲突关系
   - 剧情发展脉络：从哪里开始 → 经历什么波折 → 最终到哪里
   - 包含哪些**打脸/逆袭/反转**的关键时刻
   - 如何与主线或其他剧情线交织

### 网文风格要求
- **爽点密集**：每条剧情线要包含多个小高潮和1-2个大高潮
- **冲突升级**：敌人/挑战要逐步升级，不能平铺直叙
- **钩子设计**：每个阶段结束都要有悬念，引出下一阶段
- **读者期待**：让读者始终有"接下来会发生什么"的期待
"""
        
        # 添加角色信息
        characters = project_data.get('characters', [])
        if characters:
            characters_list = []
            for char in characters[:8]:  # 限制显示数量
                char_name = char.get('name', '未命名')
                char_role = char.get('role_type', '角色')
                # 类型安全处理：确保 personality 是字符串才进行切片
                personality = char.get('personality', '待定')
                if isinstance(personality, str):
                    char_personality = personality[:50]
                    personality_suffix = '...' if len(personality) > 50 else ''
                else:
                    char_personality = str(personality)[:50] if personality else '待定'
                    personality_suffix = '...' if len(str(personality)) > 50 else ''
                characters_list.append(f"- **{char_name}** ({char_role}): {char_personality}{personality_suffix}")
            
            characters_text = "\n".join(characters_list)
            base_prompt += f"\n## 主要角色\n{characters_text}\n"
        
        # 添加组织信息
        organizations = project_data.get('organizations', [])
        if organizations:
            orgs_list = []
            for org in organizations[:5]:  # 限制显示数量
                org_name = org.get('name', '未命名组织')
                org_type = org.get('organization_type', '组织')
                # 类型安全处理：确保 organization_purpose 是字符串才进行切片
                purpose = org.get('organization_purpose', '待定')
                if isinstance(purpose, str):
                    org_purpose = purpose[:50]
                    purpose_suffix = '...' if len(purpose) > 50 else ''
                else:
                    org_purpose = str(purpose)[:50] if purpose else '待定'
                    purpose_suffix = '...' if len(str(purpose)) > 50 else ''
                orgs_list.append(f"- **{org_name}** ({org_type}): {org_purpose}{purpose_suffix}")
            
            orgs_text = "\n".join(orgs_list)
            base_prompt += f"\n## 重要组织\n{orgs_text}\n"
        
        if outline_content:
            base_prompt += f"\n## 参考大纲\n{outline_content}\n"
        
        if plot_cards:
            cards_list = []
            for card in plot_cards[:5]:
                card_title = card.get('title', '')
                # 类型安全处理：确保 content 是字符串才进行切片
                content = card.get('content', '')
                if isinstance(content, str):
                    card_content = content[:100]
                else:
                    card_content = str(content)[:100] if content else ''
                cards_list.append(f"- {card_title}: {card_content}...")
            
            cards_text = "\n".join(cards_list)
            base_prompt += f"\n## 可用剧情卡片\n{cards_text}\n"
        
        if custom_prompt:
            base_prompt += f"\n## 特殊要求\n{custom_prompt}\n"
        
        example_est = chapter_count if main_with_length else 25
        if main_with_length:
            est_rule = f"5. 全书共 {chapter_count} 章，主线贯穿全书：estimated_chapters 必须等于 {chapter_count}（固定值，不要自行估算）"
        else:
            est_rule = """5. estimated_chapters 的估算逻辑（请在心里计算后直接给出数字，不要在JSON里解释）：
   - 主线剧情线(main): 通常 30-50 章（占项目总章节数的 60-80%）
   - 重要支线(sub): 根据复杂度，通常 10-25 章
   - 次要支线/角色线(character/minor): 通常 5-12 章
   - 估算参考因素：
     * 剧情复杂度：涉及角色多、冲突复杂的需要更多章节
     * 剧情线的重要性和篇幅占比"""

        base_prompt += f"""
## 输出格式
请按以下JSON格式输出，数组必须包含且仅包含 {count} 个元素：

**重要**: 必须使用英文字段名，不要使用中文字段名！

```json
[
    {{
        "title": "剧情线标题",
        "description": "剧情线详细描述",
        "line_type": "main",
        "estimated_chapters": {example_est},
        "plot_cards": []
    }}
]
```

**严格要求（请逐条严格遵守）**:
1. 输出的JSON数组必须严格包含 {count} 条剧情线，不得多于或少于此数量
2. 必须使用英文字段名：title, description, line_type, estimated_chapters, plot_cards
3. line_type 必须是 "main", "sub", 或 "character" 之一
4. **estimated_chapters 字段是【必填】字段，且必须满足以下条件**：
   - 必须存在 estimated_chapters 字段，不能省略
   - estimated_chapters 的值必须是**阿拉伯数字整型**，例如 25、30、40
   - **不要**写成字符串或带单位的形式，例如 "25章"、"三十"、"30 chapters" 都是错误的
   - 正确示例：`"estimated_chapters": {example_est}`
{est_rule}
6. 不要在字段名中使用中文
7. **所有文字内容（标题、描述等）必须使用简体中文撰写**，不得出现英文描述
"""

        return base_prompt.strip()

    @classmethod
    def get_single_line_beats_prompt(
        cls,
        project_data: Dict[str, Any],
        line: Dict[str, Any]
    ) -> str:
        """
        生成单条剧情线节点规划的精简 Prompt（网文风格优化版）
        """
        title = project_data.get('title', '未命名')
        genre = project_data.get('genre', '通用')

        line_title = line.get('title', '未命名')
        line_desc = line.get('description', '')
        line_type = line.get('line_type', 'main')

        # 获取类型对应的节点类型
        genre_structure = None
        beat_types_hint = "opening, power_up, face_slap, twist, climax, cliff_hanger"
        for key in cls.GENRE_PLOT_STRUCTURES:
            if key in genre or genre in key:
                genre_structure = cls.GENRE_PLOT_STRUCTURES[key]
                beat_types_hint = ", ".join(list(genre_structure['beat_types'].keys())[:6])
                break

        chapters = line.get('estimated_chapters')
        chapters = chapters if isinstance(chapters, int) and chapters > 0 else None
        lo, hi = suggested_beat_count(chapters)
        count_text = f"{lo}-{hi} 个节点" if lo != hi else f"{lo} 个节点"

        length_block = ""
        chapters_field = ""
        chapters_rule = ""
        if chapters:
            opening_cap = min(OPENING_BEAT_MAX_CHAPTERS, max(4, chapters // 10))
            length_block = f"""
【全书体量】全书 {chapters} 章，约每 {CHAPTERS_PER_MAIN_BEAT} 章一个节点；每个节点 = 一个 10-30 章的剧情单元（一张地图 / 一个对手层级 / 一件大事），后续会被切成若干个 4 章桥段来写
【篇幅纪律】
- chapters 之和 = {chapters}；第一个节点（开篇：金手指到手 / 第一次冲突）≤ {opening_cap} 章，前 30 章内必须进入第一个正式冲突循环
- weight 只表示重要性（高潮节点最高），不再代表篇幅；篇幅由 chapters 单独给出
- 相邻节点必须换舞台或换对手层级，不得在同一层级原地打转"""
            chapters_field = f"\n- chapters: 本节点预计章数（整数，之和 = {chapters}）"
            chapters_rule = ', "chapters": 8'
        rhythm = genre_structure['rhythm_guide'] if genre_structure else ""

        prompt = f"""为以下剧情线设计 {count_text}(beats)，采用网文节奏。

【项目】{title} ({genre})
【剧情线】{line_title} ({line_type})
【描述】{line_desc}{length_block}

【网文节奏要求】
1. 每2-3个节点安排一个爽点（打脸/突破/收获）
2. 每个节点结尾要有钩子（悬念/危机/期待）
3. 冲突要持续升级，敌人越来越强：对手层级、赌注、舞台逐节点抬高，不得回落
{rhythm}

【节点结构】
- index: 序号
- key: 节点类型（{beat_types_hint}）
- title: 标题（网文感，吸引人）
- description: 200-300字，包含：核心事件、爽点设计、承上启下、钩子设计
- weight: 重要性权重（和=1.0，全书最大高潮所在节点最高）{chapters_field}
- location: 本节点主要舞台（地图 / 势力 / 城市，可空）
- antagonist: 本节点主要对手或压力来源及其层级（可空）
- realm: 本节点主角境界 / 实力 / 地位从哪到哪（如"炼气三层→炼气五层"，可空）

【输出格式】仅输出JSON数组：
```json
[
  {{"index": 1, "key": "opening", "title": "废材觉醒：被驱逐的天才", "description": "故事开始，主角曾是天才却沦为废物，遭众人嘲笑。就在绝望时刻，沉睡的金手指觉醒...", "weight": 0.08{chapters_rule}, "location": "青云镇", "antagonist": "族中长辈与同辈天才", "realm": "凡人→炼气一层"}},
  {{"index": 2, "key": "power_up", "title": "秘密修炼：逆天功法", "description": "主角开始秘密修炼，白天装弱夜晚苦练，实力飞速提升但隐而不发...", "weight": 0.12{chapters_rule}, "location": "青云宗外门", "antagonist": "外门执事", "realm": "炼气一层→炼气四层"}}
]
```"""
        return prompt

    @classmethod
    def _main_timeline_table(cls, main_ctx: Dict[str, Any], highlight: Optional[tuple] = None) -> str:
        """主线节点表：| 节点 | 标题 | 权重 | 对应章节 | 概要 |；highlight=(a,b) 时区间内节点前缀 ★。"""
        rows = ["| 节点 | 标题 | 权重 | 对应章节 | 概要 |", "|---|---|---|---|---|"]
        for r in main_ctx.get("beats", []):
            idx = r.get("index")
            mark = "★ " if highlight and highlight[0] <= idx <= highlight[1] else ""
            ch = (
                f"第 {r['chapter_start']}-{r['chapter_end']} 章"
                if r.get("chapter_start") and r.get("chapter_end") else "待定"
            )
            desc = str(r.get("description") or "")[:60]
            rows.append(f"| {mark}{idx} | {r.get('title', '')} | {float(r.get('weight') or 0):.0%} | {ch} | {desc} |")
        return "\n".join(rows)

    @classmethod
    def get_sub_line_prompt(
        cls,
        project_data: Dict[str, Any],
        outline_content: Optional[str],
        main_ctx: Dict[str, Any],
        existing_subs: List[Dict[str, Any]],
        line_type: str,
        custom_prompt: Optional[str],
        sequence_index: int,
        total: int,
        budget_cap: Optional[int],
    ) -> str:
        """支线结构 prompt：把支线放到主线时间轴上设计（并行交织，不是主线续集）。"""
        genre = project_data.get('genre', '通用')
        climax = main_ctx.get("climax_beat")
        climax_title = next((r.get("title", "") for r in main_ctx.get("beats", []) if r.get("index") == climax), "")
        prompt = f"""
# 支线设计任务（第 {sequence_index}/{total} 条）

## 项目信息
| 项目 | 内容 |
|------|------|
| 书名 | {project_data.get('title', '未命名项目')} |
| 类型 | {genre} |
| 主题 | {project_data.get('theme', '待定')} |
| 全书章数 | {main_ctx.get('estimated_chapters') or '待定'} |

## 主线时间轴（支线必须挂在这条轴上）
主线《{main_ctx.get('title', '')}》共 {len(main_ctx.get('beats', []))} 个节点；权重最高的是 [节点 {climax}] {climax_title}（全书最大高潮所在）。
{cls._main_timeline_table(main_ctx)}

## 已有支线（不得重复其题材、角色诉求与高潮位置）
"""
        if existing_subs:
            for s in existing_subs:
                desc = str(s.get("description") or "")[:100]
                prompt += (
                    f"- 《{s.get('title', '')}》（{s.get('mode') or '未锚定'}，锚定节点 "
                    f"{s.get('anchor_start_beat', '?')}-{s.get('anchor_end_beat', '?')}）：{desc}\n"
                )
        else:
            prompt += "（暂无）\n"

        cap_rule = f"本条 ≤ {budget_cap} 章；" if budget_cap else ""
        prompt += f"""
## 支线三种模式（必选其一）
- companion 伴生：贯穿 ≥3 个主线节点，低频保温 + 1-2 次爆发。典型：感情线、成长线、师徒线
- inserted 插入：集中在 1-2 个主线节点内完成起承转合后退场。典型：某张地图的势力线、配角线、一次任务线
- converge 汇流：独立发展一段，最后并入主线某个节点的兑现。典型：复仇线、身世线、暗中布局线

## 网文支线纪律
1. 支线为主线服务：共享主角/配角但诉求不同，不得复述主线已有事件
2. 支线高潮与主线最大高潮（节点 {climax}）错峰；只有 converge 模式可以把结局并入主线节点
3. 支线有明确起点与终点：anchor_start_beat / anchor_end_beat 必须是上表中的节点序号，区间外这条线不出场
4. estimated_chapters 是篇幅预算：这条线作为 B 线重点推进的章数（不是独立章）。{cap_rule}companion 取接近上限，inserted 取 4-8，converge 取 6-12
5. 描述（300-500 字）写清：核心诉求、涉及角色、起点事件 → 中段波折 → 终点状态，以及它在哪个主线节点期间最活跃
"""
        characters = project_data.get('characters', [])
        if characters:
            prompt += "\n## 主要角色\n" + "\n".join(
                f"- **{c.get('name', '未命名')}** ({c.get('role_type', '角色')}): {str(c.get('personality') or '待定')[:50]}"
                for c in characters[:8]
            ) + "\n"
        if outline_content:
            prompt += f"\n## 参考大纲\n{outline_content}\n"
        if custom_prompt:
            prompt += f"\n## 特殊要求\n{custom_prompt}\n"

        prompt += """
## 输出格式（严格 JSON，英文字段名，简体中文内容）
```json
[
    {
        "title": "支线标题（10-30 字，要有网文感）",
        "description": "支线整体描述（300-500 字）",
        "line_type": "__LINE_TYPE__",
        "mode": "companion | inserted | converge",
        "anchor_start_beat": 1,
        "anchor_end_beat": 3,
        "estimated_chapters": 12,
        "plot_cards": []
    }
]
```
**严格要求**：
1. 数组必须且只能有 1 个元素
2. mode 只能是 companion / inserted / converge 之一
3. anchor_start_beat ≤ anchor_end_beat，且都是主线时间轴表中的节点序号（阿拉伯数字整型）
4. estimated_chapters 为阿拉伯数字整型，不带单位
5. 所有文字内容使用简体中文
""".replace("__LINE_TYPE__", line_type)
        return prompt.strip()

    @classmethod
    def get_sub_line_beats_prompt(
        cls,
        project_data: Dict[str, Any],
        line: Dict[str, Any],
        main_ctx: Dict[str, Any],
        quota: int,
    ) -> str:
        """支线节点 prompt：每个节点标 anchor_beat（落在哪个主线节点期间）与 relation。"""
        genre = project_data.get('genre', '通用')
        beat_types_hint = "opening, power_up, face_slap, twist, climax, cliff_hanger"
        for key in cls.GENRE_PLOT_STRUCTURES:
            if key in genre or genre in key:
                beat_types_hint = ", ".join(list(cls.GENRE_PLOT_STRUCTURES[key]['beat_types'].keys())[:6])
                break
        a, b = line.get("anchor_start_beat"), line.get("anchor_end_beat")
        max_beats = min(12, max(3, quota + 2))
        climax = main_ctx.get("climax_beat")
        highlight = (a, b) if a is not None and b is not None else None
        prompt = f"""为支线《{line.get('title', '未命名')}》设计节点（beats）。支线节点 = 这条支线在某个主线节点期间发生的一件完整的事，会整体落进那个主线节点的某一个桥段（4 章）里写完。

【项目】{project_data.get('title', '未命名')}（{genre}）
【支线】{line.get('title', '未命名')}（{line.get('mode', '')} 型，{line.get('line_type', 'sub')}）
【描述】{line.get('description', '')}
【活跃区间】主线节点 {a}-{b}（区间外不出场）
【篇幅预算】{line.get('estimated_chapters')} 章 ≈ {quota} 个桥段 → 请设计 {quota} 个左右的节点（最少 3，最多 {max_beats}）

【主线时间轴】（★ = 本支线活跃区间）
{cls._main_timeline_table(main_ctx, highlight=highlight)}

【节点设计纪律】
1. 每个节点标 anchor_beat：它发生在哪个主线节点期间，必须在 {a}-{b} 内；节点按 anchor_beat 非降序排列
2. 同一主线节点最多挂 2 个支线节点；companion 型至少覆盖 3 个不同主线节点
3. 支线高潮节点权重最高，但不要与主线最大高潮 [节点 {climax}] 同节点（converge 型除外）
4. relation：offset = 与主线错峰推进（默认）；merge = 汇入主线该节点的兑现，只有 converge 型的最后一个节点填 merge
5. 每个节点结尾留钩子；description 150-250 字写清：核心事件、涉及角色、与主线当时局面的关系、产出/变化
6. key 取节点类型之一：{beat_types_hint}

【输出格式】仅输出 JSON 数组，权重之和 = 1.0：
```json
[
  {{"index": 1, "key": "opening", "title": "初遇", "description": "...", "weight": 0.2, "anchor_beat": {a}, "relation": "offset"}},
  {{"index": 2, "key": "twist", "title": "并肩杀敌", "description": "...", "weight": 0.3, "anchor_beat": {b}, "relation": "offset"}}
]
```"""
        return prompt



class PlotPromptService:
    """剧情 Prompt 服务类"""
    
    def __init__(self):
        self.templates = PlotPromptTemplates()

    def generate_plot_card_prompt(
        self,
        project_data: Dict[str, Any],
        outline_content: Optional[str] = None,
        card_type: str = "plot",
        extend_from: Optional[str] = None,
        custom_prompt: Optional[str] = None
    ) -> str:
        """生成剧情卡片 Prompt"""
        return self.templates.get_plot_card_prompt(
            project_data, outline_content, card_type, extend_from, custom_prompt
        )
    
    def generate_plot_line_prompt(
        self,
        project_data: Dict[str, Any],
        outline_content: Optional[str] = None,
        plot_cards: Optional[List[Dict]] = None,
        line_type: str = "main",
        custom_prompt: Optional[str] = None,
        count: int = 3,
        historical_context: Optional[str] = None,
        previous_line_summary: Optional[Dict[str, Any]] = None,
        sequence_index: Optional[int] = None
    ) -> str:
        """生成剧情线 Prompt"""
        return self.templates.get_plot_line_prompt(
            project_data, outline_content, plot_cards, line_type, custom_prompt, count,
            historical_context, previous_line_summary, sequence_index
        )

    def generate_single_line_beats_prompt(
        self,
        project_data: Dict[str, Any],
        line: Dict[str, Any]
    ) -> str:
        """生成单条剧情线节点规划 Prompt（精简版）"""
        return self.templates.get_single_line_beats_prompt(project_data, line)

    def generate_sub_line_prompt(
        self,
        project_data: Dict[str, Any],
        outline_content: Optional[str],
        main_ctx: Dict[str, Any],
        existing_subs: List[Dict[str, Any]],
        line_type: str,
        custom_prompt: Optional[str],
        sequence_index: int,
        total: int,
        budget_cap: Optional[int],
    ) -> str:
        """生成支线结构 Prompt（锚定主线时间轴）"""
        return self.templates.get_sub_line_prompt(
            project_data, outline_content, main_ctx, existing_subs, line_type, custom_prompt,
            sequence_index, total, budget_cap,
        )

    def generate_sub_line_beats_prompt(
        self,
        project_data: Dict[str, Any],
        line: Dict[str, Any],
        main_ctx: Dict[str, Any],
        quota: int,
    ) -> str:
        """生成支线节点规划 Prompt（带 anchor_beat / relation）"""
        return self.templates.get_sub_line_beats_prompt(project_data, line, main_ctx, quota)
