/**
 * 全局智能助笔（参考岚笺 GlobalAssistantHost）：项目内每个页面都可用的右侧抽屉，书架等项目外页面不挂载。
 * 三个界面：对话（一个输入框，助笔用全书工具定位目标）/ 核对（本书需要注意的事项）/ 任务（后台任务、处理记录、对话记录）。
 * 对话界面始终挂着（关掉只是隐藏），草稿、滚动位置和进行中的任务都不会丢。
 * 版式：56px 头部 = 记录 · 新对话 · 标题，右边宽屏 / 关闭；下面一条页签（对话 / 核对 / 任务）；
 * 宽屏模式以外左边缘可以拖宽（宽度存 localStorage）。正文外观是 AI 助手面板（globals.css 的 as-*）。
 */
import { useCallback, useEffect, type CSSProperties } from 'react';
import { useNavigate } from 'react-router-dom';
import { History, NotebookPen, PanelRightClose, PanelRightOpen, Plus, Sparkles, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useRunningAIJobs } from '@/store/aiJobsStore';
import { isWideViewport, useAssistantStore, type AssistantMode } from '@/store/assistantStore';
import { ResizeHandle } from '@/components/project-shell/ResizeHandle';
import { RIGHT_PANE, RIGHT_PANE_KEY } from '@/components/project-shell/paneSizes';
import { usePaneWidth } from '@/components/project-shell/usePaneWidth';
import { AssistantChecks } from './AssistantChecks';
import { AssistantConversation } from './AssistantConversation';
import { AssistantTasks } from './AssistantTasks';

const MODES: { id: AssistantMode; label: string }[] = [
  { id: 'agent', label: '对话' },
  { id: 'checks', label: '核对' },
  { id: 'tasks', label: '任务' },
];

export function GlobalAssistantHost({ projectId }: { projectId: string }) {
  const open = useAssistantStore((s) => s.open);
  const mode = useAssistantStore((s) => s.mode);
  const wide = useAssistantStore((s) => s.wide);
  const setOpen = useAssistantStore((s) => s.setOpen);
  const setMode = useAssistantStore((s) => s.setMode);
  const setWide = useAssistantStore((s) => s.setWide);
  const compose = useAssistantStore((s) => s.compose);
  const requestNewSession = useAssistantStore((s) => s.requestNewSession);
  const openReview = useAssistantStore((s) => s.openReview);
  const toggleMemo = useAssistantStore((s) => s.toggleMemo);
  const running = useRunningAIJobs(projectId);
  const navigate = useNavigate();
  const pane = usePaneWidth(RIGHT_PANE_KEY, RIGHT_PANE);

  // 窄屏上抽屉盖满整屏：作者点了「去页面查看」之类就收起，不然跳过去了也看不见；
  // 一轮结束时团队自己带过去的（auto）不收，作者还要看回复
  const onNavigate = useCallback(
    (page: string, search?: string, auto?: boolean) => {
      navigate(`/project/${projectId}/${page}${search ? `?${search}` : ''}`);
      if (!auto && !isWideViewport()) setOpen(false);
    },
    [navigate, projectId, setOpen],
  );

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && wide) setWide(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, wide, setWide]);

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-black/25 lg:hidden" onClick={() => setOpen(false)} />}
      {open && !wide && (
        <ResizeHandle
          side="right"
          width={pane.width}
          limits={RIGHT_PANE}
          label="智能助笔宽度"
          onResize={pane.setWidth}
          onCommit={pane.commit}
          className="hidden lg:block"
        />
      )}
      <aside
        aria-label="智能助笔"
        aria-hidden={!open}
        style={{ '--ws-right': `${pane.width}px` } as CSSProperties}
        className={cn(
          // lg:relative z-30：压过页面顶栏（z-20）——宽屏抽屉把主栏挤窄时，顶栏右侧的徽标会伸进抽屉、盖住标题
          'ws-assistant flex h-full flex-none flex-col border-l border-surface-border bg-surface-paper lg:relative lg:z-30',
          'max-lg:fixed max-lg:inset-y-0 max-lg:right-0 max-lg:z-50 max-lg:w-[min(440px,100vw)] max-lg:shadow-xl',
          wide ? 'lg:w-[min(760px,58vw)]' : 'lg:w-[var(--ws-right)]',
          !open && 'hidden',
        )}
      >
        <header className="flex h-14 flex-none items-center gap-1 border-b border-surface-border px-3">
          <button
            onClick={() => setMode('tasks')}
            className={cn('ws-icon-btn h-8 w-8', mode === 'tasks' && 'ws-icon-btn--on')}
            title="任务与对话记录"
          >
            <History className="h-4 w-4" />
          </button>
          <button onClick={requestNewSession} className="ws-icon-btn ws-icon-btn--on h-8 w-8" title="新对话（之前的对话在「任务」里回看）">
            <Plus className="h-4 w-4" />
          </button>
          <span className="ml-1 flex min-w-0 items-center gap-1.5 text-[13px] font-medium text-content">
            <Sparkles className="h-3.5 w-3.5 shrink-0 text-brand" />
            <span className="truncate">智能助笔 · 共创室</span>
          </span>
          <div className="ml-auto flex items-center gap-0.5">
            <button onClick={toggleMemo} className="ws-icon-btn h-8 w-8" title="作品备忘：你的长期偏好与已定约定，每轮都带给团队">
              <NotebookPen className="h-4 w-4" />
            </button>
            <button onClick={() => setWide(!wide)} className="ws-icon-btn hidden h-8 w-8 lg:inline-flex" title={wide ? '收起宽屏' : '展开宽屏'}>
              {wide ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
            </button>
            <button onClick={() => setOpen(false)} className="ws-icon-btn h-8 w-8" title="关闭（Alt+A）">
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>
        <nav className="ws-session-tabs" aria-label="智能助笔区域">
          {MODES.map((m) => (
            <button
              key={m.id}
              onClick={() => setMode(m.id)}
              aria-pressed={mode === m.id}
              className={cn('ws-session-tab', mode === m.id && 'ws-session-tab--on')}
            >
              {m.label}
              {m.id === 'tasks' && running.length > 0 && (
                <span className="as-dot bg-gold-400" aria-label="有正在运行的任务" />
              )}
            </button>
          ))}
        </nav>
        <div className="min-h-0 flex-1">
          <div className={cn('h-full', mode !== 'agent' && 'hidden')}>
            <AssistantConversation key={projectId} projectId={projectId} onNavigate={onNavigate} />
          </div>
          {mode === 'checks' && (
            <AssistantChecks
              projectId={projectId}
              onNavigate={onNavigate}
              onAsk={compose}
              onOpenReview={openReview}
            />
          )}
          {mode === 'tasks' && <AssistantTasks projectId={projectId} onOpenConversation={() => setMode('agent')} />}
        </div>
      </aside>
    </>
  );
}
