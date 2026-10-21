/**
 * 全局智能助笔 ·「共创室」对话界面（参考岚笺 GlobalAssistantHost 的 agent 页 + creative-team）：
 * 一个输入框和一支创作团队：主编默认发言、可以把事交给成员，作者也能「@成员」直接找人；回复附「处理记录」；
 * 修改只给候选（内容修改候选 / 章节候选稿），规划给草案卡片（卷纲 / 剧情单元 / 章纲），确认后才写入；
 * 顶部的创作进度告诉作者下一步；需要作者决定时出提问卡；对话保存在服务端，刷新后可续接。
 * 输入框旁的上下文用量表（参照写代码 agent）：上限在团队设置里按项目设，运行中每一步刷新，较早的对话装不下时自动压成前情摘要。
 * 外观是 AI 助手面板（参照 Claude / ChatGPT）：团队的回复是正文排版，作者的话是浅灰圆角块，输入框和工具条合成一个大框。
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import {
  ArrowDown, ArrowUp, Check, ChevronRight, Copy, FilePenLine, ListChecks, Loader2, MapPin, PencilLine, Quote, Sparkles, Square,
  TriangleAlert, X,
} from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { assistantApi } from '@/services/api';
import { AIJobError, runAIJob, useAIJobsStore, waitForAIJob } from '@/store/aiJobsStore';
import { emitAssistantData, pageContextOf, useAssistantStore, type AssistantDataChange } from '@/store/assistantStore';
import type {
  AssistantAnswer, AssistantChapterCandidateRef, AssistantContextUsage, AssistantEntityCandidate, AssistantFieldCandidate,
  AssistantMember, AssistantMessageView, AssistantPageContext, AssistantPlan, AssistantPreview, AssistantProgress,
  AssistantRunResult, AssistantSessionView, AssistantTeam,
} from '@/types/assistant';
import { appendQuote, appendRequest } from '@/utils/assistantText';
import {
  changeItems, liveCardOwner, mentionMember, pendingChanges, planEntity, planKey, questionCardKey, type ChangeCards,
} from '@/utils/cocreation';
import { formatTokens } from '@/utils/contextUsage';
import type { SSEClientOptions, SSEMessage } from '@/utils/sseClient';
import { ChangeList, PendingTray, type DecideChange, type RenderDetail } from './AssistantChanges';
import { AuthorQuestionCard } from './AuthorQuestionCard';
import { confirmPlan, entityAction, errorDetail, fieldAction } from './changeActions';
import { EntityCandidateCard } from './EntityCandidateCard';
import { FieldCandidateCard } from './FieldCandidateCard';
import { ContextMeter, MemberAvatar, MemberPicker, NextStepHint, PlanCard, RichText, TeamSettings } from './CocreationParts';

const MAX_CHARS = 4000;
const REVIEW_KEY = 'assistant-review-before-send';
const INPUT_MAX_HEIGHT = 200;
/** 离底部这么近就算「停在最新处」：新内容来了跟着滚；往上翻着看就不拽回来 */
const STICK_PX = 80;
/** 成员回复超过这么长就先折起来（窄抽屉里 300 字就快一屏了，几千字的草稿会占好几屏） */
const LONG_REPLY = 300;

/** 一条发言带出的卡片（与消息里存的同一组字段） */
type Attachments = ChangeCards;

const noAttachments = (): Attachments => ({ candidates: [], entity_candidates: [], chapter_candidates: [], plans: [] });
const attachmentsOf = (m: AssistantMessageView): Attachments => ({
  candidates: m.candidates, entity_candidates: m.entity_candidates ?? [], chapter_candidates: m.chapter_candidates ?? [], plans: m.plans ?? [],
});

interface LiveTurn {
  goal: string;
  steps: { label: string; detail: string; ok: boolean }[];
  text: string;
  /** 本轮发言的成员（speaker 事件） */
  member?: AssistantMember | null;
  /** 发言者这一段提出的卡片（运行中就显示，跑完以服务端存的为准） */
  cards: Attachments;
  /** 主编交给成员的事：处理中 / 成员的回复 / 成员提出的卡片 */
  delegations: { member: AssistantMember; task: string; content: string; cards: Attachments }[];
}

const newLive = (goal: string, text = ''): LiveTurn => ({ goal, steps: [], text, cards: noAttachments(), delegations: [] });

