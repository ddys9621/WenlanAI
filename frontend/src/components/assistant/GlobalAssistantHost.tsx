/**
 * 全局智能助笔（参考岚笺 GlobalAssistantHost）：项目内每个页面都可用的右侧抽屉，书架等项目外页面不挂载。
 * 三个界面：对话（一个输入框，助笔用全书工具定位目标）/ 核对（本书需要注意的事项）/ 任务（后台任务、处理记录、对话记录）。
 * 对话界面始终挂着（关掉只是隐藏），草稿、滚动位置和进行中的任务都不会丢。
 */
import { useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Maximize2, Minimize2, Sparkles, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useRunningAIJobs } from '@/store/aiJobsStore';
import { useAssistantStore, type AssistantMode } from '@/store/assistantStore';
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
  const running = useRunningAIJobs(projectId);
  const navigate = useNavigate();

  const onNavigate = useCallback(
    (page: string, search?: string) => navigate(`/project/${projectId}/${page}${search ? `?${search}` : ''}`),
    [navigate, projectId],
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
      {open && <div className="fixed inset-0 z-40 bg-content/30 lg:hidden" onClick={() => setOpen(false)} />}
      <aside
        aria-label="智能助笔"
        aria-hidden={!open}
        className={cn(
          'flex h-full flex-none flex-col border-l border-surface-border bg-surface',
          'max-lg:fixed max-lg:inset-y-0 max-lg:right-0 max-lg:z-50 max-lg:w-[min(440px,100vw)] max-lg:shadow-md',
          wide ? 'lg:w-[min(760px,58vw)]' : 'lg:w-[400px]',
          !open && 'hidden',
        )}
      >
        <header className="flex h-12 flex-none items-center gap-2 border-b border-surface-border bg-surface-paper px-3">
          <span className="flex items-center gap-1.5 font-serif text-sm font-semibold text-content">
            <Sparkles className="h-4 w-4 text-brand" />智能助笔
          </span>
          <nav className="ml-2 flex rounded border border-surface-border bg-white p-0.5" aria-label="智能助笔区域">
            {MODES.map((m) => (
              <button
                key={m.id}
                onClick={() => setMode(m.id)}
                aria-pressed={mode === m.id}
                className={cn(
                  'relative rounded-sm px-2.5 py-0.5 text-xs transition-colors',
                  mode === m.id ? 'bg-brand text-white' : 'text-content-secondary hover:text-content',
                )}
              >
                {m.label}
                {m.id === 'tasks' && running.length > 0 && (
                  <span className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-signal" aria-label="有正在运行的任务" />
                )}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-0.5">
            <button
              onClick={() => setWide(!wide)}
              className="hidden rounded p-1.5 text-content-tertiary hover:bg-surface-hover hover:text-content lg:block"
              title={wide ? '收起宽屏' : '展开宽屏'}
            >
              {wide ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </button>
            <button onClick={() => setOpen(false)} className="rounded p-1.5 text-content-tertiary hover:bg-surface-hover hover:text-content" title="关闭（Alt+A）">
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>
        <div className="min-h-0 flex-1">
          <div className={cn('h-full', mode !== 'agent' && 'hidden')}>
            <AssistantConversation key={projectId} projectId={projectId} onNavigate={onNavigate} />
          </div>
          {mode === 'checks' && (
            <AssistantChecks
              projectId={projectId}
              onNavigate={onNavigate}
              onAsk={compose}
              onOpenConversation={() => setMode('agent')}
            />
          )}
          {mode === 'tasks' && <AssistantTasks projectId={projectId} onOpenConversation={() => setMode('agent')} />}
        </div>
      </aside>
    </>
  );
}
