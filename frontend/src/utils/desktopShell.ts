/** 桌面版（pywebview 窗口）注入的 window.pywebview.api；浏览器里不存在。方法由 backend/start_app.py 的 MainAPI 提供。 */
export interface DesktopApi {
  open_logs: () => Promise<unknown>
}

declare global {
  interface Window {
    pywebview?: { api?: Partial<DesktopApi> }
  }
}

export function getDesktopApi(win: Pick<Window, 'pywebview'> | undefined): DesktopApi | null {
  const api = win?.pywebview?.api
  return api && typeof api.open_logs === 'function' ? (api as DesktopApi) : null
}
