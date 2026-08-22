import { create } from 'zustand';
import type {
  AgentSuggestion,
  ChatMessage,
  ColorLabel,
  ParamPatch,
  Photo,
  Project,
  ReviewItem,
  Source,
  StyleCardData,
} from '../types';
import {
  fetchProjects,
  fetchStyleCards,
  getMockPhotoList,
  patchParams as remotePatchParams,
} from '../api';

export type Page = 'workspace' | 'review' | 'settings';
export type ViewMode = 'original' | 'split' | 'processed';
export type InspectorTab = 'params' | 'measure' | 'trace' | 'agent';
export type RightTab = 'style' | 'adjust';

interface FilmFilter {
  rating: number | null;
  color: ColorLabel | '';
  status: string;
  scene: string;
}

interface AppState {
  page: Page;
  projects: Project[];
  photosByProject: Record<string, Photo[]>;
  activeProjectId: string;
  activePhotoId: string | null;
  styleCards: StyleCardData[];
  photos: Photo[];
  backend: boolean;
  params: ParamPatch;
  paramsByProject: Record<string, ParamPatch>;
  generation: number;
  viewMode: ViewMode;
  splitPos: number;
  zoom: number;
  inspectorTab: InspectorTab;
  rightTab: RightTab;
  messages: ChatMessage[];
  conversations: Record<string, ChatMessage[]>;
  suggestions: AgentSuggestion[];
  suggestionsByProject: Record<string, AgentSuggestion[]>;
  reviewItems: ReviewItem[];
  filter: string;
  filmFilter: FilmFilter;
  sortBy: 'name' | 'rating' | 'date';
  search: string;

  setPage: (page: Page) => void;
  setPhotos: (photos: Photo[], backend: boolean) => void;
  setProjects: (projects: Project[]) => void;
  selectProject: (projectId: string) => void;
  addProject: (name: string) => void;
  selectPhoto: (photoId: string) => void;
  setViewMode: (mode: ViewMode) => void;
  setSplitPos: (pos: number) => void;
  setZoom: (zoom: number) => void;
  setInspectorTab: (tab: InspectorTab) => void;
  setRightTab: (tab: RightTab) => void;
  setFilter: (filter: string) => void;
  setFilmFilter: (patch: Partial<FilmFilter>) => void;
  setSortBy: (sort: 'name' | 'rating' | 'date') => void;
  setSearch: (search: string) => void;
  patchParam: (patch: ParamPatch, source?: Source) => Promise<void>;
  patchProjectParam: (projectId: string, patch: ParamPatch, source?: Source) => Promise<void>;
  setPhotoRating: (projectId: string, photoId: string, rating: number) => void;
  setPhotoColor: (projectId: string, photoId: string, color: ColorLabel | undefined) => void;
  addMessage: (message: ChatMessage) => void;
  addProjectMessage: (projectId: string, message: ChatMessage) => void;
  applySuggestion: (suggestion: AgentSuggestion) => Promise<void>;
  applyProjectSuggestion: (projectId: string, suggestion: AgentSuggestion) => Promise<void>;
  ignoreSuggestion: (id: string) => void;
  ignoreProjectSuggestion: (projectId: string, id: string) => void;
  markReview: (id: string, state: 'accepted' | 'rejected') => void;
}

function defaultParams(): ParamPatch {
  return {
    exposure: { ev: 0.28, mode: 'auto' },
    whitebalance: { mode: 'as_shot', temp: 5200, tint: 0 },
    tone: { highlights: -20, shadows: 10, contrast: 0.1 },
    colorcal: { saturation: 0.05, vibrance: 0.1 },
    refine: { sharpen: 0.2, chroma_denoise: 0.5 },
  };
}

const initialProjects = fetchProjects();
const initialPhotoList = getMockPhotoList();
const initialPhotoMap: Record<string, Photo[]> = {};
for (const project of initialProjects) {
  initialPhotoMap[project.id] = project.photoIds
    .map((id) => initialPhotoList.find((p) => p.id === id))
    .filter((p): p is Photo => Boolean(p));
}
const initialParamsByProject: Record<string, ParamPatch> = {};
for (const project of initialProjects) {
  initialParamsByProject[project.id] = defaultParams();
}
const initialConversations: Record<string, ChatMessage[]> = {};
for (const project of initialProjects) {
  initialConversations[project.id] = [
    { id: `c-${project.id}-1`, role: 'agent', text: '当前项目已加载，可以开始修图或提问。' },
  ];
}

const initialSuggestions: AgentSuggestion[] = [
  {
    id: 's1',
    title: '提亮人脸 +0.28 EV',
    reason: 'face_luminance 95 < target 115',
    confidence: 0.87,
    patch: { exposure: { ev: 0.28 } },
  },
  {
    id: 's2',
    title: '压暗高光 -20',
    reason: 'highlight_clip 0.4% within safe range',
    confidence: 0.72,
    patch: { tone: { highlights: -20 } },
  },
];

const initialSuggestionsByProject: Record<string, AgentSuggestion[]> = {};
for (const project of initialProjects) {
  initialSuggestionsByProject[project.id] = initialSuggestions;
}

