/** 项目外页面的全局导航（顶栏与窄屏抽屉共用）和版本状态（顶栏的新版本提示、账户菜单里的版本卡片）。 */
import { BookMarked, BookOpen, Library, Puzzle, Settings, Users, type LucideIcon } from 'lucide-react'
import { useUpdateStore } from '@/store/updateStore'

export interface AppNavItem {
  icon: LucideIcon
  label: string
  path: string
}

export interface AppNavGroup {
  label: string
  adminOnly?: boolean
  items: AppNavItem[]
}

export const APP_NAV_GROUPS: AppNavGroup[] = [
  {
    label: '创作台',
    items: [
      { icon: Library, label: '书架', path: '/projects' },
      { icon: BookOpen, label: '拆书参考', path: '/book-dissect' },
      { icon: BookMarked, label: '知识库', path: '/knowledge' },
      { icon: Puzzle, label: 'MCP 插件', path: '/mcp-plugins' },
      { icon: Settings, label: '设置', path: '/settings' },
    ],
  },
  // 管理台只给管理员看（后端 /admin 接口对普通用户一律 403）
  { label: '管理台', adminOnly: true, items: [{ icon: Users, label: '用户管理', path: '/user-management' }] },
]

export function navGroupsFor(isAdmin: boolean): AppNavGroup[] {
  return APP_NAV_GROUPS.filter((group) => isAdmin || !group.adminOnly)
}

/** 检查更新只对管理员开放（can_manage），新版本提示也只给管理员；版本号谁都看得到 */
export function useVersionStatus() {
  const info = useUpdateStore((s) => s.info)
  const result = useUpdateStore((s) => s.result)
  const hasUpdate = useUpdateStore((s) => s.hasUpdate) && !!info?.can_manage
  const currentVersion = info?.current_version ?? result?.current_version ?? null
  // exe / docker 看 Release 版本，源码运行看落后几个提交
  const updateLabel = !hasUpdate || !result
    ? null
    : result.run_mode === 'source'
      ? `远端有 ${result.git?.behind ?? 0} 个新提交`
      : result.latest
        ? `新版本 v${result.latest.version}`
        : '有新版本'
  const runMode = info?.run_mode === 'source' ? '源码运行' : info?.run_mode === 'docker' ? 'Docker' : info?.run_mode === 'exe' ? '安装版' : ''
  const upToDate = !!info?.can_manage && !!result && !result.has_update
  return { currentVersion, hasUpdate, updateLabel, runMode, upToDate }
}
