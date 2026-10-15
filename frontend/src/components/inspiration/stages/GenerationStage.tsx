/** 灵感模式 - 创建中 / 创建完成：四个生成节点的时间线，一行一个节点，列对齐 */

import { ArrowRight, CheckCircle2, Clock, Loader2, RefreshCw, RotateCcw, XCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { GENERATION_TIPS, NODE_META, NODE_STATUS_LABEL } from '../copy';
import { formatBookTitle, formatDuration, getNodePreview } from '../flow';
import { Notice, RotatingTip, StageCard, StageFooter, StageHeader } from '../shared';
import type { GenStepStatus, WizardState } from '../types';
import type { GenerationArtifacts, GenerationNodeKey } from '../useProjectGeneration';

export function GenerationStage({
  state,
  bookTitle,
  artifacts,
  runningNode,
  canRegenerate,
  onRegenerate,
  onEnterProject,
  onRestart,
}: {
  state: WizardState;
  bookTitle?: string;
  artifacts: GenerationArtifacts;
  runningNode: GenerationNodeKey | null;
  canRegenerate: boolean;
  onRegenerate: (node: GenerationNodeKey) => void;
  onEnterProject: () => void;
  onRestart: () => void;
}) {
  const isComplete = state.currentStep === 'complete';
  const title = formatBookTitle(bookTitle || state.projectTitle);
  const progress = Math.round(Math.min(state.progress, 100));
  const { elapsedSec, stallLevel, lastUpdateAt } = state.generationMeta;
  // GEN_TICK 每秒触发重渲染，这里直接按当前时间算"多久没新进度"
  const sinceLastSec = lastUpdateAt ? Math.floor((Date.now() - lastUpdateAt) / 1000) : 0;

  return (
    <StageCard>
      {isComplete ? (
        <StageHeader
          eyebrow="创建完成"
          title={`${title}创建完成`}
          description="世界观、角色、总纲与卷纲均已生成。下一步进入卷纲：逐个剧情单元生成章纲，确认后就能开写；也可以在智能助笔里让主编带着团队推进。"
          action={<CheckCircle2 className="h-8 w-8 text-emerald-500" />}
        />
      ) : (
        <>
          <StageHeader
            eyebrow="创建中"
            stepLabel="第 7 步"
            title={`正在为${title}搭建内容资产`}
            description="四个环节依次生成，完成后自动进入下一步；中途请留在当前页面。"
            action={
              <div className="text-right">
                <div className="text-2xl font-semibold leading-7 tracking-tight text-content tabular-nums">{progress}%</div>
                <div className="mt-0.5 text-xs text-content-tertiary tabular-nums">已用 {formatDuration(elapsedSec)}</div>
              </div>
            }
          />
          <div className="hh-progress mt-4">
            <div className="hh-progress-bar" style={{ width: `${progress}%` }} />
          </div>
          <div className="mt-2 flex items-center gap-2 text-sm text-content-secondary" role="status" aria-live="polite">
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-brand" />
            <span key={state.progressMessage} className="min-w-0 animate-fade-in truncate" title={state.progressMessage}>
              {state.progressMessage || '正在准备'}
            </span>
            {stallLevel === 'slow' && (
              <span className="shrink-0 text-xs text-content-tertiary">这一步耗时较长，AI 仍在生成</span>
            )}
          </div>
          {stallLevel === 'stalled' && (
            <Notice tone="warning" className="mt-3">
              已 {formatDuration(sinceLastSec)} 没有新进度，可能是模型排队或这一步内容较多。可以继续等待；若始终无响应，稍后可从当前环节重跑。
            </Notice>
          )}
        </>
      )}

      <ol className="mt-5 divide-y divide-surface-border/70 border border-surface-border/80 bg-white/60">
        {NODE_META.map((node) => {
          const status = state.generationSteps[node.key];
          const running = status === 'processing';
          const preview = getNodePreview(node.key, artifacts);
          const detail = preview || node.hint;
          const showRegenerate = isComplete && canRegenerate && status === 'completed';

          return (
            <li
              key={node.key}
              className={cn(
                'grid grid-cols-[1.25rem_3.5rem_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3',
                running && 'bg-brand/[0.04]',
              )}
            >
              <NodeStatusIcon status={status} running={running} />
              <span className={cn('text-sm font-medium', status === 'pending' ? 'text-content-tertiary' : 'text-content')}>
                {node.label}
              </span>
              <span
                title={detail}
                className={cn('truncate text-sm leading-6', preview ? 'text-content-secondary' : 'text-content-tertiary')}
              >
                {detail}
              </span>
              {showRegenerate ? (
                <button
                  type="button"
                  onClick={() => onRegenerate(node.key)}
                  disabled={runningNode !== null}
                  className="hh-btn-ghost h-8 px-2.5 text-xs text-brand"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  重跑
                </button>
              ) : (
                <span
                  className={cn(
                    'text-xs tabular-nums',
                    status === 'completed'
                      ? 'text-emerald-600'
                      : status === 'error'
                        ? 'text-red-500'
                        : running
                          ? 'text-brand'
                          : 'text-content-tertiary',
                  )}
                >
                  {running ? NODE_STATUS_LABEL.processing : NODE_STATUS_LABEL[status]}
                </span>
              )}
            </li>
          );
        })}
      </ol>

      {isComplete ? (
        <StageFooter
          left="重跑某一环节会清理它之后的旧数据并按序重新生成；也可以进入项目后再逐项修改。"
          right={
            <>
              <button type="button" onClick={onRestart} className="hh-btn-ghost hh-btn-sm">
                <RotateCcw className="h-3.5 w-3.5" />
                再来一本
              </button>
              {state.projectId && (
                <button type="button" onClick={onEnterProject} className="hh-btn-primary">
                  进入卷纲规划
                  <ArrowRight className="h-4 w-4" />
                </button>
              )}
            </>
          }
        />
      ) : (
        <StageFooter left={<RotatingTip tips={GENERATION_TIPS} />} />
      )}
    </StageCard>
  );
}

function NodeStatusIcon({ status, running }: { status: GenStepStatus; running: boolean }) {
  if (running) return <Loader2 className="h-5 w-5 animate-spin text-brand" />;
  if (status === 'completed') return <CheckCircle2 className="h-5 w-5 text-emerald-500" />;
  if (status === 'error') return <XCircle className="h-5 w-5 text-red-500" />;
  return <Clock className="h-5 w-5 text-content-tertiary" />;
}
