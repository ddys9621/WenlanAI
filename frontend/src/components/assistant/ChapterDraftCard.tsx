/**
 * 对话里的写作卡：write_chapter 写的一章。后台在写时显示进度；写好了就在这里看正文、和现在的正文对比，
 * 直接采用（替换正文，旧稿先进历史版本）或丢弃，不用跳到章节页。自动执行已经采用的显示「已采用」。
 * 卡片认哪份候选稿见 pickWriteCandidate（自动执行采用的那份 / 开写之后的最新一份），状态以章节那边为准。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { isAxiosError } from 'axios';
import { ArrowUpRight, Check, FileText, Loader2, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { chapterApi, chapterCandidateApi } from '@/services/api';
import { useAIJobsStore } from '@/store/aiJobsStore';
import { emitAssistantData } from '@/store/assistantStore';
import type { AssistantChapterWrite } from '@/types/assistant';
import type { CandidateDetail } from '@/types/writing';
import { diffBlocks } from '@/utils/assistantText';
import { pickWriteCandidate, writeCardState, type WriteCardState } from '@/utils/cocreation';
import { loadAutoAnalyze } from '@/utils/writingFlow';
import { errorDetail } from './changeActions';
import { StatusDot, type StatusTone } from './CocreationParts';

const STATE: Record<WriteCardState, { label: string; tone: StatusTone }> = {
  writing: { label: '正在写', tone: 'brand' },
  pending: { label: '待采用', tone: 'orange' },
  adopted: { label: '已采用', tone: 'green' },
  discarded: { label: '已丢弃', tone: 'gray' },
  superseded: { label: '被新稿取代', tone: 'gray' },
  none: { label: '没写出来', tone: 'red' },
};

interface ChapterDraftCardProps {
  write: AssistantChapterWrite;
  /** 去章节写作页（带上候选稿就直接打开它） */
  onOpen: (chapterId: string, candidateId?: string) => void;
}

