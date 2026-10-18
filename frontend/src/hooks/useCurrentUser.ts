import { createContext, useContext } from 'react'
import type { User } from '@/types'

/** 当前登录用户：ProtectedRoute 确认登录后提供，受保护页面里都能读到（侧栏、管理员路由按 is_admin 判断） */
export const CurrentUserContext = createContext<User | null>(null)

export function useCurrentUser(): User | null {
  return useContext(CurrentUserContext)
}
