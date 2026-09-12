import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Plus, Pencil, Trash2, Zap, X, Loader2, RefreshCw, Layers, Search, Film, Eye, ChevronUp, Download, LayoutGrid, Sparkles, BookOpen, Fingerprint } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { useStore } from '@/store';
import { useChapterSync } from '@/store/hooks';
import { AIJobError, runAIJob, useAIJob, useAIJobsStore, useRunningAIJobs, waitForAIJob } from '@/store/aiJobsStore';
import {
  chapterApi,
  writingStyleApi,
  chapterOutlineLinkApi,
  deaiFindingRoute,
  isActionableDeaiFinding,
  isPositiveDeaiFinding,
  type ChapterWriteResult,
  type ChapterRegenerateRequest,
  type ChapterRegenerateResult,
  type DeaiFinding,
  type DeaiFindingIn,
  type DeaiPatchStats,
  type DeaiReviewResponse,
} from '@/services/api';
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

/** 去 AI 味措辞层本地统计里给用户看的几项（键名同后端 deai_metrics.METRIC_LABELS） */
const DEAI_METRIC_VIEW: Array<{ key: string; label: string; hint: string }> = [
  { key: 'sentence_len_std', label: '句长标准差', hint: '人类偏高' },
  { key: 'conjunctions_per_k', label: '连词/千字', hint: 'AI 偏高' },
  { key: 'particles_per_k', label: '语气词/千字', hint: '人类偏高' },
  { key: 'machine_phrase_clusters', label: '机器词成群', hint: '同段 ≥2 个' },
  { key: 'flat_runs', label: '句长扁平段', hint: '连续 3 句等长' },
  { key: 'contrast_frames', label: '不是…而是…', hint: '' },
];

const formatDeaiMetrics = (metrics: Record<string, number>) =>
  DEAI_METRIC_VIEW
    .filter(({ key }) => typeof metrics[key] === 'number')
    .map(({ key, label }) => `${label} ${metrics[key]}`)
    .join(' · ');

