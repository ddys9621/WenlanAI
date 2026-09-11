/**
 * AI 任务事件归约（纯函数，无 React / 网络依赖）
 *
 * 把 SSE 事件流折叠成 AIJobState：progress / llm 取最新，stage 按 name、tool_call 按 call_id 合并，
 * reference 追加，content 累积，result / done / error 落终态。桥段填充等场景级事件（partial / bridges /
 * meta）不进状态，由页面通过 aiJobsStore.subscribe 自行处理；这里只更新 lastSeq。
 */
import type {
  AIJobLLMEvent,
  AIJobReferenceEvent,
  AIJobSnapshot,
  AIJobStage,
  AIJobStageEvent,
  AIJobState,
  AIJobToolCall,
  AIJobToolCallEvent,
} from '@/types/ai_job';
import type { SSEMessage } from '@/utils/sseClient';

export function createJobState(init: {
  id: string;
  kind: string;
  title: string;
  projectId?: string | null;
  startedAt?: number;
  meta?: Record<string, unknown>;
}): AIJobState {
  return {
    id: init.id,
    kind: init.kind,
    title: init.title,
    projectId: init.projectId ?? null,
    meta: init.meta ?? {},
    status: 'running',
    startedAt: init.startedAt ?? Date.now(),
    finishedAt: null,
    lastSeq: 0,
    progress: null,
    wordCount: null,
    stages: [],
    toolCalls: [],
    references: [],
    llm: null,
    content: '',
    result: null,
    error: null,
    errorCode: null,
    connection: 'connecting',
  };
}

export const isTerminal = (s: Pick<AIJobState, 'status'>) => s.status !== 'running';

const num = (v: unknown, fallback = 0) => (typeof v === 'number' && Number.isFinite(v) ? v : fallback);

function mergeBy<T>(list: T[], key: (x: T) => string, item: T): T[] {
  const idx = list.findIndex((x) => key(x) === key(item));
  if (idx < 0) return [...list, item];
  return list.map((x, i) => (i === idx ? { ...x, ...item } : x));
}

function stripUndefined<T extends object>(obj: T): T {
  return Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== undefined)) as T;
}

export function applyEvent(state: AIJobState, m: SSEMessage, now: number = Date.now()): AIJobState {
  const seq = typeof m.seq === 'number' ? m.seq : state.lastSeq;
  const next: AIJobState = { ...state, lastSeq: Math.max(state.lastSeq, seq) };

  switch (m.type) {
    case 'progress': {
      const message = typeof m.message === 'string' && m.message ? m.message : state.progress?.message ?? '';
      const pct = typeof m.progress === 'number' ? m.progress : state.progress?.pct ?? 0;
      next.progress = { message, pct };
      if (typeof m.word_count === 'number') next.wordCount = m.word_count;
      return next;
    }
    case 'stage': {
      const e = m as unknown as AIJobStageEvent;
      const item: AIJobStage = stripUndefined({
        name: e.name,
        label: e.label,
        status: e.status,
        elapsed: e.elapsed,
        detail: e.detail,
        error: e.error,
      });
      next.stages = mergeBy(state.stages, (s) => s.name, item);
      return next;
    }
    case 'tool_call': {
      const e = m as unknown as AIJobToolCallEvent;
      const item: AIJobToolCall = stripUndefined({
        call_id: e.call_id,
        tool: e.tool,
        plugin: e.plugin,
        status: e.status,
        args_preview: e.args_preview,
        elapsed_ms: e.elapsed_ms,
        result_chars: e.result_chars,
        error: e.error,
      });
      next.toolCalls = mergeBy(state.toolCalls, (c) => c.call_id, item);
      return next;
    }
    case 'reference':
      next.references = [...state.references, m as unknown as AIJobReferenceEvent];
      return next;
    case 'llm': {
      const e = m as unknown as AIJobLLMEvent;
      next.llm = {
        model: e.model ?? state.llm?.model ?? '',
        phase: e.phase,
        reasoning_chars: num(e.reasoning_chars),
        content_chars: num(e.content_chars),
        elapsed: num(e.elapsed),
        finish_reason: e.finish_reason ?? null,
      };
      return next;
    }
    case 'thinking': {
      // 桥段填充等场景级思考计数（无模型名）：归一到 llm 行
      const contentChars = num(m.content_chars);
      next.llm = {
        model: state.llm?.model ?? '',
        phase: contentChars > 0 ? 'streaming' : 'thinking',
        reasoning_chars: num(m.reasoning_chars),
        content_chars: contentChars,
        elapsed: num(m.elapsed),
        finish_reason: null,
      };
      return next;
    }
    case 'content':
    case 'chunk':
      if (typeof m.content === 'string') next.content = state.content + m.content;
      return next;
    case 'result':
      next.result = m.data ?? null;
      return next;
    case 'done':
      next.status = 'done';
      next.finishedAt = now;
      if (next.progress) next.progress = { ...next.progress, pct: 100 };
      return next;
    case 'error': {
      const text = (typeof m.error === 'string' && m.error) || (typeof m.message === 'string' && m.message) || '未知错误';
      next.status = m.code === 499 ? 'cancelled' : 'error';
      next.error = text;
      next.errorCode = typeof m.code === 'number' ? m.code : null;
      next.finishedAt = now;
      return next;
    }
    default:
      return next;
  }
}

/** 从后端快照重建状态：先套用最新态事件，再把 lastSeq 归零——首次接管要从 0 回放完整日志（stage / tool_call / reference / content） */
export function fromSnapshot(s: AIJobSnapshot): AIJobState {
  let state = createJobState({
    id: s.id,
    kind: s.kind,
    title: s.title,
    projectId: s.project_id,
    startedAt: s.started_at * 1000,
    meta: s.meta ?? {},
  });
  const live = Object.values(s.live ?? {}).sort((a, b) => num(a.seq) - num(b.seq));
  for (const e of live) state = applyEvent(state, e as unknown as SSEMessage);
  if (s.last_progress && !state.progress) state = applyEvent(state, s.last_progress as unknown as SSEMessage);
  return {
    ...state,
    status: s.status,
    finishedAt: s.finished_at ? s.finished_at * 1000 : null,
    error: s.error,
    result: s.result ?? null,
    lastSeq: 0,
    connection: 'connecting',
  };
}
