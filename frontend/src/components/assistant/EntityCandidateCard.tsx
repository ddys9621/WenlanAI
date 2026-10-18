/** 新建对象候选：列出拟新建的角色 / 组织字段，作者「建档」才真正写入，可放弃；与内容修改候选并列。 */
import { useState } from 'react';
import { isAxiosError } from 'axios';
import { Check, ExternalLink, Loader2, UserPlus, X } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { assistantApi } from '@/services/api';
import { emitAssistantData } from '@/store/assistantStore';
import type { AssistantEntityCandidate } from '@/types/assistant';

const STATUS: Record<AssistantEntityCandidate['status'], { label: string; cls: string }> = {
  candidate: { label: '待确认', cls: 'lj-badge--candidate' },
  applied: { label: '已建档', cls: 'lj-badge--ok' },
  rejected: { label: '没有采用', cls: 'lj-badge--muted' },
};

const ENTITY_LABEL: Record<string, string> = { character: '角色', organization: '组织', setting_entry: '设定条目' };

const FIELD_LABELS: Record<string, string> = {
  role_type: '角色类型', age: '年龄', gender: '性别', personality: '性格', background: '背景',
  appearance: '外貌', speech_style: '说话风格', organization_type: '组织类型', organization_purpose: '宗旨',
  category: '分类', summary: '简述', details: '详细设定',
};
const ROLE_LABELS: Record<string, string> = { protagonist: '主角', supporting: '配角', antagonist: '反派' };
const FIELD_ORDER = ['role_type', 'organization_type', 'organization_purpose', 'age', 'gender', 'appearance',
  'speech_style', 'category', 'summary', 'personality', 'background', 'details'];

const errorDetail = (err: unknown) => {
  if (isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') return detail;
  }
  return err instanceof Error ? err.message : '操作失败';
};

interface EntityCandidateCardProps {
  projectId: string;
  candidate: AssistantEntityCandidate;
  onChange: (next: AssistantEntityCandidate) => void;
  onOpenPage?: (page: string) => void;
}

export function EntityCandidateCard({ projectId, candidate, onChange, onOpenPage }: EntityCandidateCardProps) {
  const [busy, setBusy] = useState(false);
  const status = STATUS[candidate.status];
  const rest = candidate.payload;
  const rows = FIELD_ORDER
    .filter((k) => rest[k])
    .map((k) => ({ key: k, label: FIELD_LABELS[k] ?? k, value: k === 'role_type' ? (ROLE_LABELS[rest[k]] ?? rest[k]) : rest[k] }));

  const act = async (action: 'apply' | 'reject') => {
    setBusy(true);
    try {
      const call = action === 'apply' ? assistantApi.applyEntityCandidate : assistantApi.rejectEntityCandidate;
      const next = await call(projectId, candidate.id);
      onChange(next);
      if (action === 'apply') {
        emitAssistantData({ entity: next.entity_type, targetId: next.created_entity_id });
        toast.success(`已建档：${candidate.label}`);
      } else {
        toast.success('已放弃这份新建候选');
      }
    } catch (err) {
      toast.error(errorDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded border border-brand/30 bg-white">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-surface-border-light px-3 py-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <UserPlus className="h-3.5 w-3.5 flex-none text-brand" />
          <div className="min-w-0">
            <p className="truncate text-xs font-semibold text-content">{candidate.label}</p>
            <p className="text-[11px] text-content-tertiary">新建{ENTITY_LABEL[candidate.entity_type] ?? '对象'} · 作者确认后才建档</p>
          </div>
        </div>
        <span className={cn('lj-badge', status.cls)}>{status.label}</span>
      </header>
      {candidate.reason && <p className="border-b border-surface-border-light px-3 py-1.5 text-[11px] text-content-secondary">理由：{candidate.reason}</p>}
      <dl className="max-h-56 space-y-1.5 overflow-y-auto px-3 py-2">
        {rows.length === 0 && <p className="text-[11px] text-content-tertiary">只有名字，其余留空（建档后可在页面补充）</p>}
        {rows.map((r) => (
          <div key={r.key}>
            <dt className="text-[11px] font-medium text-content-tertiary">{r.label}</dt>
            <dd className="whitespace-pre-wrap text-xs leading-6 text-content">{r.value}</dd>
          </div>
        ))}
      </dl>
      <footer className="flex flex-wrap items-center justify-end gap-1.5 border-t border-surface-border-light px-3 py-2">
        {candidate.status !== 'candidate' && candidate.page && onOpenPage && (
          <button onClick={() => onOpenPage(candidate.page!)} className="hh-btn-ghost hh-btn-sm mr-auto h-7 px-2 text-[11px]">
            <ExternalLink className="h-3 w-3" />去页面查看
          </button>
        )}
        {candidate.status === 'candidate' && (
          <>
            <button onClick={() => void act('reject')} disabled={busy} className="hh-btn-ghost hh-btn-sm h-7 px-2 text-[11px]">
              <X className="h-3 w-3" />不建
            </button>
            <button onClick={() => void act('apply')} disabled={busy} className="hh-btn-primary hh-btn-sm h-7 px-2.5 text-[11px]">
              {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}建档
            </button>
          </>
        )}
      </footer>
    </section>
  );
}
