/**
 * 章节正文自动保存接 React：每章一个 AutosaveController（停笔 1.5 秒存、最多 10 秒必存、409 冲突暂停）；
 * 换章 / 卸载 / 页面切到后台时立即保存；有未保存修改时关闭或刷新页面先确认。
 * 服务端回显的正文与发出的不一致视为没写进去：按失败处理并稍后重试，不让编辑器误以为已保存。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { chapterApi } from '@/services/api'
import { AutosaveController, ConflictError, type SaveStatus } from '@/utils/autosave'
import type { Chapter } from '@/types'

export interface AutosaveState {
  status: SaveStatus
  error?: string
  savedAt: Date | null
}

function errorText(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string' && detail) return detail
    return error.response ? `保存失败（${error.response.status}）` : '网络断开，稍后自动重试'
  }
  return error instanceof Error ? error.message : '保存失败'
}

export function useChapterAutosave(
  chapter: Pick<Chapter, 'id' | 'content' | 'content_hash'>,
  onSaved: (saved: Chapter) => void,
) {
  const [state, setState] = useState<AutosaveState>({ status: 'saved', savedAt: null })
  const ctlRef = useRef<AutosaveController | null>(null)
  const onSavedRef = useRef(onSaved)
  onSavedRef.current = onSaved

  useEffect(() => {
    const chapterId = chapter.id
    const ctl = new AutosaveController({
      content: chapter.content ?? '',
      baseHash: chapter.content_hash ?? null,
      save: async (content, baseHash) => {
        try {
          const saved = await chapterApi.saveContent(chapterId, content, baseHash)
          if ((saved.content ?? '') !== content) throw new Error('保存没有生效，稍后自动重试')
          onSavedRef.current(saved)
          return { content, contentHash: saved.content_hash ?? '' }
        } catch (error) {
          if (axios.isAxiosError(error) && error.response?.status === 409) throw new ConflictError(errorText(error))
          throw new Error(errorText(error))
        }
      },
      onStatus: (status, error) => setState((prev) => ({ ...prev, status, error })),
      onSaved: () => setState((prev) => ({ ...prev, savedAt: new Date() })),
    })
    ctlRef.current = ctl
    setState({ status: 'saved', savedAt: null })
    return () => {
      void ctl.flush()
      ctl.dispose()
      if (ctlRef.current === ctl) ctlRef.current = null
    }
    // 每章一个控制器；同一章里的正文变化走 update / reset
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapter.id])

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!ctlRef.current?.dirty) return
      void ctlRef.current.flush()
      event.preventDefault()
      event.returnValue = ''
    }
    const hidden = () => {
      if (document.visibilityState === 'hidden') void ctlRef.current?.flush()
    }
    window.addEventListener('beforeunload', beforeUnload)
    document.addEventListener('visibilitychange', hidden)
    return () => {
      window.removeEventListener('beforeunload', beforeUnload)
      document.removeEventListener('visibilitychange', hidden)
    }
  }, [])

  const update = useCallback((content: string) => ctlRef.current?.update(content), [])
  const flush = useCallback(() => ctlRef.current?.flush() ?? Promise.resolve(), [])
  const overwrite = useCallback(() => ctlRef.current?.overwrite() ?? Promise.resolve(), [])
  const reset = useCallback((content: string, baseHash: string | null) => ctlRef.current?.reset(content, baseHash), [])
  const controller = useCallback(() => ctlRef.current, [])

  return { state, update, flush, overwrite, reset, controller }
}
