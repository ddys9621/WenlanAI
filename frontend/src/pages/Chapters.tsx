import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Plus, Pencil, Trash2, Zap, X, Loader2, RefreshCw, Layers, Search, Film, Eye, ChevronUp, Download, LayoutGrid, Sparkles, BookOpen } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { useStore } from '@/store';
import { useChapterSync } from '@/store/hooks';
import { AIJobError, runAIJob, useAIJob, useAIJobsStore, useRunningAIJobs, waitForAIJob } from '@/store/aiJobsStore';
import { chapterApi, writingStyleApi, chapterOutlineLinkApi, type ChapterWriteResult, type ChapterRegenerateResult } from '@/services/api';
import type { SSEClientOptions } from '@/utils/sseClient';
import { normalizeAnalysisData, type NormalizedAnalysisData } from '@/utils/chapterAnalysis';
import type { Chapter, ChapterCanGenerateResponse, ChapterGenerateRequest, PlotCardWithLinks, WritingStyle } from '@/types';
import { AIJobBanner } from '@/components/ai-job/AIJobBanner';
import { AIJobProcess } from '@/components/ai-job/AIJobProcess';
import { SceneGenerator } from '@/components/SceneGenerator';
import { MCPSelector } from '@/components/MCPSelector';
import {
  ReferencePackSelector,
  DEFAULT_SELECTOR_VALUE,
  type ReferencePackSelectorValue,
} from '@/components/ReferencePackSelector';
import { ImitationDialog } from '@/components/ImitationDialog';

const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  draft: { label: '草稿', cls: 'bg-gray-100 text-gray-500' },
  writing: { label: '生成中', cls: 'bg-blue-50 text-blue-600' },
  completed: { label: '已完成', cls: 'bg-emerald-50 text-emerald-600' },
};

interface FormData {
  title: string;
  chapter_number: number;
  content: string;
}

interface StreamState {
  chapterId: string;
  chapterTitle: string;
  progress: number;
  message: string;
  content: string;
  mode: 'single' | 'batch';
}

interface BatchStatusState {
  status: 'running' | 'completed' | 'cancelled' | 'error';
  total: number;
  completed: number;
  progress: number;
  currentChapterId: string | null;
  currentChapterNumber: number | null;
  currentChapterTitle: string | null;
  message: string;
  skippedCount: number;
  errorMessage?: string;
}

/** 页面自带面板承担正文任务；横幅只兜底其它任务，面板隐藏（后台运行）时才把正文任务也放进横幅 */
const WRITE_JOB_KINDS = ['chapter_generate', 'chapter_regenerate'];
const OTHER_JOB_KINDS = ['chapter_analyze', 'scene_generate', 'chapter_imitate'];

const abortError = () => new DOMException('Request aborted', 'AbortError');

interface RegenVersionItem {
  task_id: string;
  status: string;
  version_number: number | null;
  version_note: string | null;
  original_word_count: number | null;
  regenerated_word_count: number | null;
  created_at: string | null;
  completed_at: string | null;
}

