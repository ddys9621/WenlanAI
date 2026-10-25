import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { AssistantPlan } from '@/types/assistant';
import { PlanCard } from './CocreationParts';

const plan: AssistantPlan = {
  kind: 'volumes', title: '分卷草案：2 卷', volumes: [
    { id: 'v1', volume_number: 1, title: '藏书楼', chapter_start: 1, chapter_end: 60, summary: '', unit_count: 0 },
    { id: 'v2', volume_number: 2, title: '问道台', chapter_start: 61, chapter_end: 120, summary: '', unit_count: 0 },
  ],
};
const render = (p: AssistantPlan, extra: { showActions?: boolean } = {}) =>
  renderToStaticMarkup(h(PlanCard, { plan: p, onNavigate: () => {}, ...extra }));

describe('PlanCard', () => {
  it('草案：可以采用并确认', () => {
    const html = render(plan);
    expect(html).toContain('草案');
    expect(html).toContain('采用并确认');
  });

  it('卷纲已被重新分卷替换（或删了）：标「已失效」，不给确认，指去谋篇页看现在的版本', () => {
    const html = render({ ...plan, gone: true });
    expect(html).toContain('已失效');
    expect(html).not.toContain('采用并确认');
    expect(html).toContain('谋篇页');
  });

  it('在待确认栏里展开时只给看：确认在那一行上', () => {
    expect(render(plan, { showActions: false })).not.toContain('采用并确认');
  });
});
