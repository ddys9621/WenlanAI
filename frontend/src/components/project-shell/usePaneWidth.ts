import { useCallback, useEffect, useState } from 'react'
import { readWidth, viewportWidth, writeWidth, type PaneLimits } from './paneSizes'

/** 一栏的宽度：拖动时只改状态，松手才存；窗口缩放时按存的宽度（或比例默认值）重新夹一遍 */
export function usePaneWidth(key: string, limits: PaneLimits) {
  const [width, setWidth] = useState(() => readWidth(key, limits, viewportWidth()))

  useEffect(() => {
    const onResize = () => setWidth(readWidth(key, limits, window.innerWidth))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [key, limits])

  const commit = useCallback((value: number) => writeWidth(key, value), [key])
  return { width, setWidth, commit }
}
