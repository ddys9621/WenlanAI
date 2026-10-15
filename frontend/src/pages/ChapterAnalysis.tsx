/**
 * 章节写作（原「章节管理」与「剧情分析」两页合并；版式参考岚笺写作台）。
 *
 * 满高工作台：左侧章节目录（搜索 / 新建 / 从章纲同步 / 批量生成；选中行可 生成候选稿 / 去 AI 味重写 / 场景生成 / 分析 / 删除，
 * 并标出待审候选稿、章纲已改、章纲待确认）；右侧稿纸：正文 | 候选稿 | 历史版本 三个界面——正文直接码字（自动保存、AI 行内补全、
 * 专注模式），旁边可开记忆标注 / 叙事状态面板；正文任务运行时就地显示流式面板。
 * AI 输出一律先成候选稿，作者采用才写入正文（参考岚笺）。任务编排在 useChapterWriteJobs，页面只管选中章节与阅读态。
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  BookOpen, Download, FileCheck2, Film, History, Layers, Loader2, PanelRightClose, PanelRightOpen, Plus, RefreshCw, Search,
  Trash2, Zap,
} from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { useStore } from '@/store';
import { useChapterSync } from '@/store/hooks';
import { chapterApi, type ChapterAnnotationsResponse } from '@/services/api';
import { normalizeAnalysisData, type NormalizedAnalysisData } from '@/utils/chapterAnalysis';
import type { MemoryAnnotation } from '@/utils/annotationSegments';
import { readDomSelection, resolveSelection, type TextSelection } from '@/utils/selectionOffsets';
import type { Chapter, ChapterCanGenerateResponse, ChapterGenerateRequest } from '@/types';
import { OTHER_JOB_KINDS, WRITE_JOB_KINDS, useChapterWriteJobs } from '@/hooks/useChapterWriteJobs';
import { AIJobBanner } from '@/components/ai-job/AIJobBanner';
import AnnotatedText from '@/components/AnnotatedText';
import MemorySidebar from '@/components/MemorySidebar';
import { SceneGenerator } from '@/components/SceneGenerator';
import { useAssistantDataChange, useAssistantDetail } from '@/hooks/useAssistantPage';
import { useAssistantStore, type AssistantDataChange } from '@/store/assistantStore';
import { BatchGenerateModal } from '@/components/chapters/BatchGenerateModal';
import { CandidatePanel } from '@/components/chapters/CandidatePanel';
import { ChapterEditModal } from '@/components/chapters/ChapterEditModal';
import { ChapterGenerateModal } from '@/components/chapters/ChapterGenerateModal';
import { ChapterStreamPanel } from '@/components/chapters/ChapterStreamPanel';
import { ChapterWritingPane, type ChapterWritingPaneHandle } from '@/components/chapters/ChapterWritingPane';
import { DeaiRewriteModal, type RewriteMode } from '@/components/chapters/DeaiRewriteModal';
import { NarrativeStatePanel } from '@/components/chapters/NarrativeStatePanel';
import { VersionHistoryPanel } from '@/components/chapters/VersionHistoryPanel';

type SidebarTab = 'memory' | 'narrative';
type ReaderTab = 'content' | 'candidates' | 'versions';

export default function ChapterAnalysis() {
  const { currentProject, chapters } = useStore();
  const { refreshChapters, deleteChapter } = useChapterSync();
  const projectId = currentProject?.id;
  const sorted = useMemo(() => [...chapters].sort((a, b) => a.chapter_number - b.chapter_number), [chapters]);

  // ---------- 阅读区：选中章节 / 标注 / 叙事状态 ----------
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Chapter | null>(null);
  const [annotations, setAnnotations] = useState<ChapterAnnotationsResponse | null>(null);
  const [narrative, setNarrative] = useState<NormalizedAnalysisData | null>(null);
  const [narrativeLoading, setNarrativeLoading] = useState(false);
  const [contentLoading, setContentLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>('memory');
  const [activeAnnotationId, setActiveAnnotationId] = useState<string>();
  const [scrollToContent, setScrollToContent] = useState<string>();
  const [scrollToSidebar, setScrollToSidebar] = useState<string>();
  const [readerTab, setReaderTab] = useState<ReaderTab>('content');
  const [focusCandidateId, setFocusCandidateId] = useState<string | null>(null);
  const [candidatesVersion, setCandidatesVersion] = useState(0);
  const [selection, setSelection] = useState<TextSelection | null>(null);
  const [search, setSearch] = useState('');
  const manuscriptRef = useRef<HTMLDivElement>(null);
  const paneRef = useRef<ChapterWritingPaneHandle>(null);
  const [searchParams, setSearchParams] = useSearchParams();

  const loadSelected = useCallback(async (id: string) => {
    setContentLoading(true);
    try {
      const [ch, ann] = await Promise.all([chapterApi.getChapter(id), chapterApi.getAnnotations(id).catch(() => null)]);
      setDetail(ch);
      setAnnotations(ann);
      setNarrativeLoading(true);
      chapterApi.getAnalysis(id)
        .then((d) => setNarrative(normalizeAnalysisData(d as unknown as Record<string, unknown>)))
        .catch(() => setNarrative(null))
        .finally(() => setNarrativeLoading(false));
    } catch {
      toast.error('加载章节内容失败');
    } finally {
      setContentLoading(false);
    }
  }, []);

  const selectChapter = useCallback((id: string) => {
    setSelectedId(id);
    setActiveAnnotationId(undefined);
    setSelection(null);
    setReaderTab('content');
    setFocusCandidateId(null);
    void loadSelected(id);
  }, [loadSelected]);

  const clearSelection = useCallback(() => {
    setSelectedId(null);
    setDetail(null);
    setAnnotations(null);
    setNarrative(null);
  }, []);

  useEffect(() => {
    clearSelection();
    if (projectId) void refreshChapters();
  }, [projectId, refreshChapters, clearSelection]);

  // 首次：默认选第一个有正文的章（从智能助笔 / 核对清单跳来时带 ?chapter=，由下面的深链处理）
  useEffect(() => {
    if (selectedId || sorted.length === 0 || searchParams.get('chapter')) return;
    const first = sorted.find((c) => c.word_count > 0) ?? sorted[0];
    selectChapter(first.id);
  }, [sorted, selectedId, selectChapter, searchParams]);

  // 深链：?chapter=<id>&tab=candidates&candidate=<id>（智能助笔的候选稿、核对清单）；处理完清掉参数
  useEffect(() => {
    const chapterId = searchParams.get('chapter');
    if (!chapterId || !sorted.some((c) => c.id === chapterId)) return;
    const tab = searchParams.get('tab');
    selectChapter(chapterId);
    if (tab === 'candidates' || tab === 'versions') setReaderTab(tab);
    setFocusCandidateId(searchParams.get('candidate'));
    setSearchParams({}, { replace: true });
  }, [searchParams, sorted, selectChapter, setSearchParams]);

  // 全局智能助笔：登记作者正在看的章节与选中的正文（只作参考上下文）
  useAssistantDetail(detail ? {
    label: `章节写作 · 第 ${detail.chapter_number} 章《${detail.title}》`,
    chapter_id: detail.id,
    selection: selection && selection.text ? { start: selection.start, end: selection.end, text: selection.text } : null,
  } : null);

  // 助笔给本章产生了候选稿：刷新候选稿列表与章节列表里的待审数
  const onAssistantData = useCallback((change: AssistantDataChange) => {
    if (change.entity !== 'chapter_candidate') return;
    void refreshChapters();
    if (change.chapterId && change.chapterId === selectedId) setCandidatesVersion((v) => v + 1);
  }, [refreshChapters, selectedId]);
  useAssistantDataChange(onAssistantData);

  // ---------- 正文任务 ----------
  const onChapterWritten = useCallback((id: string) => {
    if (id === selectedId) void loadSelected(id);
  }, [selectedId, loadSelected]);

  const openCandidate = useCallback((chapterId: string, candidateId: string) => {
    if (chapterId !== selectedId) {
      setSelectedId(chapterId);
      setSelection(null);
      void loadSelected(chapterId);
    }
    setFocusCandidateId(candidateId);
    setReaderTab('candidates');
  }, [selectedId, loadSelected]);

  const jobs = useChapterWriteJobs({
    projectId,
    chapters: sorted,
    refreshChapters,
    onChapterWritten,
    onCandidateReady: (chapterId, candidateId) => {
      jobs.closeStreamPanel();
      openCandidate(chapterId, candidateId);
    },
  });
  const streamChapterId = jobs.streamState?.chapterId;

  // 正文任务开始 / 批量切章时自动切到该章
  useEffect(() => {
    if (streamChapterId && streamChapterId !== selectedId) selectChapter(streamChapterId);
  }, [streamChapterId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------- 弹窗 ----------
  const [creating, setCreating] = useState(false);
  const [genTarget, setGenTarget] = useState<{ chapter: Chapter; check: ChapterCanGenerateResponse } | null>(null);
  const [rewriteTarget, setRewriteTarget] = useState<Chapter | null>(null);
  const [showBatch, setShowBatch] = useState(false);
  const [sceneTarget, setSceneTarget] = useState<{ outlineId: string; title: string } | null>(null);
  const [syncing, setSyncing] = useState(false);

  const handleSyncFromOutlines = async () => {
    if (!projectId) return;
    setSyncing(true);
    try {
      const res = await chapterApi.syncFromOutlines(projectId);
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

  const handleDelete = async (c: Chapter) => {
    if (!confirm(`确定删除章节「${c.title}」吗？`)) return;
    try {
      await deleteChapter(c.id);
      if (c.id === selectedId) clearSelection();
      toast.success('章节已删除');
    } catch {
      toast.error('删除失败');
    }
  };

  const openGenerate = async (chapter: Chapter) => {
    try {
      const check = await chapterApi.checkCanGenerate(chapter.id);
      if (!check.can_generate) {
        toast.error(check.reason || '当前不满足生成条件');
        return;
      }
      setGenTarget({ chapter, check });
      void jobs.loadRelatedCardsForChapter(chapter);
    } catch {
      toast.error('生成条件检查失败');
    }
  };

  const confirmGenerate = async (body: ChapterGenerateRequest) => {
    if (!genTarget) return;
    const { chapter } = genTarget;
    // 首次生成前：前置章节若有未分析（缺记忆状态）的，提醒用户是否继续
    if (!(await jobs.confirmUnanalyzedPrevious(chapter))) return;
    setGenTarget(null);
    void jobs.startStream({ chapter, kind: 'chapter_generate', requestBody: body, mode: 'single' }).catch(() => { /* 已 toast / 已停止 */ });
  };

  const confirmRewrite = async (promptIds: string[], mode: RewriteMode) => {
    if (!rewriteTarget) return;
    const chapter = rewriteTarget;
    setRewriteTarget(null);
    // 重写的是已保存的正文：先把编辑器里没保存的修改存上
    await paneRef.current?.flush();
    void jobs.startStream({ chapter, kind: 'chapter_regenerate', requestBody: { prompt_ids: promptIds, mode }, mode: 'single' }).catch(() => { /* 已 toast / 已停止 */ });
  };

  /** 标注视图里选中文字 → 记下与正文逐字一致的位置，交给智能助笔改写 / 润色 / 追问 */
  const captureSelection = () => {
    if (!detail?.content) return;
    const raw = readDomSelection(manuscriptRef.current);
    if (!raw) return;
    const resolved = resolveSelection(detail.content, raw.text, raw.startHint);
    if (resolved) setSelection(resolved);
  };

  const afterContentReplaced = () => {
    void refreshChapters();
    if (selectedId) void loadSelected(selectedId);
    setSelection(null);
    setReaderTab('content');
  };

  // 编辑器自动保存 / 改标题：只把字数、状态、标题同步给章节列表（列表不带正文）
  const onContentSaved = useCallback((saved: Chapter) => {
    setDetail((d) => (d && d.id === saved.id
      ? { ...d, content: saved.content, content_hash: saved.content_hash, word_count: saved.word_count, status: saved.status, updated_at: saved.updated_at }
      : d));
    useStore.getState().updateChapter(saved.id, { word_count: saved.word_count, status: saved.status });
  }, []);

  const onTitleSaved = useCallback((saved: Chapter) => {
    setDetail((d) => (d && d.id === saved.id ? { ...d, title: saved.title } : d));
    useStore.getState().updateChapter(saved.id, { title: saved.title });
  }, []);

  const handleAnnotationClick = (annotation: MemoryAnnotation, source: 'content' | 'sidebar') => {
    setActiveAnnotationId(annotation.id);
    if (source === 'content') {
      setSidebarTab('memory');
      setSidebarOpen(true);
      setScrollToSidebar(annotation.id);
      setTimeout(() => setScrollToSidebar(undefined), 100);
    } else {
      setScrollToContent(annotation.id);
      setTimeout(() => setScrollToContent(undefined), 100);
    }
  };

  // ---------- 派生 ----------
  const totalWords = chapters.reduce((s, c) => s + c.word_count, 0);
  const pendingCandidates = chapters.reduce((s, c) => s + (c.pending_candidates ?? 0), 0);
  const hasAnnotations = Boolean(annotations && annotations.annotations.length > 0);
  const streamPanelVisible = Boolean(jobs.streamState && !jobs.panelHidden && jobs.streamState.chapterId === selectedId);
  const { batchStatus, batchRunning, streamBusy } = jobs;
  const selectedSummary = sorted.find((c) => c.id === selectedId);
  const keyword = search.trim();
  const visibleChapters = keyword
    ? sorted.filter((c) => c.title.includes(keyword) || String(c.chapter_number) === keyword.replace(/^第|章$/g, ''))
    : sorted;
  const detailReady = Boolean(detail && detail.id === selectedId);

  const readerTabs = (
    <div className="flex items-center gap-1.5">
      <div className="flex items-center gap-0.5 rounded-sm border border-surface-border bg-surface p-0.5">
        {([
          ['content', '正文', BookOpen],
          ['candidates', `候选稿${(selectedSummary?.pending_candidates ?? 0) > 0 ? ` ${selectedSummary?.pending_candidates}` : ''}`, FileCheck2],
          ['versions', '历史版本', History],
        ] as const).map(([key, label, Icon]) => (
          <button
            key={key}
            onClick={() => setReaderTab(key)}
            className={cn(
              'flex items-center gap-1 rounded-sm px-2 py-1 text-xs font-medium',
              readerTab === key ? 'bg-brand text-white' : 'text-content-secondary hover:text-content',
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>
      {readerTab === 'content' && (
        <button
          onClick={() => setSidebarOpen((v) => !v)}
          className={cn('lj-tool w-8 justify-center px-0', sidebarOpen && 'lj-tool--active')}
          title={sidebarOpen ? '收起记忆标注 / 叙事状态' : '记忆标注 / 叙事状态'}
          aria-label="分析面板"
        >
          {sidebarOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
        </button>
      )}
    </div>
  );

  const annotatedView = hasAnnotations && annotations && detail ? (
    <div onMouseUp={captureSelection} onKeyUp={captureSelection}>
      <p className="mb-3 font-sans text-xs text-content-tertiary">
        只读标注视图 · 共 {annotations.summary.total_annotations} 个标注：
        {annotations.summary.hooks > 0 && ` 🎣${annotations.summary.hooks}个钩子`}
        {annotations.summary.foreshadows > 0 && ` 🌟${annotations.summary.foreshadows}个伏笔`}
        {annotations.summary.plot_points > 0 && ` 💎${annotations.summary.plot_points}个情节点`}
        {annotations.summary.character_events > 0 && ` 👤${annotations.summary.character_events}个角色事件`}
      </p>
      <div ref={manuscriptRef} data-manuscript>
        <AnnotatedText
          content={detail.content || ''}
          annotations={annotations.annotations}
          onAnnotationClick={(a) => handleAnnotationClick(a, 'content')}
          activeAnnotationId={activeAnnotationId}
          scrollToAnnotation={scrollToContent}
          style={{ lineHeight: 2, fontSize: 16 }}
        />
      </div>
    </div>
  ) : undefined;

  return (
    <div className="flex animate-fade-in flex-col gap-3 lg:h-[calc(100dvh-6.75rem)]">
      {/* 批量生成进度 */}
      {batchStatus && (
        <section className="hh-panel shrink-0 space-y-2.5 px-4 py-3">
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
              <button onClick={jobs.cancelBatch} className="hh-btn-ghost hh-btn-sm text-red-500 hover:bg-red-50 hover:text-red-600">
                取消
              </button>
            )}
          </div>
          <div className="hh-progress h-2">
            <div
              className={cn('hh-progress-bar', batchStatus.status === 'completed' && 'bg-emerald-500', batchStatus.status === 'error' && 'bg-red-500')}
              style={{ width: `${Math.min(batchStatus.progress, 100)}%` }}
            />
          </div>
        </section>
      )}

      {/* 后台 AI 任务横幅：分析 / 场景 / 仿写常驻；正文任务在面板不可见（后台运行 / 看别的章）时也进横幅 */}
      <AIJobBanner projectId={projectId} kinds={streamPanelVisible ? OTHER_JOB_KINDS : [...WRITE_JOB_KINDS, ...OTHER_JOB_KINDS]} />

      {sorted.length === 0 ? (
        <section className="hh-panel flex flex-col items-center px-6 py-14 text-center">
          <span className="flex h-14 w-14 items-center justify-center bg-brand/10 text-brand">
            <BookOpen className="h-7 w-7" />
          </span>
          <h2 className="mt-5 text-xl font-semibold tracking-tight text-content">还没有章节</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">
            「从章纲同步」把章纲一键转成章节骨架，或「新建章节」直接开写。
          </p>
          <div className="mt-6 flex gap-2">
            <button onClick={() => void handleSyncFromOutlines()} disabled={syncing} className="hh-btn-secondary">
              {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              从章纲同步
            </button>
            <button onClick={() => setCreating(true)} className="hh-btn-primary">
              <Plus className="h-4 w-4" />
              新建章节
            </button>
          </div>
        </section>
      ) : (
        <div className="grid min-h-0 flex-1 overflow-hidden rounded border border-surface-border bg-white lg:grid-cols-[272px_minmax(0,1fr)]">
          {/* 左栏：章节目录 */}
          <aside className="flex min-h-0 flex-col bg-surface-paper max-lg:max-h-[45vh] max-lg:border-b lg:border-r lg:border-surface-border">
            <div className="flex shrink-0 items-center gap-1.5 border-b border-surface-border px-2.5 py-2.5">
              <div className="relative min-w-0 flex-1">
                <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-content-tertiary" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="搜索章节"
                  aria-label="搜索章节"
                  className="h-8 w-full pl-7 pr-2 text-xs"
                />
              </div>
              <ExplorerButton title="新建章节" onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" />
              </ExplorerButton>
              <ExplorerButton title="从章纲同步：把章纲一键转成章节骨架" onClick={() => void handleSyncFromOutlines()} disabled={syncing}>
                {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              </ExplorerButton>
              <ExplorerButton title="批量生成候选稿（服务端串行，关掉浏览器也不停）" onClick={() => setShowBatch(true)} disabled={batchRunning || streamBusy}>
                <Layers className="h-4 w-4" />
              </ExplorerButton>
            </div>
            <p className="shrink-0 px-3 pb-1.5 pt-2 text-[11px] text-content-tertiary tabular-nums">
              共 {chapters.length} 章 · {totalWords.toLocaleString()} 字{pendingCandidates > 0 ? ` · 待审候选稿 ${pendingCandidates}` : ''}
            </p>
            <div className="min-h-0 flex-1 overflow-y-auto pb-2">
              {visibleChapters.map((c) => {
                const isSelected = c.id === selectedId;
                const generating = jobs.isGenerating(c.id);
                const currentBatchChapter = batchRunning && batchStatus?.currentChapterId === c.id;
                const analyzing = jobs.analyzingChapterIds.has(c.id);
                const canWrite = !generating && !batchRunning && !streamBusy;
                const flagged = (c.pending_candidates ?? 0) > 0 || c.outline_changed || c.outline_review_status === 'draft' || c.outline_upstream_stale;
                return (
                  <div
                    key={c.id}
                    onClick={() => selectChapter(c.id)}
                    className={cn(
                      'group cursor-pointer px-3 py-2 transition-colors',
                      isSelected ? 'bg-gold-50 shadow-[inset_3px_0_#e99a35]' : 'hover:bg-surface-hover',
                      currentBatchChapter && !isSelected && 'bg-brand-50',
                    )}
                  >
                    <div className="flex items-baseline gap-2">
                      <span className="shrink-0 text-[11px] text-content-tertiary tabular-nums">第{c.chapter_number}章</span>
                      <span className={cn('min-w-0 flex-1 truncate text-[13px] text-content', isSelected && 'font-medium')}>{c.title}</span>
                      <span className="shrink-0 text-[11px] text-content-tertiary tabular-nums">
                        {generating ? <Loader2 className="inline h-3 w-3 animate-spin text-brand" /> : c.word_count > 0 ? `${c.word_count.toLocaleString()}字` : '空'}
                      </span>
                    </div>
                    {(flagged || currentBatchChapter) && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {currentBatchChapter && <span className="lj-badge lj-badge--candidate">串行生成中</span>}
                        {(c.pending_candidates ?? 0) > 0 && <span className="lj-badge lj-badge--candidate">候选稿 {c.pending_candidates}</span>}
                        {c.outline_changed && <span className="lj-badge lj-badge--stale" title="正文写完后章纲又改过">章纲已改</span>}
                        {c.outline_upstream_stale && <span className="lj-badge lj-badge--stale" title="卷纲 / 总纲改过">上游已改</span>}
                        {c.outline_review_status === 'draft' && <span className="lj-badge lj-badge--draft" title="AI 草拟的章纲，尚未确认">章纲待确认</span>}
                      </div>
                    )}
                    <div className={cn('mt-1 items-center gap-0.5', isSelected ? 'flex' : 'hidden group-hover:flex')} onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => void openGenerate(c)}
                        disabled={!canWrite}
                        className="hh-icon-btn-plain h-7 w-7 hover:text-brand"
                        title={c.word_count > 0 ? 'AI 重新写一稿（存为候选稿，不会覆盖现有正文）' : 'AI 生成候选稿'}
                        aria-label="AI 生成候选稿"
                      >
                        {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
                      </button>
                      {c.word_count > 0 && (
                        <button onClick={() => setRewriteTarget(c)} disabled={!canWrite} className="hh-icon-btn-plain h-7 w-7 hover:text-brand" title="去 AI 味重写（结果存为候选稿）" aria-label="去 AI 味重写">
                          <RefreshCw className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {c.chapter_outline_id && (
                        <button onClick={() => setSceneTarget({ outlineId: c.chapter_outline_id!, title: c.title })} className="hh-icon-btn-plain h-7 w-7 hover:text-brand" title="场景生成" aria-label="场景生成">
                          <Film className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {c.word_count > 0 && (
                        <button onClick={() => void jobs.handleAnalyze(c)} disabled={analyzing} className="hh-icon-btn-plain h-7 w-7 hover:text-brand" title="分析（提取记忆 / 叙事状态 / 一致性）" aria-label="分析">
                          {analyzing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
                        </button>
                      )}
                      <button onClick={() => void handleDelete(c)} className="hh-icon-btn-plain ml-auto h-7 w-7 hover:text-cinnabar" title="删除" aria-label="删除">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })}
              {visibleChapters.length === 0 && <p className="px-3 py-6 text-center text-xs text-content-tertiary">没有匹配的章节</p>}
            </div>
          </aside>

          {/* 右栏：流式面板 / 稿纸 */}
          <section className="flex min-h-0 min-w-0 flex-col max-lg:h-[80vh]">
            {streamPanelVisible && jobs.streamState ? (
              <div className="min-h-0 flex-1 overflow-y-auto p-3">
                <ChapterStreamPanel
                  streamState={jobs.streamState}
                  streamJob={jobs.streamJob}
                  streamDone={jobs.streamDone}
                  batchRunning={batchRunning}
                  showProcess={jobs.showProcess}
                  onToggleProcess={() => jobs.setShowProcess((v) => !v)}
                  onHide={jobs.hideStreamPanel}
                  onCancel={jobs.cancelStream}
                  onClose={jobs.closeStreamPanel}
                  relatedCards={jobs.relatedCards}
                  loadingCards={jobs.loadingCards}
                  onReviewCandidate={() => {
                    const id = jobs.streamState?.chapterId;
                    jobs.closeStreamPanel();
                    if (id) {
                      if (id !== selectedId) selectChapter(id);
                      setReaderTab('candidates');
                    }
                  }}
                />
              </div>
            ) : !selectedId || !detailReady || !detail ? (
              <div className="flex flex-1 items-center justify-center text-sm text-content-tertiary">
                {contentLoading ? <Loader2 className="h-5 w-5 animate-spin text-brand" /> : '从左侧选择一个章节'}
              </div>
            ) : readerTab === 'content' && projectId ? (
              <div className="flex min-h-0 flex-1">
                <ChapterWritingPane
                  ref={paneRef}
                  projectId={projectId}
                  chapter={detail}
                  bookWords={totalWords}
                  headerRight={readerTabs}
                  readView={annotatedView}
                  onSaved={onContentSaved}
                  onTitleSaved={onTitleSaved}
                  onSelection={setSelection}
                  onOpenHistory={() => setReaderTab('versions')}
                  onAskAssistant={() => useAssistantStore.getState().compose('')}
                />
                {/* 侧栏：记忆标注 / 叙事状态（智能助笔在项目右侧的全局抽屉里） */}
                {sidebarOpen && (
                  <aside className="flex w-[320px] shrink-0 flex-col border-l border-surface-border bg-white max-xl:hidden">
                    <div className="flex shrink-0 gap-1 border-b border-surface-border px-3 py-2.5">
                      {([['memory', '记忆标注'], ['narrative', '叙事状态']] as const).map(([key, label]) => (
                        <button key={key} onClick={() => setSidebarTab(key)} className={cn('hh-chip px-3 py-1 text-xs', sidebarTab === key && 'hh-chip--active')}>
                          {label}
                        </button>
                      ))}
                    </div>
                    <div className="min-h-0 flex-1 overflow-y-auto p-3">
                      {sidebarTab === 'memory' ? (
                        hasAnnotations && annotations ? (
                          <MemorySidebar
                            annotations={annotations.annotations}
                            activeAnnotationId={activeAnnotationId}
                            onAnnotationClick={(a) => handleAnnotationClick(a, 'sidebar')}
                            scrollToAnnotation={scrollToSidebar}
                          />
                        ) : (
                          <p className="py-8 text-center text-xs leading-6 text-content-tertiary">
                            暂无标注数据。点左侧 🔍 分析本章后，可在「标注」视图里高亮钩子 / 伏笔 / 情节点。
                          </p>
                        )
                      ) : (
                        <NarrativeStatePanel data={narrative} loading={narrativeLoading} />
                      )}
                    </div>
                  </aside>
                )}
              </div>
            ) : (
              <>
                <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-surface-border bg-white px-3 py-1.5">
                  <span className="truncate font-serif text-[15px] font-semibold text-content">
                    第 {detail.chapter_number} 章<span className="ml-2">{detail.title}</span>
                  </span>
                  {readerTabs}
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto">
                  {readerTab === 'candidates' ? (
                    <CandidatePanel
                      key={`${detail.id}-${candidatesVersion}`}
                      chapter={detail}
                      focusCandidateId={focusCandidateId}
                      onAdopted={afterContentReplaced}
                      onChanged={() => void refreshChapters()}
                    />
                  ) : (
                    <VersionHistoryPanel chapter={detail} onRestored={afterContentReplaced} />
                  )}
                </div>
              </>
            )}
          </section>
        </div>
      )}

      {/* 弹窗 */}
      {projectId && (
        <ChapterEditModal
          open={creating}
          projectId={projectId}
          defaultChapterNumber={sorted.length > 0 ? sorted[sorted.length - 1].chapter_number + 1 : 1}
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            void refreshChapters();
            selectChapter(id);
          }}
        />
      )}
      {projectId && genTarget && (
        <ChapterGenerateModal
          open
          projectId={projectId}
          chapter={genTarget.chapter}
          genCheck={genTarget.check}
          relatedCards={jobs.relatedCards}
          loadingCards={jobs.loadingCards}
          onClose={() => setGenTarget(null)}
          onConfirm={(body) => void confirmGenerate(body)}
        />
      )}
      {projectId && rewriteTarget && (
        <DeaiRewriteModal
          open
          projectId={projectId}
          chapter={rewriteTarget}
          busy={streamBusy || batchRunning}
          onClose={() => setRewriteTarget(null)}
          onConfirm={(promptIds, mode) => void confirmRewrite(promptIds, mode)}
        />
      )}
      <BatchGenerateModal
        open={showBatch}
        chapters={sorted}
        onClose={() => setShowBatch(false)}
        onStart={(args) => {
          setShowBatch(false);
          void jobs.startBatch(args);
        }}
      />
      {sceneTarget && (
        <SceneGenerator
          chapterOutlineId={sceneTarget.outlineId}
          chapterTitle={sceneTarget.title}
          projectId={projectId}
          onClose={() => setSceneTarget(null)}
          onComplete={() => void refreshChapters()}
        />
      )}
    </div>
  );
}

function ExplorerButton({ title, onClick, disabled, children }: { title: string; onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={title}
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded border border-surface-border bg-white text-content-secondary hover:border-brand/50 hover:text-brand disabled:cursor-not-allowed disabled:opacity-50"
    >
      {children}
    </button>
  );
}
