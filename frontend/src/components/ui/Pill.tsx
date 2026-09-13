/** 小标签（替代 antd Tag 的几种语义色） */
import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export type PillTone = 'default' | 'brand' | 'red' | 'orange' | 'gold' | 'green' | 'purple';

const TONE: Record<PillTone, string> = {
  default: 'bg-surface-hover text-content-secondary',
  brand: 'bg-brand/[0.08] text-brand',
  red: 'bg-red-50 text-red-600',
  orange: 'bg-orange-50 text-orange-600',
  gold: 'bg-amber-50 text-amber-700',
  green: 'bg-emerald-50 text-emerald-600',
  purple: 'bg-violet-50 text-violet-600',
};

export function Pill({ tone = 'default', className, children }: { tone?: PillTone; className?: string; children: ReactNode }) {
  return <span className={cn('inline-flex items-center px-1.5 py-0.5 text-[11px] font-medium leading-4', TONE[tone], className)}>{children}</span>;
}