export const useAppStore = create<AppState>((set, get) => ({
  page: 'workspace',
  projects: initialProjects,
  photosByProject: initialPhotoMap,
  activeProjectId: initialProjects[0]?.id ?? '',
  activePhotoId: initialPhotoMap[initialProjects[0]?.id ?? '']?.[0]?.id ?? null,
  styleCards: fetchStyleCards(),
  photos: initialPhotoList,
  backend: false,
  params: defaultParams(),
  paramsByProject: initialParamsByProject,
  generation: 12,
  viewMode: 'split',
  splitPos: 0.5,
  zoom: 1,
  inspectorTab: 'params',
  rightTab: 'style',
  messages: initialConversations[initialProjects[0]?.id ?? ''] ?? [],
  conversations: initialConversations,
  suggestions: initialSuggestions,
  suggestionsByProject: initialSuggestionsByProject,
  reviewItems: [
    { id: 'r1', photoName: 'DSC_5237.NEF', reason: 'FINAL_QC 高光溢出 3.2%', ruleIds: ['qc_rollback_rule'], state: 'pending' },
    { id: 'r2', photoName: 'DSC_5310.NEF', reason: 'face region unreliable', ruleIds: ['face_rule'], state: 'pending' },
  ],
  filter: '全部',
  filmFilter: { rating: null, color: '', status: '全部', scene: '' },
  sortBy: 'name',
  search: '',

  setPage: (page) => set({ page }),
  setPhotos: (photos, backend) =>
    set({ photos, backend, activePhotoId: photos[0]?.id ?? null }),
  setProjects: (projects) => set({ projects }),
  selectProject: (projectId) =>
    set((state) => {
      const photos = state.photosByProject[projectId] ?? [];
      return {
        activeProjectId: projectId,
        activePhotoId: photos[0]?.id ?? null,
        rightTab: 'style',
        messages: state.conversations[projectId] ?? [],
      };
    }),
  addProject: (name) =>
    set((state) => {
      const id = `prj${Date.now()}`;
      const project: Project = {
        id,
        name,
        createdAt: new Date().toISOString().slice(0, 10),
        photoIds: [],
      };
      return {
        projects: [...state.projects, project],
        photosByProject: { ...state.photosByProject, [id]: [] },
        paramsByProject: { ...state.paramsByProject, [id]: defaultParams() },
        conversations: {
          ...state.conversations,
          [id]: [{ id: `c-${id}-1`, role: 'agent', text: '新项目已创建。' }],
        },
        suggestionsByProject: { ...state.suggestionsByProject, [id]: [] },
        activeProjectId: id,
        activePhotoId: null,
        messages: [{ id: `c-${id}-1`, role: 'agent', text: '新项目已创建。' }],
        rightTab: 'style',
      };
    }),
  selectPhoto: (photoId) => set({ activePhotoId: photoId }),
  setViewMode: (viewMode) => set({ viewMode }),
  setSplitPos: (splitPos) => set({ splitPos }),
  setZoom: (zoom) => set({ zoom }),
  setInspectorTab: (inspectorTab) => set({ inspectorTab }),
  setRightTab: (rightTab) => set({ rightTab }),
  setFilter: (filter) => set({ filter }),
  setFilmFilter: (patch) =>
    set((state) => ({ filmFilter: { ...state.filmFilter, ...patch } })),
  setSortBy: (sortBy) => set({ sortBy }),
  setSearch: (search) => set({ search }),

  patchParam: async (patch, source = 'user') => {
    const result = await remotePatchParams(patch, source);
    set({
      params: result.params,
      generation: result.generation,
    });
  },

  patchProjectParam: async (projectId, patch, source = 'user') => {
    const result = await remotePatchParams(patch, source);
    set((state) => ({
      params: result.params,
      generation: result.generation,
      paramsByProject: {
        ...state.paramsByProject,
        [projectId]: result.params,
      },
    }));
  },

  setPhotoRating: (projectId, photoId, rating) =>
    set((state) => {
      const photos = (state.photosByProject[projectId] ?? []).map((p) =>
        p.id === photoId ? { ...p, rating } : p,
      );
      return {
        photosByProject: { ...state.photosByProject, [projectId]: photos },
      };
    }),

  setPhotoColor: (projectId, photoId, color) =>
    set((state) => {
      const photos = (state.photosByProject[projectId] ?? []).map((p) =>
        p.id === photoId ? { ...p, colorLabel: color } : p,
      );
      return {
        photosByProject: { ...state.photosByProject, [projectId]: photos },
      };
    }),

  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),

  addProjectMessage: (projectId, message) =>
    set((state) => ({
      conversations: {
        ...state.conversations,
        [projectId]: [...(state.conversations[projectId] ?? []), message],
      },
      messages:
        projectId === state.activeProjectId
          ? [...state.messages, message]
          : state.messages,
    })),

  applySuggestion: async (suggestion) => {
    await get().patchParam(suggestion.patch, 'agent');
    set((state) => ({
      suggestions: state.suggestions.filter((s) => s.id !== suggestion.id),
    }));
  },

  applyProjectSuggestion: async (projectId, suggestion) => {
    await get().patchProjectParam(projectId, suggestion.patch, 'agent');
    set((state) => ({
      suggestionsByProject: {
        ...state.suggestionsByProject,
        [projectId]: (state.suggestionsByProject[projectId] ?? []).filter(
          (s) => s.id !== suggestion.id,
        ),
      },
      conversations: {
        ...state.conversations,
        [projectId]: [
          ...(state.conversations[projectId] ?? []),
          {
            id: `apply-${suggestion.id}`,
            role: 'system',
            text: `已应用建议：${suggestion.title}`,
          },
        ],
      },
    }));
  },

  ignoreSuggestion: (id) =>
    set((state) => ({
      suggestions: state.suggestions.filter((s) => s.id !== id),
    })),

  ignoreProjectSuggestion: (projectId, id) =>
    set((state) => ({
      suggestionsByProject: {
        ...state.suggestionsByProject,
        [projectId]: (state.suggestionsByProject[projectId] ?? []).filter(
          (s) => s.id !== id,
        ),
      },
    })),

  markReview: (id, nextState) =>
    set((appState) => ({
      reviewItems: appState.reviewItems.map((item) =>
        item.id === id ? { ...item, state: nextState } : item,
      ),
    })),
}));
