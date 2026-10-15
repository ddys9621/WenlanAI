"""剧情卡片的 Prompt 模板（剧情线 / 节点已取消，规划链见 volume_planning）"""
from typing import Dict, Any, Optional


class PlotPromptTemplates:
    """剧情 Prompt 模板管理器"""

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
