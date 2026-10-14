/** 页面向全局智能助笔登记「作者正在看什么」（章节 / 人物 / 地点 / 选中的正文），离开页面时清掉。 */
import { useEffect } from 'react';
import { ASSISTANT_DATA_EVENT, useAssistantStore, type AssistantDataChange, type AssistantDetail } from '@/store/assistantStore';

export function useAssistantDetail(detail: AssistantDetail | null): void {
  const setDetail = useAssistantStore((s) => s.setDetail);
  const key = JSON.stringify(detail ?? {});
  useEffect(() => {
    setDetail(JSON.parse(key) as AssistantDetail);
  }, [key, setDetail]);
  useEffect(() => () => setDetail(null), [setDetail]);
}

/** 助笔应用了修改 / 产生了候选稿：页面按需刷新自己的数据 */
export function useAssistantDataChange(handler: (change: AssistantDataChange) => void): void {
  useEffect(() => {
    const listener = (event: Event) => handler((event as CustomEvent<AssistantDataChange>).detail);
    window.addEventListener(ASSISTANT_DATA_EVENT, listener);
    return () => window.removeEventListener(ASSISTANT_DATA_EVENT, listener);
  }, [handler]);
}
