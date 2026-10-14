/**
 * 全局智能助笔的界面状态：抽屉开关 / 界面（对话 · 核对 · 任务）/ 宽屏、作者所在页面的上下文、待填入输入框的要求。
 * 页面上下文只带给助笔参考（当前页面不是权限边界）：项目壳按路由登记页面，具体页面再补充正在看的章节 / 选中的正文等。
 */
import { create } from 'zustand';
import type { AssistantPageContext, AssistantSelectionCtx } from '@/types/assistant';

export type AssistantMode = 'agent' | 'checks' | 'tasks';

export interface AssistantDetail {
  label?: string;
  chapter_id?: string | null;
  character_id?: string | null;
  outline_id?: string | null;
  location_id?: string | null;
  selection?: AssistantSelectionCtx | null;
}

interface AssistantState {
  open: boolean;
  mode: AssistantMode;
  wide: boolean;
  route: { page: string; label: string };
  detail: AssistantDetail;
  composeRequest: { text: string; nonce: number } | null;
  setOpen: (open: boolean) => void;
  toggle: () => void;
  setMode: (mode: AssistantMode) => void;
  setWide: (wide: boolean) => void;
  setRoute: (page: string, label: string) => void;
  setDetail: (detail: AssistantDetail | null) => void;
  /** 打开助笔并把一段要求填进输入框（不自动发送） */
  compose: (text: string) => void;
}

const OPEN_KEY = 'assistant-open';
const WIDE_KEY = 'assistant-wide';
const readFlag = (key: string) => typeof localStorage !== 'undefined' && localStorage.getItem(key) === 'true';
const writeFlag = (key: string, value: boolean) => {
  if (typeof localStorage !== 'undefined') localStorage.setItem(key, String(value));
};

let nonce = 0;

export const useAssistantStore = create<AssistantState>((set, get) => ({
  open: readFlag(OPEN_KEY),
  mode: 'agent',
  wide: readFlag(WIDE_KEY),
  route: { page: '', label: '' },
  detail: {},
  composeRequest: null,
  setOpen: (open) => {
    writeFlag(OPEN_KEY, open);
    set({ open });
  },
  toggle: () => get().setOpen(!get().open),
  setMode: (mode) => set({ mode }),
  setWide: (wide) => {
    writeFlag(WIDE_KEY, wide);
    set({ wide });
  },
  setRoute: (page, label) => set({ route: { page, label }, detail: {} }),
  setDetail: (detail) => set({ detail: detail ?? {} }),
  compose: (text) => {
    writeFlag(OPEN_KEY, true);
    nonce += 1;
    set({ open: true, mode: 'agent', composeRequest: { text, nonce } });
  },
}));

export function pageContextOf(state: Pick<AssistantState, 'route' | 'detail'>): AssistantPageContext {
  const { route, detail } = state;
  return {
    page: route.page,
    label: detail.label || route.label,
    chapter_id: detail.chapter_id ?? null,
    character_id: detail.character_id ?? null,
    outline_id: detail.outline_id ?? null,
    location_id: detail.location_id ?? null,
    selection: detail.selection ?? null,
  };
}

/** 助笔应用修改 / 产生候选稿后通知各页面刷新 */
export const ASSISTANT_DATA_EVENT = 'mumu:assistant-data';

export interface AssistantDataChange {
  entity: string | null;
  targetId?: string | null;
  chapterId?: string | null;
}

export function emitAssistantData(change: AssistantDataChange): void {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent<AssistantDataChange>(ASSISTANT_DATA_EVENT, { detail: change }));
}
