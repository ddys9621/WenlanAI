/**
 * 全局智能助笔 ·「共创室」对话界面（参考岚笺 GlobalAssistantHost 的 agent 页 + creative-team）：
 * 一个输入框和一支创作团队：主编默认发言、可以把事交给成员，作者也能「@成员」直接找人；回复附「处理记录」；
 * 修改只给候选（内容修改候选 / 章节候选稿），规划给草案卡片（卷纲 / 剧情单元 / 章纲），确认后才写入；
 * 顶部的创作进度告诉作者下一步；需要作者决定时出提问卡；对话保存在服务端，刷新后可续接。
 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import {
  Check, ChevronDown, Copy, FilePenLine, Loader2, MessageSquarePlus, PencilLine, Quote, SendHorizontal, Sparkles, Square, TriangleAlert, X,
} from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { assistantApi } from '@/services/api';
import { AIJobError, runAIJob, useAIJobsStore, waitForAIJob } from '@/store/aiJobsStore';
import { emitAssistantData, pageContextOf, useAssistantStore, type AssistantDataChange } from '@/store/assistantStore';
import type {
  AssistantAnswer, AssistantChapterCandidateRef, AssistantFieldCandidate, AssistantMember, AssistantMessageView, AssistantPageContext,
  AssistantPreview, AssistantProgress, AssistantRunResult, AssistantSessionView, AssistantTeam,
} from '@/types/assistant';
import { appendQuote, appendRequest, HISTORY_LIMIT } from '@/utils/assistantText';
import { mentionMember, questionCardKey } from '@/utils/cocreation';
import type { SSEClientOptions, SSEMessage } from '@/utils/sseClient';
import { AuthorQuestionCard } from './AuthorQuestionCard';
import { FieldCandidateCard } from './FieldCandidateCard';
import { MemberAvatar, PlanCard, ProgressStrip, TeamBar, TeamSettings } from './CocreationParts';

const MAX_CHARS = 4000;
const REVIEW_KEY = 'assistant-review-before-send';

interface LiveTurn {
  goal: string;
  steps: { label: string; detail: string; ok: boolean }[];
  text: string;
  /** 本轮发言的成员（speaker 事件） */
  member?: AssistantMember | null;
  /** 主编交给成员的事：处理中 / 成员的回复 */
  delegations: { member: AssistantMember; task: string; content: string }[];
}

const newLive = (goal: string, text = ''): LiveTurn => ({ goal, steps: [], text, delegations: [] });

/** 回复里的 **加粗** 显示成粗体，其余照原样换行 */
function RichText({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*\n]+\*\*)/g);
  return (
    <p className="whitespace-pre-wrap break-words text-[13px] leading-7 text-content">
      {parts.map((part, i) => (part.startsWith('**') && part.endsWith('**') && part.length > 4
        ? <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>
        : <span key={i}>{part}</span>))}
    </p>
  );
}

