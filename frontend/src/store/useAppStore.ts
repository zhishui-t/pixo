import { create } from 'zustand';
import type {
  AgentSuggestion,
  ChatMessage,
  ColorLabel,
  ParamPatch,
  PhotoView,
  Project,
  ReviewItem,
  Source,
  StyleCardData,
} from '../types';
import {
  ensureSession,
  fetchProjects,
  fetchStyleCards,
  getMockPhotoList,
  getMockSessionId,
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
  photosByProject: Record<string, PhotoView[]>;
  activeProjectId: string;
  activePhotoId: string | null;
  styleCards: StyleCardData[];
  photos: PhotoView[];
  backend: boolean;
  /** 后端在线时 ensureSession 建立的真实会话 id；null=尚未建立（mock 模式）。 */
  sessionId: string | null;
  /** t91：skin 部位掩码路由是否就绪（null=未探测）。 */
  skinMaskReady: boolean | null;
  /**
   * t8：split_tone OKLCh 域能力（UI_OKLCH_SPEC §5.3 门控）——
   * 首次参数往返后按 canonical.split_tone 是否含 color_domain 键判定，
   * 结果一次性缓存（null=未探测，false 时分离色调面板退回 hsv 标注形态）。
   */
  splitToneDomainReady: boolean | null;
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
  setPhotos: (photos: PhotoView[], backend: boolean) => void;
  setSkinMaskReady: (v: boolean | null) => void;
  setSplitToneDomainReady: (v: boolean | null) => void;
  setProjects: (projects: Project[]) => void;
  setStyleCards: (cards: StyleCardData[]) => void;
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
  probeSplitToneDomain: (canonical: ParamPatch | undefined) => void;
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
    exposure: { mode: 0.28 },
    whitebalance: { mode: 'as_shot', temp: 5200, tint: 0 },
    tone: { highlights: -0.2, shadows: 0.1, contrast: 0.1 },
    colorcal: { saturation: 0.05, vibrance: 0.1 },
    refine: { sharpen: 0.2, chroma_denoise: 0.5 },
  };
}

const initialProjects = fetchProjects();
const initialPhotoList = getMockPhotoList();
const initialPhotoMap: Record<string, PhotoView[]> = {};
for (const project of initialProjects) {
  initialPhotoMap[project.id] = project.photoIds
    .map((id) => initialPhotoList.find((p) => p.photo_id === id))
    .filter((p): p is PhotoView => Boolean(p));
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
    patch: { exposure: { mode: 0.28 } },
  },
  {
    id: 's2',
    title: '压暗高光 -20',
    reason: 'highlight_clip 0.4% within safe range',
    confidence: 0.72,
    patch: { tone: { highlights: -0.2 } },
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
  activePhotoId: initialPhotoMap[initialProjects[0]?.id ?? '']?.[0]?.photo_id ?? null,
  styleCards: [],
  photos: initialPhotoList,
  backend: false,
  sessionId: null,
  skinMaskReady: null,
  splitToneDomainReady: null,
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
    set((state) => ({
      photos,
      backend,
      activePhotoId: photos[0]?.photo_id ?? null,
      // 后端在线时把后端照片装入当前项目的 Filmstrip 数据源（项目仍是
      // 本地概念，最小正确：只覆盖当前 activeProject 的槽位）；
      // mock 模式维持初始 mock 映射不动（项目-照片分组仅前端概念）。
      photosByProject: backend
        ? { ...state.photosByProject, [state.activeProjectId]: photos }
        : state.photosByProject,
    })),
  setSkinMaskReady: (v) => set({ skinMaskReady: v }),
  setSplitToneDomainReady: (v) => set({ splitToneDomainReady: v }),
  setProjects: (projects) => set({ projects }),
  setStyleCards: (cards) => set({ styleCards: cards }),
  selectProject: (projectId) =>
    set((state) => {
      const photos = state.photosByProject[projectId] ?? [];
      return {
        activeProjectId: projectId,
        activePhotoId: photos[0]?.photo_id ?? null,
        rightTab: 'style',
        messages: state.conversations[projectId] ?? [],
        // 恢复该项目的参数副本（此前切换后 params 悬空为上一项目的值）。
        params: state.paramsByProject[projectId] ?? {},
        // TODO：generation 目前是全局单值，切项目未恢复该项目的代数；
        // 后续应维护 perProject generation 或以会话回读为准。
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

  /**
   * §5.3 门控探测：canonical.split_tone 含 color_domain 键 → 后端支持 oklch 域。
   * 仅在未探测（null）时落值，一次性缓存；mock 模式 canonical 回读 patch，
   * 探测自然为 true。
   */
  probeSplitToneDomain: (canonical: ParamPatch | undefined) => {
    if (get().splitToneDomainReady !== null) return;
    const bucket = canonical?.split_tone;
    if (bucket !== undefined && typeof bucket === 'object' && bucket !== null) {
      set({ splitToneDomainReady: 'color_domain' in bucket });
    }
  },

  patchParam: async (patch, source = 'user') => {
    const sessionId = get().sessionId ?? getMockSessionId();
    const result = await remotePatchParams(patch, source, sessionId);
    get().probeSplitToneDomain(result.canonical);
    set({
      params: result.params,
      generation: result.generation,
    });
  },

  patchProjectParam: async (projectId, patch, source = 'user') => {
    // 后端在线且尚未建立会话：先 ensureSession（当前选中照片），
    // 避免硬传 demo-session 触发 404 并把 backendAvailable 打成 false。
    // 建会话失败时 ensureSession 回退 demo id（本次 patch 由 api 层降级 mock），
    // 且不缓存 demo id——下一次 patch 会重试建会话。
    let sessionId = get().sessionId;
    if (!sessionId) {
      const photoId = get().activePhotoId;
      const sid = photoId && get().backend ? await ensureSession(photoId) : getMockSessionId();
      if (sid !== getMockSessionId()) set({ sessionId: sid });
      sessionId = sid;
    }
    const result = await remotePatchParams(patch, source, sessionId);
    get().probeSplitToneDomain(result.canonical);
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
        p.photo_id === photoId ? { ...p, rating } : p,
      );
      return {
        photosByProject: { ...state.photosByProject, [projectId]: photos },
      };
    }),

  setPhotoColor: (projectId, photoId, color) =>
    set((state) => {
      const photos = (state.photosByProject[projectId] ?? []).map((p) =>
        p.photo_id === photoId ? { ...p, colorLabel: color } : p,
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

// 风格卡异步接线（t60）：后端 GET /api/styles 优先、离线回退 mock；
// store 创建即拉取一次（fire-and-forget），成功与否都落到 styleCards。
void fetchStyleCards().then((cards) => useAppStore.getState().setStyleCards(cards));
