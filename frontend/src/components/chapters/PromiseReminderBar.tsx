/**
 * 正文底栏的伏笔提醒：写这一章该照应的伏笔——本章章纲要回收 / 推进的在前，再是超期 / 临近计划回收、
 * 掉线太久没提的。每条可以「本章回收」「本章强化」「暂停提醒 20 章」（暂停只记在本机）；右边打开全书悬念时间线。
 * 没有要提醒的就不显示。挑选和排序与写正文时带进上下文的那批同一套（后端 story_ledger_service.chapter_reminders）。
 */
import { useCallback, useEffect, useState } from 'react';
import { BellOff, ChartGantt, Check, ChevronDown, ChevronUp, Loader2, RotateCcw, TrendingUp } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { ledgerApi } from '@/services/api';
import type { PromiseReminder, PromiseUpdate } from '@/types/ledger';
import { activeReminders, loadSnoozes, PROMISE_TYPE_LABELS, SNOOZE_CHAPTERS, snoozePromise } from '@/utils/ledger';
import { PromiseTimeline } from '@/components/ledger/PromiseTimeline';

const OPEN_KEY = 'promise-bar-open';

export function PromiseReminderBar({ projectId, chapterNumber }: { projectId: string; chapterNumber: number }) {
  const [items, setItems] = useState<PromiseReminder[]>([]);
  const [snoozes, setSnoozes] = useState<Record<string, number>>(() => loadSnoozes(projectId));
  // 默认收成一行（不挤正文），展开过就记住
  const [open, setOpen] = useState(() => typeof localStorage !== 'undefined' && localStorage.getItem(OPEN_KEY) === 'true');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [timeline, setTimeline] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems((await ledgerApi.promiseReminders(projectId, chapterNumber)).items);
    } catch {
      setItems([]);
    }
  }, [chapterNumber, projectId]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { setSnoozes(loadSnoozes(projectId)); }, [projectId]);

  const update = async (item: PromiseReminder, data: PromiseUpdate, done: string) => {
    setBusyId(item.id);
    try {
      await ledgerApi.updatePromise(projectId, item.id, data);
      toast.success(done);
      await load();
    } catch {
      /* 拦截器已提示 */
    } finally {
      setBusyId(null);
    }
  };

  const toggle = () => {
    setOpen((v) => {
      localStorage.setItem(OPEN_KEY, String(!v));
      return !v;
    });
  };

  const visible = activeReminders(items, snoozes, chapterNumber);
  if (!visible.length) return timeline ? <PromiseTimeline projectId={projectId} currentChapter={chapterNumber} onClose={() => setTimeline(false)} /> : null;
  const due = visible.filter((i) => !i.resolved_here).length;
  return (
    <section className="border-t border-surface-border bg-surface-paper px-4 py-1.5 text-[12px]" aria-label="伏笔提醒">
      <div className="flex min-w-0 items-center gap-2">
        <button onClick={toggle} className="flex min-w-0 items-center gap-1.5 text-content-secondary hover:text-content" aria-expanded={open}>
          {open ? <ChevronDown className="h-3.5 w-3.5 flex-none" /> : <ChevronUp className="h-3.5 w-3.5 flex-none" />}
          <span className="flex-none font-medium text-content">伏笔提醒</span>
          <span className="flex-none text-content-tertiary">{due ? `${due} 条要照应` : '本章都照应了'}</span>
          {!open && visible[0] && <span className="min-w-0 truncate text-content-tertiary">· 「{visible[0].title}」{visible[0].reason}</span>}
        </button>
        <button onClick={() => setTimeline(true)} className="ml-auto flex flex-none items-center gap-1 text-content-tertiary hover:text-brand" title="打开全书悬念时间线：埋设、回收和核对建议">
          <ChartGantt className="h-3.5 w-3.5" />时间线
        </button>
      </div>
      {open && (
        <ul className="mt-1 max-h-40 space-y-1 overflow-y-auto pb-1">
          {visible.map((p) => {
            const urgent = p.planned === 'resolve' || p.reason.includes('超期');
            return (
              <li key={p.id} className="flex min-w-0 items-center gap-2" title={[p.content, p.how && `章纲：${p.how}`].filter(Boolean).join('\n')}>
                <span className="lj-badge flex-none">{PROMISE_TYPE_LABELS[p.promise_type]}</span>
                <span className="min-w-0 truncate">
                  <span className="text-content">{p.title}</span>
                  <span className={cn('ml-1.5', p.resolved_here ? 'text-brand' : urgent ? 'text-cinnabar' : 'text-gold-500')}>{p.reason}</span>
                  {p.how && !p.resolved_here && <span className="ml-1.5 text-content-tertiary">· {p.how}</span>}
                </span>
                <span className="ml-auto flex flex-none items-center gap-0.5">
                  {busyId === p.id && <Loader2 className="h-3.5 w-3.5 animate-spin text-brand" />}
                  {p.resolved_here ? (
                    <button onClick={() => void update(p, { status: 'open' }, '已改回未回收')} disabled={busyId !== null}
                      className="ws-icon-btn h-6 w-6" title="改回未回收">
                      <RotateCcw className="h-3.5 w-3.5" />
                    </button>
                  ) : (
                    <>
                      <button
                        onClick={() => void update(p, { status: 'resolved', resolved_chapter_number: chapterNumber, note: `作者在第 ${chapterNumber} 章标记回收` }, `「${p.title}」标为在第 ${chapterNumber} 章回收`)}
                        disabled={busyId !== null} className="ws-icon-btn h-6 w-6" title="直接标记为已在本章回收"
                      >
                        <Check className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => void update(p, { activated_chapter_number: chapterNumber }, `「${p.title}」标为在第 ${chapterNumber} 章强化`)}
                        disabled={busyId !== null || p.reinforced_here} className={cn('ws-icon-btn h-6 w-6', p.reinforced_here && 'text-brand')}
                        title={p.reinforced_here ? '本章已强化' : '标记为本章强化（最近提及挪到这一章，转推进中）'}
                      >
                        <TrendingUp className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => setSnoozes(snoozePromise(projectId, p.id, chapterNumber))}
                        className="ws-icon-btn h-6 w-6" title={`暂停提醒 ${SNOOZE_CHAPTERS} 章（只记在本机）`}
                      >
                        <BellOff className="h-3.5 w-3.5" />
                      </button>
                    </>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {timeline && <PromiseTimeline projectId={projectId} currentChapter={chapterNumber} onClose={() => setTimeline(false)} />}
    </section>
  );
}
