/**
 * Store Hooks - 提供数据获取和自动同步功能
 * 这些 hooks 封装了数据获取逻辑，并自动更新 store
 */

import { useCallback } from 'react';
import { toast } from 'sonner';
import { useStore } from './index';
import { projectApi, outlineApi, characterApi, chapterApi } from '../services/api';
import type {
  PaginationResponse,
  Outline,
  Character,
  Chapter,
  Project,
  ProjectCreate,
  ProjectUpdate,
  OutlineCreate,
  OutlineUpdate,
  ChapterCreate,
  ChapterUpdate,
  ChapterGenerateRequest,
} from '../types';

/**
 * 项目数据同步 Hook
 */
export function useProjectSync() {
  const { setProjects, setLoading, setProjectsInitialized, addProject, updateProject, removeProject } = useStore();

  // 刷新项目列表
  const refreshProjects = useCallback(async () => {
    try {
      setLoading(true);
      const data = await projectApi.getProjects();
      const projects = Array.isArray(data) ? data : (data as PaginationResponse<Project>).items || [];
      setProjects(projects);
      return projects;
    } catch (error) {
      console.error('刷新项目列表失败:', error);
      toast.error('刷新项目列表失败');
      return [];
    } finally {
      setLoading(false);
      setProjectsInitialized(true);
    }
  }, [setProjects, setLoading, setProjectsInitialized]);

  // 创建项目（带同步）
  const createProject = useCallback(async (data: ProjectCreate) => {
    try {
      const created = await projectApi.createProject(data);
      addProject(created);
      return created;
    } catch (error) {
      console.error('创建项目失败:', error);
      throw error;
    }
  }, [addProject]);

  // 更新项目（带同步）
  const updateProjectSync = useCallback(async (id: string, data: ProjectUpdate) => {
    try {
      const updated = await projectApi.updateProject(id, data);
      updateProject(id, updated);
      return updated;
    } catch (error) {
      console.error('更新项目失败:', error);
      throw error;
    }
  }, [updateProject]);

  // 删除项目（带同步）
  const deleteProject = useCallback(async (id: string) => {
    try {
      await projectApi.deleteProject(id);
      removeProject(id);
    } catch (error) {
      console.error('删除项目失败:', error);
      throw error;
    }
  }, [removeProject]);

  return {
    refreshProjects,
    createProject,
    updateProject: updateProjectSync,
    deleteProject,
  };
}

/**
 * 角色数据同步 Hook
 */
export function useCharacterSync() {
  const { currentProject, setCharacters, removeCharacter } = useStore();

  // 刷新角色列表
  const refreshCharacters = useCallback(async (projectId?: string) => {
    const id = projectId || currentProject?.id;
    if (!id) return [];

    try {
      const data = await characterApi.getCharacters(id);
      const characters = Array.isArray(data) ? data : (data as PaginationResponse<Character>).items || [];
      setCharacters(characters);
      return characters;
    } catch (error) {
      console.error('刷新角色列表失败:', error);
      toast.error('刷新角色列表失败');
      return [];
    }
  }, [currentProject?.id, setCharacters]);

  // 删除角色（带同步）
  const deleteCharacter = useCallback(async (id: string) => {
    try {
      await characterApi.deleteCharacter(id);
      removeCharacter(id);
    } catch (error) {
      console.error('删除角色失败:', error);
      throw error;
    }
  }, [removeCharacter]);

  return {
    refreshCharacters,
    deleteCharacter,
  };
}

/**
 * 大纲数据同步 Hook
 */
export function useOutlineSync() {
  const { currentProject, setOutlines, addOutline, updateOutline, removeOutline } = useStore();

  // 刷新大纲列表
  const refreshOutlines = useCallback(async (projectId?: string) => {
    const id = projectId || currentProject?.id;
    if (!id) return [];

    try {
      const data = await outlineApi.getOutlines(id);
      const outlines = Array.isArray(data) ? data : (data as PaginationResponse<Outline>).items || [];
      setOutlines(outlines);
      return outlines;
    } catch (error) {
      console.error('刷新大纲列表失败:', error);
      toast.error('刷新大纲列表失败');
      return [];
    }
  }, [currentProject?.id, setOutlines]); // 添加 currentProject?.id 到依赖数组

  // 创建大纲（带同步）
  const createOutline = useCallback(async (data: OutlineCreate) => {
    try {
      const projectId = currentProject?.id;
      if (!projectId) {
        throw new Error('当前项目ID不存在');
      }
      const created = await outlineApi.createOutline(projectId, data);
      addOutline(created);
      return created;
    } catch (error) {
      console.error('创建大纲失败:', error);
      throw error;
    }
  }, [addOutline, currentProject?.id]);

  // 更新大纲（带同步）
  const updateOutlineSync = useCallback(async (id: string, data: OutlineUpdate) => {
    try {
      const updated = await outlineApi.updateOutline(id, data);
      updateOutline(id, updated);
      toast.success('大纲更新成功');
      return updated;
    } catch (error) {
      console.error('更新大纲失败:', error);
      const status = (error as { response?: { status?: number } }).response?.status;
      
      // 处理版本冲突
      if (status === 409) {
        toast.error('版本冲突：大纲已被其他用户修改，请刷新后重试');
      } else {
        toast.error('更新大纲失败');
      }
      throw error;
    }
  }, [updateOutline]);

  // 删除大纲（带同步）
  const deleteOutline = useCallback(async (id: string) => {
    try {
      await outlineApi.deleteOutline(id);
      removeOutline(id);
    } catch (error) {
      console.error('删除大纲失败:', error);
      throw error;
    }
  }, [removeOutline]);

  // 激活大纲版本（带同步）
  const activateOutline = useCallback(async (id: string) => {
    try {
      const activated = await outlineApi.activateOutline(id);
      updateOutline(id, activated);
      return activated;
    } catch (error) {
      console.error('激活大纲失败:', error);
      throw error;
    }
  }, [updateOutline]);

  return {
    refreshOutlines,
    createOutline,
    updateOutline: updateOutlineSync,
    deleteOutline,
    activateOutline,
  };
}

