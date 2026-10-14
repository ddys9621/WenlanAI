import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface PageHeaderProps {
  title: ReactNode
  eyebrow?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  /** 标题右侧的小徽标（状态 / 计数） */
  badges?: ReactNode
  className?: string
}

/** 页头（参考岚笺）：衬线标题 + 朱砂短下划线 + 右侧操作区，底部细分隔线。 */
export function PageHeader({ title, eyebrow, description, actions, badges, className }: PageHeaderProps) {
  return (
    <header className={cn('lj-page-header', className)}>
      <div className="min-w-0">
        {eyebrow && <p className="hh-eyebrow mb-1.5">{eyebrow}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="lj-page-title">{title}</h1>
          {badges}
        </div>
        {description && <p className="lj-page-desc">{description}</p>}
      </div>
      {actions && <div className="lj-page-actions">{actions}</div>}
    </header>
  )
}
