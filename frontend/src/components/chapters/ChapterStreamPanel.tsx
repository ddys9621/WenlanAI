/** AI 创作面板：全局正文任务在页面里的视图（关面板 / 切页 / 刷新都不影响任务） */
import { useEffect, useRef } from 'react';
import { LayoutGrid, Loader2, Zap } from 'lucide-react';
import { cn } from '@/lib/utils';
import { AIJobProcess } from '@/components/ai-job/AIJobProcess';
import type { StreamState } from '@/hooks/useChapterWriteJobs';
import type { AIJobState } from '@/types/ai_job';
import type { PlotCardWithLinks } from '@/types';

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
  relatedCards: PlotCardWithLinks[];
  loadingCards: boolean;
  onContentChange: (content: string) => void;
  onSave: () => Promise<void>;
}

const CARD_TYPE_LABEL: Record<string, string> = { plot: '剧情', character: '角色', scene: '场景', conflict: '冲突' };

export function ChapterStreamPanel({
  streamState, streamJob, streamDone, batchRunning, showProcess, onToggleProcess, onHide, onCancel, onClose,
  relatedCards, loadingCards, onContentChange, onSave,
}: ChapterStreamPanelProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isRewrite = streamJob?.kind === 'chapter_regenerate';

  useEffect(() => {
    if (streamDone || !textareaRef.current) return;
    textareaRef.current.scrollTop = textareaRef.current.scrollHeight;
  }, [streamState.content, streamDone]);

  return (
    <section className="hh-panel overflow-hidden border-brand/30">
      <div className="border-b border-surface-border/80 px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center bg-brand/10 text-brand">
              <Zap className="h-4 w-4" />
            </span>
            <span className="text-sm font-semibold text-content">
              {batchRunning ? '批量串行生成：' : streamDone ? '已完成：' : isRewrite ? '去 AI 味重写中：' : 'AI 创作中：'}
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
              <button onClick={onCancel} className="hh-btn-ghost hh-btn-sm text-red-500 hover:bg-red-50 hover:text-red-600">
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
            className={cn('hh-progress-bar', streamDone && 'bg-emerald-500', streamJob?.status === 'error' && 'bg-red-500')}
            style={{ width: `${Math.min(streamState.progress, 100)}%` }}
          />
        </div>
        <p className="mt-2 text-xs text-content-tertiary">
          {streamJob?.status === 'error' ? `${isRewrite ? '重写' : '生成'}失败：${streamJob.error ?? ''}` : streamState.message}
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
                      <span className="hh-tag px-1.5 py-0.5 text-[10px]">{CARD_TYPE_LABEL[card.card_type] ?? '其他'}</span>
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
            ref={textareaRef}
            value={streamState.content}
            onChange={(e) => { if (streamDone) onContentChange(e.target.value); }}
            readOnly={!streamDone}
            className="min-h-[400px] w-full flex-1 resize-none !border-0 !bg-transparent p-5 text-sm leading-7 text-content !shadow-none outline-none focus:!shadow-none"
            placeholder={streamDone ? '生成完成，可直接编辑内容…' : isRewrite ? 'AI 正在重写…' : 'AI 正在创作中…'}
          />
          {streamDone && (
            <div className="flex items-center justify-between gap-3 border-t border-surface-border/80 bg-white/40 px-5 py-3">
              <span className="text-xs text-content-tertiary">已写入正文，可在上方直接编辑。修改后点击「保存修改」更新到数据库。</span>
              <button onClick={() => void onSave()} className="hh-btn-primary hh-btn-sm shrink-0">
                保存修改
              </button>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
