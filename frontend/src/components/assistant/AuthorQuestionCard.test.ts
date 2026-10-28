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

  it('系统提问卡：顶上写明选定直接写入，输入框提示可以自己写', () => {
    const card: AssistantQuestionCard = {
      note: '选定后直接写进作品设定（改动里可以撤销）',
      questions: [{ id: 'description', prompt: '选一个简介：', mode: 'single', write: { field_id: 'project.description' },
        options: [{ id: 'o1', label: '杂役靠歪理成道' }, { id: 'o2', label: '少年拆穿正统骗局' }] }],
    };
    const html = renderToStaticMarkup(h(AuthorQuestionCard, { question: card, busy: false, onSubmit: () => {} }));
    expect(html).toContain('选定后直接写进作品设定');
    expect(html).toContain('都不满意就写你想要的');
  });
});