function StepList({ steps, live }: { steps: { label: string; summary?: string; detail?: string; ok: boolean }[]; live?: boolean }) {
  if (!steps.length) return null;
  return (
    <details className="mt-2 rounded border border-surface-border-light bg-surface-paper px-2.5 py-1.5" open={live}>
      <summary className="cursor-pointer select-none text-[11px] text-content-tertiary">处理记录 · {steps.length} 步</summary>
      <ol className="mt-1 space-y-0.5">
        {steps.map((s, i) => (
          <li key={i} className="flex items-start gap-1.5 text-[11px] leading-5 text-content-secondary">
            {s.ok ? <Check className="mt-0.5 h-3 w-3 flex-none text-brand" /> : <TriangleAlert className="mt-0.5 h-3 w-3 flex-none text-gold-500" />}
            <span><span className="text-content">{s.label}</span>{(s.summary || s.detail) && <> · {s.summary || s.detail}</>}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}

function ChapterCandidateLink({ item, onOpen }: { item: AssistantChapterCandidateRef; onOpen: (item: AssistantChapterCandidateRef) => void }) {
  return (
    <button onClick={() => onOpen(item)} className="mt-2 flex w-full items-start gap-2 rounded border border-gold-300/50 bg-gold-50/50 px-2.5 py-2 text-left hover:bg-gold-50">
      <FilePenLine className="mt-0.5 h-3.5 w-3.5 flex-none text-gold-500" />
      <span className="min-w-0">
        <span className="block text-xs font-medium text-content">第 {item.chapter_number} 章《{item.chapter_title}》候选稿 · {item.word_count} 字</span>
        <span className="block truncate text-[11px] text-content-tertiary">{item.preview || '去章节写作页审阅后采用'}</span>
      </span>
    </button>
  );
}

interface AssistantConversationProps {
  projectId: string;
  onNavigate: (page: string, search?: string) => void;
}

export function AssistantConversation({ projectId, onNavigate }: AssistantConversationProps) {
  const route = useAssistantStore((s) => s.route);
  const detail = useAssistantStore((s) => s.detail);
  const composeRequest = useAssistantStore((s) => s.composeRequest);
  const page = useMemo(() => pageContextOf({ route, detail }), [route, detail]);

  const [view, setView] = useState<AssistantSessionView | null>(null);
  const [loadError, setLoadError] = useState('');
  const [draft, setDraft] = useState(() => sessionStorage.getItem(`assistant-draft:${projectId}`) ?? '');
  const [live, setLive] = useState<LiveTurn | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [reviewBeforeSend, setReviewBeforeSend] = useState(() => localStorage.getItem(REVIEW_KEY) === 'true');
  const [preview, setPreview] = useState<{ data: AssistantPreview; key: string } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [team, setTeam] = useState<AssistantTeam | null>(null);
  const [showTeam, setShowTeam] = useState(false);
  const [progress, setProgress] = useState<AssistantProgress | null>(null);
  const jobIdRef = useRef<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // 运行中产生的页面刷新 / 跳转等它结束再做：不在任务写库时触发一大批页面请求，也不在半途把作者带走
  const pendingRef = useRef<{ nav: string | null; data: AssistantDataChange[] }>({ nav: null, data: [] });

  const scrollToEnd = useCallback(() => {
    requestAnimationFrame(() => listRef.current?.scrollTo({ top: listRef.current.scrollHeight }));
  }, []);

  const reload = useCallback(async () => {
    try {
      const next = await assistantApi.session(projectId);
      setView(next);
      setLoadError('');
      return next;
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : '对话读取失败');
      return null;
    }
  }, [projectId]);

  const loadProgress = useCallback(async () => {
    try {
      setProgress(await assistantApi.progress(projectId));
    } catch { /* 进度只是提示，读不到就不显示 */ }
  }, [projectId]);

  useEffect(() => {
    void assistantApi.team(projectId).then(setTeam).catch(() => setTeam(null));
    void loadProgress();
  }, [loadProgress, projectId]);

  useEffect(() => { sessionStorage.setItem(`assistant-draft:${projectId}`, draft); }, [draft, projectId]);

  const handleEvent = useCallback((m: SSEMessage) => {
    if (m.type === 'content' && typeof m.content === 'string') {
      const piece = m.content;
      setLive((prev) => (prev ? { ...prev, text: prev.text + piece } : prev));
      scrollToEnd();
    } else if (m.type === 'content_reset') {
      setLive((prev) => (prev ? { ...prev, text: '' } : prev));
    } else if (m.type === 'tool') {
      const step = { label: String(m.label ?? m.name ?? ''), detail: String(m.detail ?? ''), ok: m.ok !== false };
      setLive((prev) => (prev ? { ...prev, steps: [...prev.steps, step] } : prev));
      scrollToEnd();
    } else if (m.type === 'candidate' && m.candidate) {
      const candidate = m.candidate as AssistantFieldCandidate;
      setView((prev) => (prev ? { ...prev, candidates: [...prev.candidates.filter((c) => c.id !== candidate.id), candidate] } : prev));
    } else if (m.type === 'chapter_candidate' && m.candidate) {
      const item = m.candidate as AssistantChapterCandidateRef;
      pendingRef.current.data.push({ entity: 'chapter_candidate', chapterId: item.chapter_id, targetId: item.id });
    } else if (m.type === 'navigate' && typeof m.page === 'string') {
      pendingRef.current.nav = m.page;
    } else if (m.type === 'speaker' && m.member) {
      const member = m.member as AssistantMember;
      setLive((prev) => (prev ? { ...prev, member } : prev));
    } else if (m.type === 'member_start' && m.member) {
      const member = m.member as AssistantMember;
      const task = String(m.task ?? '');
      setLive((prev) => (prev ? { ...prev, delegations: [...prev.delegations, { member, task, content: '' }] } : prev));
      scrollToEnd();
    } else if (m.type === 'member_message' && m.member) {
      const member = m.member as AssistantMember;
      const content = String(m.content ?? '');
      setLive((prev) => {
        if (!prev) return prev;
        const index = prev.delegations.findIndex((d) => d.member.id === member.id && !d.content);
        const delegations = index < 0
          ? [...prev.delegations, { member, task: '', content }]
          : prev.delegations.map((d, i) => (i === index ? { ...d, content } : d));
        return { ...prev, delegations };
      });
      scrollToEnd();
    } else if (m.type === 'plan' && m.plan) {
      const kind = (m.plan as { kind?: string }).kind;
      pendingRef.current.data.push({ entity: kind === 'outlines' ? 'chapter_outline' : 'volume' });
    } else if (m.type === 'job' && m.job) {
      const job = m.job as { title?: string };
      toast.success(`${job.title ?? '后台任务'}已开始，进度在右下角任务托盘`);
      void useAIJobsStore.getState().syncFromServer(projectId);
    }
  }, [projectId, scrollToEnd]);

  const flushPending = useCallback(() => {
    const { nav, data } = pendingRef.current;
    pendingRef.current = { nav: null, data: [] };
    data.forEach(emitAssistantData);
    if (nav) onNavigate(nav);
  }, [onNavigate]);

  /** 跟进一个已在跑的任务（刷新页面 / 切回项目后续接） */
  const follow = useCallback(async (jobId: string, goal: string) => {
    jobIdRef.current = jobId;
    setBusy(true);
    setLive(newLive(goal, useAIJobsStore.getState().jobs[jobId]?.content ?? ''));
    const unsubscribe = useAIJobsStore.getState().subscribe(jobId, (m) => handleEvent(m));
    try {
      await waitForAIJob(jobId);
    } catch {
      /* 失败 / 停止都以服务端记录为准 */
    } finally {
      unsubscribe();
      jobIdRef.current = null;
      setBusy(false);
      setLive(null);
      await reload();
      flushPending();
      void loadProgress();
      scrollToEnd();
    }
  }, [flushPending, handleEvent, loadProgress, reload, scrollToEnd]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const next = await reload();
      if (cancelled || !next?.active_run || next.active_run.status !== 'running') return;
      await useAIJobsStore.getState().syncFromServer(projectId);
      const job = Object.values(useAIJobsStore.getState().jobs).find(
        (j) => j.kind === 'assistant_run' && j.meta?.run_id === next.active_run?.id && j.status === 'running',
      );
      if (job && !cancelled) void follow(job.id, next.active_run.goal);
    })();
    scrollToEnd();
    return () => { cancelled = true; };
  }, [follow, projectId, reload, scrollToEnd]);

  useEffect(() => {
    if (!composeRequest) return;
    if (composeRequest.text) {
      setDraft((prev) => appendRequest(prev, composeRequest.text));
      setNotice('已填入输入框，可修改后发送；已有草稿会保留。');
    }
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [composeRequest]);

  const pageKey = JSON.stringify(page);
  const previewCurrent = Boolean(preview && preview.key === `${draft.trim()}\n${pageKey}`);

  const runJob = async (goal: string, connect: (o: SSEClientOptions<AssistantRunResult>) => Promise<unknown>) => {
    setBusy(true);
    setLive(newLive(goal));
    scrollToEnd();
    try {
      await runAIJob<AssistantRunResult>({
        kind: 'assistant_run',
        title: `智能助笔：${goal.slice(0, 24)}`,
        projectId,
        openModal: false,
        onStarted: (id) => { jobIdRef.current = id; },
        connect,
        onEvent: (m) => handleEvent(m),
      });
      return true;
    } catch (err) {
      const cancelled = err instanceof AIJobError && err.job.status === 'cancelled';
      if (!cancelled) toast.error(err instanceof Error ? err.message : '助笔没跑成');
      return false;
    } finally {
      jobIdRef.current = null;
      await reload();
      setBusy(false);
      setLive(null);
      flushPending();
      void loadProgress();
      scrollToEnd();
    }
  };

  const loadPreview = async (message: string, context: AssistantPageContext) => {
    setPreviewLoading(true);
    try {
      const data = await assistantApi.preview(projectId, { message, page: context });
      setPreview({ data, key: `${message}\n${JSON.stringify(context)}` });
      scrollToEnd();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '发送核对没准备好');
    } finally {
      setPreviewLoading(false);
    }
  };

  const send = async () => {
    const message = draft.trim();
    if (!message || busy || message.length > MAX_CHARS) return;
    if (reviewBeforeSend && !previewCurrent) {
      await loadPreview(message, page);
      return;
    }
    setPreview(null);
    setNotice('');
    setDraft('');
    setView((prev) => (prev ? {
      ...prev,
      messages: [...prev.messages, {
        id: `pending-${Date.now()}`, role: 'user', content: message, created_at: null, run_id: null, steps: [], candidates: [], chapter_candidates: [],
      }],
    } : prev));
    const ok = await runJob(message, (o) => assistantApi.sendStream(projectId, { message, page }, o));
    if (!ok) setDraft((prev) => prev || message);
  };

  const answer = async (answers: AssistantAnswer[]) => {
    const run = view?.active_run;
    if (!run || busy) return;
    await runJob(run.goal, (o) => assistantApi.answerStream(projectId, run.id, answers, o));
  };

  const stop = () => {
    if (jobIdRef.current) void useAIJobsStore.getState().cancel(jobIdRef.current);
  };

  const startNew = async () => {
    if (busy) return;
    try {
      setView(await assistantApi.newSession(projectId));
      setPreview(null);
      toast.success('已开始新对话，之前的对话可在「任务」里回看');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '没能开始新对话');
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send();
    }
  };

  const copy = async (m: AssistantMessageView) => {
    try {
      await navigator.clipboard.writeText(m.content);
      setCopied(m.id);
      setTimeout(() => setCopied((c) => (c === m.id ? null : c)), 1500);
    } catch {
      toast.error('复制没成功，可以直接选中文字复制');
    }
  };

  const quote = (m: AssistantMessageView) => {
    const selected = window.getSelection()?.toString().trim();
    setDraft((prev) => appendQuote(prev, selected || m.content));
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const candidatesById = useMemo(() => new Map((view?.candidates ?? []).map((c) => [c.id, c])), [view?.candidates]);
  const updateCandidate = (next: AssistantFieldCandidate) =>
    setView((prev) => (prev ? { ...prev, candidates: prev.candidates.map((c) => (c.id === next.id ? next : c)) } : prev));
  const openChapterCandidate = (item: AssistantChapterCandidateRef) =>
    onNavigate('chapter-analysis', `chapter=${item.chapter_id}&tab=candidates&candidate=${item.id}`);

  const messages = view?.messages ?? [];
  const waitingRun = view?.active_run?.status === 'waiting_input' ? view.active_run : null;
  const historyCount = Math.min(messages.length, HISTORY_LIMIT);
  const members = team?.members ?? [];
  const mention = (member: AssistantMember) => {
    setDraft((prev) => mentionMember(prev, member.name));
    requestAnimationFrame(() => inputRef.current?.focus());
  };
  const askEditor = (label: string) => {
    setDraft((prev) => appendRequest(mentionMember(prev, '主编'), `请看看创作进度，按建议推进下一步：${label}。需要我拍板的地方先问我。`));
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const renderMessage = (m: AssistantMessageView): ReactNode => {
    const fieldCandidates = m.candidates.map((id) => candidatesById.get(id)).filter((c): c is AssistantFieldCandidate => Boolean(c));
    const isUser = m.role === 'user';
    return (
      <article key={m.id} className={cn('rounded border px-3 py-2.5', isUser ? 'border-surface-border-light bg-surface-paper' : 'border-surface-border bg-white')}>
        <header className="mb-1 flex items-center justify-between gap-2">
          <span className="flex items-center gap-1.5 text-[11px] font-medium text-content-tertiary">
            {isUser ? '你' : m.member
              ? <><MemberAvatar member={m.member} /><span className="text-content-secondary">{m.member.name}</span></>
              : <><Sparkles className="h-3 w-3 text-brand" />智能助笔</>}
            {m.delegated && <span className="lj-badge lj-badge--muted">受主编委托</span>}
            {m.answer && <span className="lj-badge lj-badge--muted">回答</span>}
            {m.question && <span className="lj-badge lj-badge--candidate">提问</span>}
          </span>
          <span className="flex items-center gap-0.5">
            <span className="mr-1 text-[10px] text-content-tertiary">{m.content.length} 字</span>
            <button onClick={() => void copy(m)} className="rounded p-1 text-content-tertiary hover:bg-surface-hover hover:text-content" title="复制">
              {copied === m.id ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            </button>
            <button onClick={() => quote(m)} className="rounded p-1 text-content-tertiary hover:bg-surface-hover hover:text-content" title="引用到输入框（可先选中其中几句）">
              <Quote className="h-3 w-3" />
            </button>
            {isUser && !m.answer && (
              <button onClick={() => { setDraft(m.content); inputRef.current?.focus(); }} className="rounded p-1 text-content-tertiary hover:bg-surface-hover hover:text-content" title="编辑后再发">
                <PencilLine className="h-3 w-3" />
              </button>
            )}
          </span>
        </header>
        <RichText text={m.content} />
        {!isUser && <StepList steps={m.steps} />}
        {fieldCandidates.map((c) => (
          <div key={c.id} className="mt-2">
            <FieldCandidateCard projectId={projectId} candidate={c} onChange={updateCandidate} onOpenPage={(p) => onNavigate(p)} />
          </div>
        ))}
        {m.chapter_candidates.map((item) => <ChapterCandidateLink key={item.id} item={item} onOpen={openChapterCandidate} />)}
        {(m.plans ?? []).map((plan, i) => <PlanCard key={`${m.id}-plan-${i}`} plan={plan} onNavigate={(p) => onNavigate(p)} />)}
      </article>
    );
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <details className="border-b border-surface-border-light bg-surface-paper px-3 py-1.5 text-[11px] text-content-secondary">
        <summary className="flex cursor-pointer select-none items-center gap-2">
          <span className="truncate font-medium text-content">{page.label || '本项目'}</span>
          {page.selection && <span className="lj-badge lj-badge--candidate">已选 {page.selection.text.length} 字</span>}
          <span className="ml-auto flex items-center gap-0.5 text-content-tertiary">当前内容<ChevronDown className="h-3 w-3" /></span>
        </summary>
        <p className="mt-1 leading-5 text-content-tertiary">共创室会参考你所在的页面，但不限于这里：可以直接说要处理的设定、人物或章节，团队会自己定位。</p>
        {page.selection && <p className="mt-1 line-clamp-3 border-l-2 border-gold-300 pl-2 leading-5">{page.selection.text}</p>}
      </details>
      {progress && <ProgressStrip progress={progress} onAsk={askEditor} disabled={busy} />}

      <div ref={listRef} className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-3 py-3">
        {showTeam && team && <TeamSettings projectId={projectId} team={team} onChange={setTeam} onClose={() => setShowTeam(false)} />}
        {loadError && <p className="rounded border border-cinnabar/30 bg-cinnabar-wash px-3 py-2 text-xs text-cinnabar">{loadError}</p>}
        {!messages.length && !live && (
          <div className="rounded border border-dashed border-surface-border bg-surface-paper px-3 py-3">
            <p className="text-[11px] tracking-wide text-content-tertiary">共创室 · 一支团队陪你把书写完</p>
            <h3 className="mt-0.5 font-serif text-base font-semibold text-content">从一个想法开始</h3>
            <p className="mt-1 text-xs leading-6 text-content-secondary">
              主编会先弄清你想写什么，再按 总纲 → 卷纲 → 章纲 → 正文 推进，把专业的事交给世界观、人物、总纲、章节、正文、审校几位成员。
              需要你拍板时会先问你；所有改动和规划都是候选或草案，你确认了才写进书里。
            </p>
            {members.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {members.map((mb) => (
                  <button key={mb.id} onClick={() => mention(mb)} className="flex items-center gap-1 rounded border border-surface-border-light bg-white px-1.5 py-1 text-[11px] text-content-secondary hover:border-brand/40" title={mb.responsibility}>
                    <MemberAvatar member={mb} />{mb.name}
                  </button>
                ))}
              </div>
            )}
            <div className="mt-2 grid grid-cols-2 gap-1.5">
              {(team?.starters ?? []).map((s) => (
                <button key={s.id} onClick={() => { setDraft((prev) => appendRequest(prev, s.message)); inputRef.current?.focus(); }}
                  className="rounded border border-surface-border-light bg-white px-2.5 py-2 text-left hover:border-brand/40 hover:bg-brand-50">
                  <span className="block text-xs font-semibold text-content">{s.label}</span>
                  <span className="block text-[11px] text-content-tertiary">{s.hint}</span>
                </button>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-content-tertiary">快捷入口只填入要求，不会自动发送；已有草稿会保留。点成员头像可以「@」他直接对话。</p>
          </div>
        )}
        {messages.map(renderMessage)}
        {live?.delegations.map((d, i) => (
          <article key={`delegation-${i}`} className="rounded border border-surface-border bg-white px-3 py-2.5">
            <header className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-content-tertiary">
              <MemberAvatar member={d.member} /><span className="text-content-secondary">{d.member.name}</span>
              <span className="lj-badge lj-badge--muted">受主编委托</span>
              {!d.content && <Loader2 className="h-3 w-3 animate-spin text-brand" />}
            </header>
            {d.content ? <RichText text={d.content} /> : <p className="text-xs text-content-tertiary">正在处理：{d.task || '主编交代的事'}</p>}
          </article>
        ))}
        {live && (
          <article className="rounded border border-brand/30 bg-white px-3 py-2.5">
            <header className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-brand">
              <Loader2 className="h-3 w-3 animate-spin" />
              {live.member ? <><MemberAvatar member={live.member} />{live.member.name}</> : '智能助笔'} · {live.text ? '正在回复' : live.steps.length ? '正在处理' : '思考中'}
            </header>
            {live.text ? <RichText text={live.text} /> : <p className="text-xs text-content-tertiary">正在查找相关内容…</p>}
            <StepList steps={live.steps} live />
          </article>
        )}
        {waitingRun?.question && !busy && (
          <AuthorQuestionCard key={questionCardKey(waitingRun)} question={waitingRun.question} busy={busy} onSubmit={(a) => void answer(a)} />
        )}
        {preview && (
          <section className={cn('rounded border bg-white px-3 py-2.5', previewCurrent ? 'border-brand/40' : 'border-gold-300')}>
            <header className="mb-1 flex items-center justify-between">
              <span className="text-xs font-semibold text-content">发送前核对</span>
              <span className="text-[11px] text-content-tertiary">{previewCurrent ? '核对后点「确认发送」' : '要求或页面变了，请更新核对'}</span>
            </header>
            <p className="mb-1 border-l-2 border-gold-300 bg-gold-50/50 px-2 py-1 text-xs leading-6">{preview.data.message}</p>
            {preview.data.sections.map((s) => (
              <details key={s.label} className="border-t border-surface-border-light py-1">
                <summary className="cursor-pointer text-[11px] text-brand">{s.label}</summary>
                <pre className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap break-words font-sans text-[11px] leading-5 text-content-secondary">{s.content}</pre>
              </details>
            ))}
            <details className="border-t border-surface-border-light py-1">
              <summary className="cursor-pointer text-[11px] text-brand">助笔的规则与工具</summary>
              <pre className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap break-words font-sans text-[11px] leading-5 text-content-secondary">{preview.data.rules}</pre>
            </details>
          </section>
        )}
      </div>

      <div className="border-t border-surface-border bg-white px-3 py-2">
        {notice && <p className="mb-1 text-[11px] text-content-tertiary">{notice}</p>}
        {busy && <p className="mb-1 text-[11px] text-brand">正在处理本轮要求…可以先写下一条，处理完再发。</p>}
        {waitingRun && !busy && <p className="mb-1 text-[11px] text-gold-500">团队在等你回答上面的问题；直接发新要求会结束那轮提问。</p>}
        <TeamBar members={members} onMention={mention} onOpenSettings={() => setShowTeam((v) => !v)} />
        <textarea
          ref={inputRef}
          value={draft}
          onChange={(e) => { setDraft(e.target.value); setNotice(''); }}
          onKeyDown={onKeyDown}
          rows={3}
          maxLength={MAX_CHARS}
          placeholder="和主编说说你的想法；「@成员」可直接找人…（Ctrl+Enter 发送）"
          className="hh-textarea text-sm"
        />
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <span className="text-[10px] text-content-tertiary">{draft.length}/{MAX_CHARS}</span>
          <span className="text-[10px] text-content-tertiary" title="每次带入最近的对话，超长消息保留首尾">带入 {historyCount} 条历史</span>
          <label className="flex cursor-pointer items-center gap-1 text-[11px] text-content-secondary">
            <input type="checkbox" checked={reviewBeforeSend} onChange={(e) => { setReviewBeforeSend(e.target.checked); localStorage.setItem(REVIEW_KEY, String(e.target.checked)); setPreview(null); }} />
            发送前核对
          </label>
          <div className="ml-auto flex items-center gap-1.5">
            <button onClick={() => void startNew()} disabled={busy} className="hh-btn-ghost hh-btn-sm h-8 px-2 text-[11px]" title="开始新对话">
              <MessageSquarePlus className="h-3.5 w-3.5" />新对话
            </button>
            {preview && !busy && (
              <button onClick={() => setPreview(null)} className="hh-btn-ghost hh-btn-sm h-8 px-2 text-[11px]" title="收起核对">
                <X className="h-3.5 w-3.5" />
              </button>
            )}
            {busy ? (
              <button onClick={stop} className="hh-btn-secondary hh-btn-sm h-8"><Square className="h-3.5 w-3.5" />停止</button>
            ) : (
              <button onClick={() => void send()} disabled={!draft.trim() || previewLoading} className="hh-btn-primary hh-btn-sm h-8">
                {previewLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <SendHorizontal className="h-3.5 w-3.5" />}
                {reviewBeforeSend ? (previewCurrent ? '确认发送' : preview ? '更新核对' : '核对后发送') : '发送'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
