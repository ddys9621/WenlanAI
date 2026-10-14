/** 助笔向作者提问（参考岚笺 AuthorQuestionCard）：单选 / 多选 / 填写；推荐项只是建议，提交后助笔才继续。 */
import { useMemo, useState } from 'react';
import { Loader2, MessageCircleQuestion, Send } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { AssistantAnswer, AssistantQuestionCard } from '@/types/assistant';

interface AuthorQuestionCardProps {
  question: AssistantQuestionCard;
  busy: boolean;
  onSubmit: (answers: AssistantAnswer[]) => void;
}

export function AuthorQuestionCard({ question, busy, onSubmit }: AuthorQuestionCardProps) {
  const [answers, setAnswers] = useState<Record<string, AssistantAnswer>>(() => Object.fromEntries(
    question.questions.map((q) => [q.id, { id: q.id, choices: [], text: '', skipped: false }]),
  ));

  const update = (id: string, patch: Partial<AssistantAnswer>) =>
    setAnswers((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));

  const toggleChoice = (id: string, optionId: string, single: boolean) => {
    const current = answers[id].choices;
    const next = single ? [optionId] : current.includes(optionId) ? current.filter((c) => c !== optionId) : [...current, optionId];
    update(id, { choices: next, skipped: false });
  };

  const ready = useMemo(
    () => question.questions.every((q) => {
      const a = answers[q.id];
      return a.skipped || a.choices.length > 0 || a.text.trim().length > 0;
    }),
    [answers, question.questions],
  );

  return (
    <section className="rounded border border-gold-300/60 bg-gold-50/60 px-3 py-3">
      <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-content">
        <MessageCircleQuestion className="h-3.5 w-3.5 text-gold-500" />
        需要你决定
      </p>
      <div className="space-y-3">
        {question.questions.map((q) => {
          const a = answers[q.id];
          return (
            <div key={q.id} className="rounded border border-surface-border-light bg-white px-3 py-2">
              <p className="text-sm leading-6 text-content">{q.prompt}</p>
              {q.mode !== 'text' && (
                <div className="mt-1.5 space-y-1">
                  {q.options.map((o) => {
                    const checked = a.choices.includes(o.id);
                    return (
                      <label key={o.id} className={cn('flex cursor-pointer items-start gap-2 rounded px-2 py-1 text-xs', checked ? 'lj-selected' : 'hover:bg-surface-hover')}>
                        <input
                          type={q.mode === 'single' ? 'radio' : 'checkbox'}
                          name={`q-${q.id}`}
                          checked={checked}
                          onChange={() => toggleChoice(q.id, o.id, q.mode === 'single')}
                          className="mt-0.5"
                        />
                        <span>
                          <span className="font-medium text-content">{o.label}</span>
                          {o.recommended && <span className="lj-badge lj-badge--ok ml-1.5">推荐</span>}
                          {o.description && <span className="block text-[11px] text-content-tertiary">{o.description}</span>}
                        </span>
                      </label>
                    );
                  })}
                </div>
              )}
              <textarea
                value={a.text}
                onChange={(e) => update(q.id, { text: e.target.value, skipped: false })}
                rows={q.mode === 'text' ? 3 : 1}
                placeholder={q.mode === 'text' ? '写下你的回答' : '补充说明（可选）'}
                className="hh-textarea mt-1.5 text-xs"
              />
              <label className="mt-1 flex cursor-pointer items-center gap-1.5 text-[11px] text-content-tertiary">
                <input type="checkbox" checked={a.skipped} onChange={(e) => update(q.id, { skipped: e.target.checked, choices: [], text: '' })} />
                这题先跳过
              </label>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="text-[11px] text-content-tertiary">推荐项只是建议；提交后助笔才会继续。</span>
        <button
          onClick={() => onSubmit(question.questions.map((q) => answers[q.id]))}
          disabled={!ready || busy}
          className="hh-btn-primary hh-btn-sm h-8"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}提交回答
        </button>
      </div>
    </section>
  );
}
