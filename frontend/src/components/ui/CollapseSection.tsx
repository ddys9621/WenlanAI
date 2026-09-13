/** 可折叠分组：原生 <details>，零 JS；替代 antd Collapse（ghost） */
import type { ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';

export function CollapseSection({
  title, count, defaultOpen = true, className, children,
}: { title: ReactNode; count?: number; defaultOpen?: boolean; className?: string; children: ReactNode }) {
  return (
    <details open={defaultOpen} className={cn('group', className)}>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 py-2 text-[13px] font-semibold text-content select-none [&::-webkit-details-marker]:hidden">
        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-content-tertiary transition-transform group-open:rotate-90" />
        <span className="flex items-center gap-1.5">{title}</span>
        {count != null && <span className="bg-surface-hover px-1.5 py-px text-[11px] font-medium text-content-secondary tabular-nums">{count}</span>}
      </summary>
      <div className="pb-2 pl-5">{children}</div>
    </details>
  );
}
