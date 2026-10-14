/** 内容修改候选：修改前 / 建议修改为 对比（只标改动的句子），作者应用才写入，可撤销；对不上时拒绝而不是覆盖。 */
import { useMemo, useState } from 'react';
import { isAxiosError } from 'axios';
import { Check, ExternalLink, Loader2, Undo2, X } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { assistantApi } from '@/services/api';
import { emitAssistantData } from '@/store/assistantStore';
import type { AssistantFieldCandidate } from '@/types/assistant';
import { diffBlocks, formatFieldValue } from '@/utils/assistantText';

const STATUS: Record<AssistantFieldCandidate['status'], { label: string; cls: string }> = {
  candidate: { label: '待确认', cls: 'lj-badge--candidate' },
  applied: { label: '已应用', cls: 'lj-badge--ok' },
  undone: { label: '已撤销', cls: 'lj-badge--muted' },
  rejected: { label: '没有采用', cls: 'lj-badge--muted' },
};

const errorDetail = (err: unknown) => {
  if (isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') return detail;
  }
  return err instanceof Error ? err.message : '操作失败';
};

interface FieldCandidateCardProps {
  projectId: string;
  candidate: AssistantFieldCandidate;
  onChange: (next: AssistantFieldCandidate) => void;
  onOpenPage?: (page: string) => void;
}

export function FieldCandidateCard({ projectId, candidate, onChange, onOpenPage }: FieldCandidateCardProps) {
  const [busy, setBusy] = useState(false);
  const before = formatFieldValue(candidate.before);
  const after = formatFieldValue(candidate.after);
  const blocks = useMemo(() => diffBlocks(before, after), [before, after]);
  const changes = blocks.filter((b) => b.kind === 'change').length;
  const status = STATUS[candidate.status];

  const act = async (action: 'apply' | 'undo' | 'reject') => {
    setBusy(true);
    try {
      const call = action === 'apply' ? assistantApi.applyCandidate : action === 'undo' ? assistantApi.undoCandidate : assistantApi.rejectCandidate;
      const next = await call(projectId, candidate.id);
      onChange(next);
      if (action !== 'reject') emitAssistantData({ entity: next.entity, targetId: next.target_id });
      toast.success(action === 'apply' ? `已应用到「${candidate.label}」` : action === 'undo' ? '已撤销这次修改' : '已放弃这份候选');
    } catch (err) {
      toast.error(errorDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded border border-brand/30 bg-white">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-surface-border-light px-3 py-2">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold text-content">{candidate.label}</p>
          <p className="text-[11px] text-content-tertiary">修改候选 · 标色处为改动 · {changes} 处</p>
        </div>
        <span className={cn('lj-badge', status.cls)}>{status.label}</span>
      </header>
      {candidate.reason && <p className="border-b border-surface-border-light px-3 py-1.5 text-[11px] text-content-secondary">理由：{candidate.reason}</p>}
      <div className="grid gap-px bg-surface-border-light sm:grid-cols-2">
        <div className="bg-surface-paper px-3 py-2">
          <p className="mb-1 text-[11px] font-medium text-content-tertiary">修改前 · {before.length} 字</p>
          <p className="max-h-56 overflow-y-auto whitespace-pre-wrap text-xs leading-6 text-content-secondary">
            {before === '' ? '（空白）' : blocks.map((b, i) => (
              <span key={i} className={cn(b.kind === 'change' && b.before && 'bg-cinnabar-wash text-cinnabar line-through decoration-cinnabar/40')}>{b.before}</span>
            ))}
          </p>
        </div>
        <div className="bg-white px-3 py-2">
          <p className="mb-1 text-[11px] font-medium text-content-tertiary">建议修改为 · {after.length} 字</p>
          <p className="max-h-56 overflow-y-auto whitespace-pre-wrap text-xs leading-6 text-content">
            {blocks.map((b, i) => (
              <span key={i} className={cn(b.kind === 'change' && b.after && 'bg-brand-100 text-brand-700')}>{b.after}</span>
            ))}
          </p>
        </div>
      </div>
      <footer className="flex flex-wrap items-center justify-end gap-1.5 border-t border-surface-border-light px-3 py-2">
        {candidate.page && onOpenPage && (
          <button onClick={() => onOpenPage(candidate.page!)} className="hh-btn-ghost hh-btn-sm mr-auto h-7 px-2 text-[11px]">
            <ExternalLink className="h-3 w-3" />去页面查看
          </button>
        )}
        {candidate.status === 'candidate' && (
          <>
            <button onClick={() => void act('reject')} disabled={busy} className="hh-btn-ghost hh-btn-sm h-7 px-2 text-[11px]">
              <X className="h-3 w-3" />不用这份
            </button>
            <button onClick={() => void act('apply')} disabled={busy} className="hh-btn-primary hh-btn-sm h-7 px-2.5 text-[11px]">
              {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}应用到此项
            </button>
          </>
        )}
        {candidate.status === 'applied' && (
          <button onClick={() => void act('undo')} disabled={busy} className="hh-btn-secondary hh-btn-sm h-7 px-2.5 text-[11px]">
            {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Undo2 className="h-3 w-3" />}撤销本次修改
          </button>
        )}
      </footer>
    </section>
  );
}
