import { describe, expect, it } from 'vitest'
import { getDesktopApi } from './desktopShell'

describe('getDesktopApi', () => {
  it('浏览器里没有 pywebview：返回 null', () => {
    expect(getDesktopApi({})).toBeNull()
    expect(getDesktopApi(undefined)).toBeNull()
  })

  it('pywebview 已注入但 api 还没就绪（pywebviewready 之前）：返回 null', () => {
    expect(getDesktopApi({ pywebview: {} })).toBeNull()
    expect(getDesktopApi({ pywebview: { api: {} } })).toBeNull()
  })

  it('桌面版：返回带 open_logs 的 api', () => {
    const open_logs = async () => null
    expect(getDesktopApi({ pywebview: { api: { open_logs } } })?.open_logs).toBe(open_logs)
  })
})
