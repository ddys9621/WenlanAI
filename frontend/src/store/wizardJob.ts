/**
 * 向导一步（世界观 / 角色 / 总纲 / 卷纲）= 一个通用后台任务：灵感模式与快速开始向导共用。
 *
 * 后端四步早已跑在 ai_jobs 上（切页 / 断线不中断），这里让前端也经全局任务 store 订阅：
 * - 断线按 lastSeq 续上事件流，而不是把还在后台跑的一步判成失败（重跑时还会撞上 409 / 写出重复数据）
 * - 拿到后端 job id，「停止」才能真正取消后端任务
 * - store 重连次数用尽（connection=lost）时按失败返回，流程不会一直挂在「生成中」
 */
import { AIJobError, useAIJobsStore, waitForAIJob } from '@/store/aiJobsStore';
import type { AIJobState } from '@/types/ai_job';
import { isTerminal } from '@/utils/aiJobReducer';
import type { SSEClientOptions } from '@/utils/sseClient';

export type WizardJobKind = 'wizard_world_building' | 'wizard_characters' | 'wizard_outline' | 'wizard_volumes';

export const WIZARD_CONNECTION_LOST = '与后端的连接已断开，这一步可能仍在后台运行；稍后可从这一步继续';

interface RunWizardJobParams<T> {
  kind: WizardJobKind;
  title: string;
  projectId?: string | null;
  /** 发起请求：把 options 透传给 wizardStreamApi 的对应方法 */
  connect: (options: SSEClientOptions<T>) => Promise<unknown>;
  /** 后端 progress 事件（0-100，本步内的进度） */
  onProgress?: (message: string, progress: number) => void;
  /** 拿到后端 job id（停止按钮用它取消后端任务） */
  onStarted?: (jobId: string) => void;
}

/** 后端任务被停止（取消）结束，而不是失败 */
export const isJobCancelled = (error: unknown): boolean =>
  error instanceof AIJobError && error.job.status === 'cancelled';

function waitForJobOrConnectionLost(jobId: string): Promise<AIJobState> {
  return new Promise((resolve, reject) => {
    const lost = (job?: AIJobState) => Boolean(job && !isTerminal(job) && job.connection === 'lost');
    const unsubscribe = useAIJobsStore.subscribe((state) => {
      if (!lost(state.jobs[jobId])) return;
      unsubscribe();
      reject(new Error(WIZARD_CONNECTION_LOST));
    });
    if (lost(useAIJobsStore.getState().jobs[jobId])) {
      unsubscribe();
      reject(new Error(WIZARD_CONNECTION_LOST));
      return;
    }
    waitForAIJob(jobId).then(resolve, reject).finally(unsubscribe);
  });
}

/** 发起一步并等到终态：done → result；失败 / 停止 → reject（AIJobError 带终态 job）；发起即被拒 → reject 后端 detail */
export async function runWizardJob<T>({ kind, title, projectId, connect, onProgress, onStarted }: RunWizardJobParams<T>): Promise<T> {
  const jobId = await useAIJobsStore.getState().start<T>({
    kind,
    title,
    projectId: projectId ?? null,
    openModal: false,
    connect,
    onEvent: (message) => {
      if (message.type !== 'progress' || typeof message.progress !== 'number') return;
      onProgress?.(typeof message.message === 'string' ? message.message : '', message.progress);
    },
  });
  onStarted?.(jobId);
  const job = await waitForJobOrConnectionLost(jobId);
  return job.result as T;
}
