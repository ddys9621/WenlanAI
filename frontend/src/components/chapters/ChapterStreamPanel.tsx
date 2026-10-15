/** AI 创作面板：全局正文任务在页面里的视图（关面板 / 切页 / 刷新都不影响任务）。结果是候选稿，在候选稿面板审阅采用。 */
import { useEffect, useRef } from 'react';
import { FileCheck2, Zap } from 'lucide-react';
import { cn } from '@/lib/utils';
import { AIJobProcess } from '@/components/ai-job/AIJobProcess';
import type { StreamState } from '@/hooks/useChapterWriteJobs';
import type { AIJobState } from '@/types/ai_job';

interface ChapterStreamPanelProps {
  streamState: StreamState;
  streamJob: AIJobState | null;
  streamDone: boolean;
  batchRunning: boolean;
  showProcess: boolean;
  onToggleProcess: () => void;
  onHide: () => void;
  onCancel: () => void;
  onClose: () => void;
  /** 打开候选稿审阅（生成 / 重写完成后） */
  onReviewCandidate: () => void;
}

export function ChapterStreamPanel({
  streamState, streamJob, streamDone, batchRunning, showProcess, onToggleProcess, onHide, onCancel, onClose,
  onReviewCandidate,
}: ChapterStreamPanelProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isRewrite = streamJob?.kind === 'chapter_regenerate';

  useEffect(() => {
    if (streamDone || !textareaRef.current) return;
    textareaRef.current.scrollTop = textareaRef.current.scrollHeight;
  }, [streamState.content, streamDone]);

  return (
    <section className="hh-panel overflow-hidden">
      <div className="border-b border-surface-border px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-brand-100 text-brand">
              <Zap className="h-4 w-4" />
            </span>
            <span className="text-sm font-semibold text-content">
              {batchRunning ? '批量串行生成：' : streamDone ? '候选稿已就绪：' : isRewrite ? '去 AI 味重写中：' : 'AI 创作中：'}
              {streamState.chapterTitle}
            </span>
            {streamState.mode === 'batch' && <span className="hh-tag">串行队列</span>}
            <span className="text-xs text-content-tertiary tabular-nums">{streamState.content.length.toLocaleString()} 字</span>
          </div>
          <div className="flex items-center gap-2">
            {streamJob && (
              <button onClick={onToggleProcess} className="hh-btn-ghost hh-btn-sm">
                {showProcess ? '收起过程' : '查看过程'}
              </button>
            )}
            {!streamDone && !batchRunning && (
              <button onClick={onHide} className="hh-btn-ghost hh-btn-sm">
                后台运行
              </button>
            )}
            {(!streamDone || batchRunning) && (
              <button onClick={onCancel} className="hh-btn-ghost hh-btn-sm text-cinnabar hover:bg-cinnabar-wash hover:text-cinnabar-deep">
                {batchRunning ? '取消批量' : isRewrite ? '停止重写' : '停止生成'}
              </button>
            )}
            {streamDone && !batchRunning && (
              <button onClick={onClose} className="hh-btn-ghost hh-btn-sm">
                关闭面板
              </button>
            )}
          </div>
        </div>
        <div className="hh-progress mt-3">
          <div
            className={cn('hh-progress-bar', streamDone && 'bg-brand-400', streamJob?.status === 'error' && 'bg-cinnabar')}
            style={{ width: `${Math.min(streamState.progress, 100)}%` }}
          />
        </div>
        <p className="mt-2 text-xs text-content-tertiary">
          {streamJob?.status === 'error' ? `${isRewrite ? '重写' : '生成'}失败：${streamJob.error ?? ''}` : streamState.message}
        </p>
      </div>

      {/* 过程面板：阶段 / MCP 工具 / 参考资料（记忆、参考包） */}
      {streamJob && showProcess && (
        <div className="border-b border-surface-border/80 bg-white/40 px-5 py-4">
          <AIJobProcess job={streamJob} />
        </div>
      )}

      <div className="flex min-h-[400px]">
        {/* 流式内容编辑区 */}
        <div className="flex flex-1 flex-col">
          <textarea
            ref={textareaRef}
            value={streamState.content}
            readOnly
            className="lj-manuscript min-h-[400px] w-full flex-1 resize-none !rounded-none !border-0 !bg-transparent p-5 !text-[15px] !leading-8 !shadow-none outline-none focus:!shadow-none"
            placeholder={isRewrite ? 'AI 正在重写…' : 'AI 正在创作中…'}
          />
          {streamDone && !batchRunning && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-border bg-surface-paper px-5 py-3">
              <span className="text-xs text-content-secondary">
                这是<span className="font-medium text-content">候选稿</span>，正文还没变：到候选稿面板查看审校报告，可直接采用、改几句再采用或丢弃。
              </span>
              <button onClick={onReviewCandidate} className="hh-btn-primary hh-btn-sm shrink-0">
                <FileCheck2 className="h-4 w-4" />
                审阅候选稿
              </button>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
