/** 灵感模式 - 项目生成编排 Hook（支持逐节点重跑） */

import { useCallback, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { wizardStreamApi } from '../../services/api';
import { runWizardJob, type WizardJobKind } from '../../store/wizardJob';
import type {
  ApiError,
  Character,
  GenerateCharactersResponse,
  GenerateOutlineResponse,
  Outline,
  WizardVolumesResponse,
  WorldBuildingResponse,
} from '../../types';
import type { SSEClientOptions } from '../../utils/sseClient';
import type { GenerationSteps, GenStepStatus, WizardAction, WizardData } from './types';
import type { MCPSelectorValue } from '../MCPSelector';
import type { KbSourceChoice } from '../../types/knowledge';
import { kbChoicePayload } from '../../utils/knowledge';

export type GenerationNodeKey = 'worldBuilding' | 'characters' | 'outline' | 'volumes';

export interface GenerationArtifacts {
  worldBuilding: WorldBuildingResponse | null;
  characters: Character[];
  outline: Outline | null;
  volumes: WizardVolumesResponse | null;
}

/** 灵感模式固定用默认篇幅创建项目：全书章节数（卷纲按它分卷） */
const DEFAULT_CHAPTER_COUNT = 30;

interface UseProjectGenerationOptions {
  dispatch: React.Dispatch<WizardAction>;
  mcpSettings: MCPSelectorValue;
  /** 灵感模式里选的对标书（可选）：只在建项目那一步传，项目建好后关联上，后续各步由后端按关联注入仿写参考 */
  kbChoice?: KbSourceChoice;
}

const EMPTY_ARTIFACTS: GenerationArtifacts = {
  worldBuilding: null,
  characters: [],
  outline: null,
  volumes: null,
};

type StageProgressPreset = Partial<Record<GenerationNodeKey, [number, number]>>;

const NODE_PROGRESS_PRESETS: Record<GenerationNodeKey, StageProgressPreset> = {
  worldBuilding: {
    worldBuilding: [0, 25],
    characters: [25, 50],
    outline: [50, 75],
    volumes: [75, 100],
  },
  characters: {
    characters: [0, 34],
    outline: [34, 67],
    volumes: [67, 100],
  },
  outline: {
    outline: [0, 50],
    volumes: [50, 100],
  },
  volumes: {
    volumes: [0, 100],
  },
};

const INITIAL_NODE_STATUS: Record<GenerationNodeKey, Partial<Record<GenerationNodeKey, 'pending' | 'completed'>>> = {
  worldBuilding: {},
  characters: {
    worldBuilding: 'completed',
  },
  outline: {
    worldBuilding: 'completed',
    characters: 'completed',
  },
  volumes: {
    worldBuilding: 'completed',
    characters: 'completed',
    outline: 'completed',
  },
};

const mapProgress = (
  preset: StageProgressPreset,
  node: GenerationNodeKey,
  rawProgress: number,
) => {
  const [start, end] = getNodeRange(preset, node);
  const safeProgress = Math.max(0, Math.min(rawProgress, 100));
  return start + Math.floor(((end - start) * safeProgress) / 100);
};

const getNodeRange = (preset: StageProgressPreset, node: GenerationNodeKey): [number, number] =>
  preset[node] || [0, 100];

const getOutlineFromResponse = (response: GenerateOutlineResponse | null) =>
  response?.outline || response?.outlines?.[0] || null;

const nodeStatus = (node: GenerationNodeKey, status: GenStepStatus) =>
  ({ [node]: status }) as Partial<GenerationSteps>;

/** 一个生成节点对应的后台任务 */
interface NodeJob<T> {
  kind: WizardJobKind;
  title: string;
  projectId?: string;
  /** 节点开始时进度条上的文案 */
  startMessage: string;
  connect: (options: SSEClientOptions<T>) => Promise<unknown>;
}

export function useProjectGeneration({ dispatch, mcpSettings, kbChoice }: UseProjectGenerationOptions) {
  const [artifacts, setArtifacts] = useState<GenerationArtifacts>(EMPTY_ARTIFACTS);
  const [runningNode, setRunningNode] = useState<GenerationNodeKey | null>(null);
  const generationRunRef = useRef(0);

  const mcpEnabled = useMemo(
    () => mcpSettings.enable && mcpSettings.selected.length > 0,
    [mcpSettings.enable, mcpSettings.selected.length],
  );
  const mcpPlugins = useMemo(
    () => (mcpSettings.enable ? mcpSettings.selected : []),
    [mcpSettings.enable, mcpSettings.selected],
  );

  const resetArtifacts = useCallback(() => {
    setArtifacts(EMPTY_ARTIFACTS);
    setRunningNode(null);
  }, []);

  const createRunId = useCallback(() => {
    generationRunRef.current += 1;
    return generationRunRef.current;
  }, []);

  const isRunActive = useCallback((runId: number) => generationRunRef.current === runId, []);

  const dispatchIfActive = useCallback((runId: number, action: WizardAction) => {
    if (!isRunActive(runId)) return false;
    dispatch(action);
    return true;
  }, [dispatch, isRunActive]);

  const cancelGeneration = useCallback(() => {
    generationRunRef.current += 1;
    setRunningNode(null);
  }, []);

  const cleanupDownstreamData = useCallback(async (projectId: string, progressBase: number, runId: number) => {
    dispatchIfActive(runId, {
      type: 'GEN_PROGRESS',
      payload: {
        progress: progressBase,
        message: '正在清理旧的角色、大纲和章节...',
      },
    });

    await wizardStreamApi.cleanupWizardDataStream(projectId, {
      onProgress: (message, progress) => {
        if (!isRunActive(runId)) return;
        const nextProgress = progressBase + Math.floor((Math.max(progress, 0) / 100) * 8);
        dispatch({
          type: 'GEN_PROGRESS',
          payload: {
            progress: Math.min(nextProgress, progressBase + 8),
            message,
          },
        });
      },
    });
  }, [dispatch, dispatchIfActive, isRunActive]);

  /**
   * 一个节点 = 一个后台任务（断线按 lastSeq 续上）：标为进行中，后端 0-100 的进度映射到本节点在总进度条上的区间。
   * 失败 / 停止直接 reject，由 runFromNode 统一把当前节点标成失败。
   */
  const runNodeJob = useCallback(<T>(
    node: GenerationNodeKey,
    preset: StageProgressPreset,
    runId: number,
    job: NodeJob<T>,
  ): Promise<T> => {
    dispatchIfActive(runId, { type: 'GEN_STEP_UPDATE', payload: nodeStatus(node, 'processing') });
    dispatchIfActive(runId, {
      type: 'GEN_PROGRESS',
      payload: { progress: getNodeRange(preset, node)[0], message: job.startMessage },
    });
    return runWizardJob<T>({
      kind: job.kind,
      title: job.title,
      projectId: job.projectId,
      connect: job.connect,
      onProgress: (message, progress) => {
        dispatchIfActive(runId, {
          type: 'GEN_PROGRESS',
          payload: { progress: mapProgress(preset, node, progress), message },
        });
      },
    });
  }, [dispatchIfActive]);

  const runWorldBuilding = useCallback(async (
    data: WizardData,
    preset: StageProgressPreset,
    runId: number,
    existingProjectId?: string,
  ) => {
    const result = await runNodeJob<WorldBuildingResponse>('worldBuilding', preset, runId, existingProjectId
      ? {
          kind: 'wizard_world_building',
          title: '向导：重新生成世界构建',
          projectId: existingProjectId,
          startMessage: '正在重生成世界观...',
          connect: (options) => wizardStreamApi.regenerateWorldBuildingStream(
            existingProjectId,
            { enable_mcp: mcpEnabled, selected_plugins: mcpPlugins },
            options,
          ),
        }
      : {
          kind: 'wizard_world_building',
          title: '向导：生成世界构建',
          startMessage: '正在生成世界观...',
          connect: (options) => wizardStreamApi.generateWorldBuildingStream(
            {
              title: data.title,
              description: data.description,
              theme: data.theme,
              genre: data.genre.join('、'),
              narrative_perspective: data.narrative_perspective,
              target_words: 100000,
              chapter_count: 30,
              character_count: 5,
              enable_mcp: mcpEnabled,
              selected_plugins: mcpPlugins,
              ...kbChoicePayload(kbChoice),
            },
            options,
          ),
        });

    if (isRunActive(runId)) {
      setArtifacts((current) => ({ ...current, worldBuilding: result }));
      dispatch({ type: 'GEN_STEP_UPDATE', payload: { worldBuilding: 'completed' } });
      if (result?.project_id) dispatch({ type: 'GEN_PROJECT_CREATED', payload: result.project_id });
    }

    return result;
  }, [dispatch, isRunActive, mcpEnabled, mcpPlugins, kbChoice, runNodeJob]);

  const runCharacters = useCallback(async (
    projectId: string,
    data: WizardData,
    preset: StageProgressPreset,
    worldBuilding: WorldBuildingResponse | null,
    runId: number,
  ) => {
    const result = await runNodeJob<GenerateCharactersResponse>('characters', preset, runId, {
      kind: 'wizard_characters',
      title: '向导：生成角色',
      projectId,
      startMessage: '正在生成角色...',
      connect: (options) => wizardStreamApi.generateCharactersStream(
        {
          project_id: projectId,
          count: 5,
          world_context: worldBuilding
            ? {
                time_period: worldBuilding.time_period || '',
                location: worldBuilding.location || '',
                atmosphere: worldBuilding.atmosphere || '',
                rules: worldBuilding.rules || '',
              }
            : undefined,
          theme: data.theme,
          genre: data.genre.join('、'),
          enable_mcp: mcpEnabled,
          selected_plugins: mcpPlugins,
        },
        options,
      ),
    });

    const characters: Character[] = result?.characters || [];
    if (isRunActive(runId)) {
      setArtifacts((current) => ({ ...current, characters }));
      dispatch({ type: 'GEN_STEP_UPDATE', payload: { characters: 'completed' } });
    }
    return characters;
  }, [dispatch, isRunActive, mcpEnabled, mcpPlugins, runNodeJob]);

  const runOutline = useCallback(async (
    projectId: string,
    data: WizardData,
    preset: StageProgressPreset,
    runId: number,
  ) => {
    const response = await runNodeJob<GenerateOutlineResponse>('outline', preset, runId, {
      kind: 'wizard_outline',
      title: '向导：生成故事大纲',
      projectId,
      startMessage: '正在生成故事大纲...',
      connect: (options) => wizardStreamApi.generateCompleteOutlineStream(
        {
          project_id: projectId,
          chapter_count: 30,
          narrative_perspective: data.narrative_perspective,
          target_words: 100000,
          enable_mcp: mcpEnabled,
          selected_plugins: mcpPlugins,
        },
        options,
      ),
    });

    const outline = getOutlineFromResponse(response);
    if (isRunActive(runId)) {
      setArtifacts((current) => ({ ...current, outline }));
      dispatch({ type: 'GEN_STEP_UPDATE', payload: { outline: 'completed' } });
    }
    return outline;
  }, [dispatch, isRunActive, mcpEnabled, mcpPlugins, runNodeJob]);

  const runVolumes = useCallback(async (
    projectId: string,
    preset: StageProgressPreset,
    runId: number,
  ) => {
    const response = await runNodeJob<WizardVolumesResponse>('volumes', preset, runId, {
      kind: 'wizard_volumes',
      title: '向导：生成卷纲',
      projectId,
      startMessage: '正在生成卷纲...',
      connect: (options) => wizardStreamApi.generateVolumesStream(
        { project_id: projectId, chapter_count: DEFAULT_CHAPTER_COUNT },
        options,
      ),
    });

    if (isRunActive(runId)) {
      setArtifacts((current) => ({ ...current, volumes: response }));
      dispatch({ type: 'GEN_STEP_UPDATE', payload: { volumes: 'completed' } });
    }
    return response;
  }, [dispatch, isRunActive, runNodeJob]);

  const runFromNode = useCallback(async (
    startNode: GenerationNodeKey,
    data: WizardData,
    runId: number,
    existingProjectId?: string,
  ) => {
    const preset = NODE_PROGRESS_PRESETS[startNode];
    const initialStatus = INITIAL_NODE_STATUS[startNode];

    setRunningNode(startNode);
    dispatchIfActive(runId, { type: 'GEN_START', payload: { title: data.title } });
    dispatchIfActive(runId, { type: 'GEN_STEP_UPDATE', payload: initialStatus });

    if (startNode === 'worldBuilding') {
      setArtifacts(EMPTY_ARTIFACTS);
    } else if (startNode === 'characters') {
      setArtifacts((current) => ({
        ...current,
        characters: [],
        outline: null,
        volumes: null,
      }));
    } else if (startNode === 'outline') {
      setArtifacts((current) => ({
        ...current,
        outline: null,
        volumes: null,
      }));
    } else {
      setArtifacts((current) => ({
        ...current,
        volumes: null,
      }));
    }

    // 正在跑的环节：失败时把它标红，确认页从这里续跑（清理下游数据算作下一环节的准备工作）
    let activeNode: GenerationNodeKey = startNode;
    try {
      let projectId = existingProjectId || '';
      let worldBuilding = startNode === 'worldBuilding' ? null : artifacts.worldBuilding;

      if (startNode === 'worldBuilding') {
        worldBuilding = await runWorldBuilding(data, preset, runId, existingProjectId);
        if (!isRunActive(runId)) return;
        projectId = worldBuilding?.project_id || projectId;

        if (existingProjectId) {
          activeNode = 'characters';
          await cleanupDownstreamData(projectId, getNodeRange(preset, 'characters')[0] - 8, runId);
          if (!isRunActive(runId)) return;
          dispatch({ type: 'GEN_STEP_UPDATE', payload: { characters: 'pending', outline: 'pending', volumes: 'pending' } });
          setArtifacts((current) => ({
            ...current,
            characters: [],
            outline: null,
            volumes: null,
          }));
        }
      }

      if (!projectId) {
        throw new Error('项目创建失败');
      }

      if (startNode === 'characters') {
        await cleanupDownstreamData(projectId, Math.max(getNodeRange(preset, 'characters')[0], 0), runId);
        if (!isRunActive(runId)) return;
        dispatch({ type: 'GEN_STEP_UPDATE', payload: { characters: 'pending', outline: 'pending', volumes: 'pending' } });
      }

      if (startNode === 'worldBuilding' || startNode === 'characters') {
        activeNode = 'characters';
        await runCharacters(projectId, data, preset, worldBuilding, runId);
        if (!isRunActive(runId)) return;
      }

      if (startNode === 'outline' || startNode === 'volumes') {
        // 重跑总纲 / 卷纲：后端分卷时保留已有章纲的卷、替换其余草稿卷，不必先清理
        dispatch({ type: 'GEN_STEP_UPDATE', payload: { volumes: 'pending' } });
      }

      if (startNode !== 'volumes') {
        activeNode = 'outline';
        await runOutline(projectId, data, preset, runId);
        if (!isRunActive(runId)) return;
      }

      activeNode = 'volumes';
      await runVolumes(projectId, preset, runId);
      if (!isRunActive(runId)) return;

      dispatch({ type: 'GEN_COMPLETE' });
      toast.success(startNode === 'worldBuilding' && !existingProjectId ? '项目创建成功！' : '已从当前节点重新生成');
    } catch (error) {
      if (!isRunActive(runId)) return;
      const apiError = error as ApiError;
      const message = apiError.response?.data?.detail || apiError.message || '未知错误';
      dispatch({ type: 'GEN_STEP_UPDATE', payload: nodeStatus(activeNode, 'error') });
      toast.error(`创建项目失败：${message}`);
      dispatch({ type: 'GEN_ERROR', payload: message });
    } finally {
      if (isRunActive(runId)) {
        setRunningNode(null);
      }
    }
  }, [artifacts.worldBuilding, cleanupDownstreamData, dispatch, dispatchIfActive, isRunActive, runCharacters, runOutline, runVolumes, runWorldBuilding]);

  const startGeneration = useCallback(async (data: WizardData) => {
    const runId = createRunId();
    await runFromNode('worldBuilding', data, runId);
  }, [createRunId, runFromNode]);

  const regenerateFrom = useCallback(async (
    startNode: GenerationNodeKey,
    data: WizardData,
    projectId: string,
  ) => {
    const runId = createRunId();
    await runFromNode(startNode, data, runId, projectId);
  }, [createRunId, runFromNode]);

  return {
    artifacts,
    runningNode,
    startGeneration,
    regenerateFrom,
    cancelGeneration,
    resetArtifacts,
  };
}
