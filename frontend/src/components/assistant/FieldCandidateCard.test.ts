import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { AssistantFieldCandidate } from '@/types/assistant';
import { FieldCandidateCard } from './FieldCandidateCard';

const candidate: AssistantFieldCandidate = {
  id: 'f1', field_id: 'project.theme', target_id: 'p', entity: 'project', label: '作品设定·主题', page: 'world-setting',
  before: '旧主题', after: '歪理也能成道', reason: '', status: 'candidate', run_id: 'r', created_at: null, decided_at: null,
};

describe('FieldCandidateCard', () => {
  it('卡片上可以应用或不用', () => {
    const html = renderToStaticMarkup(h(FieldCandidateCard, { projectId: 'p', candidate, onChange: () => {}, onOpenPage: () => {} }));
    expect(html).toContain('应用');
    expect(html).toContain('不用这份');
  });

  it('选项字段按页面写法对比（后端给的 before_text / after_text），不显示英文代码', () => {
    const choice: AssistantFieldCandidate = {
      ...candidate, field_id: 'relationship.status', entity: 'relationship', label: '关系「陈默 → 苏雪」·状态',
      before: 'active', after: 'broken', before_text: '进行中', after_text: '已破裂',
    };
    const html = renderToStaticMarkup(h(FieldCandidateCard, { projectId: 'p', candidate: choice, onChange: () => {} }));
    expect(html).toContain('进行中');
    expect(html).toContain('已破裂');
    expect(html).not.toContain('broken');
  });

  it('在待确认栏里展开看明细：只留前后对比和去页面查看，应用 / 不用在那一行上', () => {
    const html = renderToStaticMarkup(h(FieldCandidateCard, {
      projectId: 'p', candidate, onChange: () => {}, onOpenPage: () => {}, showActions: false,
    }));
    expect(html).toContain('歪理也能成道');
    expect(html).toContain('去页面查看');
    expect(html).not.toContain('不用这份');
    expect(html).not.toMatch(/>\s*(<svg[^]*?<\/svg>)?\s*应用\s*</);
  });
});
