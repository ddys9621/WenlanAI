/**
 * 剧情分析（章节与正文）：原「章节管理」与「剧情分析」两页合并。
 *
 * 左侧章节列表：新建 / 编辑 / 生成 / 去 AI 味重写 / 场景生成 / 分析 / 删除；
 * 右侧阅读区：正文（带记忆标注）+ 记忆标注 / 叙事状态侧栏；正文任务运行时就地显示流式面板。
 * 任务编排在 useChapterWriteJobs，页面只管选中章节与阅读态。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BookOpen, ChevronLeft, ChevronRight, Copy, Download, Film, Layers, Loader2, PanelRightClose, PanelRightOpen,
  Pencil, Plus, RefreshCw, Search, Trash2, Zap,
} from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { useStore } from '@/store';
import { useChapterSync } from '@/store/hooks';
import { chapterApi, type ChapterAnnotationsResponse } from '@/services/api';
import { normalizeAnalysisData, type NormalizedAnalysisData } from '@/utils/chapterAnalysis';
import type { MemoryAnnotation } from '@/utils/annotationSegments';
import type { Chapter, ChapterCanGenerateResponse, ChapterGenerateRequest } from '@/types';
import { OTHER_JOB_KINDS, WRITE_JOB_KINDS, useChapterWriteJobs } from '@/hooks/useChapterWriteJobs';
import { AIJobBanner } from '@/components/ai-job/AIJobBanner';
import AnnotatedText from '@/components/AnnotatedText';
import MemorySidebar from '@/components/MemorySidebar';
import { SceneGenerator } from '@/components/SceneGenerator';
import { BatchGenerateModal } from '@/components/chapters/BatchGenerateModal';
import { ChapterEditModal } from '@/components/chapters/ChapterEditModal';
import { ChapterGenerateModal } from '@/components/chapters/ChapterGenerateModal';
import { ChapterStreamPanel } from '@/components/chapters/ChapterStreamPanel';
import { DeaiRewriteModal } from '@/components/chapters/DeaiRewriteModal';
import { NarrativeStatePanel } from '@/components/chapters/NarrativeStatePanel';

const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  draft: { label: '草稿', cls: 'bg-gray-100 text-gray-500' },
  writing: { label: '生成中', cls: 'bg-blue-50 text-blue-600' },
  completed: { label: '已完成', cls: 'bg-emerald-50 text-emerald-600' },
};

type SidebarTab = 'memory' | 'narrative';

export default function ChapterAnalysis() {
  const { currentProject, chapters } = useStore();
  const { refreshChapters, deleteChapter, updateChapter } = useChapterSync();
  const projectId = currentProject?.id;
  const sorted = useMemo(() => [...chapters].sort((a, b) => a.chapter_number - b.chapter_number), [chapters]);

  // ---------- 阅读区：选中章节 / 标注 / 叙事状态 ----------
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Chapter | null>(null);
  const [annotations, setAnnotations] = useState<ChapterAnnotationsResponse | null>(null);
  const [narrative, setNarrative] = useState<NormalizedAnalysisData | null>(null);
  const [narrativeLoading, setNarrativeLoading] = useState(false);
  const [contentLoading, setContentLoading] = useState(false);
  const [showAnnotations, setShowAnnotations] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>('memory');
  const [activeAnnotationId, setActiveAnnotationId] = useState<string>();
  const [scrollToContent, setScrollToContent] = useState<string>();
  const [scrollToSidebar, setScrollToSidebar] = useState<string>();

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

  // 首次：默认选第一个有正文的章
  useEffect(() => {
    if (selectedId || sorted.length === 0) return;
    const first = sorted.find((c) => c.word_count > 0) ?? sorted[0];
    selectChapter(first.id);
  }, [sorted, selectedId, selectChapter]);

  // ---------- 正文任务 ----------
  const onChapterWritten = useCallback((id: string) => {
    if (id === selectedId) void loadSelected(id);
  }, [selectedId, loadSelected]);

  const jobs = useChapterWriteJobs({ projectId, chapters: sorted, refreshChapters, onChapterWritten });
  const streamChapterId = jobs.streamState?.chapterId;

  // 正文任务开始 / 批量切章时自动切到该章
  useEffect(() => {
    if (streamChapterId && streamChapterId !== selectedId) selectChapter(streamChapterId);
  }, [streamChapterId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------- 弹窗 ----------
  const [editState, setEditState] = useState<{ editing: Chapter | null } | null>(null);
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

  const confirmRewrite = (promptIds: string[]) => {
    if (!rewriteTarget) return;
    const chapter = rewriteTarget;
    setRewriteTarget(null);
    void jobs.startStream({ chapter, kind: 'chapter_regenerate', requestBody: { prompt_ids: promptIds }, mode: 'single' }).catch(() => { /* 已 toast / 已停止 */ });
  };

  const saveStreamContent = async () => {
    const state = jobs.streamState;
    if (!state) return;
    try {
      await updateChapter(state.chapterId, { content: state.content });
      toast.success('内容已保存');
      if (state.chapterId === selectedId) void loadSelected(state.chapterId);
    } catch {
      toast.error('保存失败');
    }
  };

  const copyText = async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(`${what}已复制到剪贴板`);
    } catch {
      toast.error('复制失败，请稍后重试');
    }
  };

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
  const idx = sorted.findIndex((c) => c.id === selectedId);
  const prev = idx > 0 ? sorted[idx - 1] : null;
  const next = idx >= 0 && idx < sorted.length - 1 ? sorted[idx + 1] : null;
  const totalWords = chapters.reduce((s, c) => s + c.word_count, 0);
  const completedCount = chapters.filter((c) => c.status === 'completed').length;
  const hasAnnotations = Boolean(annotations && annotations.annotations.length > 0);
  const streamPanelVisible = Boolean(jobs.streamState && !jobs.panelHidden && jobs.streamState.chapterId === selectedId);
  const { batchStatus, batchRunning, streamBusy } = jobs;

  return (
    <div className="animate-fade-in space-y-6">
      {/* 头部 */}
      <section className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0">
          <h1 className="text-[28px] font-semibold tracking-tight text-content md:text-[32px]">剧情分析</h1>
          <p className="mt-2 max-w-[600px] text-sm leading-6 text-content-secondary">
            {chapters.length > 0 ? `共 ${chapters.length} 章 · ${totalWords.toLocaleString()} 字。` : ''}
            左侧管理章节，右侧阅读正文与分析结果。从章纲同步生成骨架，再逐章 / 批量交给 AI 成稿；已完成的章可用去 AI 味提示词重写。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <button onClick={() => void handleSyncFromOutlines()} disabled={syncing} className="hh-btn-secondary">
            {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            从章纲同步
          </button>
          <button onClick={() => setShowBatch(true)} disabled={batchRunning || streamBusy} className="hh-btn-secondary">
            <Layers className="h-4 w-4" />
            批量生成
          </button>
          <button onClick={() => setEditState({ editing: null })} className="hh-btn-primary">
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
            点击右上角「从章纲同步」把章纲一键转成章节骨架，或「新建章节」手动添加。
          </p>
        </section>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
          {/* 左栏：章节列表 */}
          <section className="hh-panel divide-y divide-surface-border/80 overflow-hidden lg:max-h-[calc(100dvh-220px)] lg:overflow-y-auto">
            {sorted.map((c) => {
              const status = STATUS_MAP[c.status] || STATUS_MAP.draft;
              const isSelected = c.id === selectedId;
              const generating = jobs.isGenerating(c.id);
              const currentBatchChapter = batchRunning && batchStatus?.currentChapterId === c.id;
              const analyzing = jobs.analyzingChapterIds.has(c.id);
              const canWrite = !generating && !batchRunning && !streamBusy;
              return (
                <div
                  key={c.id}
                  onClick={() => selectChapter(c.id)}
                  className={cn(
                    'cursor-pointer border-l-2 px-4 py-3 transition-colors',
                    isSelected ? 'border-brand bg-brand/[0.06]' : 'border-transparent hover:bg-brand/[0.04]',
                    currentBatchChapter && !isSelected && 'bg-brand/[0.03]',
                  )}
                >
                  <div className="flex items-center gap-3">
                    <div
                      className={cn(
                        'flex h-8 w-8 flex-shrink-0 items-center justify-center text-sm font-semibold tabular-nums',
                        c.status === 'completed' ? 'bg-brand/10 text-brand' : 'bg-surface-hover text-content-secondary',
                      )}
                    >
                      {c.chapter_number}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className={cn('truncate text-sm text-content', isSelected ? 'font-semibold' : 'font-medium')}>{c.title}</span>
                        <span className={cn('flex-shrink-0 px-1.5 py-0.5 text-[10px] font-medium', status.cls)}>{status.label}</span>
                      </div>
                      <p className="mt-0.5 text-xs text-content-tertiary tabular-nums">
                        {c.word_count > 0 ? `${c.word_count.toLocaleString()} 字` : '暂无内容'}
                        {currentBatchChapter && <span className="ml-2 text-brand">串行生成中</span>}
                      </p>
                    </div>
                  </div>
                  <div className="mt-1.5 flex items-center gap-0.5 pl-11" onClick={(e) => e.stopPropagation()}>
                    <button onClick={() => setEditState({ editing: c })} className="hh-icon-btn-plain h-7 w-7 hover:text-brand" title="编辑" aria-label="编辑">
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    {c.status === 'completed' && c.word_count > 0 ? (
                      <button
                        onClick={() => setRewriteTarget(c)}
                        disabled={!canWrite}
                        className="hh-icon-btn-plain h-7 w-7 hover:text-brand"
                        title="去 AI 味重写（按项目提示词重写并覆盖正文）"
                        aria-label="去 AI 味重写"
                      >
                        {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                      </button>
                    ) : (
                      <button
                        onClick={() => void openGenerate(c)}
                        disabled={!canWrite}
                        className="hh-icon-btn-plain h-7 w-7 hover:text-brand"
                        title="AI 生成"
                        aria-label="AI 生成"
                      >
                        {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
                      </button>
                    )}
                    {c.chapter_outline_id && (
                      <button
                        onClick={() => setSceneTarget({ outlineId: c.chapter_outline_id!, title: c.title })}
                        className="hh-icon-btn-plain h-7 w-7 hover:text-brand"
                        title="场景生成"
                        aria-label="场景生成"
                      >
                        <Film className="h-3.5 w-3.5" />
                      </button>
                    )}
                    {c.status === 'completed' && (
                      <button
                        onClick={() => void jobs.handleAnalyze(c)}
                        disabled={analyzing}
                        className="hh-icon-btn-plain h-7 w-7 hover:text-brand"
                        title="分析（提取记忆 / 叙事状态 / 一致性）"
                        aria-label="分析"
                      >
                        {analyzing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
                      </button>
                    )}
                    <button onClick={() => void handleDelete(c)} className="hh-icon-btn-plain h-7 w-7 hover:text-red-500" title="删除" aria-label="删除">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              );
            })}
          </section>

          {/* 右栏：流式面板 / 阅读区 */}
          {streamPanelVisible && jobs.streamState ? (
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
              onContentChange={jobs.setStreamContent}
              onSave={saveStreamContent}
            />
          ) : (
            <section className="hh-panel flex min-h-[520px] flex-col overflow-hidden">
              {!selectedId || !detail ? (
                <div className="flex flex-1 items-center justify-center text-sm text-content-tertiary">
                  {contentLoading ? <Loader2 className="h-5 w-5 animate-spin text-brand" /> : '从左侧选择一个章节查看'}
                </div>
              ) : (
                <>
                  {/* 工具栏 */}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-surface-border/80 px-5 py-3">
                    <div className="flex min-w-0 items-center gap-2">
                      <button onClick={() => prev && selectChapter(prev.id)} disabled={!prev} className="hh-icon-btn-plain h-8 w-8" title={prev ? `上一章：${prev.title}` : '已是第一章'} aria-label="上一章">
                        <ChevronLeft className="h-4 w-4" />
                      </button>
                      <span className="truncate text-sm font-semibold text-content">第 {detail.chapter_number} 章：{detail.title}</span>
                      <button onClick={() => next && selectChapter(next.id)} disabled={!next} className="hh-icon-btn-plain h-8 w-8" title={next ? `下一章：${next.title}` : '已是最后一章'} aria-label="下一章">
                        <ChevronRight className="h-4 w-4" />
                      </button>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <button onClick={() => void copyText(`第${detail.chapter_number}章: ${detail.title}`, '章节标题')} className="hh-chip flex items-center gap-1 px-2 py-1 text-[11px]">
                        <Copy className="h-3 w-3" />
                        复制标题
                      </button>
                      <button onClick={() => void copyText(detail.content || '', '章节内容')} disabled={!detail.content} className="hh-chip flex items-center gap-1 px-2 py-1 text-[11px] disabled:opacity-50">
                        <Copy className="h-3 w-3" />
                        复制内容
                      </button>
                      {hasAnnotations && (
                        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-content-secondary">
                          <input type="checkbox" checked={showAnnotations} onChange={(e) => setShowAnnotations(e.target.checked)} />
                          显示标注
                        </label>
                      )}
                      <button onClick={() => setSidebarOpen((v) => !v)} className="hh-icon-btn-plain h-8 w-8" title={sidebarOpen ? '隐藏分析面板' : '显示分析面板'} aria-label="分析面板">
                        {sidebarOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
                      </button>
                    </div>
                  </div>
                  {hasAnnotations && annotations && (
                    <p className="border-b border-surface-border/80 px-5 py-2 text-xs text-content-tertiary">
                      共 {annotations.summary.total_annotations} 个标注：
                      {annotations.summary.hooks > 0 && ` 🎣${annotations.summary.hooks}个钩子`}
                      {annotations.summary.foreshadows > 0 && ` 🌟${annotations.summary.foreshadows}个伏笔`}
                      {annotations.summary.plot_points > 0 && ` 💎${annotations.summary.plot_points}个情节点`}
                      {annotations.summary.character_events > 0 && ` 👤${annotations.summary.character_events}个角色事件`}
                    </p>
                  )}

                  <div className="flex flex-1 flex-col gap-4 p-5 xl:flex-row">
                    {/* 正文 */}
                    <div className="min-w-0 flex-1 xl:max-h-[calc(100dvh-320px)] xl:overflow-y-auto">
                      {contentLoading ? (
                        <div className="flex items-center gap-2 py-6 text-xs text-content-secondary">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          加载中…
                        </div>
                      ) : !detail.content ? (
                        <div className="py-10 text-center text-sm text-content-tertiary">本章还没有正文：点左侧 ⚡ 交给 AI 生成，或 ✎ 手动编辑。</div>
                      ) : (
                        <>
                          {!hasAnnotations && (
                            <p className="mb-4 border border-dashed border-surface-border bg-white/60 px-3 py-2 text-xs text-content-tertiary">
                              该章尚未分析，没有记忆标注。点左侧 🔍 分析后可在正文里高亮钩子 / 伏笔 / 情节点。
                            </p>
                          )}
                          {showAnnotations && hasAnnotations && annotations ? (
                            <AnnotatedText
                              content={detail.content}
                              annotations={annotations.annotations}
                              onAnnotationClick={(a) => handleAnnotationClick(a, 'content')}
                              activeAnnotationId={activeAnnotationId}
                              scrollToAnnotation={scrollToContent}
                              style={{ lineHeight: 2, fontSize: 16 }}
                            />
                          ) : (
                            <div className="whitespace-pre-wrap break-words text-base leading-8 text-content">{detail.content}</div>
                          )}
                        </>
                      )}
                    </div>

                    {/* 侧栏：记忆标注 / 叙事状态 */}
                    {sidebarOpen && (
                      <aside className="border-t border-surface-border/80 pt-4 xl:w-[380px] xl:shrink-0 xl:border-l xl:border-t-0 xl:pl-4 xl:pt-0">
                        <div className="mb-3 flex gap-1">
                          {([['memory', '记忆标注'], ['narrative', '叙事状态']] as const).map(([key, label]) => (
                            <button
                              key={key}
                              onClick={() => setSidebarTab(key)}
                              className={cn('hh-chip px-3 py-1 text-xs', sidebarTab === key ? 'bg-brand text-white' : 'text-content-secondary')}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                        <div className="xl:max-h-[calc(100dvh-380px)] xl:overflow-y-auto">
                          {sidebarTab === 'memory' ? (
                            hasAnnotations && annotations ? (
                              <MemorySidebar
                                annotations={annotations.annotations}
                                activeAnnotationId={activeAnnotationId}
                                onAnnotationClick={(a) => handleAnnotationClick(a, 'sidebar')}
                                scrollToAnnotation={scrollToSidebar}
                              />
                            ) : (
                              <p className="py-8 text-center text-xs text-content-tertiary">暂无标注数据</p>
                            )
                          ) : (
                            <NarrativeStatePanel data={narrative} loading={narrativeLoading} />
                          )}
                        </div>
                      </aside>
                    )}
                  </div>
                </>
              )}
            </section>
          )}
        </div>
      )}

      {/* 弹窗 */}
      {projectId && (
        <ChapterEditModal
          open={editState !== null}
          projectId={projectId}
          editing={editState?.editing ?? null}
          defaultChapterNumber={sorted.length > 0 ? sorted[sorted.length - 1].chapter_number + 1 : 1}
          onClose={() => setEditState(null)}
          onSaved={(id) => {
            void refreshChapters();
            if (id === selectedId) void loadSelected(id);
            else if (!editState?.editing) selectChapter(id);
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
          onConfirm={confirmRewrite}
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

function StatItem({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="px-5 py-4 md:px-6">
      <p className="text-xs text-content-tertiary">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-content tabular-nums">{value}</p>
    </div>
  );
}
