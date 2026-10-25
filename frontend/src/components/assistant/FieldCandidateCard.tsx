/** 内容修改候选：修改前 / 建议改为 对比（只标改动的句子），作者应用才写入，可撤销；对不上时拒绝而不是覆盖。 */
import { useMemo, useState } from 'react';
import { ArrowUpRight, Check, Loader2, Undo2 } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import type { AssistantFieldCandidate } from '@/types/assistant';
import { diffBlocks, formatFieldValue } from '@/utils/assistantText';
import { errorDetail, fieldAction } from './changeActions';
import { StatusDot, type StatusTone } from './CocreationParts';

const STATUS: Record<AssistantFieldCandidate['status'], { label: string; tone: StatusTone }> = {
  candidate: { label: '待确认', tone: 'orange' },
  applied: { label: '已应用', tone: 'green' },
  undone: { label: '已撤销', tone: 'gray' },
  rejected: { label: '没有采用', tone: 'gray' },
};

interface FieldCandidateCardProps {
  projectId: string;
  candidate: AssistantFieldCandidate;
  onChange: (next: AssistantFieldCandidate) => void;
  onOpenPage?: (page: string) => void;
  /** false = 只看前后对比（在待确认栏里展开时，应用 / 不用在那一行上，不再重复一套） */
  showActions?: boolean;
}

export function FieldCandidateCard({ projectId, candidate, onChange, onOpenPage, showActions = true }: FieldCandidateCardProps) {
  const [busy, setBusy] = useState(false);
  // 选项字段（关系状态、角色类型、分类…）按页面写法对比，不显示英文代码
  const before = formatFieldValue(candidate.before_text ?? candidate.before);
  const after = formatFieldValue(candidate.after_text ?? candidate.after);
  const blocks = useMemo(() => diffBlocks(before, after), [before, after]);
  const changes = blocks.filter((b) => b.kind === 'change').length;
  const status = STATUS[candidate.status];

  const act = async (action: 'apply' | 'undo' | 'reject') => {
    setBusy(true);
    try {
      onChange(await fieldAction(projectId, candidate, action));
      toast.success(action === 'apply' ? `已应用到「${candidate.label}」` : action === 'undo' ? '已撤销这次修改' : '已放弃这份候选');
    } catch (err) {
      toast.error(errorDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="as-card">
      <header className="as-card-head">
        <div className="flex items-center gap-2">
          <span className="as-kind">修改 · {changes} 处</span>
          <span className="ml-auto"><StatusDot tone={status.tone} label={status.label} /></span>
        </div>
        <p className="mt-1.5 truncate text-[14px] font-semibold text-content">{candidate.label}</p>
        {candidate.reason && <p className="mt-1 text-[13px] leading-[1.6] text-content-secondary">{candidate.reason}</p>}
      </header>
      <div className="space-y-3 px-4 pb-3.5">
        <div>
          <p className="as-meta mb-1">修改前 · {before.length} 字</p>
          <p className="max-h-44 overflow-y-auto whitespace-pre-wrap break-words rounded-[8px] bg-surface-paper px-3 py-2 text-[13px] leading-[1.7] text-content-secondary">
            {before === '' ? '（空白）' : blocks.map((b, i) => (
              <span key={i} className={cn(b.kind === 'change' && b.before && 'rounded-sm bg-cinnabar-wash text-cinnabar line-through decoration-cinnabar/40')}>{b.before}</span>
            ))}
          </p>
        </div>
        <div>
          <p className="as-meta mb-1">建议改为 · {after.length} 字</p>
          <p className="max-h-44 overflow-y-auto whitespace-pre-wrap break-words rounded-[8px] border border-surface-border-light px-3 py-2 text-[13px] leading-[1.7] text-content">
            {blocks.map((b, i) => (
              <span key={i} className={cn(b.kind === 'change' && b.after && 'rounded-sm bg-brand-100 text-brand-700')}>{b.after}</span>
            ))}
          </p>
        </div>
      </div>
      <footer className="as-card-foot">
        {candidate.page && onOpenPage && (
          <button onClick={() => onOpenPage(candidate.page!)} className="as-link mr-auto">
            去页面查看<ArrowUpRight className="h-3.5 w-3.5" />
          </button>
        )}
        {showActions && candidate.status === 'candidate' && (
          <>
            <button onClick={() => void act('reject')} disabled={busy} className="as-btn-reject">不用这份</button>
            <button onClick={() => void act('apply')} disabled={busy} className="as-btn-primary">
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}应用
            </button>
          </>
        )}
        {showActions && candidate.status === 'applied' && (
          <button onClick={() => void act('undo')} disabled={busy} className="as-btn-secondary">
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Undo2 className="h-3.5 w-3.5" />}撤销本次修改
          </button>
        )}
      </footer>
    </section>
  );
}
