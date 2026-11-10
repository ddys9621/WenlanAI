import { Loader2, Sparkles } from 'lucide-react'

export function PageLoading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-transparent px-4 supports-[height:100dvh]:min-h-dvh">
      <div className="fanqie-soft-card flex min-w-[240px] flex-col items-center gap-4 px-8 py-10 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-brand/10 text-brand">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
        <div>
          <p className="text-base font-semibold text-content">正在准备创作空间</p>
          <p className="mt-1 flex items-center justify-center gap-1 text-sm text-content-secondary">
            <Sparkles className="h-3.5 w-3.5 text-brand" />
            请稍候，界面马上就绪
          </p>
        </div>
      </div>
    </div>
  )
}
