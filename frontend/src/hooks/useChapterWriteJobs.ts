/**
 * 章节正文任务编排：单章生成 / 去 AI 味重写 / 批量串行 / 刷新后接管运行中任务 / 等待分析 / 取消。
 *
 * 任务本身由全局 aiJobsStore 持有（关面板、切页、刷新都不中断），这里只维护页面视图需要的派生状态，
 * 并把「完成后落库」的时刻通过 onChapterWritten 通知页面刷新阅读区。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { chapterApi, chapterOutlineLinkApi, type ChapterRegenerateRequest, type ChapterRegenerateResult, type ChapterWriteResult } from '@/services/api';
import { AIJobError, runAIJob, useAIJob, useAIJobsStore, useRunningAIJobs, waitForAIJob } from '@/store/aiJobsStore';
import type { SSEClientOptions } from '@/utils/sseClient';
import { normalizeAnalysisData } from '@/utils/chapterAnalysis';
import { selectBatchChapters } from '@/utils/chapterBatch';
import type { Chapter, ChapterGenerateRequest, PlotCardWithLinks } from '@/types';

export interface StreamState {
  chapterId: string;
  chapterTitle: string;
  progress: number;
  message: string;
  content: string;
  mode: 'single' | 'batch';
}

export interface BatchStatusState {
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

export type WriteJobKind = 'chapter_generate' | 'chapter_regenerate';

/** 页面自带面板承担正文任务；横幅只兜底其它任务，面板隐藏（后台运行）时才把正文任务也放进横幅 */
export const WRITE_JOB_KINDS = ['chapter_generate', 'chapter_regenerate'];
export const OTHER_JOB_KINDS = ['chapter_analyze', 'scene_generate', 'chapter_imitate'];

const abortError = () => new DOMException('Request aborted', 'AbortError');

interface Options {
  projectId: string | undefined;
  /** 已按 chapter_number 排好序 */
  chapters: Chapter[];
  refreshChapters: () => Promise<unknown>;
  /** 单章 / 重写 / 批量每章落库后回调（页面用来刷新阅读区） */
  onChapterWritten?: (chapterId: string) => void;
}

