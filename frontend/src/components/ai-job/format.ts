import type { AIJobLLM } from '@/types/ai_job';

export function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m${s.toString().padStart(2, '0')}s`;
}

const n = (v: number) => v.toLocaleString();

export function llmSummary(llm: AIJobLLM): string {
  const prefix = llm.model ? `模型 ${llm.model} · ` : '';
  switch (llm.phase) {
    case 'start':
      return `${prefix}等待模型响应…`;
    case 'thinking':
      return `${prefix}思考中… 已思考 ${n(llm.reasoning_chars)} 字`;
    case 'streaming':
      return `${prefix}已写出 ${n(llm.content_chars)} 字${llm.reasoning_chars ? `（思考 ${n(llm.reasoning_chars)} 字）` : ''}`;
    case 'done':
      return `${prefix}本轮输出 ${n(llm.content_chars)} 字${llm.finish_reason === 'length' ? ' · 已达 Max Tokens 上限被截断' : ''}`;
    case 'error':
      return `${prefix}模型调用失败`;
  }
}
