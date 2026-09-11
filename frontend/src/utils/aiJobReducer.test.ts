import { describe, expect, it } from 'vitest';
import type { AIJobSnapshot } from '@/types/ai_job';
import type { SSEMessage } from '@/utils/sseClient';
import { applyEvent, createJobState, fromSnapshot, isTerminal } from './aiJobReducer';

const base = () => createJobState({ id: 'j1', kind: 'demo', title: '演示', projectId: 'p1', startedAt: 1000 });
const ev = (m: Record<string, unknown>) => m as unknown as SSEMessage;

describe('applyEvent', () => {
  it('progress 只保留最新，缺省字段沿用上一条，word_count 单独记录', () => {
    let s = applyEvent(base(), ev({ type: 'progress', message: '第一步', progress: 10, seq: 1 }));
    s = applyEvent(s, ev({ type: 'progress', progress: 42, word_count: 800, seq: 2 }));
    expect(s.progress).toEqual({ message: '第一步', pct: 42 });
    expect(s.wordCount).toBe(800);
    expect(s.lastSeq).toBe(2);
  });

  it('stage 按 name 合并并保持首次出现顺序', () => {
    let s = applyEvent(base(), ev({ type: 'stage', name: 'ctx', label: '上下文', status: 'running', seq: 1 }));
    s = applyEvent(s, ev({ type: 'stage', name: 'llm', label: '模型', status: 'running', seq: 2 }));
    s = applyEvent(s, ev({ type: 'stage', name: 'ctx', label: '上下文', status: 'done', elapsed: 1.2, detail: { n: 3 }, seq: 3 }));
    expect(s.stages.map((x) => [x.name, x.status])).toEqual([['ctx', 'done'], ['llm', 'running']]);
    expect(s.stages[0].elapsed).toBe(1.2);
    expect(s.stages[0].detail).toEqual({ n: 3 });
  });

  it('tool_call 按 call_id 合并 running → done', () => {
    let s = applyEvent(base(), ev({ type: 'tool_call', call_id: 't1', tool: 'search', plugin: 'exa', status: 'running', args_preview: '{"q":1}', seq: 1 }));
    s = applyEvent(s, ev({ type: 'tool_call', call_id: 't1', tool: 'search', plugin: 'exa', status: 'done', elapsed_ms: 320, result_chars: 1500, seq: 2 }));
    expect(s.toolCalls).toEqual([
      { call_id: 't1', tool: 'search', plugin: 'exa', status: 'done', args_preview: '{"q":1}', elapsed_ms: 320, result_chars: 1500 },
    ]);
  });

  it('reference 追加，保留附加字段', () => {
    const s = applyEvent(base(), ev({ type: 'reference', kind: 'world_rules', label: '世界规则', items: [{ title: '金丹期' }], count: 1, query: '突破', seq: 1 }));
    expect(s.references).toHaveLength(1);
    expect(s.references[0].kind).toBe('world_rules');
    expect(s.references[0].query).toBe('突破');
  });

  it('llm 取最新；场景级 thinking 事件归一到 llm 行', () => {
    let s = applyEvent(base(), ev({ type: 'llm', call_id: 'c', phase: 'thinking', model: 'deepseek-v3', reasoning_chars: 120, content_chars: 0, elapsed: 3, seq: 1 }));
    expect(s.llm).toEqual({ model: 'deepseek-v3', phase: 'thinking', reasoning_chars: 120, content_chars: 0, elapsed: 3, finish_reason: null });
    s = applyEvent(s, ev({ type: 'thinking', beat_index: 2, bridge_numbers: [3, 4], reasoning_chars: 480, content_chars: 55, elapsed: 9, seq: 2 }));
    expect(s.llm).toEqual({ model: 'deepseek-v3', phase: 'streaming', reasoning_chars: 480, content_chars: 55, elapsed: 9, finish_reason: null });
  });

  it('content / chunk 累积正文', () => {
    let s = applyEvent(base(), ev({ type: 'content', content: '你好', seq: 1 }));
    s = applyEvent(s, ev({ type: 'chunk', content: '世界', seq: 2 }));
    expect(s.content).toBe('你好世界');
  });

  it('result + done → 终态 done，进度 100，记录结束时间', () => {
    let s = applyEvent(base(), ev({ type: 'progress', message: '写入', progress: 90, seq: 1 }));
    s = applyEvent(s, ev({ type: 'result', data: { id: 'c1' }, seq: 2 }));
    s = applyEvent(s, ev({ type: 'done', seq: 3 }), 5000);
    expect(s.status).toBe('done');
    expect(s.result).toEqual({ id: 'c1' });
    expect(s.progress).toEqual({ message: '写入', pct: 100 });
    expect(s.finishedAt).toBe(5000);
    expect(isTerminal(s)).toBe(true);
  });

  it('error code 499 → cancelled，其它 → error；兼容 message 字段', () => {
    const cancelled = applyEvent(base(), ev({ type: 'error', error: '已停止生成角色', code: 499, seq: 1 }), 7000);
    expect(cancelled.status).toBe('cancelled');
    expect(cancelled.error).toBe('已停止生成角色');
    expect(cancelled.errorCode).toBe(499);
    expect(cancelled.finishedAt).toBe(7000);
    const failed = applyEvent(base(), ev({ type: 'error', message: 'mcp 规划失败', seq: 1 }));
    expect(failed.status).toBe('error');
    expect(failed.error).toBe('mcp 规划失败');
    expect(failed.errorCode).toBeNull();
  });

  it('未知类型（start / meta / partial / bridges）只更新 lastSeq，不丢事件', () => {
    const s = applyEvent(base(), ev({ type: 'partial', beat_index: 1, bridges: [], seq: 9 }));
    expect(s.lastSeq).toBe(9);
    expect(s.status).toBe('running');
    expect(applyEvent(s, ev({ type: 'start', job_id: 'j1' })).lastSeq).toBe(9);
  });
});

