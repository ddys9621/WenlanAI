import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, History, RotateCcw, SlidersHorizontal, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { MCPSelector } from '@/components/MCPSelector';
import { KbSourcePicker } from '@/components/knowledge/KbSourcePicker';
import type { KbSourceChoice } from '@/types/knowledge';
import { NO_KB_CHOICE } from '@/utils/knowledge';
import { useInspirationMachine } from '@/components/inspiration/useInspirationMachine';
import { type GenerationNodeKey, useProjectGeneration } from '@/components/inspiration/useProjectGeneration';
import {
  CHOICE_STEPS,
  CONFIRM_CREATE_OPTION,
  MANUAL_INPUT_OPTIONS,
  REGENERATE_OPTIONS,
  STEP_META,
  THINKING_PHASES,
} from '@/components/inspiration/copy';
import { FLOW_STEPS, getFlowStep, getInterruption, getLoadingApiStep, getStepChipStatus } from '@/components/inspiration/flow';
import { SummaryList, type SummaryItem } from '@/components/inspiration/shared';
import { IdeaStage } from '@/components/inspiration/stages/IdeaStage';
import { ChoiceStage } from '@/components/inspiration/stages/ChoiceStage';
import { ConfirmStage } from '@/components/inspiration/stages/ConfirmStage';
import { GenerationStage } from '@/components/inspiration/stages/GenerationStage';
import type { Message, Step, WizardData } from '@/components/inspiration/types';
import type { MCPSelectorValue } from '@/components/MCPSelector';

interface InspirationModalProps {
  open: boolean;
  onClose: () => void;
  /** T2.1：第二参带上 outline 完成时后端给的下一步路由建议 */
  onEnterProject: (
    projectId: string,
    options?: { nextRoute?: 'volume_planning' | 'chapter_outlines' },
  ) => void;
  onProjectCreated?: (projectId: string) => void | Promise<void>;
}

/** 状态机在错误消息末尾附带的引导语，界面上用按钮代替 */
const ERROR_SUFFIX = /\n*你可以选择[：:]?\s*$/;

