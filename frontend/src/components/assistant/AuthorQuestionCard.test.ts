import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { AssistantQuestionCard } from '@/types/assistant';
import { AuthorQuestionCard } from './AuthorQuestionCard';

const question: AssistantQuestionCard = {
  questions: [
    {
      id: 'q1', prompt: '先出总纲还是先补人物？', mode: 'single',
      options: [{ id: 'a', label: '先出总纲', recommended: true }, { id: 'b', label: '先补人物' }],
    },
    { id: 'q2', prompt: '基调要哪几种？', mode: 'multiple', options: [{ id: 'a', label: '悬疑' }, { id: 'b', label: '热血' }] },
  ],
};

/** 每个 label 的 class，以及它里面有没有视觉隐藏（sr-only）的单选 / 多选框 */
function labels(html: string) {
  return [...html.matchAll(/<label class="([^"]*)">([\s\S]*?)<\/label>/g)].map(([, cls, inner]) => ({
    cls: cls.split(/\s+/),
    hiddenInput: /<input[^>]*class="sr-only"/.test(inner),
  }));
}

describe('AuthorQuestionCard', () => {
  it('隐藏的单选 / 多选框定位在自己的选项行里：否则它按页面最外层定位，点选项时浏览器把它滚进视野，整个页面被滚成空白', () => {
    const options = labels(renderToStaticMarkup(h(AuthorQuestionCard, { question, busy: false, onSubmit: () => {} })))
      .filter((l) => l.hiddenInput);
    expect(options).toHaveLength(4);
    for (const option of options) expect(option.cls).toContain('relative');
  });
});
