import { useEffect, useRef, type RefObject } from 'react'

/** 弹层开着时，点到 ref 外面或按 Esc 就关（书架的筛选 / 排序 / 卡片菜单、顶栏的账户菜单共用） */
export function useDismiss(ref: RefObject<HTMLElement>, open: boolean, close: () => void) {
  const closeRef = useRef(close)
  useEffect(() => {
    closeRef.current = close
  })

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) closeRef.current()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeRef.current()
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [ref, open])
}
