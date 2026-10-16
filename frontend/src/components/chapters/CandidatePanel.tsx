/**
 * 候选稿面板：AI 生成 / 去 AI 味重写 / 智能助笔的结果都先在这里审阅 —— 看审校报告、改几句、采用或丢弃。
 * 采用才写入正文（旧稿自动进历史版本）；生成后正文被改过时要确认覆盖。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { isAxiosError } from 'axios';
import { Check, FileText, Loader2, Trash2, TriangleAlert } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { chapterCandidateApi } from '@/services/api';
import { KbCitationChips } from '@/components/knowledge/KbCitationChips';
import { useKbCitations } from '@/hooks/useKbCitations';
import type { Chapter } from '@/types';
import type { CandidateAdoptResult, CandidateDetail, CandidateSummary } from '@/types/writing';
import { formatServerTime } from '@/utils/serverTime';
import { CANDIDATE_MODE_LABELS, candidateApplyPreview } from '@/utils/writingFlow';
import { AdherenceReportView } from './AdherenceReportView';

interface CandidatePanelProps {
  chapter: Chapter;
  /** 打开时要选中的候选稿（生成完成后跳过来） */
  focusCandidateId?: string | null;
  onAdopted: (result: CandidateAdoptResult) => void;
  /** 候选稿数量变化（丢弃 / 采用）后刷新章节列表 */
  onChanged?: () => void;
}

const errorDetail = (err: unknown): string => {
  if (isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') return detail;
  }
  return err instanceof Error ? err.message : '操作失败';
};

