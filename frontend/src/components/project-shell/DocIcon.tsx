import { useLocation } from 'react-router-dom'
import { entryOf } from './projectNav'

/** 页头标题前的小图标：按地址取左栏入口卡片的图标，不在入口下的页面不画 */
export function DocIcon() {
  const { pathname } = useLocation()
  const entry = entryOf(pathname)
  return entry ? <entry.icon className="h-5 w-5 shrink-0 text-content-tertiary" strokeWidth={1.75} aria-hidden /> : null
}