export function useChapterWriteJobs({ projectId, chapters, refreshChapters, onChapterWritten }: Options) {
  const [streamState, setStreamState] = useState<StreamState | null>(null);
  const [streamJobId, setStreamJobId] = useState<string | null>(null);
  const streamJob = useAIJob(streamJobId);
  const [panelHidden, setPanelHidden] = useState(false);
  const [showProcess, setShowProcess] = useState(true);
  const [streamDone, setStreamDone] = useState(false);
  const cancelJob = useAIJobsStore((s) => s.cancel);
  const attachJob = useAIJobsStore((s) => s.attach);
  const runningWriteJobs = useRunningAIJobs(projectId, WRITE_JOB_KINDS);
  const runningAnalyses = useRunningAIJobs(projectId, ['chapter_analyze']);
  const [relatedCards, setRelatedCards] = useState<PlotCardWithLinks[]>([]);
  const [loadingCards, setLoadingCards] = useState(false);

  const [batchStatus, setBatchStatus] = useState<BatchStatusState | null>(null);
  const batchCancelRef = useRef(false);
  const [analyzingIds, setAnalyzingIds] = useState<Set<string>>(new Set());

  const onWrittenRef = useRef(onChapterWritten);
  onWrittenRef.current = onChapterWritten;

  // 清理：只停掉前端的批量编排循环；正在跑的任务归 store，切页不中断
  useEffect(() => () => { batchCancelRef.current = true; }, []);

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

  /** 面板视图跟随任务状态：进度 / 文案 / 正文都来自 store（生成完成后正文转为可编辑的本地副本） */
  useEffect(() => {
    if (!streamJob || streamDone) return;
    setStreamState((prev) => {
      if (!prev || prev.chapterId !== (streamJob.meta.chapter_id ?? prev.chapterId)) return prev;
      return {
        ...prev,
        progress: streamJob.progress?.pct ?? prev.progress,
        message: streamJob.progress?.message || prev.message,
        content: streamJob.content,
      };
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
    setStreamState({
      chapterId,
      chapterTitle: job.title,
      progress: job.progress?.pct ?? 0,
      message: job.progress?.message ?? '正在生成…',
      content: useAIJobsStore.getState().jobs[job.id]?.content ?? '',
      mode: 'single',
    });
    void waitForAIJob(job.id)
      .then(async () => {
        setStreamDone(true);
        await refreshChapters();
        onWrittenRef.current?.(chapterId);
      })
      .catch(() => { /* 失败 / 停止：面板保留错误态由任务弹窗展示 */ });
  }, [streamJobId, runningWriteJobs, refreshChapters]);

  const startStream = useCallback(async ({
    chapter,
    kind,
    requestBody,
    mode,
  }: {
    chapter: Chapter;
    kind: WriteJobKind;
    requestBody: ChapterGenerateRequest | ChapterRegenerateRequest;
    mode: 'single' | 'batch';
  }): Promise<ChapterWriteResult | ChapterRegenerateResult | null> => {
    const isRewrite = kind === 'chapter_regenerate';
    setStreamDone(false);
    setPanelHidden(false);
    setStreamJobId(null);
    await loadRelatedCardsForChapter(chapter);

    setStreamState({
      chapterId: chapter.id,
      chapterTitle: chapter.title,
      progress: 0,
      message: mode === 'batch' ? '准备串行生成…' : isRewrite ? '准备重写…' : '准备生成…',
      content: '',
      mode,
    });

    try {
      const job = await runAIJob({
        kind,
        title: `${isRewrite ? '去 AI 味重写' : '生成'}第 ${chapter.chapter_number} 章《${chapter.title}》`,
        projectId: chapter.project_id,
        openModal: false,
        meta: { chapter_id: chapter.id },
        onStarted: setStreamJobId,
        connect: (options: SSEClientOptions<unknown>) =>
          isRewrite
            ? chapterApi.regenerateChapterStream(chapter.id, requestBody as ChapterRegenerateRequest, options as SSEClientOptions<ChapterRegenerateResult>)
            : chapterApi.generateChapterStream(chapter.id, requestBody as ChapterGenerateRequest, options as SSEClientOptions<ChapterWriteResult>),
        onEvent: (m) => {
          if (mode === 'batch' && m.type === 'progress' && typeof m.progress === 'number') {
            const pct = m.progress;
            const message = typeof m.message === 'string' ? m.message : undefined;
            setBatchStatus((prev) => {
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
      setStreamState((prev) => (prev && prev.chapterId === chapter.id ? { ...prev, progress: 100, content: finalContent } : prev));
      setStreamDone(true);
      await refreshChapters();
      onWrittenRef.current?.(chapter.id);
      if (mode === 'single') {
        toast.success(`「${chapter.title}」${isRewrite ? '重写完成，已覆盖正文' : '生成完成'}`);
      }
      return (job.result as ChapterWriteResult | ChapterRegenerateResult | null) ?? null;
    } catch (error) {
      if (error instanceof AIJobError && error.job.status === 'cancelled') {
        throw abortError();
      }
      toast.error((error as Error)?.message || (isRewrite ? '重写失败' : '生成失败'));
      setStreamState(null);
      throw error;
    }
  }, [loadRelatedCardsForChapter, refreshChapters]);

  /** 等待本章分析任务（正文任务 result 里带 analysis_job_id）结束；没有分析任务则直接返回 */
  const waitForChapterAnalysis = useCallback(async (chapter: Chapter, analysisJobId: string | null | undefined) => {
    if (!analysisJobId) return;
    setAnalyzingIds((prev) => new Set(prev).add(chapter.id));
    const unsubscribe = useAIJobsStore.getState().subscribe(analysisJobId, (m) => {
      if (m.type !== 'progress' || typeof m.message !== 'string') return;
      const waitingMessage = `正在分析第 ${chapter.chapter_number} 章：${m.message}`;
      setBatchStatus((prev) => prev && prev.status === 'running' && prev.currentChapterId === chapter.id
        ? { ...prev, message: waitingMessage }
        : prev);
      setStreamState((prev) => prev && prev.chapterId === chapter.id
        ? { ...prev, message: waitingMessage, progress: 100 }
        : prev);
    });
    try {
      if (batchCancelRef.current) throw abortError();
      await attachJob(analysisJobId).catch(() => { /* 已在 store 中 / 已过期 → 由 waitForAIJob 判定 */ });
      await waitForAIJob(analysisJobId);
      await refreshChapters();
      onWrittenRef.current?.(chapter.id);
      setBatchStatus((prev) => prev && prev.status === 'running' && prev.currentChapterId === chapter.id
        ? { ...prev, message: `第 ${chapter.chapter_number} 章分析完成，开始整理记忆…` }
        : prev);
    } catch (error) {
      if (error instanceof AIJobError) {
        throw new Error(error.job.error || `第 ${chapter.chapter_number} 章分析失败`);
      }
      throw error;
    } finally {
      unsubscribe();
      setAnalyzingIds((prev) => {
        const next = new Set(prev);
        next.delete(chapter.id);
        return next;
      });
    }
  }, [attachJob, refreshChapters]);

  const resetStreamView = useCallback(() => {
    setStreamState(null);
    setStreamJobId(null);
    setStreamDone(false);
    setRelatedCards([]);
    setLoadingCards(false);
  }, []);

  const closeStreamPanel = useCallback(() => resetStreamView(), [resetStreamView]);

  /** 后台运行：收起面板，任务继续；顶部横幅 / 托盘可再打开 */
  const hideStreamPanel = useCallback(() => setPanelHidden(true), []);

  const cancelBatch = useCallback(() => {
    if (!batchStatus || batchStatus.status !== 'running') return;
    batchCancelRef.current = true;
    if (streamJobId) void cancelJob(streamJobId);
    resetStreamView();
    setBatchStatus((prev) => (prev ? { ...prev, status: 'cancelled', message: '已取消批量生成' } : prev));
    toast.info('已取消批量生成');
  }, [batchStatus, streamJobId, cancelJob, resetStreamView]);

  const cancelStream = useCallback(() => {
    if (batchStatus?.status === 'running') {
      cancelBatch();
      return;
    }
    if (streamJobId) void cancelJob(streamJobId);
    resetStreamView();
    toast.info('已停止生成');
  }, [batchStatus, cancelBatch, streamJobId, cancelJob, resetStreamView]);

  /** 拉取某章一致性审计中的严重问题数（失败按 0 处理，不阻塞批量流程） */
  const fetchCriticalIssueCount = useCallback(async (chapterId: string): Promise<number> => {
    try {
      const data = await chapterApi.getAnalysis(chapterId);
      return normalizeAnalysisData(data as unknown as Record<string, unknown>).consistency_audit.summary.critical;
    } catch {
      return 0;
    }
  }, []);

  /** 生成前检查：前面有「有正文但未分析（无记忆状态）」的章节则提醒用户是否继续。返回 true=继续。 */
  const confirmUnanalyzedPrevious = useCallback(async (chapter: Chapter): Promise<boolean> => {
    try {
      const res = await chapterApi.generationPrecheck(chapter.id);
      if (res.count > 0) return window.confirm(res.message);
    } catch {
      // 预检查失败不阻断生成
    }
    return true;
  }, []);

  const startBatch = useCallback(async ({ from, to, pauseOnCritical }: { from: number; to: number; pauseOnCritical: boolean }) => {
    if (!projectId) return;
    const { toGenerate, skipped } = selectBatchChapters(chapters, from, to);
    if (toGenerate.length === 0) {
      toast.info('所选范围内没有待生成的章节');
      return;
    }
    // 批量生成前：以首个待生成章节为基准检查前置未分析章节，提醒用户是否继续
    if (!(await confirmUnanalyzedPrevious(toGenerate[0]))) return;

    batchCancelRef.current = false;
    setBatchStatus({
      status: 'running',
      total: toGenerate.length,
      completed: 0,
      progress: 0,
      currentChapterId: null,
      currentChapterNumber: null,
      currentChapterTitle: null,
      message: skipped > 0 ? `已自动跳过 ${skipped} 章已有内容的章节` : '准备开始串行生成…',
      skippedCount: skipped,
    });
    if (skipped > 0) toast.info(`已自动跳过 ${skipped} 章已有内容的章节`);

    try {
      for (let index = 0; index < toGenerate.length; index += 1) {
        const chapter = toGenerate[index];
        if (batchCancelRef.current) break;

        setBatchStatus((prev) => prev ? {
          ...prev,
          currentChapterId: chapter.id,
          currentChapterNumber: chapter.chapter_number,
          currentChapterTitle: chapter.title,
          message: `正在生成第 ${chapter.chapter_number} 章`,
          progress: (prev.completed / prev.total) * 100,
        } : prev);

        const result = await startStream({
          chapter,
          kind: 'chapter_generate',
          requestBody: { target_word_count: 3000, enable_mcp: true, auto_analyze: true },
          mode: 'batch',
        });
        await waitForChapterAnalysis(chapter, (result as ChapterWriteResult | null)?.analysis_job_id);
        if (batchCancelRef.current) break;

        // 一致性闸门：本章审计出严重问题时暂停批量，避免错误设定向后传播
        if (pauseOnCritical) {
          const criticalCount = await fetchCriticalIssueCount(chapter.id);
          if (criticalCount > 0) {
            const goOn = window.confirm(
              `第 ${chapter.chapter_number} 章检测到 ${criticalCount} 个严重一致性问题（详见该章「叙事状态」面板）。\n\n` +
              '继续批量生成可能让错误设定影响后续章节。\n' +
              '「确定」继续生成后续章节；「取消」停止批量，先修复本章。',
            );
            if (!goOn) {
              batchCancelRef.current = true;
              setBatchStatus((prev) => prev ? {
                ...prev,
                status: 'cancelled',
                message: `已在第 ${chapter.chapter_number} 章后暂停：${criticalCount} 个严重一致性问题待处理`,
              } : prev);
              toast.warning(`批量生成已暂停，请先处理第 ${chapter.chapter_number} 章的一致性问题`);
              break;
            }
          }
        }

        setBatchStatus((prev) => prev ? {
          ...prev,
          completed: index + 1,
          progress: ((index + 1) / prev.total) * 100,
          message: `已完成 ${index + 1} / ${prev.total} 章`,
        } : prev);
      }

      if (batchCancelRef.current) return;
      setBatchStatus((prev) => prev ? {
        ...prev,
        status: 'completed',
        completed: prev.total,
        progress: 100,
        message: `批量串行生成完成，共完成 ${prev.total} 章`,
      } : prev);
      toast.success('批量生成完成');
    } catch (error) {
      if ((error as DOMException)?.name === 'AbortError') return;
      setBatchStatus((prev) => prev ? {
        ...prev,
        status: 'error',
        errorMessage: (error as Error)?.message || '批量生成失败',
        message: prev.currentChapterNumber
          ? `第 ${prev.currentChapterNumber} 章生成失败，批量任务已停止`
          : '批量生成失败',
      } : prev);
      toast.error((error as Error)?.message || '批量生成失败');
    }
  }, [projectId, chapters, confirmUnanalyzedPrevious, startStream, waitForChapterAnalysis, fetchCriticalIssueCount]);

  /** 触发分析（通用后台任务 + 弹窗：阶段 / 模型进度可见，可后台运行） */
  const handleAnalyze = useCallback(async (chapter: Chapter) => {
    if (!projectId) return;
    try {
      await useAIJobsStore.getState().start({
        kind: 'chapter_analyze',
        title: `分析第 ${chapter.chapter_number} 章《${chapter.title}》`,
        projectId,
        meta: { chapter_id: chapter.id },
        connect: (options) => chapterApi.analyzeChapterStream(chapter.id, options),
        onSettled: (job) => {
          if (job.status === 'done') {
            toast.success(`「${chapter.title}」分析完成`);
            void refreshChapters().then(() => onWrittenRef.current?.(chapter.id));
          }
        },
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '分析启动失败');
    }
  }, [projectId, refreshChapters]);

  const setStreamContent = useCallback((content: string) => {
    setStreamState((prev) => (prev ? { ...prev, content } : prev));
  }, []);

  const analyzingChapterIds = new Set<string>([
    ...analyzingIds,
    ...runningAnalyses.map((j) => (typeof j.meta.chapter_id === 'string' ? j.meta.chapter_id : '')).filter(Boolean),
  ]);
  const batchRunning = batchStatus?.status === 'running';
  const streamBusy = !!streamState && !streamDone;

  return {
    streamState,
    streamJob,
    streamDone,
    panelHidden,
    showProcess,
    setShowProcess,
    batchStatus,
    batchRunning,
    streamBusy,
    isGenerating: (chapterId: string) => streamState?.chapterId === chapterId && !streamDone,
    analyzingChapterIds,
    relatedCards,
    loadingCards,
    loadRelatedCardsForChapter,
    startStream,
    startBatch,
    cancelStream,
    cancelBatch,
    closeStreamPanel,
    hideStreamPanel,
    setStreamContent,
    handleAnalyze,
    confirmUnanalyzedPrevious,
  };
}