export function CandidatePanel({ chapter, focusCandidateId, onAdopted, onChanged }: CandidatePanelProps) {
  const [items, setItems] = useState<CandidateSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CandidateDetail | null>(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [autoAnalyze, setAutoAnalyze] = useState(false);
  const citations = useKbCitations(chapter.project_id, 'chapter_candidate', detail ? [detail.id] : []);

  const loadList = useCallback(async (prefer?: string | null) => {
    setLoading(true);
    try {
      const res = await chapterCandidateApi.list(chapter.id, 'pending');
      setItems(res.items);
      const next = res.items.find((c) => c.id === prefer) ?? res.items[0] ?? null;
      setSelectedId(next?.id ?? null);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [chapter.id]);

  useEffect(() => { void loadList(focusCandidateId); }, [loadList, focusCandidateId]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    chapterCandidateApi.get(chapter.id, selectedId)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
        setText(d.content);
      })
      .catch(() => { if (!cancelled) setDetail(null); });
    return () => { cancelled = true; };
  }, [chapter.id, selectedId]);

  const edited = detail !== null && text !== detail.content;
  const preview = useMemo(
    () => (detail ? candidateApplyPreview(chapter.content ?? '', detail, text) : null),
    [chapter.content, detail, text],
  );

  const adopt = async (force = false) => {
    if (!detail) return;
    setBusy(true);
    try {
      const result = await chapterCandidateApi.adopt(chapter.id, detail.id, {
        content: edited ? text : undefined,
        force,
        auto_analyze: autoAnalyze,
      });
      toast.success(result.snapshot_version_id ? '已采用：旧稿已存进历史版本，可随时恢复' : '已采用');
      onAdopted(result);
      onChanged?.();
      await loadList();
    } catch (err) {
      const message = errorDetail(err);
      if (isAxiosError(err) && err.response?.status === 409 && message.includes('修改过') && !force) {
        if (window.confirm(`${message}\n\n确定用这份候选稿覆盖吗？`)) {
          setBusy(false);
          await adopt(true);
          return;
        }
      } else {
        toast.error(message);
        if (isAxiosError(err) && err.response?.status === 409) await loadList();
      }
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    if (!detail || !window.confirm('丢弃这份候选稿？丢弃后不能再采用。')) return;
    setBusy(true);
    try {
      await chapterCandidateApi.discard(chapter.id, detail.id);
      toast.success('已丢弃');
      onChanged?.();
      await loadList();
    } catch (err) {
      toast.error(errorDetail(err));
    } finally {
      setBusy(false);
    }
  };

  if (loading && items.length === 0) {
    return <div className="flex flex-1 items-center justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-brand" /></div>;
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-16 text-center">
        <FileText className="h-8 w-8 text-content-tertiary" />
        <p className="mt-3 text-sm font-medium text-content">暂无待审阅的候选稿</p>
        <p className="mt-1 max-w-sm text-xs leading-5 text-content-tertiary">
          AI 生成、去 AI 味重写、智能助笔的结果都会先放在这里，采用后才写入正文——不会再直接覆盖你写的内容。
        </p>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <ul className="shrink-0 divide-y divide-surface-border-light border-b border-surface-border lg:w-56 lg:border-b-0 lg:border-r">
        {items.map((c) => (
          <li key={c.id}>
            <button
              onClick={() => setSelectedId(c.id)}
              className={cn('w-full px-3 py-2.5 text-left hover:bg-surface-hover', c.id === selectedId && 'lj-selected')}
            >
              <div className="flex items-center gap-1.5">
                <span className="lj-badge lj-badge--candidate">{c.source_label}</span>
                <span className="text-[11px] text-content-tertiary">{CANDIDATE_MODE_LABELS[c.mode]}</span>
              </div>
              <p className="mt-1 line-clamp-2 text-xs leading-5 text-content-secondary">{c.preview || '（空）'}</p>
              <p className="mt-1 flex flex-wrap gap-1 text-[11px] text-content-tertiary">
                <span className="tabular-nums">{c.word_count.toLocaleString()} 字</span>
                {c.adherence?.passed === false && <span className="lj-badge lj-badge--stale">偏离章纲</span>}
                {c.base_stale && <span className="lj-badge lj-badge--draft">正文已改</span>}
              </p>
            </button>
          </li>
        ))}
      </ul>

      {detail ? (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="space-y-3 border-b border-surface-border px-5 py-4">
            <div className="flex flex-wrap items-center gap-2 text-xs text-content-secondary">
              <span className="lj-badge lj-badge--candidate">{detail.source_label}</span>
              <span>{CANDIDATE_MODE_LABELS[detail.mode]}</span>
              <span className="tabular-nums">· {detail.word_count.toLocaleString()} 字</span>
              {typeof detail.quality?.score === 'number' && <span className="tabular-nums">· AI 味 {detail.quality.score}</span>}
              <span className="text-content-tertiary">· {formatServerTime(detail.created_at)}</span>
            </div>
            {(detail.base_stale || detail.outline_changed) && (
              <div className="flex items-start gap-2 rounded border border-gold-300/50 bg-gold-50 px-3 py-2 text-xs text-gold-500">
                <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <div className="space-y-0.5">
                  {detail.base_stale && <p>正文在生成这份候选稿之后被修改过，整章采用会覆盖这些修改（当前正文会先存进历史版本）。</p>}
                  {detail.outline_changed && <p>生成期间章纲被改过，这份候选稿可能和新章纲对不上。</p>}
                </div>
              </div>
            )}
            <AdherenceReportView report={detail.adherence} />
            <KbCitationChips citations={citations[detail.id]} />
          </div>

          <div className="flex min-h-0 flex-1 flex-col">
            {detail.mode === 'replace_range' && detail.original_text && (
              <div className="border-b border-surface-border-light bg-surface-paper px-5 py-3">
                <p className="mb-1 text-[11px] font-medium text-content-tertiary">原文（将被替换）</p>
                <p className="lj-manuscript whitespace-pre-wrap text-[14px] leading-7 text-content-tertiary line-through">{detail.original_text}</p>
              </div>
            )}
            {detail.mode === 'append' && (
              <p className="border-b border-surface-border-light bg-surface-paper px-5 py-2 text-[11px] text-content-tertiary">这段会接在正文末尾</p>
            )}
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              className="lj-manuscript min-h-[320px] w-full flex-1 resize-none !rounded-none !border-0 !bg-transparent px-5 py-4 !text-[15px] !leading-8 !shadow-none focus:!shadow-none"
              aria-label="候选稿内容（可直接修改后采用）"
            />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-border bg-surface-paper px-5 py-3">
            <div className="flex flex-wrap items-center gap-3 text-xs text-content-secondary">
              {edited && <span className="lj-badge lj-badge--draft">已修改，采用时用你改过的版本</span>}
              {preview === null && <span className="lj-badge lj-badge--stale">选段在正文里对不上了，无法采用</span>}
              <label className="flex cursor-pointer items-center gap-1.5">
                <input type="checkbox" checked={autoAnalyze} onChange={(e) => setAutoAnalyze(e.target.checked)} />
                采用后自动分析本章
              </label>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => void discard()} disabled={busy} className="hh-btn-ghost hh-btn-sm text-cinnabar hover:bg-cinnabar-wash">
                <Trash2 className="h-3.5 w-3.5" />
                丢弃
              </button>
              <button onClick={() => void adopt()} disabled={busy || preview === null || !text.trim()} className="hh-btn-primary hh-btn-sm">
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                {edited ? '采用修改后的版本' : '采用'}
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-brand" /></div>
      )}
    </div>
  );
}
