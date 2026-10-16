/**
 * 章节正文任务编排：单章生成 / 去 AI 味重写 / 批量串行 / 刷新后接管运行中任务 / 等待分析 / 取消。
 *
 * 任务本身由全局 aiJobsStore 持有（关面板、切页、刷新都不中断），这里只维护页面视图需要的派生状态。
 * 单章生成与重写的结果是候选稿（不动正文）：完成时通过 onCandidateReady 让页面打开候选稿审阅；
 * 批量每章过闸门后服务端自动采用，通过 onChapterWritten 通知页面刷新阅读区。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { chapterApi, type ChapterRegenerateRequest, type ChapterRegenerateResult, type ChapterWriteResult } from '@/services/api';
import { AIJobError, runAIJob, useAIJob, useAIJobsStore, useRunningAIJobs, waitForAIJob } from '@/store/aiJobsStore';
import type { SSEClientOptions } from '@/utils/sseClient';
import { countBatchTargets, describeBatchEvent, selectBatchChapters } from '@/utils/chapterBatch';
import type { Chapter, ChapterBatchEvent, ChapterBatchResult, ChapterGenerateRequest } from '@/types';

export interface StreamState {
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

type WriteJobKind = 'chapter_generate' | 'chapter_regenerate';

/** 页面自带面板承担正文任务；横幅只兜底其它任务，面板隐藏（后台运行）时才把正文任务也放进横幅 */
export const WRITE_JOB_KINDS = ['chapter_generate', 'chapter_regenerate'];
/** chapter_batch = 服务端批量（页面有批量进度条；横幅兜底展示，刷新 / 切页回来也能看到） */
export const OTHER_JOB_KINDS = ['chapter_analyze', 'chapter_imitate', 'chapter_batch'];

const abortError = () => new DOMException('Request aborted', 'AbortError');

interface Options {
  projectId: string | undefined;
  /** 已按 chapter_number 排好序 */
  chapters: Chapter[];
  refreshChapters: () => Promise<unknown>;
  /** 批量每章写入 / 分析完成后回调（页面用来刷新阅读区） */
  onChapterWritten?: (chapterId: string) => void;
  /** 单章生成 / 重写完成：候选稿已就绪（页面打开候选稿审阅） */
  onCandidateReady?: (chapterId: string, candidateId: string) => void;
}

const candidateIdOf = (result: unknown): string | null => {
  const id = (result as { candidate_id?: unknown } | null)?.candidate_id;
  return typeof id === 'string' && id ? id : null;
};

