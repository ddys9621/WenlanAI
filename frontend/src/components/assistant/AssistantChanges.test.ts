import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { AssistantEntityCandidate, AssistantPlan } from '@/types/assistant';
import { changeItems, type ChangeItem } from '@/utils/cocreation';
import { ChangeList, PendingTray } from './AssistantChanges';

const entity = (id: string, status: AssistantEntityCandidate['status'], title: string): AssistantEntityCandidate => ({
  id, entity_type: 'setting_entry', label: `新建设定条目「${title}」`, page: 'setting-entries', payload: { title, summary: '很长的设定' },
  reason: '', status, run_id: 'r', created_entity_id: null, created_at: null, decided_at: null,
});
const plan: AssistantPlan = {
  kind: 'volumes', title: '分卷草案：2 卷', volumes: [
    { id: 'v1', volume_number: 1, title: '藏书楼', chapter_start: 1, chapter_end: 60, summary: '', unit_count: 0 },
  ],
};

const lookups = {
  fields: new Map(),
  entities: new Map([['e1', entity('e1', 'candidate', '歪理成道')], ['e2', entity('e2', 'applied', '玄天界与五域')]]),
  confirmedPlans: new Set<string>(),
};
const items = changeItems({ candidates: [], entity_candidates: ['e1', 'e2'], chapter_candidates: [], plans: [plan] }, lookups);
/** 明细：看得出调用方要不要卡片自带的按钮 */
const detail = (_item: ChangeItem, opts: { showActions: boolean }) =>
  createElement('section', { className: 'full-card' }, opts.showActions ? '卡片自带按钮' : '卡片只给看');

describe('ChangeList（回复里的改动）', () => {
  it('默认收起成一行摘要，不把整张卡片铺在对话里', () => {
    const html = renderToStaticMarkup(createElement(ChangeList, { items, renderDetail: detail }));
    expect(html).toContain('改动 3 项 · 待确认 2 · 已采用 1');
    expect(html).toMatch(/<details class="as-disclosure">/); // 没有 open
    expect(html).not.toContain('full-card');
    expect(html).toContain('歪理成道');
  });

  it('没有改动就什么都不画', () => {
    expect(renderToStaticMarkup(createElement(ChangeList, { items: [], renderDetail: detail }))).toBe('');
  });
});

describe('PendingTray（输入框上方的待确认栏）', () => {
  const pending = items.filter((i) => i.state === 'pending');
  const props = {
    items: pending, onOpenChange: () => {}, detailKey: null, onDetailChange: () => {}, renderDetail: detail, onDecide: async () => true,
  };
  const row = (html: string, title: string) => html.split('<li').find((li) => li.includes(title)) ?? '';

  it('收起时一行：几项待确认、分别是什么，带「全部采用」', () => {
    const html = renderToStaticMarkup(createElement(PendingTray, { ...props, open: false }));
    expect(html).toContain('2 项待你确认');
    expect(html).toContain('新建设定条目 1 · 分卷草案 1');
    expect(html).toContain('全部采用');
    expect(html).not.toContain('歪理成道'); // 收起时不列明细
  });

  it('展开后每项一行，带单条的建档 / 不建', () => {
    const html = renderToStaticMarkup(createElement(PendingTray, { ...props, open: true }));
    expect(html).toContain('歪理成道');
    expect(html).toContain('不建');
    expect(html).toContain('建档');
    expect(html).toContain('全部放弃');
  });

  it('点开一行看明细：明细卡片只给看，建档 / 不建只在那一行上（两套按钮会被同时点到）', () => {
    const html = renderToStaticMarkup(createElement(PendingTray, { ...props, open: true, detailKey: pending[0].key }));
    expect(html).toContain('卡片只给看');
    expect(html).not.toContain('卡片自带按钮');
  });

  it('草案没有「不用」，也空出同样的位置，各行的箭头对得齐', () => {
    const html = renderToStaticMarkup(createElement(PendingTray, { ...props, open: true }));
    expect(row(html, '分卷草案：2 卷')).toMatch(/<span aria-hidden="true" class="[^"]*\binvisible\b/);
    expect(row(html, '歪理成道')).not.toMatch(/\binvisible\b/);
  });

  it('没有待确认的就不出现', () => {
    expect(renderToStaticMarkup(createElement(PendingTray, { ...props, items: [], open: true }))).toBe('');
  });
});
