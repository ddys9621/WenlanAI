"""章节重新生成相关的Schema定义"""
from pydantic import BaseModel, Field
from typing import Optional, List


class PreserveElementsConfig(BaseModel):
    """保留元素配置"""
    preserve_structure: bool = Field(False, description="是否保留整体结构")
    preserve_dialogues: List[str] = Field(default_factory=list, description="需要保留的对话片段关键词")
    preserve_plot_points: List[str] = Field(default_factory=list, description="需要保留的情节点关键词")
    preserve_character_traits: bool = Field(True, description="保持角色性格一致")


class DeaiFindingIn(BaseModel):
    """重生成 deai 模式带入的一条诊断信号（chapter_deai_reviews.result.findings 里勾选的条目）。

    start/end 是诊断时核实到的原文偏移；正文没改过时直接可用，改过则后端按 evidence 重新定位。
    """
    feature: str = Field(..., description="判据特征名")
    evidence: str = Field("", description="原文引证")
    fix: str = Field("", description="怎么改")
    layer: str = Field("", description="架构 / 篇章 / 措辞")
    severity: str = Field("medium", description="high / medium / low")
    start: Optional[int] = Field(None, description="引证在原文中的起始偏移")
    end: Optional[int] = Field(None, description="引证在原文中的结束偏移")


class ChapterRegenerateRequest(BaseModel):
    """章节重新生成请求"""
    
    # 修改来源
    modification_source: str = Field("custom", description="修改来源: custom/analysis_suggestions/mixed")
    
    # 基于分析建议
    selected_suggestion_indices: Optional[List[int]] = Field(None, description="选中的建议索引列表")
    
    # 自定义修改指令
    custom_instructions: Optional[str] = Field(None, description="用户自定义的修改要求")
    
    # 保留配置
    preserve_elements: Optional[PreserveElementsConfig] = Field(None, description="保留元素配置")

    # 去 AI 味最小改动模式（sepia refactor）：模型只输出 find/replace 补丁清单，后端在原文上机械套用
    # （deai_patch.apply_edits），没被命中的字一个不变；协议见 prompts/deai/refactor.md
    deai_mode: bool = Field(False, description="去 AI 味最小改动模式：补丁式改稿而非整章重写")
    deai_findings: List[DeaiFindingIn] = Field(default_factory=list, description="勾选带入的诊断信号（结构化）")
    deai_protect_dialogue: bool = Field(True, description="对话引语不动，除非某条带入的诊断信号正指向它")
    
    # 生成参数
    style_id: Optional[int] = Field(None, description="写作风格ID")
    target_word_count: int = Field(3000, description="目标字数", ge=500, le=10000)
    focus_areas: List[str] = Field(default_factory=list, description="重点优化方向")

    # R8 拆书参考包显式参数（任一为空则走 injector 默认）
    pack_ids: Optional[List[str]] = Field(None, description="显式选中的拆书参考包 ID 列表")
    dimensions: Optional[List[str]] = Field(None, description="显式选中的参考维度")
    strength: Optional[str] = Field(None, description="参考强度：light/medium/deep")

    # 版本管理
    save_as_version: bool = Field(True, description="是否保存为新版本")
    version_note: Optional[str] = Field(None, description="版本说明", max_length=500)
    auto_apply: bool = Field(False, description="是否自动应用（替换当前内容）")


class ApplyRegenerationRequest(BaseModel):
    """应用重新生成版本请求"""
    source: str = Field(
        "regenerated",
        description="应用来源: regenerated(把该版本新稿写入正文)/original(回滚到该版本改稿前的原稿)",
    )
