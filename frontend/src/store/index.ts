import { create } from 'zustand';
import type { Project, Outline, Character, Chapter, PlotCard, Volume, ChapterOutline } from '../types';

interface AppState {
  currentProject: Project | null;
  setCurrentProject: (project: Project | null) => void;

  projects: Project[];
  projectsInitialized: boolean;
  setProjects: (projects: Project[]) => void;
  setProjectsInitialized: (initialized: boolean) => void;
  addProject: (project: Project) => void;
  updateProject: (id: string, project: Partial<Project>) => void;
  removeProject: (id: string) => void;

  outlines: Outline[];
  setOutlines: (outlines: Outline[]) => void;
  addOutline: (outline: Outline) => void;
  updateOutline: (id: string, outline: Partial<Outline>) => void;
  removeOutline: (id: string) => void;

  characters: Character[];
  setCharacters: (characters: Character[]) => void;
  addCharacter: (character: Character) => void;
  updateCharacter: (id: string, character: Partial<Character>) => void;
  removeCharacter: (id: string) => void;

  chapters: Chapter[];
  setChapters: (chapters: Chapter[]) => void;
  addChapter: (chapter: Chapter) => void;
  updateChapter: (id: string, chapter: Partial<Chapter>) => void;
  removeChapter: (id: string) => void;

  currentChapter: Chapter | null;
  setCurrentChapter: (chapter: Chapter | null) => void;

  // 剧情卡片状态
  plotCards: PlotCard[];
  setPlotCards: (plotCards: PlotCard[]) => void;
  addPlotCard: (plotCard: PlotCard) => void;
  updatePlotCard: (plotCard: PlotCard) => void;
  removePlotCard: (id: string) => void;

  // 卷纲状态
  volumes: Volume[];
  setVolumes: (volumes: Volume[]) => void;
  updateVolume: (volume: Volume) => void;
  removeVolume: (id: string) => void;

  // 章纲状态
  chapterOutlines: ChapterOutline[];
  setChapterOutlines: (chapterOutlines: ChapterOutline[]) => void;
  addChapterOutline: (chapterOutline: ChapterOutline) => void;
  updateChapterOutline: (chapterOutline: ChapterOutline) => void;
  removeChapterOutline: (id: string) => void;

  loading: boolean;
  setLoading: (loading: boolean) => void;

  clearProjectData: () => void;
}

export const useStore = create<AppState>((set) => ({
  currentProject: null,
  setCurrentProject: (project) => set({ currentProject: project }),

  projects: [],
  projectsInitialized: false,
  setProjects: (projects) => set({ projects }),
  setProjectsInitialized: (initialized) => set({ projectsInitialized: initialized }),
  addProject: (project) => set((state) => ({ 
    projects: [...state.projects, project] 
  })),
  updateProject: (id, updatedProject) => set((state) => ({
    projects: state.projects.map((p) => 
      p.id === id ? { ...p, ...updatedProject } : p
    ),
    currentProject: state.currentProject?.id === id 
      ? { ...state.currentProject, ...updatedProject } 
      : state.currentProject,
  })),
  removeProject: (id) => set((state) => ({
    projects: state.projects.filter((p) => p.id !== id),
    currentProject: state.currentProject?.id === id ? null : state.currentProject,
  })),

  outlines: [],
  setOutlines: (outlines) => set({ outlines }),
  addOutline: (outline) => set((state) => ({ 
    outlines: [...state.outlines, outline] 
  })),
  updateOutline: (id, updatedOutline) => set((state) => ({
    outlines: state.outlines.map((o) => 
      o.id === id ? { ...o, ...updatedOutline } : o
    ),
  })),
  removeOutline: (id) => set((state) => ({
    outlines: state.outlines.filter((o) => o.id !== id),
  })),

  characters: [],
  setCharacters: (characters) => set({ characters }),
  addCharacter: (character) => set((state) => ({ 
    characters: [...state.characters, character] 
  })),
  updateCharacter: (id, updatedCharacter) => set((state) => ({
    characters: state.characters.map((c) => 
      c.id === id ? { ...c, ...updatedCharacter } : c
    ),
  })),
  removeCharacter: (id) => set((state) => ({
    characters: state.characters.filter((c) => c.id !== id),
  })),

  chapters: [],
  setChapters: (chapters) => set({ chapters }),
  addChapter: (chapter) => set((state) => ({ 
    chapters: [...state.chapters, chapter] 
  })),
  updateChapter: (id, updatedChapter) => set((state) => ({
    chapters: state.chapters.map((c) => 
      c.id === id ? { ...c, ...updatedChapter } : c
    ),
    currentChapter: state.currentChapter?.id === id 
      ? { ...state.currentChapter, ...updatedChapter } 
      : state.currentChapter,
  })),
  removeChapter: (id) => set((state) => ({
    chapters: state.chapters.filter((c) => c.id !== id),
    currentChapter: state.currentChapter?.id === id ? null : state.currentChapter,
  })),

  currentChapter: null,
  setCurrentChapter: (chapter) => set({ currentChapter: chapter }),

  // 剧情卡片状态实现
  plotCards: [],
  setPlotCards: (plotCards) => set({ plotCards }),
  addPlotCard: (plotCard) => set((state) => ({ 
    plotCards: [...state.plotCards, plotCard] 
  })),
  updatePlotCard: (updatedPlotCard) => set((state) => ({
    plotCards: state.plotCards.map((card) => 
      card.id === updatedPlotCard.id ? updatedPlotCard : card
    ),
  })),
  removePlotCard: (id) => set((state) => ({
    plotCards: state.plotCards.filter((card) => card.id !== id),
  })),

  // 卷纲状态实现
  volumes: [],
  setVolumes: (volumes) => set({ volumes }),
  updateVolume: (updated) => set((state) => ({
    volumes: state.volumes.map((v) => (v.id === updated.id ? updated : v)),
  })),
  removeVolume: (id) => set((state) => ({
    volumes: state.volumes.filter((v) => v.id !== id),
  })),

  // 章纲状态实现
  chapterOutlines: [],
  setChapterOutlines: (chapterOutlines) => set({ chapterOutlines }),
  addChapterOutline: (chapterOutline) => set((state) => ({ 
    chapterOutlines: [...state.chapterOutlines, chapterOutline] 
  })),
  updateChapterOutline: (updatedChapterOutline) => set((state) => ({
    chapterOutlines: state.chapterOutlines.map((outline) => 
      outline.id === updatedChapterOutline.id ? updatedChapterOutline : outline
    ),
  })),
  removeChapterOutline: (id) => set((state) => ({
    chapterOutlines: state.chapterOutlines.filter((outline) => outline.id !== id),
  })),

  loading: false,
  setLoading: (loading) => set({ loading }),

  clearProjectData: () => set({
    outlines: [],
    characters: [],
    chapters: [],
    currentChapter: null,
    plotCards: [],
    volumes: [],
    chapterOutlines: [],
  }),
}));