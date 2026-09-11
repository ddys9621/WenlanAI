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


  return {
    refreshChapters,
    createChapter,
    updateChapter: updateChapterSync,
    deleteChapter,
  };
}
