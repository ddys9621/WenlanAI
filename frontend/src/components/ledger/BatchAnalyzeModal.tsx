/** 按章序批量分析：伏笔的推进 / 回收要求前文已入账，所以从小到大逐章分析（导入的书、手写的章节、过期分析都靠它补齐） */
import { useEffect, useState } from 'react'
import { Modal } from '@/components/ui/Modal'
import type { BatchAnalyzeRequest } from '@/types/ledger'

const MODES: { value: BatchAnalyzeRequest['mode']; label: string; hint: string }[] = [
  { value: 'stale', label: '补齐并更新', hint: '没分析过的、分析后正文又改过的都分析一遍（推荐）' },
  { value: 'missing', label: '只补没分析的', hint: '已分析过的章一律跳过' },
  { value: 'all', label: '全部重新分析', hint: '范围内每章都重来一遍（耗时、耗 token）' },
]

export function BatchAnalyzeModal({ open, latestChapter, onClose, onStart }: {
  open: boolean
  latestChapter: number
  onClose: () => void
  onStart: (request: BatchAnalyzeRequest) => void
}) {
  const [from, setFrom] = useState(1)
  const [to, setTo] = useState(Math.max(1, latestChapter))
  const [mode, setMode] = useState<BatchAnalyzeRequest['mode']>('stale')

  useEffect(() => {
    if (open) setTo(Math.max(1, latestChapter))
  }, [open, latestChapter])

  return (
    <Modal
      open={open}
      title="按章序分析"
      onClose={onClose}
      size="md"
      footer={(
        <>
          <button onClick={onClose} className="hh-btn-ghost">取消</button>
          <button onClick={() => onStart({ from_chapter: from, to_chapter: Math.max(from, to), mode })} className="hh-btn-primary">开始</button>
        </>
      )}
    >
      <div className="space-y-4 text-sm">
        <div className="flex items-center gap-2 text-content-secondary">
          第<input type="number" min={1} value={from} onChange={(e) => setFrom(Math.max(1, Number(e.target.value) || 1))} className="h-9 w-24" />章
          到<input type="number" min={1} value={to} onChange={(e) => setTo(Math.max(1, Number(e.target.value) || 1))} className="h-9 w-24" />章
        </div>
        <div className="space-y-2">
          {MODES.map((m) => (
            <label key={m.value} className="flex cursor-pointer items-start gap-2">
              <input type="radio" name="analyze-mode" className="mt-1" checked={mode === m.value} onChange={() => setMode(m.value)} />
              <span className="leading-6"><span className="font-medium text-content">{m.label}</span><span className="ml-2 text-xs text-content-secondary">{m.hint}</span></span>
            </label>
          ))}
        </div>
        <p className="text-xs leading-5 text-content-tertiary">
          后台串行执行，关掉页面也不停；某一章失败会记下原因并继续后面的章，之前的分析结果原样保留。正被单独分析的章会跳过。
        </p>
      </div>
    </Modal>
  )
}
