/**
 * 当前打开的项目 id：进入项目壳（pages/ProjectDetail）时设置、离开时清空。
 * axios 拦截器（services/api.ts）与 ssePost（utils/sseClient.ts）据此给每个请求带 X-Project-Id；
 * 后端 get_user_ai_service 用它读取项目 AI 偏好，覆盖模型 / 参数（接口仍复用设置页那一套）。
 * 纯模块变量、不碰 window：vitest node 环境可直接测。
 */
export const PROJECT_HEADER = 'X-Project-Id'

let activeProjectId: string | null = null

export function setActiveProjectId(id: string | null): void {
  const trimmed = id?.trim()
  activeProjectId = trimmed ? trimmed : null
}

export function getActiveProjectId(): string | null {
  return activeProjectId
}

/** 有活动项目就在 headers 上追加 X-Project-Id（返回新对象，不改入参） */
export function withProjectHeader(headers: Record<string, string>): Record<string, string> {
  return activeProjectId ? { ...headers, [PROJECT_HEADER]: activeProjectId } : { ...headers }
}
