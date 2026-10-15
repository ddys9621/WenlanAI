/**
 * 正文自动保存（参考岚笺保存队列）：停笔 delay 毫秒后保存，连续输入最多 maxWait 毫秒必存一次；同一时刻只有一个保存在飞，
 * 保存途中又改了就存完再排下一次。每次保存带上次的正文指纹（base），409 = 正文在别处被改过 → conflict，暂停自动保存，
 * 直到作者选「载入最新」（reset）或「用我的版本覆盖」（overwrite，不带 base，旧稿进历史版本）；其他失败 → error，retryDelay 后重试。
 */

export type SaveStatus = 'saved' | 'dirty' | 'saving' | 'error' | 'conflict'

export interface SaveResult {
  contentHash: string
  content: string
}

export class ConflictError extends Error {}

export interface AutosaveOptions {
  content: string
  baseHash: string | null
  save: (content: string, baseHash: string | null) => Promise<SaveResult>
  onStatus?: (status: SaveStatus, error?: string) => void
  onSaved?: (result: SaveResult) => void
  delay?: number
  maxWait?: number
  retryDelay?: number
}

export class AutosaveController {
  private saved: string
  private current: string
  private hash: string | null
  private status: SaveStatus = 'saved'
  private timer: ReturnType<typeof setTimeout> | null = null
  private firstDirtyAt: number | null = null
  private inflight: Promise<void> | null = null
  private disposed = false
  private readonly delay: number
  private readonly maxWait: number
  private readonly retryDelay: number
  private readonly opts: AutosaveOptions

  constructor(opts: AutosaveOptions) {
    this.opts = opts
    this.saved = this.current = opts.content
    this.hash = opts.baseHash
    this.delay = opts.delay ?? 1500
    this.maxWait = opts.maxWait ?? 10000
    this.retryDelay = opts.retryDelay ?? 5000
  }

  get dirty(): boolean {
    return this.current !== this.saved
  }

  get baseHash(): string | null {
    return this.hash
  }

  get state(): SaveStatus {
    return this.status
  }

  update(content: string): void {
    this.current = content
    if (this.status === 'conflict' || this.disposed) return
    if (!this.dirty) {
      this.clearTimer()
      this.firstDirtyAt = null
      if (!this.inflight) this.setStatus('saved')
      return
    }
    this.firstDirtyAt ??= Date.now()
    if (!this.inflight) this.setStatus('dirty')
    this.schedule()
  }

  /** 立即保存（有未保存的修改时），等保存结束 */
  flush(): Promise<void> {
    this.clearTimer()
    return this.run()
  }

  /** 外部换了正文（采用候选稿 / 恢复旧版 / 冲突后载入最新）：以它为新的已保存基准 */
  reset(content: string, baseHash: string | null): void {
    this.clearTimer()
    this.saved = this.current = content
    this.hash = baseHash
    this.firstDirtyAt = null
    this.setStatus('saved')
  }

  /** 冲突后「用我的版本覆盖」：不带 base 保存（服务端先把当前正文存进历史版本） */
  async overwrite(): Promise<void> {
    if (this.status !== 'conflict') return
    this.hash = null
    this.setStatus('dirty')
    await this.run()
  }

  dispose(): void {
    this.disposed = true
    this.clearTimer()
  }

  private async run(): Promise<void> {
    if (this.inflight) {
      await this.inflight
      return this.dirty && this.status === 'dirty' ? this.run() : undefined
    }
    if (!this.dirty || this.status === 'conflict') return
    const content = this.current
    this.setStatus('saving')
    this.inflight = this.saveOnce(content).finally(() => { this.inflight = null })
    await this.inflight
    if (this.dirty && this.status === 'dirty' && !this.disposed) this.schedule()
  }

  private async saveOnce(content: string): Promise<void> {
    try {
      const result = await this.opts.save(content, this.hash)
      this.saved = content
      this.hash = result.contentHash
      this.firstDirtyAt = this.dirty ? Date.now() : null
      this.opts.onSaved?.(result)
      this.setStatus(this.dirty ? 'dirty' : 'saved')
    } catch (error) {
      if (error instanceof ConflictError) {
        this.setStatus('conflict', error.message)
        return
      }
      this.setStatus('error', error instanceof Error ? error.message : '保存失败')
      if (!this.disposed) this.schedule(this.retryDelay)
    }
  }

  private schedule(wait?: number): void {
    this.clearTimer()
    const due = wait ?? Math.max(0, Math.min(this.delay, (this.firstDirtyAt ?? Date.now()) + this.maxWait - Date.now()))
    this.timer = setTimeout(() => {
      this.timer = null
      void this.run()
    }, due)
  }

  private clearTimer(): void {
    if (this.timer !== null) clearTimeout(this.timer)
    this.timer = null
  }

  private setStatus(status: SaveStatus, error?: string): void {
    if (status === this.status && !error) return
    this.status = status
    this.opts.onStatus?.(status, error)
  }
}