describe('fromSnapshot', () => {
  const snapshot: AIJobSnapshot = {
    id: 'j2', kind: 'bridge_fill', title: 'AI 填充桥段内容', project_id: 'p1', scope: 'bridge_fill:p1', meta: {},
    status: 'running', started_at: 1700000000, finished_at: null, elapsed: 12.5, seq: 40, error: null, result: null,
    last_progress: { type: 'progress', message: '节点 2', progress: 50, status: 'processing', seq: 38 },
    live: {
      progress: { type: 'progress', message: '节点 2', progress: 50, status: 'processing', seq: 38 },
      thinking: { type: 'thinking', beat_index: 2, bridge_numbers: [3, 4], reasoning_chars: 300, content_chars: 0, elapsed: 4, seq: 40 },
    },
  };

  it('应用 last_progress 与 live 快照，lastSeq 归零以便从头回放完整日志', () => {
    const s = fromSnapshot(snapshot);
    expect(s.id).toBe('j2');
    expect(s.projectId).toBe('p1');
    expect(s.startedAt).toBe(1700000000 * 1000);
    expect(s.progress).toEqual({ message: '节点 2', pct: 50 });
    expect(s.llm?.reasoning_chars).toBe(300);
    expect(s.lastSeq).toBe(0);
    expect(s.connection).toBe('connecting');
  });

  it('快照的 meta 进入状态；createJobState 默认空对象', () => {
    expect(fromSnapshot({ ...snapshot, meta: { chapter_id: 'c1' } }).meta).toEqual({ chapter_id: 'c1' });
    expect(createJobState({ id: 'x', kind: 'k', title: 't' }).meta).toEqual({});
    expect(createJobState({ id: 'x', kind: 'k', title: 't', meta: { a: 1 } }).meta).toEqual({ a: 1 });
  });

  it('终态快照带出 error / result / finishedAt', () => {
    const s = fromSnapshot({ ...snapshot, status: 'error', error: '模型超时', finished_at: 1700000100, live: {}, last_progress: null });
    expect(s.status).toBe('error');
    expect(s.error).toBe('模型超时');
    expect(s.finishedAt).toBe(1700000100 * 1000);
    expect(isTerminal(s)).toBe(true);
  });
});