export function useChapterWriteJobs({ projectId, chapters, refreshChapters, onChapterWritten, onCandidateReady }: Options) {
  const [streamState, setStreamState] = useState<StreamState | null>(null);
  const [streamJobId, setStreamJobId] = useState<string | null>(null);
  const streamJob = useAIJob(streamJobId);
  const [panelHidden, setPanelHidden] = useState(false);
  const [showProcess, setShowProcess] = useState(true);
  const [streamDone, setStreamDone] = useState(false);
  const cancelJob = useAIJobsStore((s) => s.cancel);
  const runningWriteJobs = useRunningAIJobs(projectId, WRITE_JOB_KINDS);
  const runningAnalyses = useRunningAIJobs(projectId, ['chapter_analyze']);

  const [batchStatus, setBatchStatus] = useState<BatchStatusState | null>(null);
  const batchCancelRef = useRef(false);
  const batchJobIdRef = useRef<string | null>(null);
  const runningBatchJobs = useRunningAIJobs(projectId, ['chapter_batch']);
  const [analyzingIds, setAnalyzingIds] = useState<Set<string>>(new Set());

  const onWrittenRef = useRef(onChapterWritten);
  onWrittenRef.current = onChapterWritten;
  const onCandidateRef = useRef(onCandidateReady);
  onCandidateRef.current = onCandidateReady;

  // 清理：只停掉前端的批量编排循环；正在跑的任务归 store，切页不中断
  useEffect(() => () => { batchCancelRef.current = true; }, []);

  /** 面板视图跟随任务状态：进度 / 文案 / 流式正文都来自 store */
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
      .then(async (finished) => {
        setStreamDone(true);
        await refreshChapters();
        const candidateId = candidateIdOf(finished.result);
        if (candidateId) onCandidateRef.current?.(chapterId, candidateId);
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
      const candidateId = candidateIdOf(job.result);
      if (mode === 'single') {
        toast.success(`「${chapter.title}」${isRewrite ? '重写' : '生成'}完成：候选稿已就绪，审阅后采用才会写入正文`);
      }
      if (candidateId) onCandidateRef.current?.(chapter.id, candidateId);
      return (job.result as ChapterWriteResult | ChapterRegenerateResult | null) ?? null;
    } catch (error) {
      if (error instanceof AIJobError && error.job.status === 'cancelled') {
        throw abortError();
      }
      toast.error((error as Error)?.message || (isRewrite ? '重写失败' : '生成失败'));
      setStreamState(null);
      throw error;
    }
  }, [refreshChapters]);

  const resetStreamView = useCallback(() => {
    setStreamState(null);
    setStreamJobId(null);
    setStreamDone(false);
  }, []);

  const closeStreamPanel = useCallback(() => resetStreamView(), [resetStreamView]);

  /** 后台运行：收起面板，任务继续；顶部横幅 / 托盘可再打开 */
  const hideStreamPanel = useCallback(() => setPanelHidden(true), []);

  const cancelBatch = useCallback(() => {
    if (!batchStatus || batchStatus.status !== 'running') return;
    batchCancelRef.current = true;
    if (batchJobIdRef.current) void cancelJob(batchJobIdRef.current);
    if (streamJobId) void cancelJob(streamJobId);
    resetStreamView();
    setBatchStatus((prev) => (prev ? { ...prev, status: 'cancelled', message: '已取消批量生成（已写完的章节已保存）' } : prev));
    toast.info('已取消批量生成');
  }, [batchStatus, streamJobId, cancelJob, resetStreamView]);

  /** 刷新 / 切页回来：服务端批量仍在跑 → 接上进度条，结束后刷新章节列表 */
  useEffect(() => {
    if (batchStatus || runningBatchJobs.length === 0) return;
    const job = runningBatchJobs[0];
    batchJobIdRef.current = job.id;
    setBatchStatus({
      status: 'running',
      total: Math.max(1, Number(job.meta.to_chapter ?? 0) - Number(job.meta.from_chapter ?? 0) + 1),
      completed: 0,
      progress: job.progress?.pct ?? 0,
      currentChapterId: null,
      currentChapterNumber: null,
      currentChapterTitle: null,
      message: job.progress?.message ?? '批量生成进行中…',
      skippedCount: 0,
    });
    void waitForAIJob(job.id)
      .then(async (finished) => {
        await refreshChapters();
        const result = finished.result as ChapterBatchResult | null;
        setBatchStatus((prev) => prev ? {
          ...prev,
          status: result?.status === 'paused' ? 'cancelled' : result?.status === 'stopped' ? 'error' : 'completed',
          completed: result?.completed.length ?? prev.completed,
          progress: 100,
          message: result?.message ?? '批量生成完成',
        } : prev);
      })
      .catch(() => {
        setBatchStatus((prev) => (prev ? { ...prev, status: 'cancelled', message: '批量生成已停止' } : prev));
      });
  }, [batchStatus, runningBatchJobs, refreshChapters]);

  /** 运行中的批量任务把进度同步到进度条（接管后没有逐章事件订阅时也能动） */
  useEffect(() => {
    const job = runningBatchJobs[0];
    if (!job || batchStatus?.status !== 'running') return;
    setBatchStatus((prev) => prev && prev.status === 'running' ? {
      ...prev,
      progress: Math.max(prev.progress, Math.min(job.progress?.pct ?? 0, 99)),
      message: job.progress?.message || prev.message,
    } : prev);
  }, [runningBatchJobs, batchStatus?.status]);

  const cancelStream = useCallback(() => {
    if (batchStatus?.status === 'running') {
      cancelBatch();
      return;
    }
    if (streamJobId) void cancelJob(streamJobId);
    resetStreamView();
    toast.info('已停止生成');
  }, [batchStatus, cancelBatch, streamJobId, cancelJob, resetStreamView]);

  /** 生成前检查：前面有未分析 / 分析过期的章节、本章章纲未确认或上游已改时提醒是否继续。返回 true=继续。 */
  const confirmUnanalyzedPrevious = useCallback(async (chapter: Chapter): Promise<boolean> => {
    try {
      const res = await chapterApi.generationPrecheck(chapter.id);
      if (res.count > 0) return window.confirm(res.message);
    } catch {
      // 预检查失败不阻断生成
    }
    return true;
  }, []);

  /**
   * 服务端批量：整段范围交给后端队列（关掉页面也不停，刷新后托盘可接管）。
   * 逐章事件 batch_chapter 驱动本地进度；暂停 / 失败的原因在 result.message 里。
   */
  const startBatch = useCallback(async ({
    from, to, pauseOnCritical, qualityGate = true, pipeline = false, autoExpand = true, adherenceGate = true,
    requireConfirmedOutline = false,
  }: {
    from: number; to: number; pauseOnCritical: boolean; qualityGate?: boolean; pipeline?: boolean; autoExpand?: boolean;
    adherenceGate?: boolean; requireConfirmedOutline?: boolean;
  }) => {
    if (!projectId) return;
    const { toGenerate, skipped } = selectBatchChapters(chapters, from, to);
    const total = countBatchTargets(chapters, from, to);
    if (total === 0) {
      toast.info('所选范围内没有待生成的章节');
      return;
    }
    // 批量生成前：以首个待生成章节为基准检查前置未分析章节，提醒用户是否继续
    if (toGenerate[0] && !(await confirmUnanalyzedPrevious(toGenerate[0]))) return;

    batchCancelRef.current = false;
    let done = 0;
    setBatchStatus({
      status: 'running',
      total,
      completed: 0,
      progress: 0,
      currentChapterId: null,
      currentChapterNumber: null,
      currentChapterTitle: null,
      message: skipped > 0 ? `已自动跳过 ${skipped} 章已有内容的章节` : '准备开始批量生成…',
      skippedCount: skipped,
    });

    try {
      const job = await runAIJob({
        kind: 'chapter_batch',
        title: `批量生成第 ${from}-${to} 章`,
        projectId,
        openModal: false,
        meta: { from_chapter: from, to_chapter: to },
        onStarted: (id: string) => { batchJobIdRef.current = id; },
        connect: (options: SSEClientOptions<unknown>) => chapterApi.batchWriteStream(projectId, {
          from_chapter: from,
          to_chapter: to,
          pause_on_critical: pauseOnCritical,
          quality_gate: qualityGate,
          pipeline,
          auto_expand: autoExpand,
          adherence_gate: adherenceGate,
          require_confirmed_outline: requireConfirmedOutline,
        }, options as SSEClientOptions<ChapterBatchResult>),
        onEvent: (m) => {
          if (m.type === 'batch_chapter') {
            const e = m as unknown as ChapterBatchEvent;
            if (e.status === 'generated') done += 1;
            const chapter = chapters.find((c) => c.chapter_number === e.chapter_number);
            setBatchStatus((prev) => prev && prev.status === 'running' ? {
              ...prev,
              completed: done,
              currentChapterId: e.chapter_id ?? chapter?.id ?? prev.currentChapterId,
              currentChapterNumber: e.chapter_number,
              currentChapterTitle: chapter?.title ?? prev.currentChapterTitle,
              message: describeBatchEvent(e) || prev.message,
            } : prev);
            if (e.chapter_id) {
              const id = e.chapter_id;
              // 章节列表上的「分析中」标记跟着批量事件走
              if (e.status === 'analyzing') setAnalyzingIds((prev) => new Set(prev).add(id));
              if (['done', 'paused', 'analysis_failed'].includes(e.status)) {
                setAnalyzingIds((prev) => {
                  const next = new Set(prev);
                  next.delete(id);
                  return next;
                });
              }
              if (e.status === 'generated' || e.status === 'done') onWrittenRef.current?.(id);
            }
          } else if (m.type === 'progress' && typeof m.progress === 'number') {
            const pct = m.progress;
            const message = typeof m.message === 'string' ? m.message : undefined;
            setBatchStatus((prev) => prev && prev.status === 'running'
              ? { ...prev, progress: Math.min(pct, 99), message: message ?? prev.message }
              : prev);
          }
        },
      });
      await refreshChapters();
      const result = job.result as ChapterBatchResult | null;
      if (result?.status === 'paused') {
        setBatchStatus((prev) => prev ? { ...prev, status: 'cancelled', completed: result.completed.length, message: result.message } : prev);
        toast.warning(result.message);
      } else if (result?.status === 'stopped') {
        setBatchStatus((prev) => prev ? {
          ...prev, status: 'error', completed: result.completed.length, errorMessage: result.message, message: result.message,
        } : prev);
        toast.error(result.message);
      } else {
        const count = result?.completed.length ?? done;
        setBatchStatus((prev) => prev ? {
          ...prev, status: 'completed', completed: count, total: Math.max(prev.total, count), progress: 100,
          message: `批量生成完成，共写了 ${count} 章`,
        } : prev);
        toast.success('批量生成完成');
      }
      if (result?.warnings?.length) toast.warning(result.warnings.slice(0, 3).join('；'));
    } catch (error) {
      if (error instanceof AIJobError && error.job.status === 'cancelled') {
        setBatchStatus((prev) => (prev ? { ...prev, status: 'cancelled', message: '已取消批量生成（已写完的章节已保存）' } : prev));
        await refreshChapters();
        return;
      }
      setBatchStatus((prev) => prev ? {
        ...prev,
        status: 'error',
        errorMessage: (error as Error)?.message || '批量生成失败',
        message: '批量生成失败',
      } : prev);
      toast.error((error as Error)?.message || '批量生成失败');
    }
  }, [projectId, chapters, confirmUnanalyzedPrevious, refreshChapters]);

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
            const warning = (job.result as { warning?: string | null } | null)?.warning;
            if (warning) toast.warning(`「${chapter.title}」分析完成，但${warning}`);
            else toast.success(`「${chapter.title}」分析完成`);
          }
          // 失败也刷新：目录里的分析状态点要变成「分析失败」，侧栏显示原因（之前的结果仍保留）
          void refreshChapters().then(() => onWrittenRef.current?.(chapter.id));
        },
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '分析启动失败');
    }
  }, [projectId, refreshChapters]);

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
    startStream,
    startBatch,
    cancelStream,
    cancelBatch,
    closeStreamPanel,
    hideStreamPanel,
    handleAnalyze,
    confirmUnanalyzedPrevious,
  };
}
