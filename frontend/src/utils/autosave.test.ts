import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AutosaveController, ConflictError, type SaveResult, type SaveStatus } from './autosave'

function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function setup(save: (content: string, base: string | null) => Promise<SaveResult>) {
  const statuses: SaveStatus[] = []
  const saved: SaveResult[] = []
  const ctl = new AutosaveController({
    content: '旧稿', baseHash: 'h0', save,
    onStatus: (s) => statuses.push(s),
    onSaved: (r) => saved.push(r),
  })
  return { ctl, statuses, saved }
}

const ok = (content: string, base: string | null): Promise<SaveResult> =>
  Promise.resolve({ contentHash: `hash:${content}`, content, base } as SaveResult & { base: string | null })

describe('AutosaveController', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('停笔 1.5 秒后保存，带上次的正文指纹', async () => {
    const save = vi.fn(ok)
    const { ctl, statuses } = setup(save)
    ctl.update('旧稿。新的一句')
    expect(ctl.dirty).toBe(true)
    await vi.advanceTimersByTimeAsync(1400)
    expect(save).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(100)
    expect(save).toHaveBeenCalledWith('旧稿。新的一句', 'h0')
    expect(ctl.dirty).toBe(false)
    expect(ctl.baseHash).toBe('hash:旧稿。新的一句')
    expect(statuses).toEqual(['dirty', 'saving', 'saved'])
  })

  it('一直在打字也最多 10 秒存一次', async () => {
    const save = vi.fn(ok)
    const { ctl } = setup(save)
    for (let i = 1; i <= 24; i++) {
      ctl.update('字'.repeat(i))
      await vi.advanceTimersByTimeAsync(500)
    }
    expect(save).toHaveBeenCalledTimes(1)
    expect(save.mock.calls[0][0]).toBe('字'.repeat(20))
  })

  it('保存途中又改了：存完立刻排下一次，用新指纹', async () => {
    const first = deferred<SaveResult>()
    const save = vi.fn((content: string, base: string | null) => (save.mock.calls.length === 1 ? first.promise : ok(content, base)))
    const { ctl } = setup(save)
    ctl.update('一')
    await vi.advanceTimersByTimeAsync(1500)
    ctl.update('一二')
    first.resolve({ contentHash: 'h1', content: '一' })
    await vi.advanceTimersByTimeAsync(0)
    expect(ctl.dirty).toBe(true)
    await vi.advanceTimersByTimeAsync(1500)
    expect(save).toHaveBeenLastCalledWith('一二', 'h1')
    expect(ctl.dirty).toBe(false)
  })

  it('改回已保存的内容就不用存了', async () => {
    const save = vi.fn(ok)
    const { ctl, statuses } = setup(save)
    ctl.update('旧稿改')
    ctl.update('旧稿')
    await vi.advanceTimersByTimeAsync(5000)
    expect(save).not.toHaveBeenCalled()
    expect(statuses.at(-1)).toBe('saved')
  })

  it('409 冲突：停止自动保存，直到作者选择覆盖', async () => {
    const save = vi.fn((content: string, base: string | null) =>
      base === null ? ok(content, base) : Promise.reject(new ConflictError('正文在别处被改过')))
    const { ctl, statuses } = setup(save)
    ctl.update('我的版本')
    await vi.advanceTimersByTimeAsync(1500)
    expect(statuses.at(-1)).toBe('conflict')
    ctl.update('我的版本，又写了一句')
    await vi.advanceTimersByTimeAsync(20000)
    expect(save).toHaveBeenCalledTimes(1)
    await ctl.overwrite()
    expect(save).toHaveBeenLastCalledWith('我的版本，又写了一句', null)
    expect(statuses.at(-1)).toBe('saved')
  })

  it('其他失败：标记出错，5 秒后自动重试', async () => {
    let fail = true
    const save = vi.fn((content: string, base: string | null) => (fail ? Promise.reject(new Error('网络断了')) : ok(content, base)))
    const { ctl, statuses } = setup(save)
    ctl.update('写了一句')
    await vi.advanceTimersByTimeAsync(1500)
    expect(statuses.at(-1)).toBe('error')
    fail = false
    await vi.advanceTimersByTimeAsync(5000)
    expect(save).toHaveBeenCalledTimes(2)
    expect(statuses.at(-1)).toBe('saved')
  })

  it('flush 立即保存并等它完成；reset 换成新的基准', async () => {
    const save = vi.fn(ok)
    const { ctl, saved } = setup(save)
    ctl.update('马上存')
    await ctl.flush()
    expect(save).toHaveBeenCalledTimes(1)
    expect(saved).toHaveLength(1)
    ctl.update('没存的')
    ctl.reset('别处的新稿', 'h9')
    expect(ctl.dirty).toBe(false)
    expect(ctl.baseHash).toBe('h9')
    await vi.advanceTimersByTimeAsync(5000)
    expect(save).toHaveBeenCalledTimes(1)
  })

  it('dispose 后不再自动保存', async () => {
    const save = vi.fn(ok)
    const { ctl } = setup(save)
    ctl.update('写了')
    ctl.dispose()
    await vi.advanceTimersByTimeAsync(5000)
    expect(save).not.toHaveBeenCalled()
  })
})
