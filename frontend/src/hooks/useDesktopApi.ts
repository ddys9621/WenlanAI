import { useEffect, useState } from 'react'
import { getDesktopApi, type DesktopApi } from '@/utils/desktopShell'

/** 桌面版 api：pywebview 在页面加载完成后才注入（随后派发 pywebviewready），首帧可能还拿不到。 */
export function useDesktopApi(): DesktopApi | null {
  const [api, setApi] = useState(() => getDesktopApi(window))

  useEffect(() => {
    const sync = () => setApi(getDesktopApi(window))
    window.addEventListener('pywebviewready', sync)
    sync()
    return () => window.removeEventListener('pywebviewready', sync)
  }, [])

  return api
}