export default function InspirationModal({
  open,
  onClose,
  onEnterProject,
  onProjectCreated,
}: InspirationModalProps) {
  const {
    state,
    dispatch,
    sendMessage,
    selectOption,
    confirmGenres,
    quickGenerate,
    regenerateOptions,
    retry,
    reset,
  } = useInspirationMachine();

  const [input, setInput] = useState('');
  const [manualOpen, setManualOpen] = useState(false);
  const [quickFilling, setQuickFilling] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [mcpSettings, setMcpSettings] = useState<MCPSelectorValue>({ enable: false, selected: [] });
  const [kbChoice, setKbChoice] = useState<KbSourceChoice>(NO_KB_CHOICE);
  const announcedProjectIdRef = useRef('');
  const dialogRef = useRef<HTMLElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  const { artifacts, runningNode, startGeneration, regenerateFrom, cancelGeneration, resetArtifacts } =
    useProjectGeneration({ dispatch, mcpSettings, kbChoice });

  const wizardData = state.wizardData as Partial<WizardData>;
  const flowStep = getFlowStep(state.currentStep);
  const activeStepIndex = FLOW_STEPS.indexOf(flowStep);
  const isIdeaStep = state.currentStep === 'idea';
  const isGenerating = state.currentStep === 'generating';
  const isComplete = state.currentStep === 'complete';
  const isConfirmStep = state.currentStep === 'confirm';
  const readyToGenerate = Boolean(
    wizardData.title &&
      wizardData.description &&
      wizardData.theme &&
      wizardData.genre?.length &&
      wizardData.narrative_perspective,
  );

  const originalBrief = useMemo(
    () => state.messages.find((message) => message.type === 'user')?.content,
    [state.messages],
  );

  const activeQuestion = useMemo(
    () =>
      [...state.messages]
        .reverse()
        .find((message) => message.type === 'ai' && message.options?.length && !message.disabled),
    [state.messages],
  );

  const historyMessages = useMemo(
    () => state.messages.filter((message) => message.id !== activeQuestion?.id),
    [activeQuestion?.id, state.messages],
  );

  const stageOptions = useMemo(
    () =>
      activeQuestion?.options?.filter(
        (option) => !MANUAL_INPUT_OPTIONS.has(option) && !REGENERATE_OPTIONS.has(option),
      ) ?? [],
    [activeQuestion?.options],
  );

  const isErrorQuestion = Boolean(activeQuestion?.options?.some((option) => REGENERATE_OPTIONS.has(option)));
  const errorMessage =
    isErrorQuestion && !state.loading ? activeQuestion?.content.replace(ERROR_SUFFIX, '').trim() : null;

  const summaryItems: SummaryItem[] = [
    { key: 'idea', label: '灵感', value: originalBrief },
    { key: 'title', label: '书名', value: wizardData.title },
    { key: 'description', label: '简介', value: wizardData.description },
    { key: 'theme', label: '主题', value: wizardData.theme },
    { key: 'genre', label: '类型', value: wizardData.genre?.join('、') },
    { key: 'perspective', label: '视角', value: wizardData.narrative_perspective },
  ];
  const missingFields = summaryItems.filter((item) => item.key !== 'idea' && !item.value?.trim()).map((item) => item.label);

  const loadingApiStep = getLoadingApiStep(state.currentStep);
  const loadingPhrases = quickFilling
    ? THINKING_PHASES.quick
    : THINKING_PHASES[loadingApiStep ?? 'title'];

  const canQuickGenerate =
    CHOICE_STEPS.has(flowStep) &&
    !state.loading &&
    Boolean(wizardData.title || wizardData.description || wizardData.theme || wizardData.genre?.length) &&
    !(state.currentStep === 'genre' && state.selectedOptions.length > 0);

  const advancedSummary = useMemo(() => {
    const mcp = !mcpSettings.enable
      ? '未启用 MCP'
      : mcpSettings.selected.length > 0
        ? `MCP ${mcpSettings.selected.length} 个插件`
        : 'MCP 已开启未选插件';
    const kb = kbChoice.sourceId ? '已选对标书' : '未选对标书';
    return `${kb} · ${mcp}`;
  }, [mcpSettings, kbChoice]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', handleEscape);
    // 弹窗常驻挂载、只切换可见性，所以聚焦要在打开时手动做，不能靠 autoFocus
    const focusTimer = window.setTimeout(() => {
      dialogRef.current?.querySelector<HTMLElement>('textarea')?.focus();
    }, 220);
    return () => {
      window.clearTimeout(focusTimer);
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleEscape);
    };
  }, [onClose, open]);

  useEffect(() => () => cancelGeneration(), [cancelGeneration]);

  // 创建期间每秒打点：驱动"已用时间"与卡顿提示
  useEffect(() => {
    if (!isGenerating) return;
    const timer = window.setInterval(() => dispatch({ type: 'GEN_TICK' }), 1000);
    return () => window.clearInterval(timer);
  }, [dispatch, isGenerating]);

  useEffect(() => {
    if (isIdeaStep) resetArtifacts();
  }, [isIdeaStep, resetArtifacts]);

  useEffect(() => {
    setManualOpen(false);
    setInput('');
  }, [state.currentStep]);

  // 换阶段时回到顶部，让用户先看到新阶段的标题与说明
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  }, [flowStep]);

  useEffect(() => {
    if (state.currentStep !== 'generating' || runningNode || state.progress > 0 || !readyToGenerate) return;
    void startGeneration(wizardData as WizardData);
  }, [readyToGenerate, runningNode, startGeneration, state.currentStep, state.progress, wizardData]);

  useEffect(() => {
    if (!state.projectId || announcedProjectIdRef.current === state.projectId) return;
    announcedProjectIdRef.current = state.projectId;
    void onProjectCreated?.(state.projectId);
  }, [onProjectCreated, state.projectId]);

  const handleSend = async () => {
    const value = input.trim();
    if (!value || state.loading) return;
    setQuickFilling(false);
    setInput('');
    setManualOpen(false);
    await sendMessage(value);
  };

  const handleOptionSelect = async (option: string) => {
    setQuickFilling(false);
    setManualOpen(false);
    await selectOption(option);
  };

  const handleRegenerateOptions = (hint?: string) => {
    setQuickFilling(false);
    setManualOpen(false);
    void regenerateOptions(hint);
  };

  const handleQuickGenerate = () => {
    setQuickFilling(true);
    setManualOpen(false);
    void quickGenerate();
  };

  const handleRetry = () => {
    if (state.retryContext) void retry();
    else if (quickFilling) void quickGenerate();
    else void regenerateOptions();
  };

  const handleRegenerateNode = async (node: GenerationNodeKey) => {
    if (!state.projectId || !readyToGenerate || runningNode) return;
    if (
      node !== 'outline' &&
      node !== 'volumes' &&
      !window.confirm('会清理该环节之后的旧角色、大纲和章节，再从这里向后重跑。继续吗？')
    ) {
      return;
    }
    await regenerateFrom(node, wizardData as WizardData, state.projectId);
  };

  const handleReset = () => {
    const hasStartedWorkflow = Boolean(state.projectId || state.progress > 0 || historyMessages.length > 1);
    if (hasStartedWorkflow && !window.confirm('这会清空当前创作流程，并忽略正在返回的旧生成结果。继续吗？')) {
      return;
    }
    announcedProjectIdRef.current = '';
    cancelGeneration();
    setInput('');
    setManualOpen(false);
    setQuickFilling(false);
    setHistoryOpen(false);
    setAdvancedOpen(false);
    setKbChoice(NO_KB_CHOICE);
    resetArtifacts();
    reset();
  };

  const renderStage = () => {
    if (isGenerating || isComplete) {
      return (
        <GenerationStage
          state={state}
          bookTitle={wizardData.title}
          artifacts={artifacts}
          runningNode={runningNode}
          canRegenerate={Boolean(state.projectId && readyToGenerate)}
          onRegenerate={(node) => void handleRegenerateNode(node)}
          onEnterProject={() => state.projectId && onEnterProject(state.projectId, { nextRoute: 'volume_planning' })}
          onRestart={handleReset}
        />
      );
    }
    if (isConfirmStep) {
      // 项目已建成但某环节失败：从失败环节继续，而不是再创建一个重复项目
      const { message: failedMessage, resumeNode } = getInterruption(state);
      const resume =
        resumeNode && readyToGenerate
          ? {
              node: resumeNode,
              steps: state.generationSteps,
              onResume: () => void regenerateFrom(resumeNode, wizardData as WizardData, state.projectId),
            }
          : undefined;
      return (
        <ConfirmStage
          bookTitle={wizardData.title}
          errorMessage={failedMessage}
          missingFields={missingFields}
          resume={resume}
          onConfirm={() => void selectOption(CONFIRM_CREATE_OPTION)}
          onRestart={handleReset}
        />
      );
    }
    if (isIdeaStep) {
      return <IdeaStage value={input} loading={state.loading} onChange={setInput} onSubmit={() => void handleSend()} />;
    }
    return (
      <ChoiceStage
        flowStep={flowStep}
        stepIndex={activeStepIndex}
        loading={state.loading}
        loadingPhrases={loadingPhrases}
        prompt={activeQuestion?.content}
        options={stageOptions}
        isMultiSelect={Boolean(activeQuestion?.isMultiSelect)}
        selectedOptions={state.selectedOptions}
        errorMessage={errorMessage}
        manualOpen={manualOpen}
        input={input}
        canQuickGenerate={canQuickGenerate}
        onInputChange={setInput}
        onOptionSelect={(option) => void handleOptionSelect(option)}
        onOpenManual={() => setManualOpen(true)}
        onCloseManual={() => setManualOpen(false)}
        onConfirmGenres={confirmGenres}
        onQuickGenerate={handleQuickGenerate}
        onRegenerate={handleRegenerateOptions}
        onRetry={handleRetry}
        onSend={() => void handleSend()}
      />
    );
  };

  return createPortal(
    <div className={cn('fixed inset-0 z-50', open ? 'pointer-events-auto' : 'pointer-events-none')} aria-hidden={!open}>
      <div
        className={cn(
          'absolute inset-0 bg-[rgba(11,26,51,0.32)] backdrop-blur-[6px] transition-opacity duration-200',
          open ? 'opacity-100' : 'opacity-0',
        )}
        onClick={onClose}
      />

      <div className="absolute inset-0 flex items-center justify-center px-4 py-6">
        <section
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="inspiration-modal-title"
          className={cn(
            'hh-glass flex w-full max-w-[760px] flex-col overflow-hidden transition-all duration-200',
            open ? 'translate-y-0 scale-100 opacity-100' : 'translate-y-3 scale-[0.98] opacity-0',
          )}
          style={{ maxHeight: 'calc(100dvh - 3rem)' }}
        >
          <header className="shrink-0 border-b border-surface-border/80 px-7 pb-5 pt-6">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="hh-eyebrow">灵感模式</p>
                <h2 id="inspiration-modal-title" className="mt-1.5 text-xl font-semibold tracking-tight text-content">
                  从一句灵感开始
                </h2>
              </div>
              <div className="-mr-2 -mt-1 flex shrink-0 items-center gap-1">
                {!isIdeaStep && (
                  <button type="button" onClick={handleReset} className="hh-btn-ghost hh-btn-sm">
                    <RotateCcw className="h-4 w-4" />
                    重新开始
                  </button>
                )}
                <button type="button" onClick={onClose} className="hh-icon-btn-plain" aria-label="关闭灵感模式">
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            <Stepper activeIndex={activeStepIndex} currentStep={state.currentStep} />
          </header>

          <div ref={bodyRef} className="hh-modal-body space-y-3">
            {!isIdeaStep && <SummaryList items={summaryItems} defaultOpen={!isGenerating && !isComplete} />}

            <div key={flowStep}>{renderStage()}</div>

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-surface-border/80 pt-3">
              <button
                type="button"
                onClick={() => setAdvancedOpen((value) => !value)}
                aria-expanded={advancedOpen}
                className="hh-btn-ghost hh-btn-sm -ml-3.5 max-w-full"
              >
                <SlidersHorizontal className="h-3.5 w-3.5 shrink-0" />
                高级设置
                <span className="hidden truncate font-normal text-content-tertiary sm:inline">· {advancedSummary}</span>
                <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 transition-transform', advancedOpen && 'rotate-180')} />
              </button>
              {historyMessages.length > 1 && (
                <button
                  type="button"
                  onClick={() => setHistoryOpen((value) => !value)}
                  aria-expanded={historyOpen}
                  className="hh-btn-ghost hh-btn-sm -mr-3.5"
                >
                  <History className="h-3.5 w-3.5" />
                  过程记录
                  <span className="hh-tag px-1.5 py-0 text-[11px] tabular-nums">{historyMessages.length}</span>
                  <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', historyOpen && 'rotate-180')} />
                </button>
              )}
            </div>

            {advancedOpen && (
              <div className="hh-subpanel animate-slide-down space-y-3 p-4">
                <KbSourcePicker
                  value={kbChoice}
                  onChange={setKbChoice}
                  disabled={Boolean(state.projectId)}
                  hint={state.projectId ? '项目已创建：到项目的「仿写参考」页调整对标书' : '项目建好后会关联它，之后各步按它注入仿写参考'}
                />
                <MCPSelector value={mcpSettings} onChange={setMcpSettings} />
              </div>
            )}

            {historyOpen && historyMessages.length > 1 && <HistoryPanel messages={historyMessages} />}
          </div>
        </section>
      </div>
    </div>,
    document.body,
  );
}

