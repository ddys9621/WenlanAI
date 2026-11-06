/** 中栏底部状态栏：作品状态 · 当前页面，右边全书计数。章节写作页用稿纸自带的状态栏。 */
import type { LucideIcon } from 'lucide-react'
import { formatCount, type ProjectStats } from './projectNav'

interface ProjectStatusBarProps {
  status: { label: string; className: string }
  section: string
  icon?: LucideIcon
  stats: ProjectStats
}

export function ProjectStatusBar({ status, section, icon: Icon, stats }: ProjectStatusBarProps) {
  return (
    <footer className="ws-statusbar">
      <div className="flex min-w-0 items-center gap-2">
        <span className={status.className}>{status.label}</span>
        <span className="text-content-tertiary">·</span>
        <span className="flex min-w-0 items-center gap-1 font-medium text-content/90">
          {Icon && <Icon className="h-3.5 w-3.5 shrink-0 text-content-tertiary" />}
          <span className="truncate">{section}</span>
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-3 tabular-nums">
        <span className="hidden sm:inline">大纲 {stats.outlines}</span>
        <span className="hidden sm:inline">角色 {stats.people + stats.organizations}</span>
        <span className="hidden sm:inline">章节 {stats.chapters}</span>
        <span>总字数: {formatCount(stats.words)}</span>
      </div>
    </footer>
  )
}
