import { createContext, useContext } from 'react'

export interface ProjectShell {
  /** 左栏「目录」页签里留给章节写作页的位置：页面把自己的章节目录 portal 进来（状态、按钮都还在页面里） */
  directorySlot: HTMLElement | null
}

export const ProjectShellContext = createContext<ProjectShell>({ directorySlot: null })

export function useProjectShell(): ProjectShell {
  return useContext(ProjectShellContext)
}