export function ChapterDraftCard({ write, onOpen }: ChapterDraftCardProps) {
  // 只取用得着的几个值（正文任务每秒几十条 content 事件，整个任务对象每条都换新）
  const writing = useAIJobsStore((s) => s.jobs[write.job_id]?.status === 'running');
  const jobMessage = useAIJobsStore((s) => s.jobs[write.job_id]?.progress?.message);
  const jobWords = useAIJobsStore((s) => s.jobs[write.job_id]?.wordCount);
  const [candidate, setCandidate] = useState<CandidateDetail | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [current, setCurrent] = useState<string | null>(null);
  const [view, setView] = useState<'text' | 'diff'>('text');
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const list = await chapterCandidateApi.list(write.chapter_id, 'all');
      const pick = pickWriteCandidate(write, list.items);
      setCandidate(pick ? await chapterCandidateApi.get(write.chapter_id, pick.id) : null);
    } catch {
      setCandidate(null);
    } finally {
      setLoaded(true);
    }
  }, [write]);

  // 后台写完（任务从运行中变成结束）就读候选稿；刷新页面后任务不在本页记录里，直接读
  useEffect(() => { if (!writing) void load(); }, [writing, load]);

  useEffect(() => {
    if (view !== 'diff' || current !== null) return;
    chapterApi.getChapter(write.chapter_id).then((c) => setCurrent(c.content ?? '')).catch(() => setCurrent(''));
  }, [current, view, write.chapter_id]);

  const blocks = useMemo(
    () => (view === 'diff' && candidate && current !== null ? diffBlocks(current, candidate.content) : []),
    [candidate, current, view],
  );
  const state = writeCardState(writing, candidate);
  const status = STATE[state];
  const notify = () => {
    emitAssistantData({ entity: 'chapter_candidate', chapterId: write.chapter_id });
    emitAssistantData({ entity: 'chapter', chapterId: write.chapter_id });
  };

  const adopt = async (force = false): Promise<void> => {
    if (!candidate) return;
    setBusy(true);
    try {
      const result = await chapterCandidateApi.adopt(write.chapter_id, candidate.id, { force, auto_analyze: loadAutoAnalyze() });
      toast.success(result.snapshot_version_id ? `已采用第 ${write.chapter_number} 章：旧稿存进了历史版本` : `已采用第 ${write.chapter_number} 章`);
      setCurrent(null);
      notify();
      await load();
    } catch (err) {
      const message = errorDetail(err);
      if (!force && isAxiosError(err) && err.response?.status === 409 && message.includes('修改过')
        && window.confirm(`${message}\n\n确定用这份稿子覆盖吗？（现在的正文会先存进历史版本）`)) {
        setBusy(false);
        await adopt(true);
        return;
      }
      toast.error(message);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    if (!candidate || !window.confirm(`丢弃第 ${write.chapter_number} 章这份稿子？丢弃后不能再采用。`)) return;
    setBusy(true);
    try {
      await chapterCandidateApi.discard(write.chapter_id, candidate.id);
      notify();
      await load();
    } catch (err) {
      toast.error(errorDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const title = `第 ${write.chapter_number} 章${write.chapter_title ? `《${write.chapter_title}》` : ''}`;
  return (
    <div className="as-card overflow-hidden" aria-label={`写作卡：${title}`}>
      <div className="flex min-w-0 items-center gap-2 border-b border-surface-border-light px-3 py-2">
        <FileText className="h-3.5 w-3.5 flex-none text-brand" />
        <span className="min-w-0 truncate text-[13px] font-medium text-content">{title}</span>
        <StatusDot tone={status.tone} label={status.label} />
        {candidate && <span className="ml-auto flex-none text-[11px] tabular-nums text-content-tertiary">{candidate.word_count.toLocaleString()} 字</span>}
      </div>

      {writing ? (
        <p className="flex items-center gap-2 px-3 py-3 text-[12px] text-content-secondary">
          <Loader2 className="h-3.5 w-3.5 flex-none animate-spin text-brand" />
          <span className="min-w-0 truncate">{jobMessage || '正文作者在后台写，写好了在这里看'}</span>
          {Boolean(jobWords) && <span className="ml-auto flex-none tabular-nums text-content-tertiary">{jobWords?.toLocaleString()} 字</span>}
        </p>
      ) : !candidate ? (
        <p className="px-3 py-3 text-[12px] text-content-tertiary">
          {loaded ? '没找到这次写出的稿子：可能没写成，或者已经在章节页处理掉了。' : '读取中…'}
        </p>
      ) : (
        <>
          <div className="flex items-center gap-1 px-3 pt-2">
            {(['text', 'diff'] as const).map((v) => (
              <button key={v} onClick={() => setView(v)} aria-pressed={view === v} className={cn('as-chip', view === v && 'as-chip--on')}>
                {v === 'text' ? '正文' : '对比'}
              </button>
            ))}
            {view === 'diff' && current !== null && !current.trim() && (
              <span className="as-meta ml-1">这一章原来是空的，全文都是新写的</span>
            )}
          </div>
          <div className={cn('relative px-3 py-2', !expanded && 'max-h-52 overflow-hidden')}>
            {view === 'text' || current === null ? (
              <p className="lj-manuscript whitespace-pre-wrap break-words text-[13px] leading-7 text-content">
                {view === 'diff' ? '读取现在的正文…' : candidate.content}
              </p>
            ) : (
              <p className="lj-manuscript whitespace-pre-wrap break-words text-[13px] leading-7">
                {blocks.map((b, i) => (b.kind === 'same'
                  ? <span key={i} className="text-content-tertiary">{b.after}</span>
                  : (
                    <span key={i}>
                      {b.before && <del className="bg-cinnabar-wash text-cinnabar">{b.before}</del>}
                      {b.after && <ins className="bg-brand-50 text-brand-700 no-underline">{b.after}</ins>}
                    </span>
                  )))}
              </p>
            )}
            {!expanded && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-white to-transparent" />}
          </div>
          <div className="flex flex-wrap items-center gap-2 border-t border-surface-border-light px-3 py-2">
            <button onClick={() => setExpanded((v) => !v)} className="as-link text-[12px]">{expanded ? '收起' : '展开全文'}</button>
            <div className="ml-auto flex items-center gap-1.5">
              <button onClick={() => onOpen(write.chapter_id, candidate.id)} className="as-chip" title="去章节写作页（审校报告、改几句再采用都在那边）">
                <ArrowUpRight className="h-3.5 w-3.5" />章节页
              </button>
              {state === 'pending' && (
                <>
                  <button onClick={() => void discard()} disabled={busy} className="as-chip hover:text-cinnabar">
                    <Trash2 className="h-3.5 w-3.5" />丢弃
                  </button>
                  <button onClick={() => void adopt()} disabled={busy || !candidate.content.trim()} className="as-btn-primary px-3">
                    {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                    {candidate.mode === 'replace_all' ? '采用（替换正文）' : '采用'}
                  </button>
                </>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
