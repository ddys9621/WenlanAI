"""章节重新生成服务：普通模式按反馈整章重写（流式）；去 AI 味模式走补丁式最小改动（见 _regenerate_deai_patch）。"""
from typing import Dict, Any, AsyncGenerator, Optional
from app.services.ai_service import AIService
from app.services.deai_anchor import locate, normalize_for_match, quote_spans
from app.services.deai_metrics import compute_metrics, metrics_delta
from app.services.deai_patch import apply_edits, parse_edits
from app.services.deai_rules import build_refactor_protocol
from app.services.prompt_service import prompt_service
from app.models.chapter import Chapter
from app.models.memory import PlotAnalysis
from app.schemas.regeneration import ChapterRegenerateRequest
from app.logger import get_logger
import difflib

logger = get_logger(__name__)


class ChapterRegenerator:
    """章节重新生成服务"""
    
    def __init__(self, ai_service: AIService):
        self.ai_service = ai_service
        logger.info("✅ ChapterRegenerator初始化成功")
    
    async def regenerate_with_feedback(
        self,
        chapter: Chapter,
        analysis: Optional[PlotAnalysis],
        regenerate_request: ChapterRegenerateRequest,
        project_context: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        根据反馈重新生成章节（流式）
        
        Args:
            chapter: 原始章节对象
            analysis: 分析结果（可选）
            regenerate_request: 重新生成请求参数
            project_context: 项目上下文（项目信息、角色、大纲等）
        
        Yields:
            包含类型和数据的字典: {'type': 'progress'/'chunk', 'data': ...}
        """
        if getattr(regenerate_request, "deai_mode", False):
            async for event in self._regenerate_deai_patch(chapter, regenerate_request):
                yield event
            return

        try:
            logger.info(f"🔄 开始重新生成章节: 第{chapter.chapter_number}章")
            
            # 1. 构建修改指令
            yield {'type': 'progress', 'progress': 5, 'message': '正在构建修改指令...'}
            modification_instructions = self._build_modification_instructions(
                analysis=analysis,
                regenerate_request=regenerate_request
            )
            
            logger.info(f"📝 修改指令构建完成，长度: {len(modification_instructions)}字符")
            
            # 2. 构建完整提示词
            yield {'type': 'progress', 'progress': 10, 'message': '正在构建生成提示词...'}
            full_prompt = self._build_regeneration_prompt(
                chapter=chapter,
                modification_instructions=modification_instructions,
                project_context=project_context,
                regenerate_request=regenerate_request
            )
            
            logger.info(f"🎯 提示词构建完成，开始AI生成")
            yield {'type': 'progress', 'progress': 15, 'message': '开始AI生成内容...'}
            
            # 3. 流式生成新内容，同时跟踪进度
            target_word_count = regenerate_request.target_word_count
            accumulated_length = 0
            
            try:
                async for chunk in self.ai_service.generate_text_stream(
                    prompt=full_prompt,
                    temperature=0.7
                ):
                    # 发送内容块
                    yield {'type': 'chunk', 'content': chunk}
                    
                    # 更新累积字数并计算进度（15%-95%）
                    accumulated_length += len(chunk)
                    # 进度从15%开始，到95%结束，为后处理预留5%
                    generation_progress = min(15 + (accumulated_length / target_word_count) * 80, 95)
                    yield {'type': 'progress', 'progress': int(generation_progress), 'word_count': accumulated_length}
                
                logger.info(f"✅ 章节重新生成完成，共生成 {accumulated_length} 字")
                yield {'type': 'progress', 'progress': 100, 'message': '生成完成'}
                
            except Exception as ai_error:
                logger.error(f"❌ AI生成流异常: {str(ai_error)}", exc_info=True)
                # 发送结构化错误信息
                yield {
                    'type': 'error', 
                    'error': f"AI生成服务异常: {str(ai_error)}", 
                    'code': 502,
                    'message': '生成过程中遇到AI服务问题，请稍后重试'
                }
                return
            
        except Exception as e:
            logger.error(f"❌ 重新生成失败: {str(e)}", exc_info=True)
            raise

    # ------------------------------------------------------------------ 去 AI 味：补丁式最小改动

    @staticmethod
    def _deai_finding_lines(regenerate_request: ChapterRegenerateRequest) -> list[str]:
        return [
            f"【去AI味·{f.layer or '措辞'}】{f.feature}：{f.fix or '按判据修正'}（原文：“{f.evidence}”）"
            for f in getattr(regenerate_request, "deai_findings", None) or []
        ]

    def build_deai_patch_prompt(self, chapter: Chapter, regenerate_request: ChapterRegenerateRequest) -> str:
        """去 AI 味补丁提示词：协议 + 修改指令 + 原文 + JSON 补丁格式。

        故意不带项目背景 / 角色 / 大纲 / 前文——那些是重写时的材料，对最小改动只是噪音，还会把模型往"重写"上推。
        """
        finding_lines = self._deai_finding_lines(regenerate_request)
        custom = (regenerate_request.custom_instructions or "").strip()
        directives = "\n".join(finding_lines) or "（本次未带入具体诊断条目：按协议自行列出缺陷清单——架构 → 篇章 → 措辞——再逐项最小修改）"
        if custom:
            directives += f"\n\n作者补充要求：\n{custom}"
        return f"""你是一位研究 AI 生成文本特征的资深小说编辑，现在对下面这一章做「去 AI 味」最小改动改稿。
你不输出全文，只输出一份补丁清单：每条给出原文里要改的片段（find）和改后的文字（replace）。
程序会在原文上机械套用——没被 find 覆盖的字一个都不会变，所以你不需要、也不应该重抄任何没问题的句子。

【改稿协议】
{build_refactor_protocol(getattr(self.ai_service, "default_model", None))}

【修改指令】
{directives}

【原文】《{chapter.title}》（第 {chapter.chapter_number} 章，{chapter.word_count or len(chapter.content or '')} 字）
{chapter.content}

【输出】只输出一个 JSON 对象，不要 Markdown 代码块、不要解释：
{{"edits": [{{"find": "从原文逐字复制的片段（含标点），8–80 字，必须在全文中唯一——不够唯一就往前后多带几个字", "replace": "改后的文字；整句删除就给空字符串", "why": "对应哪条修改指令 / 判据，一句话"}}]}}
规则：
- find 必须与原文逐字相同，否则这条会被丢弃；同一处只给一条，两条的 find 不要重叠；
- 对话引号里的话不要动，除非修改指令明确指向它；
- 替换为主、删除次之、增加最少；所有 replace 的总字数不要超过对应 find 的总字数；
- 没有缺陷的句子不要出现在 find 里；通读中发现的同类问题可以一并修，但 why 里要写出对应的判据。"""

    def _allowed_quote_spans(self, content: str, regenerate_request: ChapterRegenerateRequest) -> list[tuple[int, int]]:
        """带入的诊断信号正指向的引语区间——只有这些对话允许改。deai_protect_dialogue=False 时全部放开。"""
        quotes = quote_spans(content)
        if not getattr(regenerate_request, "deai_protect_dialogue", True):
            return quotes
        targets: list[tuple[int, int]] = []
        for f in getattr(regenerate_request, "deai_findings", None) or []:
            span = None
            if f.start is not None and f.end is not None and f.evidence:
                # 诊断时的偏移只有在那儿仍是这句引证时才可信（正文改过就会错位），否则按 evidence 重新定位
                at_offset = normalize_for_match(content[f.start:f.end])[0]
                wanted = normalize_for_match(f.evidence)[0]
                if wanted and (wanted in at_offset or at_offset in wanted):
                    span = (f.start, f.end)
            if span is None and f.evidence:
                anchor = locate(content, f.evidence)
                span = (anchor[0], anchor[1]) if anchor else None
            if span:
                targets.append(span)
        return [q for q in quotes if any(q[0] < t_end and q[1] > t_start for t_start, t_end in targets)]

    async def _regenerate_deai_patch(
        self, chapter: Chapter, regenerate_request: ChapterRegenerateRequest,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """去 AI 味模式：模型出补丁 → 机械套用 → 一次性发出整篇新稿 + 套用统计 + 前后指标对比。"""
        content = chapter.content or ""
        logger.info(f"🧽 去 AI 味补丁改稿: 第{chapter.chapter_number}章，带入 {len(regenerate_request.deai_findings or [])} 条诊断")
        yield {'type': 'progress', 'progress': 10, 'message': '正在构建补丁提示词...'}
        prompt = self.build_deai_patch_prompt(chapter, regenerate_request)
        yield {'type': 'progress', 'progress': 15, 'message': '模型正在生成补丁清单...'}
        try:
            # 低温：最小改动模式要的是克制，0.7 会鼓励它顺手重写没问题的句子
            response = await self.ai_service.generate_text_stream_collect(
                prompt=prompt, temperature=0.3, context="deai-refactor",
            )
        except Exception as ai_error:
            logger.error(f"❌ 去 AI 味补丁生成异常: {ai_error}", exc_info=True)
            yield {'type': 'error', 'error': f"AI生成服务异常: {ai_error}", 'code': 502, 'message': '生成过程中遇到AI服务问题，请稍后重试'}
            return
        raw = response.get("content", "") if isinstance(response, dict) else str(response or "")
        edits = parse_edits(raw)
        if not edits:
            yield {'type': 'error', 'error': '模型没有返回可解析的补丁清单（不是合法 JSON 或 edits 为空）', 'code': 502, 'message': '去 AI 味改稿失败'}
            return

        yield {'type': 'progress', 'progress': 85, 'message': f'套用 {len(edits)} 条补丁...'}
        result = apply_edits(content, edits, allowed_quote_spans=self._allowed_quote_spans(content, regenerate_request))
        if not result.applied:
            reasons = "；".join(f"「{s['find'][:20]}」{s['reason']}" for s in result.skipped[:5])
            yield {
                'type': 'error', 'code': 422, 'message': '去 AI 味改稿失败',
                'error': f"模型给出 {len(edits)} 条补丁，0 条能在原文中定位套用：{reasons}",
            }
            return

        before, after = compute_metrics(content)["metrics"], compute_metrics(result.content)["metrics"]
        yield {'type': 'chunk', 'content': result.content}
        yield {
            'type': 'deai_patch',
            'edits_proposed': len(edits),
            'applied': result.applied,
            'skipped': result.skipped,
            'chars_before': result.chars_before,
            'chars_after': result.chars_after,
            'metrics_before': before,
            'metrics_after': after,
            'metrics_delta': metrics_delta(before, after),
        }
        logger.info(f"✅ 去 AI 味补丁套用完成：{len(result.applied)} 条套用 / {len(result.skipped)} 条跳过")
        yield {'type': 'progress', 'progress': 100, 'message': f'改稿完成：套用 {len(result.applied)} 处，跳过 {len(result.skipped)} 处'}

    def _build_modification_instructions(
        self,
        analysis: Optional[PlotAnalysis],
        regenerate_request: ChapterRegenerateRequest
    ) -> str:
        """构建修改指令"""
        
        instructions = []
        
        # 标题
        instructions.append("# 章节修改指令\n")
        
        # 1. 来自分析的建议
        if (analysis and 
            regenerate_request.selected_suggestion_indices and 
            analysis.suggestions):
            
            instructions.append("## 📋 需要改进的问题（来自AI分析）：\n")
            for idx in regenerate_request.selected_suggestion_indices:
                if 0 <= idx < len(analysis.suggestions):
                    suggestion = analysis.suggestions[idx]
                    instructions.append(f"{idx + 1}. {suggestion}")
            instructions.append("")
        
        # 2. 用户自定义指令
        if regenerate_request.custom_instructions:
            instructions.append("## ✍️ 用户自定义修改要求：\n")
            instructions.append(regenerate_request.custom_instructions)
            instructions.append("")

        # 2b. 去 AI 味模式：列出带入的诊断信号；没勾 findings 也要有指令（模型按协议自行找同类问题），保证指令非空
        if getattr(regenerate_request, "deai_mode", False):
            instructions.append("## 🧽 去 AI 味改稿：\n")
            finding_lines = self._deai_finding_lines(regenerate_request)
            if finding_lines:
                instructions.extend(finding_lines)
                instructions.append("")
                instructions.append(
                    "以上带「去AI味」标记的条目是诊断报告里勾选的问题（含原文引证），逐条最小修改；"
                    "通读时发现的同类问题一并修。没有列出问题的句子原样保留。"
                )
            else:
                instructions.append(
                    "本次未带入具体诊断条目：按下方改稿协议先在心里列出缺陷清单（架构 → 篇章 → 措辞），"
                    "再逐项最小修改；没有缺陷的句子原样保留。"
                )
            instructions.append("")
        
        # 3. 重点优化方向
        if regenerate_request.focus_areas:
            instructions.append("## 🎯 重点优化方向：\n")
            focus_map = {
                "pacing": "节奏 - 调整叙事速度，拖的地方砍、赶的地方写足",
                "emotion": "情感 - 情绪写进动作和对话里，该点名就点名（\"他慌了\"），不堆身体渲染和抒情",
                "description": "场景 - 补具体的东西和动作（谁拿着什么、站在哪儿），环境一处两句，不铺陈",
                "dialogue": "对话 - 说人话、有信息量，靠对话把剧情往前推",
                "conflict": "冲突 - 把矛盾顶到明面上，让人当场说出来、做出来"
            }
            
            for area in regenerate_request.focus_areas:
                if area in focus_map:
                    instructions.append(f"- {focus_map[area]}")
            instructions.append("")
        
        # 4. 保留要求
        if regenerate_request.preserve_elements:
            preserve = regenerate_request.preserve_elements
            instructions.append("## 🔒 必须保留的元素：\n")
            
            if preserve.preserve_structure:
                instructions.append("- 保持原章节的整体结构和情节框架")
            
            if preserve.preserve_dialogues:
                instructions.append("- 必须保留以下关键对话：")
                for dialogue in preserve.preserve_dialogues:
                    instructions.append(f"  * {dialogue}")
            
            if preserve.preserve_plot_points:
                instructions.append("- 必须保留以下关键情节点：")
                for plot in preserve.preserve_plot_points:
                    instructions.append(f"  * {plot}")
            
            if preserve.preserve_character_traits:
                instructions.append("- 保持所有角色的性格特征和行为模式一致")
            
            instructions.append("")
        
        return "\n".join(instructions)
    
    def _build_regeneration_prompt(
        self,
        chapter: Chapter,
        modification_instructions: str,
        project_context: Dict[str, Any],
        regenerate_request: ChapterRegenerateRequest
    ) -> str:
        """构建完整的重新生成提示词（普通整章重写；去 AI 味模式走 build_deai_patch_prompt，不经这里）"""
        
        prompt_parts = []
        
        prompt_parts.append("""你是一个在起点、番茄写了几百万字的网文老作者，现在要根据反馈把自己的一章重写一遍。

你的任务是：
1. 弄清原章节讲了什么、想干什么
2. 把所有修改要求看明白
3. 在保持故事连贯的前提下，创作一个改进后的新版本
4. 新版本要更好读、更抓人，读起来还是手机上的连载网文，不是文学作品

---
""")
        
        # 原始章节信息
        prompt_parts.append(f"""## 📖 原始章节信息

**章节**：第{chapter.chapter_number}章
**标题**：{chapter.title}
**字数**：{chapter.word_count}字

**原始内容**：
{chapter.content}

---
""")
        
        # 修改指令
        prompt_parts.append(modification_instructions)
        prompt_parts.append("\n---\n")

        # 拆书参考注入（R5-S5）：通过 project_context 由 API 层提前组装好的拆书参考段
        # 设计文档：@/agent-docs/features/dissect_to_creation_pipeline.md §A.2
        dissect_user = project_context.get('dissect_reference_user') if isinstance(project_context, dict) else None
        if dissect_user:
            prompt_parts.append(f"## 📚 拆书参考（仅作写作手法参考，不要复刻原书具体内容）\n\n{dissect_user}")
            prompt_parts.append("\n---\n")
        dissect_system = project_context.get('dissect_reference_system') if isinstance(project_context, dict) else None
        if dissect_system:
            prompt_parts.append(f"## 🎨 文风参考（来自拆书）\n\n{dissect_system}")
            prompt_parts.append("\n---\n")

        # 项目背景信息
        prompt_parts.append(f"""## 🌍 项目背景信息

**小说标题**：{project_context.get('project_title', '未知')}
**题材**：{project_context.get('genre', '未设定')}
**主题**：{project_context.get('theme', '未设定')}
**叙事视角**：{project_context.get('narrative_perspective', '第三人称')}
**世界观设定**：
- 时代背景：{project_context.get('time_period', '未设定')}
- 地理位置：{project_context.get('location', '未设定')}
- 氛围基调：{project_context.get('atmosphere', '未设定')}

---
""")
        
        # 角色信息
        if project_context.get('characters_info'):
            prompt_parts.append(f"""## 👥 角色信息

{project_context['characters_info']}

---
""")
        
        # 章节大纲
        if project_context.get('chapter_outline'):
            prompt_parts.append(f"""## 📝 本章大纲

{project_context['chapter_outline']}

---
""")
        
        # 前置章节上下文
        if project_context.get('previous_context'):
            prompt_parts.append(f"""## 📚 前置章节上下文

{project_context['previous_context']}

---
""")
        
        # 文风要求：与正文生成同一套网文大白话规则（含视角边界），重写不能把文风拉回文学腔
        prompt_parts.append(
            "## 🎨 文风要求\n\n"
            + prompt_service.render_chapter_style_rules(project_context.get('narrative_perspective', '第三人称'))
            + "\n\n---\n"
        )

        # 创作要求
        prompt_parts.append(f"""## ✨ 创作要求

1. **解决问题**：针对上述修改指令中提到的所有问题进行改进
2. **保持连贯**：确保与前后章节的情节、人物、风格保持一致
3. **更好读**：节奏、对话、情绪都比原版顺，文风按上面「文风要求」来
4. **保留精华**：保持原章节中优秀的部分和关键情节
5. **字数控制**：目标字数约{regenerate_request.target_word_count}字（可适当浮动±20%）

---

## 🎬 开始创作

请现在开始创作改进后的新版本章节内容。

**重要提示**：
- 直接输出章节正文内容，从故事内容开始写
- **不要**输出章节标题（如"第X章"、"第X章：XXX"等）
- **不要**输出任何额外的说明、注释或元数据
- 只需要纯粹的故事正文内容
- 落笔前再看一眼：段落短、对话多、叙述用主角的口气、环境两句带过、书面词换成嘴上的词、结尾停在钩子上

现在开始：
""")
        
        full_prompt = "\n".join(prompt_parts)
        return prompt_service.apply_project_generation_prompt(
            full_prompt,
            project_context.get('generation_prompt', '') if isinstance(project_context, dict) else ''
        )
    
    def calculate_content_diff(
        self,
        original_content: str,
        new_content: str
    ) -> Dict[str, Any]:
        """
        计算两个版本的差异
        
        Returns:
            差异统计信息
        """
        # 基本统计
        diff_stats = {
            'original_length': len(original_content),
            'new_length': len(new_content),
            'length_change': len(new_content) - len(original_content),
            'length_change_percent': round((len(new_content) - len(original_content)) / len(original_content) * 100, 2) if len(original_content) > 0 else 0
        }
        
        # 计算相似度
        similarity = difflib.SequenceMatcher(None, original_content, new_content).ratio()
        diff_stats['similarity'] = round(similarity * 100, 2)
        diff_stats['difference'] = round((1 - similarity) * 100, 2)
        
        # 段落统计
        original_paragraphs = [p for p in original_content.split('\n\n') if p.strip()]
        new_paragraphs = [p for p in new_content.split('\n\n') if p.strip()]
        diff_stats['original_paragraph_count'] = len(original_paragraphs)
        diff_stats['new_paragraph_count'] = len(new_paragraphs)
        
        return diff_stats


# 全局实例
_regenerator_instance = None