/** 补丁式改稿完成后的一句话总结：套用 / 跳过 / 字数 / 指标变化 */
const formatDeaiPatchSummary = (patch: DeaiPatchStats) => {
  const deltas = DEAI_METRIC_VIEW
    .filter(({ key }) => (patch.metrics_delta[key] ?? 0) !== 0)
    .map(({ key, label }) => `${label} ${patch.metrics_before[key]}→${patch.metrics_after[key]}`)
    .slice(0, 3);
  const chars = patch.chars_after - patch.chars_before;
  return `去 AI 味改稿：套用 ${patch.applied.length} 处，跳过 ${patch.skipped.length} 处，字数 ${chars > 0 ? '+' : ''}${chars}`
    + (deltas.length ? `；${deltas.join('，')}` : '；措辞指标无变化');
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
  const runningDeaiReviews = useRunningAIJobs(currentProject?.id, ['chapter_deai_review']);
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
  /** 弹窗里正在修订的章节（诊断任务结束回调里用，避免闭包拿到旧 genTarget） */
  const genTargetRef = useRef<{ chapter: Chapter; isRegenerate: boolean } | null>(null);
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
  // 修订弹窗页签：整章重写（分析建议 / 一致性 / 架构层诊断信号 / 自定义要求）｜去 AI 味润色（内嵌诊断 + 补丁式改稿）
  const [reviseTab, setReviseTab] = useState<'rewrite' | 'polish'>('rewrite');
  // 去 AI 味诊断（sepia）：最新报告 + 勾选的 finding 下标（润色页用 patch 路由的，重写页用 rewrite 路由的）
  const [regenDeai, setRegenDeai] = useState<DeaiReviewResponse | null>(null);
  const [regenDeaiLoading, setRegenDeaiLoading] = useState(false);
  const [selectedDeaiIdx, setSelectedDeaiIdx] = useState<Set<number>>(new Set());
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
    genTargetRef.current = null;
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

  /** 诊断 findings 里可带入修订的条目：排除人类正向标记（只展示）和引证未在原文核实到的（补丁定位不了）；
   *  route 可选过滤：patch → 润色页可勾；rewrite → 重写页作"重写方向" */
  const actionableDeaiFindings = (findings: DeaiFinding[], route?: 'patch' | 'rewrite') =>
    findings
      .map((f, i) => ({ f, i }))
      .filter(({ f }) => isActionableDeaiFinding(f) && (!route || deaiFindingRoute(f) === route));

  /** 拉最新诊断进弹窗；未过期则默认勾上全部可带入条目（两个路由都勾，各页签按 route 取自己那份） */
  const loadDeaiIntoModal = useCallback(async (chapterId: string) => {
    setRegenDeaiLoading(true);
    try {
      const res = await chapterApi.getDeaiReview(chapterId);
      if (genTargetRef.current?.chapter.id !== chapterId) return;
      setRegenDeai(res);
      setSelectedDeaiIdx(new Set(res.review && !res.stale ? actionableDeaiFindings(res.review.result.findings).map(({ i }) => i) : []));
    } catch {
      if (genTargetRef.current?.chapter.id === chapterId) setRegenDeai(null);
    } finally {
      setRegenDeaiLoading(false);
    }
  }, []);

  const openGenerateModal = useCallback(async (chapter: Chapter, isRegenerate: boolean, opts?: { tab?: 'rewrite' | 'polish' }) => {
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
      genTargetRef.current = { chapter, isRegenerate };
      setShowGenModal(true);
      loadStyles();

      // 修订闭环：重生成时加载分析建议 / 一致性问题 / 去 AI 味诊断 / 版本历史
      if (isRegenerate) {
        setReviseTab(opts?.tab ?? 'rewrite');
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
        setRegenDeai(null);
        setSelectedDeaiIdx(new Set());
        void loadDeaiIntoModal(chapter.id);
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
  }, [loadRelatedCardsForChapter, loadStyles, loadDeaiIntoModal]);

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

    // 去 AI 味诊断条目按页签分流：润色页 → patch 路由的结构化上送（后端按引证偏移做补丁定位 / 对话保护）；
    // 重写页 → rewrite 路由（架构层）的作为文字"重写方向"并入 custom_instructions
    const polish = reviseTab === 'polish';
    const deaiFindings = regenDeai?.review?.result.findings ?? [];
    const selectedDeai = Array.from(selectedDeaiIdx)
      .sort((a, b) => a - b)
      .map(i => deaiFindings[i])
      .filter((f): f is DeaiFinding => Boolean(f) && deaiFindingRoute(f) === (polish ? 'patch' : 'rewrite'));
    const deaiStructured: DeaiFindingIn[] = selectedDeai.map(f => ({
      feature: f.feature,
      evidence: f.evidence,
      fix: f.fix,
      layer: f.layer,
      severity: f.severity,
      start: f.start ?? null,
      end: f.end ?? null,
    }));
    const deaiLines = polish
      ? []
      : selectedDeai.map(f => `【去AI味·${f.layer}】${f.feature}：${f.fix || '按判据修正'}（原文：“${f.evidence}”）`);

    const mergedCustom = [customInstructions.trim(), ...issueLines, ...deaiLines].filter(Boolean).join('\n');
    const hasSuggestions = !polish && selectedIdx.length > 0;
    const hasCustom = mergedCustom.length > 0;
    const modificationSource = hasSuggestions && hasCustom
      ? 'mixed'
      : hasSuggestions
        ? 'analysis_suggestions'
        : 'custom';
    // 润色：保结构、字数不超过原文（夹到接口允许区间）
    const originalWords = genTarget?.chapter.word_count ?? genConfig.target_word_count;
    const deaiWordCount = Math.min(10000, Math.max(500, originalWords));

    return {
      modification_source: modificationSource,
      selected_suggestion_indices: hasSuggestions ? selectedIdx : undefined,
      custom_instructions: hasCustom ? mergedCustom : undefined,
      preserve_elements: {
        preserve_structure: polish || preserveStructure,
        preserve_dialogues: [],
        preserve_plot_points: [],
        preserve_character_traits: preserveTraits,
      },
      style_id: polish ? undefined : genConfig.style_id,
      target_word_count: polish ? deaiWordCount : genConfig.target_word_count,
      save_as_version: true,
      auto_apply: autoApply,
      deai_mode: polish,
      deai_findings: polish ? deaiStructured : undefined,
      version_note: polish ? '去 AI 味润色' : undefined,
      // R8：整章重写支持拆书参考包（仅 enabled 时传）；润色不带
      ...(!polish && genRefPack.enabled ? {
        pack_ids: genRefPack.packIds.length > 0 ? genRefPack.packIds : undefined,
        dimensions: genRefPack.dimensions.length > 0 ? genRefPack.dimensions : undefined,
        strength: genRefPack.strength,
      } : {}),
    };
  }, [regenAnalysis, selectedSuggestionIdx, selectedIssueIdx, customInstructions, preserveStructure, preserveTraits, autoApply, genConfig, genRefPack, regenDeai, selectedDeaiIdx, reviseTab, genTarget]);

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

  /** 生成前检查：前面有「有正文但未分析（无记忆状态）」的章节则提醒用户是否继续。返回 true=继续。 */
  const confirmUnanalyzedPrevious = async (chapter: Chapter): Promise<boolean> => {
    try {
      const res = await chapterApi.generationPrecheck(chapter.id);
      if (res.count > 0) {
        return window.confirm(res.message);
      }
    } catch {
      // 预检查失败不阻断生成
    }
    return true;
  };

  const confirmGenerate = async () => {
    if (!genTarget) return;
    const { chapter, isRegenerate } = genTarget;
    // 首次生成前：前置章节若有未分析（缺记忆状态）的，提醒用户是否继续
    if (!isRegenerate && !(await confirmUnanalyzedPrevious(chapter))) return;
    const polish = isRegenerate && reviseTab === 'polish';
    const findings = regenDeai?.review?.result.findings ?? [];
    const routeSelected = (route: 'patch' | 'rewrite') =>
      Array.from(selectedDeaiIdx).filter((i) => findings[i] && deaiFindingRoute(findings[i]) === route);
    // 意图防护：没给任何修订方向时明确告知后果（重写 = 无方向整章重写；润色 = 模型自行找问题，实测效果更差）
    const noDirection = polish
      ? routeSelected('patch').length === 0
      : isRegenerate &&
        selectedSuggestionIdx.size === 0 &&
        selectedIssueIdx.size === 0 &&
        routeSelected('rewrite').length === 0 &&
        !customInstructions.trim();
    if (
      noDirection &&
      !confirm(
        polish
          ? '未勾选诊断条目：AI 将按去 AI 味协议自行找问题并做最小修改（sepia 实测：没有缺陷清单的改写效果更差）。建议先运行诊断并勾选条目。确定继续？'
          : '未勾选建议、未填写修改要求：AI 将只按章纲整体重写本章（不带针对性修订方向）。确定继续？',
      )
    ) {
      return;
    }
    // 勾选记录 = 免费的假阳性标注（哪些展示了、哪些被带入），失败不影响流程
    const reviewForFeedback = regenDeai?.review;
    if (isRegenerate && reviewForFeedback && !regenDeai?.stale) {
      const mode = polish ? 'patch' : 'rewrite';
      const candidates = actionableDeaiFindings(findings, mode).map(({ i }) => i);
      if (candidates.length > 0) {
        chapterApi
          .postDeaiReviewFeedback(chapter.id, reviewForFeedback.id, { mode, candidates, selected: routeSelected(mode) })
          .catch(() => { /* 标注丢一次无所谓 */ });
      }
    }
    const requestBody = (isRegenerate
      ? buildRegenerateRequest()
      : buildChapterGenerateRequest()) as Record<string, unknown>;
    const keepAsDraftOnly = isRegenerate && !autoApply;
    const wasDeaiPatch = polish;
    setShowGenModal(false);
    setGenCheck(null);
    setStreamDone(false);
    try {
      const result = await startStream({
        chapter,
        isRegenerate,
        requestBody,
        mode: 'single',
      });
      const patch = wasDeaiPatch ? (result as ChapterRegenerateResult | null)?.deai_patch : null;
      if (patch) {
        toast.success(formatDeaiPatchSummary(patch), { duration: 8000 });
      }
      if (keepAsDraftOnly) {
        toast.info('新稿已保存为历史版本（未覆盖正文）。可在「修订」弹窗的历史版本中应用。');
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
            ? chapterApi.regenerateChapterStream(chapter.id, requestBody as unknown as ChapterRegenerateRequest, options as SSEClientOptions<ChapterRegenerateResult>)
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

    // 批量生成前：以首个待生成章节为基准检查前置未分析章节，提醒用户是否继续
    if (!(await confirmUnanalyzedPrevious(chaptersToGenerate[0]))) return;

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
            auto_analyze: true,
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

  // ========== 5b. 去 AI 味诊断（sepia review：7 轮并行、带原文引证）：从修订弹窗「润色」页显式触发，完成后回填到弹窗 ==========
  const runDeaiReview = async (chapter: Chapter) => {
    if (!currentProject) return;
    try {
      await useAIJobsStore.getState().start({
        kind: 'chapter_deai_review',
        title: `去AI味诊断第 ${chapter.chapter_number} 章《${chapter.title}》`,
        projectId: currentProject.id,
        meta: { chapter_id: chapter.id },
        connect: (options) => chapterApi.deaiReviewStream(chapter.id, options),
        onSettled: (job) => {
          if (job.status !== 'done') return;
          if (genTargetRef.current?.chapter.id === chapter.id) {
            void loadDeaiIntoModal(chapter.id);
          } else {
            toast.success(`「${chapter.title}」去 AI 味诊断完成，打开「修订 → 去 AI 味润色」查看`);
          }
        },
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '诊断启动失败');
    }
  };

  const runningAnalysisChapterIds = new Set(
    runningAnalyses.map((j) => (typeof j.meta.chapter_id === 'string' ? j.meta.chapter_id : '')),
  );
  const runningDeaiChapterIds = new Set(
    runningDeaiReviews.map((j) => (typeof j.meta.chapter_id === 'string' ? j.meta.chapter_id : '')),
  );
  const batchRunning = batchStatus?.status === 'running';
  const isGenerating = (id: string) => streamState?.chapterId === id && !streamDone;
  const completedPreviousChapters = genCheck?.previous_chapters.filter(chapter => chapter.has_content) ?? [];
  const previousChapterPreview = completedPreviousChapters.slice(-3);
  const relatedCardPreview = relatedCards.slice(0, 3);
  const totalWords = chapters.reduce((s, c) => s + c.word_count, 0);
  const completedCount = chapters.filter((c) => c.status === 'completed').length;
  const streamBusy = !!streamState && !streamDone;
  const isPolish = Boolean(genTarget?.isRegenerate) && reviseTab === 'polish';

  // ---------- 修订弹窗两个页签共用的小块 ----------

  const toggleDeaiIdx = (i: number) =>
    setSelectedDeaiIdx((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });

  /** 一条可勾选的诊断信号（重写页的"重写方向" / 润色页的"可润色信号"共用） */
  const renderDeaiFindingCheckbox = (f: DeaiFinding, i: number) => {
    const acc = regenDeai?.acceptance?.[f.feature];
    const lowAcceptance = acc && acc.offered >= 3 && acc.selected / acc.offered < 0.34;
    return (
      <label key={i} className="flex cursor-pointer items-start gap-2 text-xs text-content-secondary hover:text-content">
        <input type="checkbox" className="mt-0.5" checked={selectedDeaiIdx.has(i)} onChange={() => toggleDeaiIdx(i)} />
        <span className="leading-5">
          <span className="mr-1 bg-surface-hover px-1 py-px text-[10px] font-medium text-content-secondary">{f.layer}</span>
          <span className={cn('mr-1 px-1 py-px text-[10px] font-medium', f.severity === 'high' ? 'bg-red-50 text-red-600' : f.severity === 'medium' ? 'bg-amber-50 text-amber-600' : 'bg-surface-hover text-content-secondary')}>
            {f.severity}
          </span>
          <span className="font-medium text-content">{f.feature}</span>
          {f.fix ? `：${f.fix}` : ''}
          {lowAcceptance && (
            <span className="ml-1 px-1 py-px text-[10px] text-content-tertiary" title={`本项目历史上这类信号你只采纳了 ${acc.selected}/${acc.offered} 次，可能是误报`}>
              常被跳过 {acc.selected}/{acc.offered}
            </span>
          )}
          {f.evidence && <span className="block text-[11px] text-content-tertiary">原文：“{f.evidence}”</span>}
        </span>
      </label>
    );
  };

  const renderAutoApplyToggle = () => (
    <label className="flex cursor-pointer items-center gap-1.5 text-xs text-content-secondary">
      <input type="checkbox" checked={autoApply} onChange={(e) => setAutoApply(e.target.checked)} />
      完成后覆盖正文（关闭则仅存为版本草稿）
    </label>
  );

  /** 版本历史：应用新稿 / 回滚原稿（重写与润色都留档在同一条历史里） */
  const renderVersionHistory = () => (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-content">历史版本</p>
      {versionLoading ? (
        <div className="flex items-center gap-2 py-1 text-xs text-content-secondary">
          <Loader2 className="h-3 w-3 animate-spin" />
          加载版本…
        </div>
      ) : versionTasks.length === 0 ? (
        <p className="text-xs text-content-tertiary">暂无历史版本（每次重写 / 润色都会自动留档）</p>
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
  );

  /** 润色页：诊断状态 / 触发 → 可润色信号（篇章 / 措辞）勾选 → 架构层去向提示 → 人味标记 / 提示 / 本地统计 */
  const renderDeaiPolishPanel = (chapter: Chapter) => {
    const reviewing = runningDeaiChapterIds.has(chapter.id);
    const runningJob = runningDeaiReviews.find((j) => j.meta.chapter_id === chapter.id);
    const review = regenDeai?.review ?? null;
    const findings = review?.result.findings ?? [];
    const patchItems = actionableDeaiFindings(findings, 'patch');
    const rewriteItems = actionableDeaiFindings(findings, 'rewrite');
    const positives = findings.filter(isPositiveDeaiFinding);
    const unverified = findings.filter((f) => !isPositiveDeaiFinding(f) && f.verified === false).length;
    const diagnoseButton = (label: string, cls: string) => (
      <button onClick={() => void runDeaiReview(chapter)} disabled={reviewing} className={cls}>
        {reviewing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Fingerprint className="h-3.5 w-3.5" />}
        {label}
      </button>
    );
    return (
      <>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-sm font-medium text-content">去 AI 味诊断</p>
            <p className="mt-1 text-xs text-content-tertiary">
              {review
                ? `${review.model_name ? `画像模型 ${review.model_name}` : ''}${review.created_at ? ` · ${new Date(review.created_at).toLocaleString('zh-CN', { hour12: false })}` : ''} · 语料参考值不是阈值；单个命中不算，成群才算`
                : '7 轮并行模型调用（架构 → 篇章 → 措辞），每轮带原文引证；只诊断不改稿。'}
            </p>
          </div>
          {review && !reviewing && diagnoseButton(regenDeai?.stale ? '重新诊断' : '再诊断一次', 'hh-chip flex items-center gap-1 px-2 py-1 text-[11px]')}
        </div>

        {reviewing ? (
          <div className="flex items-center gap-2 border border-surface-border bg-white/80 px-3 py-2 text-xs text-content-secondary">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            <span>{runningJob?.progress?.message || '诊断进行中…'}</span>
            {typeof runningJob?.progress?.pct === 'number' && <span className="ml-auto tabular-nums text-content-tertiary">{runningJob.progress.pct}%</span>}
          </div>
        ) : regenDeaiLoading ? (
          <div className="flex items-center gap-2 py-1 text-xs text-content-secondary">
            <Loader2 className="h-3 w-3 animate-spin" />
            加载诊断结果…
          </div>
        ) : !review ? (
          <div className="border border-dashed border-surface-border bg-white/60 px-3 py-4 text-center">
            <p className="text-xs text-content-secondary">本章还没有诊断。</p>
            <div className="mt-2 flex justify-center">{diagnoseButton('运行诊断（7 轮模型调用）', 'hh-btn-secondary text-xs')}</div>
          </div>
        ) : (
          <>
            {regenDeai?.stale && (
              <p className="bg-amber-50 px-2 py-1 text-[11px] font-medium text-amber-600">正文自诊断后有改动：以下引证可能对不上位置，建议重新诊断后再润色。</p>
            )}
            <p className="text-xs text-content-secondary">{review.result.summary}</p>
            {review.result.metrics && (
              <p className="text-[11px] text-content-tertiary" title="措辞层本地统计（程序按词表 / 句长算的，不经模型）；只是方向，不是阈值">
                本地统计：{formatDeaiMetrics(review.result.metrics)}
              </p>
            )}

            <div className="space-y-1.5 border-t border-brand/15 pt-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-medium text-content">可润色信号（篇章 / 措辞，勾选带入补丁改稿）</p>
                {patchItems.length > 0 && (
                  <button
                    onClick={() => {
                      const all = patchItems.every(({ i }) => selectedDeaiIdx.has(i));
                      setSelectedDeaiIdx((prev) => {
                        const next = new Set(prev);
                        patchItems.forEach(({ i }) => (all ? next.delete(i) : next.add(i)));
                        return next;
                      });
                    }}
                    className="text-[11px] text-brand hover:underline"
                  >
                    {patchItems.every(({ i }) => selectedDeaiIdx.has(i)) ? '全不选' : '全选'}
                  </button>
                )}
              </div>
              {patchItems.length === 0 ? (
                <p className="text-xs text-content-tertiary">
                  没有可补丁式修复的信号。
                  {unverified > 0 && `（${unverified} 条引证未在原文找到，已不计）`}
                </p>
              ) : (
                patchItems.map(({ f, i }) => renderDeaiFindingCheckbox(f, i))
              )}
              {unverified > 0 && patchItems.length > 0 && (
                <p className="text-[11px] text-content-tertiary">另有 {unverified} 条引证未在原文找到（模型编造或改写过头），已不计。</p>
              )}
            </div>

            {rewriteItems.length > 0 && (
              <div className="border-t border-brand/15 pt-3 text-xs text-content-secondary">
                架构层还有 {rewriteItems.length} 条（{Array.from(new Set(rewriteItems.map(({ f }) => f.feature))).slice(0, 3).join('、')}
                {rewriteItems.length > 3 ? '…' : ''}）——换词修不掉，
                <button onClick={() => setReviseTab('rewrite')} className="text-brand hover:underline">到「整章重写」里当方向处理</button>。
              </div>
            )}

            {positives.length > 0 && (
              <p className="border-t border-brand/15 pt-3 text-[11px] text-emerald-700">
                已具备的人味标记（保留）：{Array.from(new Set(positives.map((f) => f.feature))).join('、')}
              </p>
            )}
            {review.result.advisories.length > 0 && (
              <div className="space-y-0.5 text-[11px] text-content-tertiary">
                {review.result.advisories.map((a, idx) => (
                  <p key={idx}>· {a}</p>
                ))}
              </div>
            )}
            {review.result.passes.some((p) => p.error) && (
              <p className="text-[11px] text-amber-600">
                以下轮次模型输出无法解析，已跳过：{review.result.passes.filter((p) => p.error).map((p) => p.title).join('、')}
              </p>
            )}
          </>
        )}

        <p className="text-[11px] text-content-tertiary">
          润色只改勾选条目对应的位置：模型给出 find/replace，后端在原文上机械套用，没命中的字一个不变；对话引语只在被勾选条目指向时才可改；字数不超过原文。
        </p>
      </>
    );
  };

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
            const deaiReviewing = runningDeaiChapterIds.has(c.id);
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
                        title={deaiReviewing ? '修订（去 AI 味诊断进行中）' : '修订：整章重写 / 去 AI 味润色'}
                        aria-label="修订"
                      >
                        {generating || deaiReviewing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
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
                  <p className="hh-eyebrow">{genTarget.isRegenerate ? '修订' : 'AI 生成'}</p>
                  <h2 className="mt-2 truncate text-xl font-semibold tracking-tight text-content">{genTarget.chapter.title}</h2>
                  <p className="mt-1 text-sm text-content-secondary">
                    {!genTarget.isRegenerate
                      ? '选择风格与目标字数，AI 会结合章纲、前文与设定生成正文。'
                      : isPolish
                        ? '先诊断 AI 痕迹，再按勾选条目做补丁式最小改动：没命中的字一个不变，每次都留档。'
                        : '基于分析建议、诊断出的架构问题与修改要求整章重写，每次都留档。'}
                  </p>
                </div>
                <button onClick={closeGenerateModal} className="hh-icon-btn-plain -mr-2 -mt-1" aria-label="关闭">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="hh-modal-body space-y-5">
                {genTarget.isRegenerate && (
                  <div className="flex gap-1 border-b border-surface-border" role="tablist">
                    {([
                      { key: 'rewrite', label: '整章重写', icon: RefreshCw, hint: '换写法、改情节走向、修架构层问题' },
                      { key: 'polish', label: '去 AI 味润色', icon: Fingerprint, hint: '保情节保对话，只换掉机器腔' },
                    ] as const).map(({ key, label, icon: Icon, hint }) => {
                      const patchCount = key === 'polish' && regenDeai?.review && !regenDeai.stale
                        ? actionableDeaiFindings(regenDeai.review.result.findings, 'patch').length
                        : 0;
                      return (
                        <button
                          key={key}
                          role="tab"
                          aria-selected={reviseTab === key}
                          onClick={() => setReviseTab(key)}
                          title={hint}
                          className={cn(
                            '-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm transition-colors',
                            reviseTab === key ? 'border-brand font-medium text-content' : 'border-transparent text-content-secondary hover:text-content',
                          )}
                        >
                          <Icon className="h-4 w-4" />
                          {label}
                          {patchCount > 0 && <span className="bg-brand/10 px-1.5 py-px text-[10px] font-medium text-brand tabular-nums">{patchCount}</span>}
                        </button>
                      );
                    })}
                  </div>
                )}

                {!isPolish && (
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
                )}

                {!isPolish && (
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
                )}
                {!isPolish && currentProject?.id && (
                  <ReferencePackSelector
                    projectId={currentProject.id}
                    value={genRefPack}
                    onChange={setGenRefPack}
                    hint={genTarget.isRegenerate ? '让本次重写参考拆书的笔法/节奏/语料' : '让本章正文参考拆书的笔法/方法论/语料'}
                    disabledTitle="使用拆书参考包作为对标"
                  />
                )}

                {/* ===== 去 AI 味润色页签：内嵌诊断（显式触发）+ 篇章/措辞信号勾选 → 补丁式改稿 ===== */}
                {isPolish && (
                  <div className="space-y-4 border border-brand/25 bg-brand/5 p-4">
                    {renderDeaiPolishPanel(genTarget.chapter)}
                    {renderAutoApplyToggle()}
                    {renderVersionHistory()}
                  </div>
                )}

                {/* ===== 整章重写页签：分析建议 / 一致性问题 / 架构层诊断信号 / 修改要求 / 保留元素 / 版本历史 ===== */}
                {genTarget.isRegenerate && !isPolish && (
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

                    {/* 去 AI 味诊断里的架构层信号：最小改动修不了，只能在重写里当方向 */}
                    {(() => {
                      const items = regenDeai?.review ? actionableDeaiFindings(regenDeai.review.result.findings, 'rewrite') : [];
                      if (items.length === 0) return null;
                      return (
                        <div className="space-y-1.5 border-t border-brand/15 pt-3">
                          <div className="flex items-center justify-between gap-2">
                            <p className="text-xs font-medium text-content">重写方向（来自去 AI 味诊断·架构层，勾选带入）</p>
                            {regenDeai?.stale && (
                              <span className="bg-amber-50 px-1.5 py-px text-[10px] font-medium text-amber-600">正文已改动，诊断可能过期</span>
                            )}
                          </div>
                          <p className="text-[11px] text-content-tertiary">主题说破、因果太整齐、结尾三件套这类问题靠换词修不掉，需要重写时一并处理。</p>
                          {items.map(({ f, i }) => renderDeaiFindingCheckbox(f, i))}
                        </div>
                      );
                    })()}

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
                      {renderAutoApplyToggle()}
                    </div>

                    {renderVersionHistory()}
                  </div>
                )}

                {!isPolish && (
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
                )}
              </div>
              <div className="hh-modal-foot">
                <button onClick={closeGenerateModal} className="hh-btn-ghost">
                  取消
                </button>
                <button
                  onClick={confirmGenerate}
                  disabled={isPolish && (!regenDeai?.review || runningDeaiChapterIds.has(genTarget.chapter.id))}
                  title={isPolish && !regenDeai?.review ? '先运行诊断' : undefined}
                  className="hh-btn-primary"
                >
                  {isPolish ? <Fingerprint className="h-4 w-4" /> : <Zap className="h-4 w-4" />}
                  {isPolish ? '开始润色' : genTarget.isRegenerate ? '开始重写' : '开始生成'}
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