export default function Chapters() {
  const { currentProject, chapters } = useStore();
  const { refreshChapters, createChapter, updateChapter, deleteChapter } = useChapterSync();

  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormData>({ title: '', chapter_number: 1, content: '' });
  const [submitting, setSubmitting] = useState(false);
  const [loadingContent, setLoadingContent] = useState(false);

  // 流式生成状态：任务由全局 store 持有（关面板 / 切页 / 刷新都不中断），页面面板只是它的一个视图
  const [streamState, setStreamState] = useState<StreamState | null>(null);
  const [streamJobId, setStreamJobId] = useState<string | null>(null);
  const streamJob = useAIJob(streamJobId);
  const [panelHidden, setPanelHidden] = useState(false);
  const [showProcess, setShowProcess] = useState(true);
  const cancelJob = useAIJobsStore((s) => s.cancel);
  const attachJob = useAIJobsStore((s) => s.attach);
  const runningWriteJobs = useRunningAIJobs(currentProject?.id, WRITE_JOB_KINDS);
  const runningAnalyses = useRunningAIJobs(currentProject?.id, ['chapter_analyze']);
  const [streamDone, setStreamDone] = useState(false);
  const [relatedCards, setRelatedCards] = useState<PlotCardWithLinks[]>([]);
  const [loadingCards, setLoadingCards] = useState(false);
  const streamContentRef = useRef<HTMLTextAreaElement>(null);

  // 批量生成
  const [showBatchModal, setShowBatchModal] = useState(false);
  const [batchFrom, setBatchFrom] = useState(1);
  const [batchTo, setBatchTo] = useState(1);
  const [batchStatus, setBatchStatus] = useState<BatchStatusState | null>(null);
  const batchCancelRef = useRef(false);

  // 分析中的章节
  const [analyzingIds, setAnalyzingIds] = useState<Set<string>>(new Set());

  // 场景生成
  const [sceneTarget, setSceneTarget] = useState<{ outlineId: string; title: string } | null>(null);

  // 一键仿写（V3 R5）
  const [showImitationDialog, setShowImitationDialog] = useState(false);

  // 从章纲同步
  const [syncing, setSyncing] = useState(false);

  const handleSyncFromOutlines = async () => {
    if (!currentProject) return;
    setSyncing(true);
    try {
      const res = await chapterApi.syncFromOutlines(currentProject.id);
      if (res.created > 0) {
        toast.success(res.message);
        await refreshChapters();
      } else if (res.total_outlines === 0) {
        toast.info('当前项目还没有章纲，请先在「故事大纲」→「章纲」中创建');
      } else {
        toast.info('所有章纲已有对应章节，无需同步');
      }
    } catch {
      toast.error('同步失败');
    } finally {
      setSyncing(false);
    }
  };

  // AI 生成配置弹窗
  const [showGenModal, setShowGenModal] = useState(false);
  const [genTarget, setGenTarget] = useState<{ chapter: Chapter; isRegenerate: boolean } | null>(null);
  const [genConfig, setGenConfig] = useState({
    style_id: undefined as number | undefined,
    target_word_count: 3000,
    enable_mcp: true,
    selected_plugins: [] as string[],
  });
  // R8：拆书参考包选择器状态（正文生成与重生成共用）
  const [genRefPack, setGenRefPack] = useState<ReferencePackSelectorValue>(DEFAULT_SELECTOR_VALUE);
  const [genCheck, setGenCheck] = useState<ChapterCanGenerateResponse | null>(null);

  // 修订闭环：重生成时可勾选分析建议 / 一致性问题，并配置保留元素与是否自动覆盖
  const [regenAnalysis, setRegenAnalysis] = useState<NormalizedAnalysisData | null>(null);
  const [regenAnalysisLoading, setRegenAnalysisLoading] = useState(false);
  const [selectedSuggestionIdx, setSelectedSuggestionIdx] = useState<Set<number>>(new Set());
  const [selectedIssueIdx, setSelectedIssueIdx] = useState<Set<number>>(new Set());
  const [customInstructions, setCustomInstructions] = useState('');
  const [preserveStructure, setPreserveStructure] = useState(false);
  const [preserveTraits, setPreserveTraits] = useState(true);
  const [autoApply, setAutoApply] = useState(true);
  // 版本历史（重新生成任务）
  const [versionTasks, setVersionTasks] = useState<RegenVersionItem[]>([]);
  const [versionLoading, setVersionLoading] = useState(false);
  const [applyingVersionKey, setApplyingVersionKey] = useState<string | null>(null);
  // 批量生成：遇严重一致性问题暂停
  const [batchPauseOnCritical, setBatchPauseOnCritical] = useState(true);
  const [styles, setStyles] = useState<WritingStyle[]>([]);
  const [stylesLoaded, setStylesLoaded] = useState(false);

  const loadStyles = useCallback(async () => {
    if (stylesLoaded || !currentProject?.id) return;
    try {
      const res = await writingStyleApi.getProjectStyles(currentProject.id);
      setStyles(res.styles || []);
      setStylesLoaded(true);
    } catch { /* ignore */ }
  }, [currentProject?.id, stylesLoaded]);

  const loadRelatedCardsForChapter = useCallback(async (chapter: Chapter) => {
    setRelatedCards([]);
    setLoadingCards(Boolean(chapter.chapter_outline_id));

    if (!chapter.chapter_outline_id) {
      setLoadingCards(false);
      return;
    }

    try {
      const cards = await chapterOutlineLinkApi.getPlotCards(chapter.chapter_outline_id);
      setRelatedCards(cards || []);
    } catch {
      setRelatedCards([]);
    } finally {
      setLoadingCards(false);
    }
  }, []);

  const closeGenerateModal = useCallback(() => {
    setShowGenModal(false);
    setGenTarget(null);
    setGenCheck(null);
    setRelatedCards([]);
    setLoadingCards(false);
  }, []);

  const buildChapterGenerateRequest = useCallback((): ChapterGenerateRequest => ({
    style_id: genConfig.style_id,
    target_word_count: genConfig.target_word_count,
    enable_mcp: genConfig.enable_mcp,
    selected_plugins: genConfig.enable_mcp && genConfig.selected_plugins.length > 0
      ? genConfig.selected_plugins
      : undefined,
    // R8：仅 enabled 时透传拆书参考包参数
    ...(genRefPack.enabled ? {
      pack_ids: genRefPack.packIds.length > 0 ? genRefPack.packIds : undefined,
      dimensions: genRefPack.dimensions.length > 0 ? genRefPack.dimensions : undefined,
      strength: genRefPack.strength,
    } : {}),
  }), [genConfig, genRefPack]);

  const openGenerateModal = useCallback(async (chapter: Chapter, isRegenerate: boolean) => {
    setGenCheck(null);
    setRelatedCards([]);
    setLoadingCards(Boolean(chapter.chapter_outline_id));

    try {
      const check = await chapterApi.checkCanGenerate(chapter.id);
      if (!check.can_generate) {
        toast.error(check.reason || '当前不满足生成条件');
        setLoadingCards(false);
        return;
      }

      setGenCheck(check);
      setGenTarget({ chapter, isRegenerate });
      setShowGenModal(true);
      loadStyles();

      // 修订闭环：重生成时加载分析建议 / 一致性问题 / 版本历史
      if (isRegenerate) {
        setRegenAnalysis(null);
        setSelectedSuggestionIdx(new Set());
        setSelectedIssueIdx(new Set());
        setCustomInstructions('');
        setPreserveStructure(false);
        setPreserveTraits(true);
        setAutoApply(true);
        setRegenAnalysisLoading(true);
        chapterApi.getAnalysis(chapter.id)
          .then(data => setRegenAnalysis(normalizeAnalysisData(data as unknown as Record<string, unknown>)))
          .catch(() => setRegenAnalysis(null))
          .finally(() => setRegenAnalysisLoading(false));
        setVersionLoading(true);
        chapterApi.getRegenerationTasks(chapter.id, 10)
          .then(res => setVersionTasks(res.tasks || []))
          .catch(() => setVersionTasks([]))
          .finally(() => setVersionLoading(false));
      }

      await loadRelatedCardsForChapter(chapter);
    } catch {
      setLoadingCards(false);
      toast.error('生成条件检查失败');
    }
  }, [loadRelatedCardsForChapter, loadStyles]);

  // 内容预览
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [previewContent, setPreviewContent] = useState<Record<string, string>>({});
  const [loadingPreview, setLoadingPreview] = useState<string | null>(null);

  const togglePreview = async (chapter: Chapter) => {
    if (batchStatus?.status === 'running' && batchStatus.currentChapterId !== chapter.id) {
      return;
    }
    if (expandedId === chapter.id) { setExpandedId(null); return; }
    setExpandedId(chapter.id);
    if (previewContent[chapter.id]) return;
    setLoadingPreview(chapter.id);
    try {
      const detail = await chapterApi.getChapter(chapter.id);
      setPreviewContent(prev => ({ ...prev, [chapter.id]: detail.content || '暂无内容' }));
    } catch { setPreviewContent(prev => ({ ...prev, [chapter.id]: '加载失败' })); }
    finally { setLoadingPreview(null); }
  };

  useEffect(() => {
    if (currentProject?.id) refreshChapters();
  }, [currentProject?.id, refreshChapters]);

  // 清理：只停掉前端的批量编排循环；正在跑的任务归 store，切页不中断
  useEffect(() => {
    return () => {
      batchCancelRef.current = true;
    };
  }, []);

  const sorted = [...chapters].sort((a, b) => a.chapter_number - b.chapter_number);

  const openAdd = useCallback(() => {
    setGenTarget(null);
    setGenCheck(null);
    setRelatedCards([]);
    setEditingId(null);
    setForm({ title: '', chapter_number: sorted.length > 0 ? sorted[sorted.length - 1].chapter_number + 1 : 1, content: '' });
    setShowModal(true);
  }, [sorted]);

  const openEdit = useCallback(async (c: Chapter) => {
    setGenTarget(null);
    setGenCheck(null);
    setRelatedCards([]);
    setEditingId(c.id);
    setForm({ title: c.title, chapter_number: c.chapter_number, content: '' });
    setShowModal(true);
    setLoadingContent(true);
    try {
      const detail = await chapterApi.getChapter(c.id);
      setForm(prev => ({ ...prev, content: detail.content || '' }));
    } catch {
      toast.error('加载章节内容失败');
    } finally {
      setLoadingContent(false);
    }
  }, []);

  const handleSubmit = async () => {
    if (!currentProject || !form.title.trim()) return;
    setSubmitting(true);
    try {
      if (editingId) {
        // content 传原值（含空串）：`|| undefined` 会让"清空正文"被后端忽略而无法保存
        await updateChapter(editingId, { title: form.title, content: form.content });
        toast.success('章节已更新');
      } else {
        await createChapter({
          project_id: currentProject.id,
          title: form.title,
          chapter_number: form.chapter_number,
          content: form.content || undefined,
        });
        toast.success('章节已创建');
      }
      setShowModal(false);
    } catch {
      toast.error(editingId ? '更新失败' : '创建失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string, title: string) => {
    if (!confirm(`确定删除章节「${title}」吗？`)) return;
    try {
      await deleteChapter(id);
      toast.success('章节已删除');
    } catch {
      toast.error('删除失败');
    }
  };

  // ========== 1. AI 生成前检查 + 2. 流式生成 ==========
  const handleGenerate = async (chapter: Chapter) => {
    await openGenerateModal(chapter, false);
  };

  // ========== 3. 重新生成（修订闭环：分析建议 + 一致性问题 + 保留元素 + 版本） ==========
  const handleRegenerate = async (chapter: Chapter) => {
    // 弹窗内可配置修改意见与是否覆盖正文，无需提前 confirm
    await openGenerateModal(chapter, true);
  };

  /** 组装重生成请求体：勾选的建议走 selected_suggestion_indices，勾选的一致性问题并入 custom_instructions */
  const buildRegenerateRequest = useCallback((): Record<string, unknown> => {
    const suggestions = regenAnalysis?.suggestions ?? [];
    const selectedIdx = Array.from(selectedSuggestionIdx)
      .filter(i => i >= 0 && i < suggestions.length)
      .sort((a, b) => a - b);

    const issues = regenAnalysis?.consistency_audit.issues ?? [];
    const issueLines = Array.from(selectedIssueIdx)
      .sort((a, b) => a - b)
      .map(i => {
        const it = issues[i];
        if (!it) return '';
        const sev = String(it.severity || '');
        const title = String(it.title || it.rule_code || '一致性问题');
        const details = String(it.details || '');
        return `【一致性修复·${sev}】${title}${details ? `：${details}` : ''}`;
      })
      .filter(Boolean);

    const mergedCustom = [customInstructions.trim(), ...issueLines].filter(Boolean).join('\n');
    const hasSuggestions = selectedIdx.length > 0;
    const hasCustom = mergedCustom.length > 0;
    const modificationSource = hasSuggestions && hasCustom
      ? 'mixed'
      : hasSuggestions
        ? 'analysis_suggestions'
        : 'custom';

    return {
      modification_source: modificationSource,
      selected_suggestion_indices: hasSuggestions ? selectedIdx : undefined,
      custom_instructions: hasCustom ? mergedCustom : undefined,
      preserve_elements: {
        preserve_structure: preserveStructure,
        preserve_dialogues: [],
        preserve_plot_points: [],
        preserve_character_traits: preserveTraits,
      },
      style_id: genConfig.style_id,
      target_word_count: genConfig.target_word_count,
      save_as_version: true,
      auto_apply: autoApply,
      // R8：重生成也支持拆书参考包（仅 enabled 时传）
      ...(genRefPack.enabled ? {
        pack_ids: genRefPack.packIds.length > 0 ? genRefPack.packIds : undefined,
        dimensions: genRefPack.dimensions.length > 0 ? genRefPack.dimensions : undefined,
        strength: genRefPack.strength,
      } : {}),
    };
  }, [regenAnalysis, selectedSuggestionIdx, selectedIssueIdx, customInstructions, preserveStructure, preserveTraits, autoApply, genConfig, genRefPack]);

  /** 应用/回滚某个历史版本到正文 */
  const handleApplyVersion = async (taskId: string, source: 'regenerated' | 'original') => {
    if (!genTarget) return;
    const chapter = genTarget.chapter;
    const label = source === 'regenerated' ? '该版本的新稿' : '该版本改稿前的原稿';
    if (!confirm(`确定把${label}写入「${chapter.title}」正文？当前正文将被覆盖（历史版本仍保留可再次切换）。`)) return;
    setApplyingVersionKey(`${taskId}:${source}`);
    try {
      const res = await chapterApi.applyRegenerationTask(chapter.id, taskId, source);
      toast.success(res.message || '已应用');
      setPreviewContent(prev => {
        const next = { ...prev };
        delete next[chapter.id];
        return next;
      });
      await refreshChapters();
    } catch {
      /* api 拦截器已 toast */
    } finally {
      setApplyingVersionKey(null);
    }
  };

  const confirmGenerate = async () => {
    if (!genTarget) return;
    const { chapter, isRegenerate } = genTarget;
    // 意图防护：重生成但未提供任何修改意见时，明确告知这是"无方向整章重写"
    if (
      isRegenerate &&
      selectedSuggestionIdx.size === 0 &&
      selectedIssueIdx.size === 0 &&
      !customInstructions.trim() &&
      !confirm('未勾选建议、未填写修改要求：AI 将只按章纲整体重写本章（不带针对性修订方向）。确定继续？')
    ) {
      return;
    }
    const requestBody = (isRegenerate
      ? buildRegenerateRequest()
      : buildChapterGenerateRequest()) as Record<string, unknown>;
    const keepAsDraftOnly = isRegenerate && !autoApply;
    setShowGenModal(false);
    setGenCheck(null);
    setStreamDone(false);
    try {
      await startStream({
        chapter,
        isRegenerate,
        requestBody,
        mode: 'single',
      });
      if (keepAsDraftOnly) {
        toast.info('新稿已保存为历史版本（未覆盖正文）。可在「重新生成」弹窗的历史版本中应用。');
      }
    } catch (error) {
      if ((error as DOMException)?.name === 'AbortError') {
        return;
      }
    }
  };

  /** 面板视图跟随任务状态：进度 / 文案 / 正文都来自 store（生成完成后正文转为可编辑的本地副本） */
  useEffect(() => {
    if (!streamJob || streamDone) return;
    setStreamState((prev) => {
      if (!prev || prev.chapterId !== (streamJob.meta.chapter_id ?? prev.chapterId)) return prev;
      const next = {
        ...prev,
        progress: streamJob.progress?.pct ?? prev.progress,
        message: streamJob.progress?.message || prev.message,
        content: streamJob.content,
      };
      if (next.content !== prev.content) {
        requestAnimationFrame(() => {
          if (streamContentRef.current) {
            streamContentRef.current.scrollTop = streamContentRef.current.scrollHeight;
          }
        });
      }
      return next;
    });
  }, [streamJob, streamDone]);

  /** 刷新 / 切页回来：接管仍在运行的正文任务（store 已从后端同步进来） */
  useEffect(() => {
    if (streamJobId || runningWriteJobs.length === 0) return;
    const job = runningWriteJobs[0];
    const chapterId = typeof job.meta.chapter_id === 'string' ? job.meta.chapter_id : null;
    if (!chapterId) return;
    setStreamJobId(job.id);
    setStreamDone(false);
    setPanelHidden(false);
    setExpandedId(chapterId);
    setStreamState({
      chapterId,
      chapterTitle: job.title,
      progress: job.progress?.pct ?? 0,
      message: job.progress?.message ?? '正在生成…',
      content: useAIJobsStore.getState().jobs[job.id]?.content ?? '',
      mode: 'single',
    });
    void waitForAIJob(job.id)
      .then(async (done) => {
        setPreviewContent((prev) => ({ ...prev, [chapterId]: done.content || prev[chapterId] || '' }));
        setStreamDone(true);
        await refreshChapters();
      })
      .catch(() => { /* 失败 / 停止：面板保留错误态由任务弹窗展示 */ });
  }, [streamJobId, runningWriteJobs, refreshChapters]);

  const startStream = useCallback(async ({
    chapter,
    isRegenerate,
    requestBody,
    mode,
  }: {
    chapter: Chapter;
    isRegenerate: boolean;
    requestBody: Record<string, unknown>;
    mode: 'single' | 'batch';
  }): Promise<ChapterWriteResult | ChapterRegenerateResult | null> => {
    setExpandedId(chapter.id);
    setStreamDone(false);
    setPanelHidden(false);
    setStreamJobId(null);
    setPreviewContent(prev => ({ ...prev, [chapter.id]: '' }));
    await loadRelatedCardsForChapter(chapter);

    setStreamState({
      chapterId: chapter.id,
      chapterTitle: chapter.title,
      progress: 0,
      message: mode === 'batch' ? '准备串行生成…' : '准备生成…',
      content: '',
      mode,
    });

    try {
      const job = await runAIJob({
        kind: isRegenerate ? 'chapter_regenerate' : 'chapter_generate',
        title: `${isRegenerate ? '重写' : '生成'}第 ${chapter.chapter_number} 章《${chapter.title}》`,
        projectId: chapter.project_id,
        openModal: false,
        meta: { chapter_id: chapter.id },
        onStarted: setStreamJobId,
        connect: (options: SSEClientOptions<unknown>) =>
          isRegenerate
            ? chapterApi.regenerateChapterStream(chapter.id, requestBody, options as SSEClientOptions<ChapterRegenerateResult>)
            : chapterApi.generateChapterStream(chapter.id, requestBody as unknown as ChapterGenerateRequest, options as SSEClientOptions<ChapterWriteResult>),
        onEvent: (m) => {
          if (mode === 'batch' && m.type === 'progress' && typeof m.progress === 'number') {
            const pct = m.progress;
            const message = typeof m.message === 'string' ? m.message : undefined;
            setBatchStatus(prev => {
              if (!prev || prev.status !== 'running') return prev;
              return {
                ...prev,
                progress: Math.min(((prev.completed + pct / 100) / prev.total) * 100, 99),
                message: message ?? prev.message,
              };
            });
          }
        },
      });
      const finalContent = job.content;
      setStreamState(prev => (prev && prev.chapterId === chapter.id ? { ...prev, progress: 100, content: finalContent } : prev));
      setPreviewContent(prev => ({ ...prev, [chapter.id]: finalContent || prev[chapter.id] || '' }));
      setStreamDone(true);
      await refreshChapters();
      if (mode === 'single') {
        toast.success(`「${chapter.title}」生成完成`);
      }
      return (job.result as ChapterWriteResult | ChapterRegenerateResult | null) ?? null;
    } catch (error) {
      if (error instanceof AIJobError && error.job.status === 'cancelled') {
        throw abortError();
      }
      toast.error((error as Error)?.message || '生成失败');
      setStreamState(null);
      throw error;
    }
  }, [loadRelatedCardsForChapter, refreshChapters]);

  /** 等待本章分析任务（正文任务 result 里带 analysis_job_id）结束；没有分析任务则直接返回 */
  const waitForChapterAnalysis = useCallback(async (chapter: Chapter, analysisJobId: string | null | undefined) => {
    if (!analysisJobId) return;
    setAnalyzingIds(prev => new Set(prev).add(chapter.id));
    const unsubscribe = useAIJobsStore.getState().subscribe(analysisJobId, (m) => {
      if (m.type !== 'progress' || typeof m.message !== 'string') return;
      const waitingMessage = `正在分析第 ${chapter.chapter_number} 章：${m.message}`;
      setBatchStatus(prev => prev && prev.status === 'running' && prev.currentChapterId === chapter.id
        ? { ...prev, message: waitingMessage }
        : prev);
      setStreamState(prev => prev && prev.chapterId === chapter.id
        ? { ...prev, message: waitingMessage, progress: 100 }
        : prev);
    });
    try {
      if (batchCancelRef.current) throw abortError();
      await attachJob(analysisJobId).catch(() => { /* 已在 store 中 / 已过期 → 由 waitForAIJob 判定 */ });
      await waitForAIJob(analysisJobId);
      await refreshChapters();
      setBatchStatus(prev => prev && prev.status === 'running' && prev.currentChapterId === chapter.id
        ? { ...prev, message: `第 ${chapter.chapter_number} 章分析完成，开始整理记忆…` }
        : prev);
    } catch (error) {
      if (error instanceof AIJobError) {
        throw new Error(error.job.error || `第 ${chapter.chapter_number} 章分析失败`);
      }
      throw error;
    } finally {
      unsubscribe();
      setAnalyzingIds(prev => {
        const next = new Set(prev);
        next.delete(chapter.id);
        return next;
      });
    }
  }, [attachJob, refreshChapters]);

  const closeStreamPanel = () => {
    setStreamState(null);
    setStreamJobId(null);
    setStreamDone(false);
    setRelatedCards([]);
    setGenTarget(null);
    setLoadingCards(false);
  };

  /** 后台运行：收起面板，任务继续；顶部横幅 / 托盘可再打开 */
  const hideStreamPanel = () => setPanelHidden(true);

  const cancelStream = () => {
    if (batchStatus?.status === 'running') {
      cancelBatch();
      return;
    }
    if (streamJobId) void cancelJob(streamJobId);
    setStreamState(null);
    setStreamJobId(null);
    setStreamDone(false);
    setRelatedCards([]);
    setLoadingCards(false);
    toast.info('已停止生成');
  };

  /** 拉取某章一致性审计中的严重问题数（失败按 0 处理，不阻塞批量流程） */
  const fetchCriticalIssueCount = useCallback(async (chapterId: string): Promise<number> => {
    try {
      const data = await chapterApi.getAnalysis(chapterId);
      const normalized = normalizeAnalysisData(data as unknown as Record<string, unknown>);
      return normalized.consistency_audit.summary.critical;
    } catch {
      return 0;
    }
  }, []);

  // ========== 4. 批量生成 ==========
  const openBatchModal = () => {
    setBatchFrom(sorted.length > 0 ? sorted[0].chapter_number : 1);
    setBatchTo(sorted.length > 0 ? sorted[sorted.length - 1].chapter_number : 5);
    setShowBatchModal(true);
  };

  const startBatchGenerate = async () => {
    if (!currentProject) return;

    const chaptersInRange = sorted.filter(
      chapter => chapter.chapter_number >= batchFrom && chapter.chapter_number <= batchTo
    );
    const chaptersToGenerate = chaptersInRange.filter(
      chapter => !(chapter.status === 'completed' && chapter.word_count > 0)
    );
    const skippedCount = chaptersInRange.length - chaptersToGenerate.length;

    if (chaptersToGenerate.length === 0) {
      toast.info('所选范围内没有待生成的章节');
      return;
    }

    batchCancelRef.current = false;
    setShowBatchModal(false);
    setBatchStatus({
      status: 'running',
      total: chaptersToGenerate.length,
      completed: 0,
      progress: 0,
      currentChapterId: null,
      currentChapterNumber: null,
      currentChapterTitle: null,
      message: skippedCount > 0 ? `已自动跳过 ${skippedCount} 章已有内容的章节` : '准备开始串行生成…',
      skippedCount,
    });

    if (skippedCount > 0) {
      toast.info(`已自动跳过 ${skippedCount} 章已有内容的章节`);
    }

    try {
      for (let index = 0; index < chaptersToGenerate.length; index += 1) {
        const chapter = chaptersToGenerate[index];

        if (batchCancelRef.current) {
          break;
        }

        setBatchStatus(prev => prev ? {
          ...prev,
          currentChapterId: chapter.id,
          currentChapterNumber: chapter.chapter_number,
          currentChapterTitle: chapter.title,
          message: `正在生成第 ${chapter.chapter_number} 章`,
          progress: (prev.completed / prev.total) * 100,
        } : prev);

        const result = await startStream({
          chapter,
          isRegenerate: false,
          requestBody: {
            target_word_count: 3000,
            enable_mcp: true,
          },
          mode: 'batch',
        });

        await waitForChapterAnalysis(chapter, (result as ChapterWriteResult | null)?.analysis_job_id);

        if (batchCancelRef.current) {
          break;
        }

        // 一致性闸门：本章审计出严重问题时暂停批量，避免错误设定向后传播
        if (batchPauseOnCritical) {
          const criticalCount = await fetchCriticalIssueCount(chapter.id);
          if (criticalCount > 0) {
            const goOn = window.confirm(
              `第 ${chapter.chapter_number} 章检测到 ${criticalCount} 个严重一致性问题（详见该章「章节分析」面板）。\n\n` +
              `继续批量生成可能让错误设定影响后续章节。\n` +
              `「确定」继续生成后续章节；「取消」停止批量，先修复本章。`
            );
            if (!goOn) {
              batchCancelRef.current = true;
              setBatchStatus(prev => prev ? {
                ...prev,
                status: 'cancelled',
                message: `已在第 ${chapter.chapter_number} 章后暂停：${criticalCount} 个严重一致性问题待处理`,
              } : prev);
              toast.warning(`批量生成已暂停，请先处理第 ${chapter.chapter_number} 章的一致性问题`);
              break;
            }
          }
        }

        setBatchStatus(prev => prev ? {
          ...prev,
          completed: index + 1,
          progress: ((index + 1) / prev.total) * 100,
          message: `已完成 ${index + 1} / ${prev.total} 章`,
        } : prev);
      }

      if (batchCancelRef.current) {
        return;
      }

      setBatchStatus(prev => prev ? {
        ...prev,
        status: 'completed',
        completed: prev.total,
        progress: 100,
        message: `批量串行生成完成，共完成 ${prev.total} 章`,
      } : prev);
      toast.success('批量生成完成');
    } catch (error) {
      if ((error as DOMException)?.name === 'AbortError') {
        return;
      }

      setBatchStatus(prev => prev ? {
        ...prev,
        status: 'error',
        errorMessage: (error as Error)?.message || '批量生成失败',
        message: prev.currentChapterNumber
          ? `第 ${prev.currentChapterNumber} 章生成失败，批量任务已停止`
          : '批量生成失败',
      } : prev);
      toast.error((error as Error)?.message || '批量生成失败');
    }
  };

  const cancelBatch = () => {
    if (!batchStatus || batchStatus.status !== 'running') return;

    batchCancelRef.current = true;
    if (streamJobId) void cancelJob(streamJobId);
    setStreamState(null);
    setStreamJobId(null);
    setStreamDone(false);
    setRelatedCards([]);
    setLoadingCards(false);
    setBatchStatus(prev => prev ? {
      ...prev,
      status: 'cancelled',
      message: '已取消批量生成',
    } : prev);
    toast.info('已取消批量生成');
  };

  // ========== 5. 触发分析（通用后台任务 + 弹窗：阶段 / 模型进度可见，可后台运行） ==========
  const handleAnalyze = async (chapter: Chapter) => {
    if (!currentProject) return;
    try {
      await useAIJobsStore.getState().start({
        kind: 'chapter_analyze',
        title: `分析第 ${chapter.chapter_number} 章《${chapter.title}》`,
        projectId: currentProject.id,
        meta: { chapter_id: chapter.id },
        connect: (options) => chapterApi.analyzeChapterStream(chapter.id, options),
        onSettled: (job) => {
          if (job.status === 'done') {
            toast.success(`「${chapter.title}」分析完成`);
            void refreshChapters();
          }
        },
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '分析启动失败');
    }
  };

  const runningAnalysisChapterIds = new Set(
    runningAnalyses.map((j) => (typeof j.meta.chapter_id === 'string' ? j.meta.chapter_id : '')),
  );
  const batchRunning = batchStatus?.status === 'running';
  const isGenerating = (id: string) => streamState?.chapterId === id && !streamDone;
  const completedPreviousChapters = genCheck?.previous_chapters.filter(chapter => chapter.has_content) ?? [];
  const previousChapterPreview = completedPreviousChapters.slice(-3);
  const relatedCardPreview = relatedCards.slice(0, 3);
  const totalWords = chapters.reduce((s, c) => s + c.word_count, 0);
  const completedCount = chapters.filter((c) => c.status === 'completed').length;
  const streamBusy = !!streamState && !streamDone;

  return (
    <div className="animate-fade-in space-y-6">
      {/* 头部 */}
      <section className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0">
          <h1 className="text-[28px] font-semibold tracking-tight text-content md:text-[32px]">章节管理</h1>
          <p className="mt-2 max-w-[560px] text-sm leading-6 text-content-secondary">
            {chapters.length > 0
              ? `共 ${chapters.length} 章 · ${totalWords.toLocaleString()} 字。从章纲同步生成章节骨架，再逐章或批量交给 AI 成稿。`
              : '从章纲同步生成章节骨架，再逐章或批量交给 AI 成稿。'}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <button onClick={handleSyncFromOutlines} disabled={syncing} className="hh-btn-secondary">
            {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            从章纲同步
          </button>
          <button onClick={openBatchModal} disabled={batchRunning || streamBusy} className="hh-btn-secondary">
            <Layers className="h-4 w-4" />
            批量生成
          </button>
          <button onClick={openAdd} className="hh-btn-primary">
            <Plus className="h-4 w-4" />
            新建章节
          </button>
        </div>
      </section>

      {chapters.length > 0 && (
        <section className="hh-panel grid grid-cols-2 divide-surface-border/80 md:grid-cols-4 md:divide-x">
          <StatItem label="章节总数" value={chapters.length} />
          <StatItem label="已完成" value={completedCount} />
          <StatItem label="待生成" value={chapters.length - completedCount} />
          <StatItem label="累计字数" value={totalWords.toLocaleString()} />
        </section>
      )}

      {/* 批量生成进度 */}
      {batchStatus && (
        <section className="hh-panel space-y-3 p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 space-y-1">
              <div className="flex items-center gap-2 text-sm">
                <span className="font-medium text-content">
                  {batchStatus.status === 'running'
                    ? `批量串行生成中 · ${batchStatus.completed}/${batchStatus.total}`
                    : batchStatus.status === 'completed'
                      ? `批量生成完成 · ${batchStatus.total}/${batchStatus.total}`
                      : batchStatus.status === 'cancelled'
                        ? '批量生成已取消'
                        : '批量生成失败'}
                </span>
                <span className="text-content-tertiary tabular-nums">{Math.round(batchStatus.progress)}%</span>
              </div>
              <p className="text-xs text-content-secondary">
                {batchStatus.currentChapterNumber
                  ? `当前章节：第 ${batchStatus.currentChapterNumber} 章 · ${batchStatus.currentChapterTitle}`
                  : batchStatus.message}
              </p>
              {batchStatus.skippedCount > 0 && (
                <p className="text-xs text-content-tertiary">已自动跳过 {batchStatus.skippedCount} 章已有内容的章节</p>
              )}
              {batchStatus.errorMessage && <p className="text-xs text-red-500">{batchStatus.errorMessage}</p>}
            </div>
            {batchStatus.status === 'running' && (
              <button onClick={cancelBatch} className="hh-btn-ghost hh-btn-sm text-red-500 hover:bg-red-50 hover:text-red-600">
                取消
              </button>
            )}
          </div>
          <div className="hh-progress h-2">
            <div
              className={cn(
                'hh-progress-bar',
                batchStatus.status === 'completed' && 'bg-emerald-500',
                batchStatus.status === 'error' && 'bg-red-500',
              )}
              style={{ width: `${Math.min(batchStatus.progress, 100)}%` }}
            />
          </div>
        </section>
      )}

      {/* 后台 AI 任务横幅：分析 / 场景 / 仿写常驻；正文任务在面板收起（后台运行）时也进横幅 */}
      <AIJobBanner projectId={currentProject?.id} kinds={panelHidden || !streamState ? [...WRITE_JOB_KINDS, ...OTHER_JOB_KINDS] : OTHER_JOB_KINDS} />

      {/* AI 创作面板（全局任务的页面视图：关面板 / 切页 / 刷新都不影响任务） */}
      {streamState && !panelHidden && (
        <section className="hh-panel overflow-hidden border-brand/30">
          <div className="border-b border-surface-border/80 px-5 py-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center bg-brand/10 text-brand">
                  <Zap className="h-4 w-4" />
                </span>
                <span className="text-sm font-semibold text-content">
                  {batchRunning ? '批量串行生成：' : streamDone ? '已完成：' : 'AI 创作中：'}
                  {streamState.chapterTitle}
                </span>
                {streamState.mode === 'batch' && <span className="hh-tag">串行队列</span>}
                <span className="text-xs text-content-tertiary tabular-nums">{streamState.content.length.toLocaleString()} 字</span>
              </div>
              <div className="flex items-center gap-2">
                {streamJob && (
                  <button onClick={() => setShowProcess((v) => !v)} className="hh-btn-ghost hh-btn-sm">
                    {showProcess ? '收起过程' : '查看过程'}
                  </button>
                )}
                {!streamDone && !batchRunning && (
                  <button onClick={hideStreamPanel} className="hh-btn-ghost hh-btn-sm">
                    后台运行
                  </button>
                )}
                {(!streamDone || batchRunning) && (
                  <button onClick={cancelStream} className="hh-btn-ghost hh-btn-sm text-red-500 hover:bg-red-50 hover:text-red-600">
                    {batchRunning ? '取消批量' : '停止生成'}
                  </button>
                )}
                {streamDone && !batchRunning && (
                  <button onClick={closeStreamPanel} className="hh-btn-ghost hh-btn-sm">
                    关闭面板
                  </button>
                )}
              </div>
            </div>
            <div className="hh-progress mt-3">
              <div
                className={cn('hh-progress-bar', streamDone && 'bg-emerald-500', streamJob?.status === 'error' && 'bg-red-500')}
                style={{ width: `${Math.min(streamState.progress, 100)}%` }}
              />
            </div>
            <p className="mt-2 text-xs text-content-tertiary">
              {streamJob?.status === 'error' ? `生成失败：${streamJob.error ?? ''}` : streamState.message}
            </p>
          </div>

          {/* 过程面板：阶段 / MCP 工具 / 参考资料（记忆、剧情卡、参考包） */}
          {streamJob && showProcess && (
            <div className="border-b border-surface-border/80 bg-white/40 px-5 py-4">
              <AIJobProcess job={streamJob} />
            </div>
          )}

          <div className="flex min-h-[400px]">
            {/* 左侧：关联卡片 */}
            {(relatedCards.length > 0 || loadingCards) && (
              <aside className="w-64 flex-shrink-0 overflow-y-auto border-r border-surface-border/80 bg-brand/[0.03] p-4" style={{ maxHeight: '500px' }}>
                <div className="mb-3 flex items-center gap-1.5 text-xs font-medium text-content-secondary">
                  <LayoutGrid className="h-3.5 w-3.5 text-content-tertiary" />
                  关联剧情卡片
                </div>
                {loadingCards ? (
                  <div className="flex items-center justify-center gap-1.5 py-4 text-xs text-content-tertiary">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    加载中…
                  </div>
                ) : (
                  <div className="space-y-2">
                    {relatedCards.map((card) => (
                      <div key={card.id} className="hh-subpanel p-3">
                        <div className="mb-1 flex items-center gap-1.5">
                          <span className="hh-tag px-1.5 py-0.5 text-[10px]">
                            {card.card_type === 'plot' ? '剧情' : card.card_type === 'character' ? '角色' : card.card_type === 'scene' ? '场景' : card.card_type === 'conflict' ? '冲突' : '其他'}
                          </span>
                          <span className="truncate text-xs font-medium text-content">{card.title}</span>
                        </div>
                        <p className="line-clamp-3 text-[11px] leading-relaxed text-content-tertiary">{card.content || '无内容'}</p>
                      </div>
                    ))}
                  </div>
                )}
              </aside>
            )}

            {/* 右侧：流式内容编辑区 */}
            <div className="flex flex-1 flex-col">
              <textarea
                ref={streamContentRef}
                value={streamState.content}
                onChange={(e) => {
                  if (streamDone) {
                    setStreamState((prev) => (prev ? { ...prev, content: e.target.value } : null));
                  }
                }}
                readOnly={!streamDone}
                className="min-h-[400px] w-full flex-1 resize-none !border-0 !bg-transparent p-5 text-sm leading-7 text-content !shadow-none outline-none focus:!shadow-none"
                placeholder={streamDone ? '生成完成，可直接编辑内容…' : 'AI 正在创作中…'}
              />
              {streamDone && (
                <div className="flex items-center justify-between gap-3 border-t border-surface-border/80 bg-white/40 px-5 py-3">
                  <span className="text-xs text-content-tertiary">生成完成，可在上方直接编辑。修改后点击「保存修改」更新到数据库。</span>
                  <button
                    onClick={async () => {
                      if (!streamState) return;
                      try {
                        await updateChapter(streamState.chapterId, { content: streamState.content });
                        toast.success('内容已保存');
                        refreshChapters();
                      } catch {
                        toast.error('保存失败');
                      }
                    }}
                    className="hh-btn-primary hh-btn-sm shrink-0"
                  >
                    保存修改
                  </button>
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {/* 章节列表 */}
      {sorted.length > 0 ? (
        <section className="hh-panel divide-y divide-surface-border/80 overflow-hidden">
          {sorted.map((c) => {
            const status = STATUS_MAP[c.status] || STATUS_MAP.draft;
            const activeStreamChapter = streamState?.chapterId === c.id;
            const generating = isGenerating(c.id);
            const currentBatchChapter = batchRunning && batchStatus?.currentChapterId === c.id;
            const analyzing = analyzingIds.has(c.id) || runningAnalysisChapterIds.has(c.id);
            return (
              <div key={c.id} className={cn('px-5 py-3.5 transition-colors', currentBatchChapter ? 'bg-brand/[0.06]' : 'hover:bg-brand/[0.04]')}>
                <div className="flex items-center gap-4">
                  <div
                    className={cn(
                      'flex h-9 w-9 flex-shrink-0 items-center justify-center text-sm font-semibold tabular-nums',
                      c.status === 'completed' ? 'bg-brand/10 text-brand' : 'bg-surface-hover text-content-secondary',
                    )}
                  >
                    {c.chapter_number}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-semibold text-content">{c.title}</span>
                      <span className={cn('flex-shrink-0 px-2 py-0.5 text-[11px] font-medium', status.cls)}>{status.label}</span>
                      {currentBatchChapter && <span className="hh-tag flex-shrink-0 px-2 py-0.5 text-[11px]">串行生成中</span>}
                    </div>
                    <p className="mt-0.5 text-xs text-content-tertiary tabular-nums">
                      {c.word_count > 0 ? `${c.word_count.toLocaleString()} 字` : '暂无内容'}
                    </p>
                  </div>
                  {c.word_count > 0 && (
                    <button
                      onClick={() => togglePreview(c)}
                      disabled={batchRunning && batchStatus?.currentChapterId !== c.id}
                      className="hh-icon-btn-plain h-8 w-8 flex-shrink-0"
                      title="预览内容"
                      aria-label="预览内容"
                    >
                      {expandedId === c.id ? <ChevronUp className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  )}
                  <div className="flex flex-shrink-0 items-center gap-0.5">
                    <button onClick={() => openEdit(c)} className="hh-icon-btn-plain h-8 w-8 hover:text-brand" title="编辑" aria-label="编辑">
                      <Pencil className="h-4 w-4" />
                    </button>

                    {c.status === 'completed' && c.word_count > 0 ? (
                      <button
                        onClick={() => handleRegenerate(c)}
                        disabled={generating || batchRunning || streamBusy}
                        className="hh-icon-btn-plain h-8 w-8 hover:text-brand"
                        title="重新生成"
                        aria-label="重新生成"
                      >
                        {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                      </button>
                    ) : (
                      <button
                        onClick={() => handleGenerate(c)}
                        disabled={generating || batchRunning || streamBusy}
                        className="hh-icon-btn-plain h-8 w-8 hover:text-brand"
                        title="AI 生成"
                        aria-label="AI 生成"
                      >
                        {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
                      </button>
                    )}

                    {c.chapter_outline_id && (
                      <button
                        onClick={() => setSceneTarget({ outlineId: c.chapter_outline_id!, title: c.title })}
                        className="hh-icon-btn-plain h-8 w-8 hover:text-brand"
                        title="场景生成"
                        aria-label="场景生成"
                      >
                        <Film className="h-4 w-4" />
                      </button>
                    )}

                    {c.status === 'completed' && (
                      <button
                        onClick={() => handleAnalyze(c)}
                        disabled={analyzing}
                        className="hh-icon-btn-plain h-8 w-8 hover:text-brand"
                        title="分析"
                        aria-label="分析"
                      >
                        {analyzing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                      </button>
                    )}

                    <button
                      onClick={() => handleDelete(c.id, c.title)}
                      className="hh-icon-btn-plain h-8 w-8 hover:text-red-500"
                      title="删除"
                      aria-label="删除"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                {/* 内容预览区 */}
                {expandedId === c.id && (
                  <div className="mt-3 border-t border-surface-border/80 pt-3">
                    {activeStreamChapter ? (
                      <div className="space-y-3">
                        <div className="flex items-center justify-between text-xs">
                          <span className="font-medium text-brand">
                            {batchRunning ? '正在按顺序生成本章…' : streamDone ? '本章生成完成' : '正在生成本章…'}
                          </span>
                          <span className="text-content-tertiary tabular-nums">{Math.round(streamState?.progress ?? 0)}%</span>
                        </div>
                        <div className="hh-progress">
                          <div
                            className={cn('hh-progress-bar', streamDone && 'bg-emerald-500')}
                            style={{ width: `${Math.min(streamState?.progress ?? 0, 100)}%` }}
                          />
                        </div>
                        <p className="text-xs text-content-secondary">{streamState?.message || 'AI 正在创作中…'}</p>
                        <div className="hh-subpanel max-h-72 overflow-y-auto whitespace-pre-wrap p-4 text-sm leading-7 text-content-secondary">
                          {streamState?.content || 'AI 正在创作中…'}
                        </div>
                      </div>
                    ) : loadingPreview === c.id ? (
                      <div className="flex items-center gap-2 py-2 text-xs text-content-secondary">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        加载中...
                      </div>
                    ) : (
                      <div className="hh-subpanel max-h-60 overflow-y-auto whitespace-pre-wrap p-4 text-sm leading-7 text-content-secondary">
                        {previewContent[c.id] || '暂无内容'}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </section>
      ) : (
        <section className="hh-panel flex flex-col items-center px-6 py-14 text-center">
          <span className="flex h-14 w-14 items-center justify-center bg-brand/10 text-brand">
            <BookOpen className="h-7 w-7" />
          </span>
          <h2 className="mt-5 text-xl font-semibold tracking-tight text-content">还没有章节</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">
            点击右上角「从章纲同步」把章纲一键转成章节骨架，或「新建章节」手动添加。
          </p>
        </section>
      )}

      {/* 新建/编辑弹窗 */}
      {showModal &&
        createPortal(
          <div className="hh-modal-mask">
            <div className="hh-modal max-w-[760px]" role="dialog" aria-modal="true">
              <div className="hh-modal-head">
                <div>
                  <p className="hh-eyebrow">章节</p>
                  <h2 className="mt-2 text-xl font-semibold tracking-tight text-content">{editingId ? '编辑章节' : '新建章节'}</h2>
                </div>
                <button onClick={() => setShowModal(false)} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="hh-modal-body space-y-5">
                <div className="flex gap-4">
                  <div className="flex-1">
                    <label className="hh-label">章节标题</label>
                    <input
                      value={form.title}
                      onChange={(e) => setForm((p) => ({ ...p, title: e.target.value }))}
                      placeholder="输入章节标题"
                      className="hh-field"
                    />
                  </div>
                  {!editingId && (
                    <div className="w-32">
                      <label className="hh-label">章节序号</label>
                      <input
                        type="number"
                        min={1}
                        value={form.chapter_number}
                        onChange={(e) => setForm((p) => ({ ...p, chapter_number: Number(e.target.value) }))}
                        className="hh-field"
                      />
                    </div>
                  )}
                </div>
                <div>
                  <div className="mb-1.5 flex items-center justify-between">
                    <label className="text-[13px] font-medium text-content">正文内容</label>
                    <div className="flex items-center gap-2">
                      {loadingContent && (
                        <span className="inline-flex items-center gap-1 text-xs text-content-tertiary">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          加载中…
                        </span>
                      )}
                      {form.content && <span className="text-xs text-content-tertiary tabular-nums">{form.content.length.toLocaleString()} 字</span>}
                      {editingId && currentProject && (
                        <button
                          type="button"
                          onClick={() => setShowImitationDialog(true)}
                          className="hh-chip text-brand"
                          title="从已挂载参考包生成草稿追加到正文"
                        >
                          <Sparkles className="h-3 w-3" />
                          一键仿写
                        </button>
                      )}
                    </div>
                  </div>
                  <textarea
                    value={form.content}
                    onChange={(e) => setForm((p) => ({ ...p, content: e.target.value }))}
                    placeholder="输入或粘贴章节正文内容…"
                    rows={16}
                    className="hh-textarea !resize-y leading-7"
                  />
                </div>
              </div>
              <div className="hh-modal-foot">
                <button onClick={() => setShowModal(false)} className="hh-btn-ghost">
                  取消
                </button>
                <button onClick={handleSubmit} disabled={submitting || !form.title.trim()} className="hh-btn-primary">
                  {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
                  {submitting ? '保存中…' : '保存'}
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}

      {/* 场景生成弹窗 */}
      {sceneTarget && (
        <SceneGenerator
          chapterOutlineId={sceneTarget.outlineId}
          chapterTitle={sceneTarget.title}
          projectId={currentProject?.id}
          onClose={() => setSceneTarget(null)}
          onComplete={() => refreshChapters()}
        />
      )}

      {/* 一键仿写弹板（V3 R5） */}
      {editingId && currentProject && (
        <ImitationDialog
          isOpen={showImitationDialog}
          projectId={currentProject.id}
          targetChapterId={editingId}
          targetChapterTitle={form.title || '未命名章节'}
          onClose={() => setShowImitationDialog(false)}
          onApply={(draft) => {
            setForm((prev) => {
              const sep = prev.content && !prev.content.endsWith('\n') ? '\n\n' : '';
              return { ...prev, content: prev.content + sep + draft };
            });
          }}
        />
      )}

      {/* AI 生成配置弹窗 */}
      {showGenModal &&
        genTarget &&
        createPortal(
          <div className="hh-modal-mask">
            <div className="hh-modal max-w-[680px]" role="dialog" aria-modal="true">
              <div className="hh-modal-head">
                <div className="min-w-0">
                  <p className="hh-eyebrow">{genTarget.isRegenerate ? '重新生成' : 'AI 生成'}</p>
                  <h2 className="mt-2 truncate text-xl font-semibold tracking-tight text-content">{genTarget.chapter.title}</h2>
                  <p className="mt-1 text-sm text-content-secondary">
                    {genTarget.isRegenerate ? '基于分析建议与修改要求针对性改稿，每次重生成都会留档。' : '选择风格与目标字数，AI 会结合章纲、前文与设定生成正文。'}
                  </p>
                </div>
                <button onClick={closeGenerateModal} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="hh-modal-body space-y-5">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label className="hh-label">写作风格</label>
                    <select
                      value={genConfig.style_id ?? ''}
                      onChange={(e) =>
                        setGenConfig((prev) => ({
                          ...prev,
                          style_id: e.target.value ? Number(e.target.value) : undefined,
                        }))
                      }
                      className="hh-field"
                    >
                      <option value="">不使用风格（默认）</option>
                      {styles.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="hh-label flex items-center justify-between">
                      目标字数
                      <span className="text-xs font-normal text-content-secondary tabular-nums">{genConfig.target_word_count.toLocaleString()} 字</span>
                    </label>
                    <input
                      type="range"
                      min={500}
                      max={10000}
                      step={500}
                      value={genConfig.target_word_count}
                      onChange={(e) => setGenConfig((prev) => ({ ...prev, target_word_count: Number(e.target.value) }))}
                      className="mt-3 w-full accent-brand"
                    />
                    <div className="mt-1 flex justify-between text-xs text-content-tertiary tabular-nums">
                      <span>500</span>
                      <span>3000</span>
                      <span>5000</span>
                      <span>10000</span>
                    </div>
                  </div>
                </div>

                <MCPSelector
                  value={{ enable: genConfig.enable_mcp, selected: genConfig.selected_plugins }}
                  onChange={(val) =>
                    setGenConfig((prev) => ({
                      ...prev,
                      enable_mcp: val.enable,
                      selected_plugins: val.selected,
                    }))
                  }
                />
                {currentProject?.id && (
                  <ReferencePackSelector
                    projectId={currentProject.id}
                    value={genRefPack}
                    onChange={setGenRefPack}
                    hint={genTarget.isRegenerate ? '让本次重生成参考拆书的笔法/节奏/语料' : '让本章正文参考拆书的笔法/方法论/语料'}
                    disabledTitle="使用拆书参考包作为对标"
                  />
                )}

                {/* ===== 修订闭环（仅重生成）：分析建议 / 一致性问题 / 修改要求 / 保留元素 / 版本历史 ===== */}
                {genTarget.isRegenerate && (
                  <div className="space-y-4 border border-brand/25 bg-brand/5 p-4">
                    <div>
                      <p className="text-sm font-medium text-content">修订意见</p>
                      <p className="mt-1 text-xs text-content-tertiary">勾选要修复的问题并补充修改要求，AI 会在保留指定元素的前提下针对性改稿。</p>
                    </div>

                    {regenAnalysisLoading ? (
                      <div className="flex items-center gap-2 py-1 text-xs text-content-secondary">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        加载分析结果…
                      </div>
                    ) : (
                      <>
                        {(regenAnalysis?.suggestions?.length ?? 0) > 0 && (
                          <div className="space-y-1.5">
                            <p className="text-xs font-medium text-content">AI 分析建议（勾选采纳）</p>
                            {regenAnalysis!.suggestions!.map((sug, idx) => (
                              <label key={idx} className="flex cursor-pointer items-start gap-2 text-xs text-content-secondary hover:text-content">
                                <input
                                  type="checkbox"
                                  className="mt-0.5"
                                  checked={selectedSuggestionIdx.has(idx)}
                                  onChange={() =>
                                    setSelectedSuggestionIdx((prev) => {
                                      const next = new Set(prev);
                                      if (next.has(idx)) next.delete(idx);
                                      else next.add(idx);
                                      return next;
                                    })
                                  }
                                />
                                <span className="leading-5">{sug}</span>
                              </label>
                            ))}
                          </div>
                        )}

                        {(regenAnalysis?.consistency_audit.issues.length ?? 0) > 0 && (
                          <div className="space-y-1.5">
                            <p className="text-xs font-medium text-content">一致性问题（勾选带入修复）</p>
                            {regenAnalysis!.consistency_audit.issues.slice(0, 8).map((issue, idx) => {
                              const sev = String(issue.severity || 'low');
                              const sevCls =
                                sev === 'critical'
                                  ? 'bg-red-50 text-red-600'
                                  : sev === 'high'
                                    ? 'bg-amber-50 text-amber-600'
                                    : 'bg-surface-hover text-content-secondary';
                              return (
                                <label key={idx} className="flex cursor-pointer items-start gap-2 text-xs text-content-secondary hover:text-content">
                                  <input
                                    type="checkbox"
                                    className="mt-0.5"
                                    checked={selectedIssueIdx.has(idx)}
                                    onChange={() =>
                                      setSelectedIssueIdx((prev) => {
                                        const next = new Set(prev);
                                        if (next.has(idx)) next.delete(idx);
                                        else next.add(idx);
                                        return next;
                                      })
                                    }
                                  />
                                  <span className="leading-5">
                                    <span className={cn('mr-1 px-1 py-px text-[10px] font-medium', sevCls)}>{sev}</span>
                                    {String(issue.title || issue.rule_code || '一致性问题')}
                                    {issue.details ? `：${String(issue.details)}` : ''}
                                  </span>
                                </label>
                              );
                            })}
                          </div>
                        )}

                        {!regenAnalysis && (
                          <p className="text-xs text-content-tertiary">本章暂无分析结果（可先在列表中点「分析」），也可直接填写自定义修改要求。</p>
                        )}
                      </>
                    )}

                    <div>
                      <label className="hh-label text-xs">自定义修改要求（可选）</label>
                      <textarea
                        value={customInstructions}
                        onChange={(e) => setCustomInstructions(e.target.value)}
                        placeholder="例如：把中段打斗改成智斗；结尾钩子改为反派视角…"
                        rows={3}
                        className="hh-textarea !resize-y bg-white/80 text-xs"
                      />
                    </div>

                    <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-content-secondary">
                      <label className="flex cursor-pointer items-center gap-1.5">
                        <input type="checkbox" checked={preserveStructure} onChange={(e) => setPreserveStructure(e.target.checked)} />
                        保留整体结构与情节框架
                      </label>
                      <label className="flex cursor-pointer items-center gap-1.5">
                        <input type="checkbox" checked={preserveTraits} onChange={(e) => setPreserveTraits(e.target.checked)} />
                        保持角色性格一致
                      </label>
                      <label className="flex cursor-pointer items-center gap-1.5">
                        <input type="checkbox" checked={autoApply} onChange={(e) => setAutoApply(e.target.checked)} />
                        生成后覆盖正文（关闭则仅存为版本草稿）
                      </label>
                    </div>

                    {/* 版本历史：应用新稿 / 回滚原稿 */}
                    <div className="space-y-1.5">
                      <p className="text-xs font-medium text-content">历史版本</p>
                      {versionLoading ? (
                        <div className="flex items-center gap-2 py-1 text-xs text-content-secondary">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          加载版本…
                        </div>
                      ) : versionTasks.length === 0 ? (
                        <p className="text-xs text-content-tertiary">暂无历史版本（每次重生成都会自动留档）</p>
                      ) : (
                        versionTasks.map((task) => (
                          <div key={task.task_id} className="flex items-center justify-between gap-2 border border-surface-border bg-white/80 px-3 py-2 text-xs">
                            <div className="min-w-0">
                              <span className="font-medium text-content">v{task.version_number ?? 1}</span>
                              <span className="ml-2 text-content-tertiary tabular-nums">
                                {task.status === 'completed'
                                  ? `${task.original_word_count ?? '?'} → ${task.regenerated_word_count ?? '?'} 字`
                                  : task.status}
                              </span>
                              {task.version_note && <span className="ml-2 truncate text-content-secondary">{task.version_note}</span>}
                              {task.created_at && (
                                <span className="ml-2 text-content-tertiary">{new Date(task.created_at).toLocaleString('zh-CN', { hour12: false })}</span>
                              )}
                            </div>
                            {task.status === 'completed' && (
                              <div className="flex shrink-0 gap-1.5">
                                <button
                                  onClick={() => handleApplyVersion(task.task_id, 'regenerated')}
                                  disabled={applyingVersionKey !== null}
                                  className="hh-chip px-2 py-1 text-[11px] text-brand"
                                >
                                  {applyingVersionKey === `${task.task_id}:regenerated` ? '应用中…' : '应用新稿'}
                                </button>
                                <button
                                  onClick={() => handleApplyVersion(task.task_id, 'original')}
                                  disabled={applyingVersionKey !== null}
                                  className="hh-chip px-2 py-1 text-[11px]"
                                >
                                  {applyingVersionKey === `${task.task_id}:original` ? '回滚中…' : '回滚原稿'}
                                </button>
                              </div>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                )}

                <div className="hh-subpanel space-y-3 p-4">
                  <div>
                    <p className="text-sm font-medium text-content">本次生成会参考的内容</p>
                    <p className="mt-1 text-xs text-content-tertiary">后端会自动组合章纲、前文、关联剧情卡片、项目设定和可选 MCP 检索结果来生成正文。</p>
                  </div>
                  <div className="space-y-2 text-xs text-content-secondary">
                    <div className="flex items-start justify-between gap-3">
                      <span className="font-medium text-content">章纲与项目设定</span>
                      <span>{genTarget.chapter.chapter_outline_id ? '已关联章纲' : '未关联章纲'}</span>
                    </div>
                    <div className="flex items-start justify-between gap-3">
                      <span className="font-medium text-content">前文承接</span>
                      <span>{completedPreviousChapters.length > 0 ? `已纳入 ${completedPreviousChapters.length} 章前文` : '首章或暂无可参考前文'}</span>
                    </div>
                    {previousChapterPreview.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {previousChapterPreview.map((chapter) => (
                          <span key={chapter.id} className="border border-surface-border bg-white/80 px-2 py-0.5 text-[11px] text-content-secondary">
                            第 {chapter.chapter_number} 章：{chapter.title}
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="flex items-start justify-between gap-3">
                      <span className="font-medium text-content">关联剧情卡片</span>
                      <span>{loadingCards ? '加载中…' : relatedCards.length > 0 ? `${relatedCards.length} 张` : '暂无关联卡片'}</span>
                    </div>
                    {relatedCardPreview.length > 0 && (
                      <div className="space-y-1.5">
                        {relatedCardPreview.map((card) => (
                          <div key={card.id} className="border border-surface-border bg-white/80 px-3 py-2">
                            <div className="text-[11px] font-medium text-content">{card.title}</div>
                            <div className="mt-0.5 line-clamp-2 text-[11px] text-content-tertiary">{card.content || '无卡片描述'}</div>
                          </div>
                        ))}
                      </div>
                    )}
                    <div className="flex items-start justify-between gap-3">
                      <span className="font-medium text-content">MCP 外部参考</span>
                      <span>
                        {genConfig.enable_mcp
                          ? genConfig.selected_plugins.length > 0
                            ? `已选 ${genConfig.selected_plugins.length} 个插件`
                            : '已启用，使用默认检索策略'
                          : '未启用'}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
              <div className="hh-modal-foot">
                <button onClick={closeGenerateModal} className="hh-btn-ghost">
                  取消
                </button>
                <button onClick={confirmGenerate} className="hh-btn-primary">
                  <Zap className="h-4 w-4" />
                  开始生成
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}

      {/* 批量生成弹窗 */}
      {showBatchModal &&
        createPortal(
          <div className="hh-modal-mask">
            <div className="hh-modal max-w-[460px]" role="dialog" aria-modal="true">
              <div className="hh-modal-head">
                <div>
                  <p className="hh-eyebrow">批量</p>
                  <h2 className="mt-2 text-xl font-semibold tracking-tight text-content">批量生成</h2>
                  <p className="mt-1 text-sm text-content-secondary">选择要批量生成的章节范围（按章节序号）。</p>
                </div>
                <button onClick={() => setShowBatchModal(false)} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="hh-modal-body space-y-4">
                <div className="hh-subpanel px-4 py-3 text-xs leading-6 text-content-secondary">
                  系统会按章节顺序自动串行生成，并自动展开当前章节显示流式内容与进度。已有内容的章节会自动跳过，避免覆盖现有正文。
                </div>
                <label className="flex cursor-pointer items-start gap-2 text-xs text-content-secondary">
                  <input type="checkbox" className="mt-0.5" checked={batchPauseOnCritical} onChange={(e) => setBatchPauseOnCritical(e.target.checked)} />
                  <span className="leading-5">
                    <span className="font-medium text-content">遇严重一致性问题时暂停</span>
                    （每章分析完成后检查审计结果，发现 critical 问题先停下确认，避免错误设定影响后续章节）
                  </span>
                </label>
                <div className="flex items-end gap-3">
                  <div className="flex-1">
                    <label className="hh-label">起始章节</label>
                    <input
                      type="number"
                      min={sorted.length > 0 ? sorted[0].chapter_number : 1}
                      max={batchTo}
                      value={batchFrom}
                      onChange={(e) => setBatchFrom(Number(e.target.value))}
                      className="hh-field"
                    />
                  </div>
                  <span className="pb-3 text-content-tertiary">—</span>
                  <div className="flex-1">
                    <label className="hh-label">结束章节</label>
                    <input
                      type="number"
                      min={batchFrom}
                      max={sorted.length > 0 ? sorted[sorted.length - 1].chapter_number : 1}
                      value={batchTo}
                      onChange={(e) => setBatchTo(Number(e.target.value))}
                      className="hh-field"
                    />
                  </div>
                </div>
              </div>
              <div className="hh-modal-foot">
                <button onClick={() => setShowBatchModal(false)} className="hh-btn-ghost">
                  取消
                </button>
                <button onClick={startBatchGenerate} className="hh-btn-primary">
                  <Layers className="h-4 w-4" />
                  开始生成
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}

function StatItem({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="px-5 py-4 md:px-6">
      <p className="text-xs text-content-tertiary">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-content tabular-nums">{value}</p>
    </div>
  );
}