/** 运行中推来的卡片挂到提它的人下面：正在处理委托的成员挂到那条委托，否则挂到本轮发言者 */
function withLiveCard(live: LiveTurn, memberId: unknown, add: (cards: Attachments) => Attachments): LiveTurn {
  const owner = liveCardOwner(live.delegations, typeof memberId === 'string' ? memberId : undefined);
  return owner < 0
    ? { ...live, cards: add(live.cards) }
    : { ...live, delegations: live.delegations.map((d, i) => (i === owner ? { ...d, cards: add(d.cards) } : d)) };
}

/** 处理记录：默认收起的一行，展开是一条竖线串起来的步骤；运行中展开 */
function StepList({ steps, live }: { steps: { label: string; summary?: string; detail?: string; ok: boolean }[]; live?: boolean }) {
  if (!steps.length) return null;
  return (
    <details className="as-disclosure" open={live}>
      <summary className="w-fit text-[12px] text-content-tertiary hover:text-content-secondary">
        <ChevronRight className="as-chevron h-3.5 w-3.5" />处理记录 · {steps.length} 步
      </summary>
      <ol className="ml-[6px] mt-1.5 space-y-1.5 border-l border-surface-border-light pl-3.5">
        {steps.map((s, i) => (
          <li key={i} className="flex items-start gap-1.5 text-[12px] leading-5 text-content-tertiary">
            {s.ok
              ? <Check className="mt-1 h-3 w-3 flex-none text-emerald-500" />
              : <TriangleAlert className="mt-1 h-3 w-3 flex-none text-gold-500" />}
            <span><span className="text-content-secondary">{s.label}</span>{(s.summary || s.detail) && <> · {s.summary || s.detail}</>}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}

/** 「正在处理」的三个点 */
function TypingDots() {
  return <span className="as-typing" aria-label="正在处理"><span /><span /><span /></span>;
}

/** 团队一侧每条发言的头一行：成员头像 + 名字 + 补充说明；旧消息没有成员就用助笔图标 */
function SpeakerLine({ member, note, children }: { member?: AssistantMember | null; note?: string; children?: ReactNode }) {
  return (
    <div className="mb-1.5 flex h-6 items-center gap-2">
      {member
        ? <MemberAvatar member={member} />
        : <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-50 text-brand"><Sparkles className="h-3 w-3" /></span>}
      <span className="flex-none whitespace-nowrap text-[13px] font-medium text-content">{member?.name ?? '智能助笔'}</span>
      {note && <span className="as-meta min-w-0 truncate" title={note}>{note}</span>}
      {children && <span className="flex-none">{children}</span>}
    </div>
  );
}

function ChapterCandidateLink({ item, onOpen }: { item: AssistantChapterCandidateRef; onOpen: (item: AssistantChapterCandidateRef) => void }) {
  return (
    <button onClick={() => onOpen(item)} className="as-card flex w-full items-center gap-3 px-4 py-3 text-left hover:border-surface-border">
      <FilePenLine className="h-4 w-4 flex-none text-brand" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium text-content">第 {item.chapter_number} 章《{item.chapter_title}》候选稿</span>
        <span className="block truncate text-[12px] text-content-tertiary">{item.word_count} 字 · {item.preview || '去章节写作页审阅后采用'}</span>
      </span>
      <ChevronRight className="h-4 w-4 flex-none text-content-tertiary" />
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
  const newSessionNonce = useAssistantStore((s) => s.newSessionNonce);
  const reviewNonce = useAssistantStore((s) => s.reviewNonce);
  const visible = useAssistantStore((s) => s.open && s.mode === 'agent');
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
  const [usage, setUsage] = useState<AssistantContextUsage | null>(null);
  const [compacting, setCompacting] = useState(false);
  const [confirmedPlans, setConfirmedPlans] = useState<Set<string>>(() => new Set());
  const [trayOpen, setTrayOpen] = useState(false);
  const [trayDetail, setTrayDetail] = useState<string | null>(null);
  const [expandedReplies, setExpandedReplies] = useState<Set<string>>(() => new Set());
  const [showJump, setShowJump] = useState(false);
  const pageRef = useRef(page);
  const jobIdRef = useRef<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // 停在最新处（离底部不到 STICK_PX）才跟着新内容滚；往上翻着看时只亮「回到最新」
  const stickRef = useRef(true);
  const savedTopRef = useRef(0);
  // 运行中产生的页面刷新 / 跳转等它结束再做：不在任务写库时触发一大批页面请求，也不在半途把作者带走
  const pendingRef = useRef<{ nav: string | null; data: AssistantDataChange[] }>({ nav: null, data: [] });

  /** 滚到最新：force = 作者自己发了消息 / 刚打开对话 / 点了「回到最新」 */
  const scrollToEnd = useCallback((force = false) => {
    requestAnimationFrame(() => {
      const el = listRef.current;
      if (!el) return;
      if (force || stickRef.current) {
        el.scrollTop = el.scrollHeight;
        stickRef.current = true;
        setShowJump(false);
      } else {
        setShowJump(true);
      }
    });
  }, []);

  const onListScroll = () => {
    const el = listRef.current;
    if (!el || !el.clientHeight) return; // 抽屉 / 页签隐藏时不算
    savedTopRef.current = el.scrollTop;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_PX;
    if (stickRef.current) setShowJump(false);
  };

  // 关抽屉、切到核对 / 任务时对话是隐藏的，浏览器会丢掉滚动位置：重新显示时停在最新处，或回到作者刚才看的地方
  useLayoutEffect(() => {
    const el = listRef.current;
    if (!visible || !el) return;
    el.scrollTop = stickRef.current ? el.scrollHeight : savedTopRef.current;
  }, [visible]);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      if (el.clientHeight && stickRef.current) el.scrollTop = el.scrollHeight;
    });
    observer.observe(el);
    return () => observer.disconnect();
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

  /** 空闲时的用量：下一条要求开跑时大约占多少（运行中由 context 事件刷新） */
  const loadUsage = useCallback(async () => {
    try {
      setUsage(await assistantApi.contextUsage(projectId, pageRef.current));
    } catch { /* 用量只是提示，读不到就不显示 */ }
  }, [projectId]);

  useEffect(() => {
    void assistantApi.team(projectId).then(setTeam).catch(() => setTeam(null));
    void loadProgress();
  }, [loadProgress, projectId]);

  useEffect(() => { sessionStorage.setItem(`assistant-draft:${projectId}`, draft); }, [draft, projectId]);

  // 输入框跟着内容长高（像 iMessage），到上限后内部滚动
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, INPUT_MAX_HEIGHT)}px`;
  }, [draft]);

  useEffect(() => { pageRef.current = page; }, [page]);

  // 对话变了、换了上限或成员模型、一轮跑完：重新估一次下一条要求的用量
  const messageCount = view?.messages.length ?? 0;
  const sessionId = view?.session?.id;
  const contextWindow = team?.context.window;
  useEffect(() => {
    if (!busy) void loadUsage();
  }, [busy, contextWindow, loadUsage, messageCount, sessionId]);

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
      setLive((prev) => (prev ? withLiveCard(prev, m.member_id, (c) => ({ ...c, candidates: [...c.candidates, candidate.id] })) : prev));
    } else if (m.type === 'entity_candidate' && m.candidate) {
      const candidate = m.candidate as AssistantEntityCandidate;
      setView((prev) => (prev ? { ...prev, entity_candidates: [...prev.entity_candidates.filter((c) => c.id !== candidate.id), candidate] } : prev));
      setLive((prev) => (prev
        ? withLiveCard(prev, m.member_id, (c) => ({ ...c, entity_candidates: [...c.entity_candidates, candidate.id] }))
        : prev));
    } else if (m.type === 'chapter_candidate' && m.candidate) {
      const item = m.candidate as AssistantChapterCandidateRef;
      pendingRef.current.data.push({ entity: 'chapter_candidate', chapterId: item.chapter_id, targetId: item.id });
      setLive((prev) => (prev ? withLiveCard(prev, m.member_id, (c) => ({ ...c, chapter_candidates: [...c.chapter_candidates, item] })) : prev));
    } else if (m.type === 'navigate' && typeof m.page === 'string') {
      pendingRef.current.nav = m.page;
    } else if (m.type === 'speaker' && m.member) {
      const member = m.member as AssistantMember;
      setLive((prev) => (prev ? { ...prev, member } : prev));
    } else if (m.type === 'member_start' && m.member) {
      const member = m.member as AssistantMember;
      const task = String(m.task ?? '');
      setLive((prev) => (prev ? { ...prev, delegations: [...prev.delegations, { member, task, content: '', cards: noAttachments() }] } : prev));
      scrollToEnd();
    } else if (m.type === 'member_message' && m.member) {
      const member = m.member as AssistantMember;
      const content = String(m.content ?? '');
      setLive((prev) => {
        if (!prev) return prev;
        const index = prev.delegations.findIndex((d) => d.member.id === member.id && !d.content);
        const delegations = index < 0
          ? [...prev.delegations, { member, task: '', content, cards: noAttachments() }]
          : prev.delegations.map((d, i) => (i === index ? { ...d, content } : d));
        return { ...prev, delegations };
      });
      scrollToEnd();
    } else if (m.type === 'plan' && m.plan) {
      const plan = m.plan as AssistantPlan;
      pendingRef.current.data.push({ entity: plan.kind === 'outlines' ? 'chapter_outline' : 'volume' });
      setLive((prev) => (prev ? withLiveCard(prev, m.member_id, (c) => ({ ...c, plans: [...c.plans, plan] })) : prev));
    } else if (m.type === 'job' && m.job) {
      const job = m.job as { title?: string };
      toast.success(`${job.title ?? '后台任务'}已开始，进度在右下角任务托盘`);
      void useAIJobsStore.getState().syncFromServer(projectId);
    } else if (m.type === 'context' && m.context) {
      setUsage(m.context as AssistantContextUsage);
    } else if (m.type === 'compact') {
      setCompacting(m.phase === 'running');
      if (m.phase === 'done') setNotice(`较早的 ${String(m.count ?? '')} 条对话已压成前情摘要，之后接着带上`);
      if (m.phase === 'failed') setNotice('压缩较早的对话没成功，这一轮先只带装得下的近期对话');
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
      await reload(); // 先读回存好的消息再撤掉运行中的那段，中间不闪空
      setBusy(false);
      setLive(null);
      setCompacting(false);
      flushPending();
      void loadProgress();
      scrollToEnd();
    }
  }, [flushPending, handleEvent, loadProgress, reload, scrollToEnd]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const next = await reload();
      if (!cancelled) scrollToEnd(true); // 打开对话先看到最新的
      if (cancelled || !next?.active_run || next.active_run.status !== 'running') return;
      await useAIJobsStore.getState().syncFromServer(projectId);
      const job = Object.values(useAIJobsStore.getState().jobs).find(
        (j) => j.kind === 'assistant_run' && j.meta?.run_id === next.active_run?.id && j.status === 'running',
      );
      if (job && !cancelled) void follow(job.id, next.active_run.goal);
    })();
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
    scrollToEnd(true);
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
      setCompacting(false);
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
      scrollToEnd(true);
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
        id: `pending-${Date.now()}`, role: 'user', content: message, created_at: null, run_id: null, steps: [], candidates: [], entity_candidates: [], chapter_candidates: [],
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

  const startNew = useCallback(async () => {
    if (busy) {
      toast.info('团队正在处理这一轮，停止或等它结束后再开新对话');
      return;
    }
    try {
      setView(await assistantApi.newSession(projectId));
      setPreview(null);
      toast.success('已开始新对话，之前的对话可在「任务」里回看');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '没能开始新对话');
    }
  }, [busy, projectId]);

  // 头部的「新对话」按钮：store 里的计数变了就开一次（挂载时的初始值不算）
  const seenNewSession = useRef(newSessionNonce);
  useEffect(() => {
    if (newSessionNonce === seenNewSession.current) return;
    seenNewSession.current = newSessionNonce;
    void startNew();
  }, [newSessionNonce, startNew]);

  // 「核对」页点了待确认的候选：展开待确认栏（挂载时的初始值不算）
  const seenReview = useRef(reviewNonce);
  useEffect(() => {
    if (reviewNonce === seenReview.current) return;
    seenReview.current = reviewNonce;
    setTrayOpen(true);
  }, [reviewNonce]);

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
  const entityCandidatesById = useMemo(() => new Map((view?.entity_candidates ?? []).map((c) => [c.id, c])), [view?.entity_candidates]);
  const updateEntityCandidate = (next: AssistantEntityCandidate) =>
    setView((prev) => (prev ? { ...prev, entity_candidates: prev.entity_candidates.map((c) => (c.id === next.id ? next : c)) } : prev));
  const openChapterCandidate = (item: AssistantChapterCandidateRef) =>
    onNavigate('chapter-analysis', `chapter=${item.chapter_id}&tab=candidates&candidate=${item.id}`);

  const messages = view?.messages ?? [];
  const waitingRun = view?.active_run?.status === 'waiting_input' ? view.active_run : null;
  const members = team?.members ?? [];
  const mention = (member: AssistantMember) => {
    setDraft((prev) => mentionMember(prev, member.name));
    requestAnimationFrame(() => inputRef.current?.focus());
  };
  const askEditor = (label: string) => {
    setDraft((prev) => appendRequest(mentionMember(prev, '主编'), `请看看创作进度，按建议推进下一步：${label}。需要我拍板的地方先问我。`));
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const markPlanConfirmed = (plan: AssistantPlan) => setConfirmedPlans((prev) => new Set(prev).add(planKey(plan)));
  const lookups = useMemo(
    () => ({ fields: candidatesById, entities: entityCandidatesById, confirmedPlans }),
    [candidatesById, entityCandidatesById, confirmedPlans],
  );
  const pending = pendingChanges([
    ...messages.map(attachmentsOf),
    ...(live ? [live.cards, ...live.delegations.map((d) => d.cards)] : []),
  ], lookups);

  /** 改动的明细：点开一行看到的完整卡片（按钮和待确认栏里的是同一套操作；待确认栏里按钮在行上，卡片只给看） */
  const renderDetail: RenderDetail = (item, { showActions }) => {
    const { ref } = item;
    if (ref.kind === 'field') {
      return (
        <FieldCandidateCard
          projectId={projectId} candidate={ref.candidate} onChange={updateCandidate} onOpenPage={(p) => onNavigate(p)} showActions={showActions}
        />
      );
    }
    if (ref.kind === 'entity') {
      return (
        <EntityCandidateCard
          projectId={projectId} candidate={ref.candidate} onChange={updateEntityCandidate} onOpenPage={(p) => onNavigate(p)} showActions={showActions}
        />
      );
    }
    if (ref.kind === 'plan') {
      return (
        <PlanCard
          plan={ref.plan} confirmed={confirmedPlans.has(item.key)} onConfirmed={markPlanConfirmed} onFailed={() => void reload()}
          onNavigate={(p) => onNavigate(p)} showActions={showActions}
        />
      );
    }
    return <ChapterCandidateLink item={ref.item} onOpen={openChapterCandidate} />;
  };

  /** 待确认栏里的单条 / 全部处理（全部处理时页面刷新攒到最后一起发） */
  const batchChangesRef = useRef(new Set<string>());
  const decide: DecideChange = async (item, action, opts) => {
    const { ref } = item;
    const quiet = Boolean(opts?.quiet);
    const say = (text: string) => { if (!quiet) toast.success(text); };
    try {
      if (ref.kind === 'field') {
        const next = await fieldAction(projectId, ref.candidate, action, !quiet);
        updateCandidate(next);
        if (quiet && action === 'apply' && next.entity) batchChangesRef.current.add(next.entity);
        say(action === 'apply' ? `已应用到「${ref.candidate.label}」` : '已放弃这份候选');
      } else if (ref.kind === 'entity') {
        const next = await entityAction(projectId, ref.candidate, action, !quiet);
        updateEntityCandidate(next);
        if (quiet && action === 'apply') batchChangesRef.current.add(next.entity_type);
        say(action === 'apply' ? `已建档：${ref.candidate.label}` : '已放弃这份新建候选');
      } else if (ref.kind === 'plan' && action === 'apply') {
        await confirmPlan(ref.plan, !quiet);
        if (quiet) batchChangesRef.current.add(planEntity(ref.plan));
        markPlanConfirmed(ref.plan);
        say(ref.plan.kind === 'outlines' ? '章纲已确认，可以开写了' : '卷纲已确认');
      } else if (ref.kind === 'chapter') {
        openChapterCandidate(ref.item);
      }
      return true;
    } catch (err) {
      toast.error(`「${item.title}」没处理成：${errorDetail(err)}`);
      if (ref.kind === 'plan') void reload();
      return false;
    }
  };
  const flushBatchChanges = () => {
    batchChangesRef.current.forEach((entity) => emitAssistantData({ entity }));
    batchChangesRef.current.clear();
  };

  /** 回复正文；成员几千字的长回复先折起来 */
  const replyBody = (key: string, text: string, foldable: boolean): ReactNode => {
    const long = foldable && text.length > LONG_REPLY;
    const folded = long && !expandedReplies.has(key);
    const toggle = () => setExpandedReplies((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    return (
      <div>
        <div className={cn('as-prose', folded && 'relative max-h-[11.5rem] overflow-hidden')}>
          <RichText text={text} />
          {folded && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-white to-transparent" />}
        </div>
        {long && (
          <button onClick={toggle} className="as-link mt-1">{folded ? `展开全文（${text.length} 字）` : '收起'}</button>
        )}
      </div>
    );
  };

  // 正在等作者回答的那条提问：问题在下方提问卡里，消息里不再整段重复
  const activeQuestionId = waitingRun?.question && !busy
    ? [...messages].reverse().find((m) => m.question && m.run_id === waitingRun.id)?.id
    : undefined;

  /** 悬停才出现的小操作：字数、复制、引用（作者自己的话还能改了再发） */
  const messageActions = (m: AssistantMessageView): ReactNode => (
    <span className="flex items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
      {m.role !== 'user' && <span className="mr-1 text-[11px] tabular-nums text-content-tertiary">{m.content.length} 字</span>}
      <button onClick={() => void copy(m)} className="as-icon-btn h-6 w-6" title="复制">
        {copied === m.id ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
      <button onClick={() => quote(m)} className="as-icon-btn h-6 w-6" title="引用到输入框（可先选中其中几句）">
        <Quote className="h-3.5 w-3.5" />
      </button>
      {m.role === 'user' && !m.answer && (
        <button onClick={() => { setDraft(m.content); inputRef.current?.focus(); }} className="as-icon-btn h-6 w-6" title="编辑后再发">
          <PencilLine className="h-3.5 w-3.5" />
        </button>
      )}
    </span>
  );

  const renderMessage = (m: AssistantMessageView): ReactNode => {
    if (m.role === 'user') {
      // 操作按钮浮在下方的间隔里（悬停才出现），不占行高
      return (
        <div key={m.id} className="group flex flex-col items-end">
          {m.answer && <span className="as-meta mb-1">回答提问</span>}
          <div className="relative max-w-[88%]">
            <div className="as-user-msg"><RichText text={m.content} /></div>
            <div className="absolute right-0 top-full z-10">{messageActions(m)}</div>
          </div>
        </div>
      );
    }
    const note = [m.delegated && '受主编委托', m.question && '向你提问'].filter(Boolean).join(' · ');
    // 照 AI 编程软件的顺序：处理记录、改动（各一行，默认收起）在前，回复正文在最后
    return (
      <div key={m.id} className="group">
        <SpeakerLine member={m.member} note={note}>
          <span className="ml-auto">{messageActions(m)}</span>
        </SpeakerLine>
        <div className="space-y-2">
          <StepList steps={m.steps} />
          <ChangeList items={changeItems(attachmentsOf(m), lookups)} renderDetail={renderDetail} />
          {m.id === activeQuestionId
            ? <p className="as-prose text-content-secondary">向你提了 {m.question?.questions.length ?? 0} 个问题，请在下方回答。</p>
            : replyBody(m.id, m.content, Boolean(m.delegated))}
        </div>
      </div>
    );
  };

  const sendLabel = previewCurrent ? '确认发送' : preview ? '更新核对' : '核对后发送';
  const toggleReview = () => {
    const next = !reviewBeforeSend;
    setReviewBeforeSend(next);
    localStorage.setItem(REVIEW_KEY, String(next));
    setPreview(null);
  };
  const pageHint = `共创室会参考你所在的页面（${page.label || '本项目'}），但不限于这里：可以直接说要处理的设定、人物或章节，团队会自己定位。`
    + (page.selection ? `\n\n已选中：${page.selection.text.slice(0, 200)}${page.selection.text.length > 200 ? '…' : ''}` : '');

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="relative min-h-0 flex-1">
        <div ref={listRef} onScroll={onListScroll} className="h-full overflow-y-auto [overflow-anchor:none]">
          <div className="space-y-6 px-4 py-5">
            {loadError && <p className="rounded-[10px] bg-cinnabar-wash px-3.5 py-2.5 text-[13px] text-cinnabar">{loadError}</p>}
            {!messages.length && !live && (
              <div className="flex flex-col items-center pt-6 text-center">
                <span className="flex h-11 w-11 items-center justify-center rounded-full bg-brand-50 text-brand">
                  <Sparkles className="h-5 w-5" />
                </span>
                <h3 className="mt-4 text-[18px] font-semibold text-content">今天想写点什么？</h3>
                <p className="mt-2 max-w-[360px] text-[13px] leading-[1.7] text-content-secondary">
                  主编会先弄清你想写什么，再按 总纲 → 卷纲 → 章纲 → 正文 推进，把专业的事交给团队成员。
                  需要你拍板时会先问你；所有改动都是候选或草案，你确认了才写进书里。
                </p>
                <div className="mt-6 grid w-full grid-cols-2 gap-2.5 text-left">
                  {(team?.starters ?? []).map((s) => (
                    <button key={s.id} onClick={() => { setDraft((prev) => appendRequest(prev, s.message)); inputRef.current?.focus(); }}
                      className="as-card px-3.5 py-3 text-left hover:border-brand/40 hover:bg-brand-50/40">
                      <span className="block text-[13px] font-medium text-content">{s.label}</span>
                      <span className="mt-1 block text-[12px] leading-[1.5] text-content-tertiary">{s.hint}</span>
                    </button>
                  ))}
                </div>
                {members.length > 0 && (
                  <div className="mt-6 w-full">
                    <p className="as-meta mb-2">团队成员 · 点一位直接找他</p>
                    <div className="flex flex-wrap justify-center gap-1.5">
                      {members.map((mb) => (
                        <button key={mb.id} onClick={() => mention(mb)} className="as-chip pl-1" title={mb.responsibility}>
                          <MemberAvatar member={mb} />{mb.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            {messages.map(renderMessage)}
            {live?.delegations.map((d, i) => (
              <div key={`delegation-${i}`}>
                <SpeakerLine member={d.member} note={d.content ? '受主编委托' : `受主编委托 · 正在处理：${d.task || '主编交代的事'}`}>
                  {!d.content && <TypingDots />}
                </SpeakerLine>
                <div className="space-y-2">
                  <ChangeList items={changeItems(d.cards, lookups)} renderDetail={renderDetail} />
                  {d.content && replyBody(`delegation-${i}`, d.content, true)}
                </div>
              </div>
            ))}
            {live && (
              <div>
                <SpeakerLine member={live.member} note={live.text ? '正在回复' : live.steps.length ? '正在处理' : '正在思考'}>
                  {!live.text && <TypingDots />}
                </SpeakerLine>
                <div className="space-y-2">
                  <StepList steps={live.steps} live />
                  <ChangeList items={changeItems(live.cards, lookups)} renderDetail={renderDetail} />
                  {live.text && <div className="as-prose"><RichText text={live.text} /></div>}
                </div>
              </div>
            )}
            {waitingRun?.question && !busy && (
              <AuthorQuestionCard key={questionCardKey(waitingRun)} question={waitingRun.question} busy={busy} onSubmit={(a) => void answer(a)} />
            )}
            {preview && (
              <section className={cn('as-card px-4 py-3.5', !previewCurrent && 'border-gold-300')}>
                <header className="flex items-center gap-2">
                  <span className="text-[14px] font-semibold text-content">发送前核对</span>
                  <span className={cn('ml-auto text-[12px]', previewCurrent ? 'text-content-tertiary' : 'text-gold-500')}>
                    {previewCurrent ? '核对后点「确认发送」' : '要求或页面变了，请更新核对'}
                  </span>
                  {!busy && (
                    <button onClick={() => setPreview(null)} className="as-icon-btn -mr-1.5 h-7 w-7" title="收起核对">
                      <X className="h-4 w-4" />
                    </button>
                  )}
                </header>
                <p className="as-meta mt-1">
                  本次上下文约 {formatTokens(preview.data.context.used)} / {formatTokens(preview.data.context.limit)}（{preview.data.context.percent}%）
                  · 带入 {preview.data.context.history.included} 条近期对话
                  {preview.data.context.will_compact > 0 && ` · 发送时会先把较早的 ${preview.data.context.will_compact} 条压成前情摘要`}
                </p>
                <p className="as-user-msg mt-3">{preview.data.message}</p>
                <div className="mt-3 divide-y divide-surface-border-light border-t border-surface-border-light">
                  {[...preview.data.sections, { label: '助笔的规则与工具', content: preview.data.rules }].map((s) => (
                    <details key={s.label} className="as-disclosure py-2">
                      <summary className="text-[13px] text-content">
                        <ChevronRight className="as-chevron h-3.5 w-3.5 text-content-tertiary" />{s.label}
                      </summary>
                      <pre className="mt-1.5 max-h-48 overflow-y-auto whitespace-pre-wrap break-words pl-5 font-sans text-[12px] leading-5 text-content-secondary">{s.content}</pre>
                    </details>
                  ))}
                </div>
              </section>
            )}
          </div>
        </div>
        {showJump && (
          <button
            onClick={() => scrollToEnd(true)}
            className="absolute bottom-3 left-1/2 z-10 inline-flex -translate-x-1/2 items-center gap-1 rounded-full border border-surface-border bg-white px-3 py-1.5 text-[12px] text-content-secondary shadow-md hover:text-content"
          >
            <ArrowDown className="h-3.5 w-3.5" />回到最新
          </button>
        )}
        {showTeam && team && (
          <div className="absolute inset-0 z-20 overflow-y-auto bg-white px-4 py-5">
            <TeamSettings projectId={projectId} team={team} onChange={setTeam} onClose={() => setShowTeam(false)} />
          </div>
        )}
      </div>

      <div className="flex-none px-3 pb-3 pt-2">
        <PendingTray
          items={pending}
          open={trayOpen}
          onOpenChange={setTrayOpen}
          detailKey={trayDetail}
          onDetailChange={setTrayDetail}
          renderDetail={renderDetail}
          onDecide={decide}
          onBatchEnd={flushBatchChanges}
        />
        {progress && !busy && !pending.length && <NextStepHint progress={progress} onAsk={askEditor} disabled={busy} />}
        {notice && <p className="as-meta mb-2 px-1">{notice}</p>}
        {busy && <p className="mb-2 px-1 text-[12px] text-brand">正在处理本轮要求…可以先写下一条，处理完再发。</p>}
        {waitingRun && !busy && <p className="mb-2 px-1 text-[12px] text-gold-500">团队在等你回答上面的问题；直接发新要求会结束那轮提问。</p>}
        <div className="rounded-[18px] border border-surface-border bg-white shadow-[0_4px_16px_-8px_rgba(29,36,32,0.16)] transition-[border-color,box-shadow] focus-within:border-brand/50 focus-within:shadow-[0_4px_16px_-6px_rgba(40,91,77,0.28)]">
          <textarea
            ref={inputRef}
            value={draft}
            onChange={(e) => { setDraft(e.target.value); setNotice(''); }}
            onKeyDown={onKeyDown}
            rows={2}
            maxLength={MAX_CHARS}
            placeholder="和主编说说你的想法，Ctrl+Enter 发送"
            className="block min-h-[56px] w-full resize-none !rounded-none !border-0 !bg-transparent px-4 pb-1 pt-3 text-[14px] leading-[1.6] !text-content outline-none placeholder:!text-content-tertiary focus:!shadow-none"
          />
          <div className="flex items-center gap-1.5 px-2.5 pb-2.5 pt-1">
            <MemberPicker members={members} onMention={mention} onOpenSettings={() => setShowTeam((v) => !v)} />
            <span className="as-chip max-w-[11rem] shrink cursor-default" title={pageHint}>
              <MapPin className="h-3.5 w-3.5 flex-none" />
              <span className="truncate">
                {page.label || '本项目'}
                {page.selection && <span className="text-brand-600"> · 已选 {page.selection.text.length} 字</span>}
              </span>
            </span>
            <button
              onClick={toggleReview}
              aria-pressed={reviewBeforeSend}
              aria-label="发送前核对"
              className={cn('as-chip', reviewBeforeSend && 'as-chip--on px-1.5')}
              title={reviewBeforeSend ? '发送前核对：已打开，点一下关掉' : '打开后，发送前先列出这次会带给团队的内容，确认了再发'}
            >
              <ListChecks className="h-3.5 w-3.5" />{!reviewBeforeSend && '核对'}
            </button>
            <div className="ml-auto flex items-center gap-2.5">
              {draft.length > MAX_CHARS * 0.8 && (
                <span className="text-[11px] tabular-nums text-gold-500">{draft.length}/{MAX_CHARS}</span>
              )}
              <ContextMeter usage={usage} compacting={compacting} />
              {busy ? (
                <button onClick={stop} className="flex h-8 w-8 flex-none items-center justify-center rounded-full bg-content text-white hover:bg-black" title="停止">
                  <Square className="h-3 w-3 fill-current" />
                </button>
              ) : reviewBeforeSend ? (
                <button onClick={() => void send()} disabled={!draft.trim() || previewLoading} className="as-btn-primary rounded-full px-3.5" title="Ctrl+Enter">
                  {previewLoading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}{sendLabel}
                </button>
              ) : (
                <button
                  onClick={() => void send()}
                  disabled={!draft.trim() || previewLoading}
                  className="flex h-8 w-8 flex-none items-center justify-center rounded-full bg-brand text-white hover:bg-brand-600 disabled:cursor-not-allowed disabled:bg-surface-border"
                  title="发送（Ctrl+Enter）"
                >
                  {previewLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" strokeWidth={2.5} />}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