/**
 * 章节数据同步 Hook
 */
export function useChapterSync() {
  const { currentProject, setChapters, addChapter, updateChapter, removeChapter } = useStore();

  // 刷新章节列表
  const refreshChapters = useCallback(async (projectId?: string) => {
    const id = projectId || currentProject?.id;
    if (!id) return [];

    try {
      const data = await chapterApi.getChapters(id);
      const chapters = Array.isArray(data) ? data : (data as PaginationResponse<Chapter>).items || [];
      setChapters(chapters);
      return chapters;
    } catch (error) {
      console.error('刷新章节列表失败:', error);
      toast.error('刷新章节列表失败');
      return [];
    }
  }, [currentProject?.id, setChapters]); // 添加 currentProject?.id 到依赖数组

  // 创建章节（带同步）
  const createChapter = useCallback(async (data: ChapterCreate) => {
    try {
      const created = await chapterApi.createChapter(data);
      addChapter(created);
      return created;
    } catch (error) {
      console.error('创建章节失败:', error);
      throw error;
    }
  }, [addChapter]);

  // 更新章节（带同步）
  const updateChapterSync = useCallback(async (id: string, data: ChapterUpdate) => {
    try {
      const updated = await chapterApi.updateChapter(id, data);
      updateChapter(id, updated);
      return updated;
    } catch (error) {
      console.error('更新章节失败:', error);
      throw error;
    }
  }, [updateChapter]);

  // 删除章节（带同步）
  const deleteChapter = useCallback(async (id: string) => {
    try {
      await chapterApi.deleteChapter(id);
      removeChapter(id);
    } catch (error) {
      console.error('删除章节失败:', error);
      throw error;
    }
  }, [removeChapter]);

  // AI流式生成章节内容（带同步）
  const generateChapterContentStream = useCallback(async (
    chapterId: string,
    onProgress?: (content: string) => void,
    styleId?: number,
    targetWordCount?: number,
    onProgressUpdate?: (message: string, progress: number) => void,
    enableMcp?: boolean,
    selectedPlugins?: string[]
  ) => {
    // 创建 AbortController 用于超时控制
    const abortController = new AbortController();
    // 设置超时：15分钟（足够生成一章内容）
    const timeoutId = setTimeout(() => {
      abortController.abort();
    }, 15 * 60 * 1000); // 15分钟

    try {
      const requestBody: ChapterGenerateRequest = {
        style_id: styleId,
        target_word_count: targetWordCount,
        enable_mcp: enableMcp,
        selected_plugins: enableMcp && selectedPlugins && selectedPlugins.length > 0
          ? selectedPlugins
          : undefined,
      };

      // 使用fetch处理流式响应
      const response = await fetch(`/api/chapters/${chapterId}/generate-stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
        signal: abortController.signal, // 添加超时控制
        keepalive: true, // 保持连接活跃
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error('无法获取响应流');
      }

      let buffer = '';
      let fullContent = '';
      let analysisTaskId: string | undefined;

      while (true) {
        const { done, value } = await reader.read();

        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        
        // 处理缓冲区中的完整消息
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.trim() === '' || line.startsWith(':')) {
            continue;
          }

          try {
            const dataMatch = line.match(/^data: (.+)$/m);
            if (dataMatch) {
              const message = JSON.parse(dataMatch[1]);
              
              if (message.type === 'start') {
                // 开始生成
                if (onProgressUpdate) {
                  onProgressUpdate(message.message || '开始生成...', 0);
                }
              } else if (message.type === 'progress') {
                // 进度更新
                if (onProgressUpdate) {
                  onProgressUpdate(
                    message.message || '生成中...',
                    message.progress || 0
                  );
                }
              } else if (message.type === 'content' && message.content) {
                fullContent += message.content;
                if (onProgress) {
                  onProgress(fullContent);
                }
              } else if (message.type === 'error') {
                throw new Error(message.error || '生成失败');
              } else if (message.type === 'done') {
                // 生成完成，保存分析任务ID
                analysisTaskId = message.analysis_task_id;
                if (onProgressUpdate) {
                  onProgressUpdate('生成完成', 100);
                }
                // 生成完成，刷新章节数据
                await refreshChapters();
              } else if (message.type === 'analysis_started') {
                // 分析已开始
                analysisTaskId = message.task_id;
                if (onProgressUpdate) {
                  onProgressUpdate('章节分析已开始...', 100);
                }
              } else if (message.type === 'analysis_queued') {
                // 分析任务已加入队列
                analysisTaskId = message.task_id;
              }
            }
          } catch (error) {
            console.error('解析SSE消息失败:', error);
          }
        }
      }

      return {
        content: fullContent,
        analysis_task_id: analysisTaskId
      };
    } catch (error) {
      // 检查是否是超时错误
      if (error instanceof Error && error.name === 'AbortError') {
        console.error('章节生成超时（15分钟）');
        throw new Error('生成超时，请重试或联系管理员');
      }
      console.error('AI流式生成章节内容失败:', error);
      throw error;
    } finally {
      // 清除超时定时器
      clearTimeout(timeoutId);
    }
  }, [refreshChapters]);

  return {
    refreshChapters,
    createChapter,
    updateChapter: updateChapterSync,
    deleteChapter,
    generateChapterContentStream,
  };
}
