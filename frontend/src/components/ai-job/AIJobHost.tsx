/** 挂在 App 根部：通用任务弹窗 + 进入页面 / 切换项目时向后端同步正在运行的任务（刷新重连） */
import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useAIJobsStore } from '@/store/aiJobsStore';
import { AIJobModal } from './AIJobModal';

export function AIJobHost() {
  const { pathname } = useLocation();
  const syncFromServer = useAIJobsStore((s) => s.syncFromServer);
  const projectId = pathname.match(/^\/project\/([^/]+)/)?.[1] ?? null;
  const onLoginPage = pathname === '/login';

  useEffect(() => {
    if (onLoginPage) return;
    void syncFromServer();
  }, [syncFromServer, projectId, onLoginPage]);

  return <AIJobModal />;
}
