"""拆书 LLM Prompt 模板（V5 只保留章节切分兜底）。

V2-V4 的字典分类 / 章节事实 / 方法论 / 结构 / 原型 / 世界观 / 骨架 / 校验 / 长上下文 / 桥段识别
等 prompt 随实体图谱抽取核心一并删除；V5 流水线的 prompt 见 prompts_v5.py。

保留：
- SYSTEM_PROMPT_V31_BOUNDARY / LLM_BOUNDARY_PROMPT：正则切章失败时，采样头 / 中 / 尾让 LLM 推断章节边界
  （llm_chapter_splitter 使用）。
"""
from __future__ import annotations


# ============================================================
# LLM 章节切分 fallback
#
# 当正则切分返回"单章 + 字数过大"或"巨型章节混杂"时，采样头/中/尾
# 给 LLM 推断边界模式。
# 设计文档：agent-docs/features/book_dissect_v31_quality_optimization.md §6
# ============================================================

SYSTEM_PROMPT_V31_BOUNDARY = """你是一位熟悉中文小说 / 散文 / 网文格式的结构分析师。

任务规则：
1. 严格按用户给定 JSON 模板输出，字段名一字不差
2. 不输出任何解释、不要 Markdown 代码块、不要前后空白
3. 分析文本 head / mid / tail 三段采样，推断章节边界规律
4. 若无明显边界，选择 fallback_action=fixed_size 或 single_chapter
5. regex 必须是合法 Python 正则（在 re.MULTILINE 模式下使用）
6. ⚠️ JSON 字段值内严禁出现裸的英文双引号 " ——它会破坏 JSON 结构
7. ⚠️ boundary_pattern 字段特殊处理（regex 字符串）：
   - regex 中的反斜杠在 JSON 字符串里**必须双重转义**：
     - 想表达 regex `\\d+` → JSON 写成 `"boundary_pattern":"\\\\d+"`
     - 想表达 regex `第\\d+章` → JSON 写成 `"boundary_pattern":"第\\\\d+章"`
   - regex 内不要包含英文双引号 "
8. text_type 等枚举字段直接用模板给的英文小写词，无需任何引号包裹"""


LLM_BOUNDARY_PROMPT = """分析下方文本的三段采样（开头 / 中段 / 结尾各约 3000 字），推断章节边界规律。

【你要判断的问题】
1. 文本类型是什么？（novel 小说 / essay 散文集 / dialogue 对话集 / notes 笔记 / other 其他）
2. 章节边界有什么可识别的模式？例如：
   - 数字编号（第X章 / Chapter N / 壹贰叁 / 一二三）
   - 分隔线（※※※ / --- / ***）
   - 空行 + 标题行（如散文篇名独占一行）
   - 或根本没有（连续散文）
3. 如何切分？
   - regex_split：能写出一个正则匹配所有边界
   - fixed_size：没有明显边界，建议按固定字数切
   - single_chapter：这就是一个整体，不应切分

【输出 JSON 模板】
{{
  "text_type": "novel | essay | dialogue | notes | other",
  "boundary_pattern": "Python regex（若 fallback_action=regex_split；否则填 null）",
  "estimated_chapter_count": 整数（估计总章数；单章或未知填 null）,
  "estimated_chapter_chars": 整数（估计单章字符数；未知填 null）,
  "fallback_action": "regex_split | fixed_size | single_chapter"
}}

【约束】
- regex 必须能在 re.MULTILINE 模式下匹配"独占一行的标题"，不能匹配正文内偶然出现的文字
- 不确定时优先选 fixed_size（更安全，总能切出多段）
- 若总字数 < 10000 且无清晰边界，选 single_chapter

【文本采样】
[HEAD]
{head_text}

[MID]
{mid_text}

[TAIL]
{tail_text}

请直接输出 JSON。"""
