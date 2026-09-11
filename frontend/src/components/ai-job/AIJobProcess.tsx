/** 过程面板：阶段时间线 + 工具调用 + 参考资料 —— 回答"AI 现在在做什么 / 调用了什么工具 / 参考了什么" */
import { useState } from 'react';
import {
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  Loader2,
  MinusCircle,
  Wrench,
  XCircle,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import type { AIJobReferenceEvent, AIJobStage, AIJobState, AIJobToolCall, StageStatus } from '@/types/ai_job';

export function AIJobProcess({ job }: { job: AIJobState }) {
  const hasProcess = job.stages.length > 0 || job.toolCalls.length > 0 || job.references.length > 0;
  if (!hasProcess) {
    return (
      <p className="text-xs text-content-tertiary">
        {job.status === 'running' ? '等待后端上报过程信息…' : '本次任务没有过程明细。'}
      </p>
    );
  }
  const referenceCount = job.references.reduce((sum, r) => sum + r.count, 0);
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <section className="hh-subpanel p-3">
        <h3 className="mb-2 text-xs font-medium text-content-secondary">过程</h3>
        {job.stages.length === 0 ? (
          <p className="text-xs text-content-tertiary">—</p>
        ) : (
          <ol className="space-y-1.5">
            {job.stages.map((s) => (
              <StageRow key={s.name} stage={s} />
            ))}
          </ol>
        )}
      </section>
      <section className="hh-subpanel space-y-3 p-3">
        <div>
          <h3 className="mb-2 text-xs font-medium text-content-secondary">
            工具调用{job.toolCalls.length > 0 ? `（${job.toolCalls.length}）` : ''}
          </h3>
          {job.toolCalls.length === 0 ? (
            <p className="text-xs text-content-tertiary">未调用外部工具</p>
          ) : (
            <ul className="space-y-1.5">
              {job.toolCalls.map((c) => (
                <ToolCallRow key={c.call_id} call={c} />
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3 className="mb-2 text-xs font-medium text-content-secondary">
            参考资料{referenceCount > 0 ? `（${referenceCount} 条）` : ''}
          </h3>
          {job.references.length === 0 ? (
            <p className="text-xs text-content-tertiary">未注入额外参考</p>
          ) : (
            <ul className="space-y-1.5">
              {job.references.map((r, i) => (
                <ReferenceGroup key={`${r.kind}-${r.seq ?? i}`} group={r} />
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}

function StatusIcon({ status }: { status: StageStatus }) {
  const cls = 'mt-0.5 h-4 w-4 shrink-0';
  if (status === 'running') return <Loader2 className={cn(cls, 'animate-spin text-brand')} />;
  if (status === 'done') return <CheckCircle2 className={cn(cls, 'text-emerald-500')} />;
  if (status === 'error') return <XCircle className={cn(cls, 'text-red-500')} />;
  if (status === 'skipped') return <MinusCircle className={cn(cls, 'text-content-tertiary')} />;
  return <CircleDashed className={cn(cls, 'text-content-tertiary')} />;
}

function StageRow({ stage }: { stage: AIJobStage }) {
  const detail = Object.entries(stage.detail ?? {}).filter(([, v]) => v !== null && v !== undefined && typeof v !== 'object');
  return (
    <li className="flex items-start gap-2 text-sm">
      <StatusIcon status={stage.status} />
      <div className="min-w-0 flex-1">
        <p className={cn('leading-5', stage.status === 'skipped' ? 'text-content-tertiary' : 'text-content')}>
          {stage.label}
          {typeof stage.elapsed === 'number' && (
            <span className="ml-2 text-xs text-content-tertiary tabular-nums">{stage.elapsed.toFixed(1)}s</span>
          )}
        </p>
        {detail.length > 0 && (
          <p className="text-xs text-content-tertiary">{detail.map(([k, v]) => `${k}: ${String(v)}`).join(' · ')}</p>
        )}
        {stage.error && <p className="text-xs text-red-500">{stage.error}</p>}
      </div>
    </li>
  );
}

function ToolCallRow({ call }: { call: AIJobToolCall }) {
  return (
    <li className="text-sm">
      <p className="flex items-center gap-2">
        <StatusIcon status={call.status} />
        <Wrench className="h-3.5 w-3.5 shrink-0 text-content-tertiary" />
        <span className="min-w-0 truncate text-content">
          {call.plugin}.{call.tool}
        </span>
        <span className="ml-auto shrink-0 text-xs text-content-tertiary tabular-nums">
          {typeof call.elapsed_ms === 'number' && `${(call.elapsed_ms / 1000).toFixed(1)}s`}
          {typeof call.result_chars === 'number' && ` · ${call.result_chars.toLocaleString()} 字`}
        </span>
      </p>
      {call.args_preview && (
        <p className="truncate pl-6 text-xs text-content-tertiary" title={call.args_preview}>
          {call.args_preview}
        </p>
      )}
      {call.error && <p className="pl-6 text-xs text-red-500">{call.error}</p>}
    </li>
  );
}

function ReferenceGroup({ group }: { group: AIJobReferenceEvent }) {
  const [open, setOpen] = useState(false);
  const chars = typeof group.chars === 'number' ? group.chars : null;
  return (
    <li className="text-sm">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full items-center gap-2 text-left">
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-content-tertiary" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-content-tertiary" />
        )}
        <BookOpen className="h-3.5 w-3.5 shrink-0 text-brand" />
        <span className="min-w-0 truncate text-content">{group.label}</span>
        <span className="ml-auto shrink-0 text-xs text-content-tertiary tabular-nums">
          {group.count} 条{chars !== null ? ` · ${chars.toLocaleString()} 字` : ''}
        </span>
      </button>
      {open && (
        <ul className="mt-1 space-y-0.5 pl-6">
          {group.items.length === 0 && <li className="text-xs text-content-tertiary">（无条目）</li>}
          {group.items.map((it, i) => (
            <li key={`${it.title}-${i}`} className="text-xs text-content-secondary">
              <span className="text-content">{it.title}</span>
              {it.detail && <span className="text-content-tertiary"> — {it.detail}</span>}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