function Stepper({ activeIndex, currentStep }: { activeIndex: number; currentStep: Step }) {
  return (
    <ol className="mt-5 flex items-center" aria-label="流程步骤">
      {FLOW_STEPS.map((step, index) => {
        const status = getStepChipStatus(index, activeIndex, currentStep);
        const last = index === FLOW_STEPS.length - 1;
        const label = last && currentStep === 'generating' ? '创建' : last && currentStep === 'complete' ? '完成' : STEP_META[step].eyebrow;
        return (
          <li
            key={step}
            className={cn('flex min-w-0 items-center', !last && 'flex-1')}
            aria-current={status === 'current' ? 'step' : undefined}
          >
            <span className="flex shrink-0 items-center gap-1.5">
              <span
                className={cn(
                  'flex h-5 w-5 items-center justify-center border text-[10px] tabular-nums transition',
                  status === 'done'
                    ? 'border-brand bg-brand text-white'
                    : status === 'current'
                      ? 'border-brand bg-white text-brand ring-4 ring-brand/15'
                      : 'border-surface-border bg-white/60 text-content-tertiary',
                )}
              >
                {status === 'done' ? <Check className="h-3 w-3" /> : index + 1}
              </span>
              <span
                className={cn(
                  'text-xs',
                  status === 'current'
                    ? 'font-medium text-content'
                    : status === 'done'
                      ? 'text-content-secondary'
                      : 'text-content-tertiary',
                )}
              >
                {label}
              </span>
            </span>
            {!last && <span className={cn('mx-2 h-px min-w-2 flex-1', status === 'done' ? 'bg-brand' : 'bg-surface-border')} />}
          </li>
        );
      })}
    </ol>
  );
}

function HistoryPanel({ messages }: { messages: Message[] }) {
  const listRef = useRef<HTMLDivElement>(null);

  // 只滚动记录面板自身到底部，不要连带把弹窗主体也滚走
  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [messages.length]);

  return (
    <div className="hh-subpanel animate-slide-down p-4">
      <div ref={listRef} className="max-h-[40vh] space-y-2 overflow-y-auto">
        {messages.map((message) => (
          <div key={message.id} className={cn('flex', message.type === 'user' ? 'justify-end' : 'justify-start')}>
            <p
              className={cn(
                'max-w-[88%] whitespace-pre-wrap px-3.5 py-2 text-sm leading-6',
                message.type === 'user' ? 'bg-brand text-white' : 'border border-surface-border/80 bg-white/70 text-content',
              )}
            >
              {message.content}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
