/**
 * 助笔向作者提问（参考岚笺 AuthorQuestionCard）：单选 / 多选 / 填写；推荐项只是建议，提交后助笔才继续。
 * 每个选项是一行可点的框：单选是圆点，多选是方框，选中的那行描墨绿边。
 */
import { useMemo, useState } from 'react';
import { Check, HelpCircle, Loader2, Send } from 'lucide-react';
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
    <section className="as-card border-brand/30 animate-slide-up">
      <header className="flex items-start gap-2.5 px-4 pb-1 pt-3.5">
        <HelpCircle className="mt-0.5 h-4 w-4 flex-none text-brand" />
        <div className="min-w-0">
          <p className="text-[14px] font-semibold text-content">需要你决定</p>
          <p className="as-meta">推荐项只是建议；提交后团队才会继续</p>
        </div>
      </header>
      <div className="space-y-5 px-4 pb-4 pt-3">
        {question.questions.map((q, index) => {
          const a = answers[q.id];
          const single = q.mode === 'single';
          return (
            <div key={q.id}>
              <div className={cn(a.skipped && 'opacity-45')}>
                <p className="mb-2 text-[14px] font-medium leading-[1.6] text-content">
                  {question.questions.length > 1 && <span className="mr-1 text-content-tertiary">{index + 1}.</span>}
                  {q.prompt}
                </p>
                {q.mode !== 'text' && (
                  <div className="space-y-1.5">
                    {q.options.map((o) => {
                      const checked = a.choices.includes(o.id);
                      return (
                        // relative：隐藏的 input（sr-only = 绝对定位）要以本行定位。不然它按页面最外层定位、停在视野外，
                        // 点选项时浏览器把获得焦点的它滚进视野，会把 overflow-hidden 的整页滚走，看上去就是白屏
                        <label
                          key={o.id}
                          className={cn(
                            'relative flex cursor-pointer items-start gap-2.5 rounded-[10px] border px-3 py-2.5 focus-within:ring-2 focus-within:ring-brand/20',
                            checked ? 'border-brand bg-brand-50' : 'border-surface-border-light hover:border-surface-border hover:bg-surface-paper',
                          )}
                        >
                          <input
                            type={single ? 'radio' : 'checkbox'}
                            name={`q-${q.id}`}
                            checked={checked}
                            onChange={() => toggleChoice(q.id, o.id, single)}
                            className="sr-only"
                          />
                          <span className={cn(
                            'mt-[3px] flex h-4 w-4 flex-none items-center justify-center border',
                            single ? 'rounded-full' : 'rounded-[4px]',
                            checked ? 'border-brand bg-brand text-white' : 'border-surface-border bg-white',
                          )}>
                            {checked && (single ? <span className="h-1.5 w-1.5 rounded-full bg-white" /> : <Check className="h-3 w-3" strokeWidth={3} />)}
                          </span>
                          <span className="min-w-0 flex-1 text-[13px] leading-[1.6]">
                            <span className="text-content">{o.label}</span>
                            {o.recommended && <span className="ml-1.5 rounded-[4px] bg-brand-100 px-1.5 py-px text-[11px] text-brand-600">推荐</span>}
                            {o.description && <span className="block text-[12px] text-content-tertiary">{o.description}</span>}
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
                  className="as-field mt-2 resize-none py-2 text-[13px] leading-5"
                />
              </div>
              <button
                type="button"
                onClick={() => update(q.id, { skipped: !a.skipped, choices: [], text: '' })}
                className="mt-1.5 text-[12px] text-content-tertiary hover:text-content-secondary"
              >
                {a.skipped ? '已跳过，点这里撤销' : '这题先跳过'}
              </button>
            </div>
          );
        })}
      </div>
      <footer className="as-card-foot">
        <button
          onClick={() => onSubmit(question.questions.map((q) => answers[q.id]))}
          disabled={!ready || busy}
          className="as-btn-primary"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}提交回答
        </button>
      </footer>
    </section>
  );
}
