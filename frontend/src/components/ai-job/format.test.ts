import { describe, expect, it } from 'vitest';
import { formatElapsed, llmSummary } from './format';

describe('formatElapsed', () => {
  it('一分钟内只显示秒，超过一分钟显示 m + 两位秒', () => {
    expect(formatElapsed(0)).toBe('0s');
    expect(formatElapsed(59)).toBe('59s');
    expect(formatElapsed(65)).toBe('1m05s');
    expect(formatElapsed(3600)).toBe('60m00s');
  });
});

describe('llmSummary', () => {
  const base = { model: 'deepseek-v3', reasoning_chars: 1234, content_chars: 0, elapsed: 3, finish_reason: null } as const;
  it('按阶段给出可读文案', () => {
    expect(llmSummary({ ...base, phase: 'start' })).toBe('模型 deepseek-v3 · 等待模型响应…');
    expect(llmSummary({ ...base, phase: 'thinking' })).toBe('模型 deepseek-v3 · 思考中… 已思考 1,234 字');
    expect(llmSummary({ ...base, phase: 'streaming', content_chars: 2500 })).toBe('模型 deepseek-v3 · 已写出 2,500 字（思考 1,234 字）');
    expect(llmSummary({ ...base, phase: 'done', content_chars: 3000, finish_reason: 'length' })).toBe('模型 deepseek-v3 · 本轮输出 3,000 字 · 已达 Max Tokens 上限被截断');
    expect(llmSummary({ ...base, phase: 'error' })).toBe('模型 deepseek-v3 · 模型调用失败');
  });
  it('没有模型名（场景级 thinking）时不带前缀', () => {
    expect(llmSummary({ ...base, model: '', reasoning_chars: 0, phase: 'streaming', content_chars: 12 })).toBe('已写出 12 字');
  });
});
