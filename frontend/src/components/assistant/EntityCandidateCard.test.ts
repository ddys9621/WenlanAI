import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { AssistantEntityCandidate } from '@/types/assistant';
import { EntityCandidateCard } from './EntityCandidateCard';

const candidate = (patch: Partial<AssistantEntityCandidate>): AssistantEntityCandidate => ({
  id: 'e1', entity_type: 'setting_entry', label: '新建设定条目「歪理成道」', page: 'setting-entries',
  payload: { title: '歪理成道', category: 'law', summary: '一句话', content: '天下道理，歪的也能成道。' },
  fields: [{ key: 'category', label: '分类' }, { key: 'summary', label: '简述' }, { key: 'content', label: '详细设定' }],
  reason: '', status: 'candidate', entity_missing: false, run_id: 'r', created_entity_id: null, created_at: null, decided_at: null,
  ...patch,
});
const render = (c: AssistantEntityCandidate) =>
  renderToStaticMarkup(h(EntityCandidateCard, { projectId: 'p', candidate: c, onChange: () => {}, onOpenPage: () => {} }));

describe('EntityCandidateCard', () => {
  it('按后端给的字段逐行列（名称照页面），设定条目的详细设定也看得到', () => {
    const html = render(candidate({}));
    expect(html).toContain('详细设定');
    expect(html).toContain('天下道理，歪的也能成道。');
    expect(html).toContain('铁律'); // 分类显示成中文
    expect(html.indexOf('分类')).toBeLessThan(html.indexOf('详细设定'));
  });

  it('组织的字段用组织页的叫法', () => {
    const html = render(candidate({
      entity_type: 'organization', label: '新建组织「守墨人」', page: 'characters',
      payload: { name: '守墨人', personality: '隐忍', motto: '墨不尽' },
      fields: [{ key: 'motto', label: '座右铭' }, { key: 'personality', label: '组织特性' }],
    }));
    expect(html).toContain('组织特性');
    expect(html).toContain('座右铭');
    expect(html).not.toContain('性格');
  });

  it('关系卡：标题写「甲 → 乙」，状态等选项按后端给的中文显示', () => {
    const html = render(candidate({
      entity_type: 'relationship', label: '新建关系「陈默 → 苏雪」', page: 'relationships', title: '陈默 → 苏雪',
      payload: { from_name: '陈默', to_name: '苏雪', relationship_name: '师徒', status: 'active' },
      fields: [{ key: 'relationship_name', label: '关系', text: '师徒' }, { key: 'status', label: '状态', text: '进行中' }],
    }));
    expect(html).toContain('陈默 → 苏雪');
    expect(html).toContain('新建关系');
    expect(html).toContain('进行中');
    expect(html).not.toContain('>active<');
  });

  it('待确认：可以建档或不建', () => {
    const html = render(candidate({}));
    expect(html).toContain('建档');
    expect(html).toContain('不建');
  });

  it('建过档、书里却没有了：标出来，可以重新建档', () => {
    const html = render(candidate({ status: 'applied', created_entity_id: 'gone', entity_missing: true }));
    expect(html).toContain('已不在书里');
    expect(html).toContain('重新建档');
    expect(html).not.toContain('已建档');
  });

  it('已建档且还在：只给去页面查看', () => {
    const html = render(candidate({ status: 'applied', created_entity_id: 'x' }));
    expect(html).toContain('已建档');
    expect(html).toContain('去页面查看');
    expect(html).not.toContain('重新建档');
  });

  it('在待确认栏里展开看明细：那一行已经有建档 / 不建，卡片里不再重复一套按钮', () => {
    const html = renderToStaticMarkup(h(EntityCandidateCard, {
      projectId: 'p', candidate: candidate({}), onChange: () => {}, onOpenPage: () => {}, showActions: false,
    }));
    expect(html).toContain('详细设定');
    expect(html).not.toContain('<button');
  });
});
