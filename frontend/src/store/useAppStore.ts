import { create } from 'zustand';
import type {
  AgentSuggestion,
  ChatMessage,
  ParamPatch,
  Photo,
  ReviewItem,
  Source,
} from '../types';
import { patchParams, getMockSessionId } from '../api';

export type Page = 'workspace' | 'review' | 'settings';
export type ViewMode = 'original' | 'split' | 'processed';
export type InspectorTab = 'params' | 'measure' | 'trace' | 'agent';

interface AppState {
  page: Page;
  photos: Photo[];
  backend: boolean;
  activePhotoId: string | null;
  params: ParamPatch;
  generation: number;
  viewMode: ViewMode;
  splitPos: number;
  zoom: number;
  inspectorTab: InspectorTab;
  messages: ChatMessage[];
  suggestions: AgentSuggestion[];
  reviewItems: ReviewItem[];
  filter: string;
  search: string;

  setPage: (page: Page) => void;
  setPhotos: (photos: Photo[], backend: boolean) => void;
  selectPhoto: (photoId: string) => void;
  setViewMode: (mode: ViewMode) => void;
  setSplitPos: (pos: number) => void;
  setZoom: (zoom: number) => void;
  setInspectorTab: (tab: InspectorTab) => void;
  setFilter: (filter: string) => void;
  setSearch: (search: string) => void;
  patchParam: (patch: ParamPatch, source?: Source) => Promise<void>;
  addMessage: (message: ChatMessage) => void;
  applySuggestion: (suggestion: AgentSuggestion) => Promise<void>;
  ignoreSuggestion: (id: string) => void;
  markReview: (id: string, state: 'accepted' | 'rejected') => void;
}

const initialParams: ParamPatch = {
  exposure: { ev: 0.28, mode: 'auto' },
  whitebalance: { mode: 'as_shot', temp: 5200, tint: 0 },
  tone: { highlights: -20, shadows: 10, contrast: 0.1 },
  colorcal: { saturation: 0.05, vibrance: 0.1 },
  refine: { sharpen: 0.2, chroma_denoise: 0.5 },
};

export const useAppStore = create<AppState>((set, get) => ({
  page: 'workspace',
  photos: [],
  backend: false,
  activePhotoId: null,
  params: initialParams,
  generation: 12,
  viewMode: 'split',
  splitPos: 0.5,
  zoom: 1,
  inspectorTab: 'params',
  messages: [
    { id: 'm1', role: 'agent', text: '检测到人脸偏暗，建议提亮曝光。' },
    { id: 'm2', role: 'user', text: '好的，先看效果。' },
  ],
  suggestions: [
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
  ] as AgentSuggestion[],
  reviewItems: [
    { id: 'r1', photoName: 'DSC_5237.NEF', reason: 'FINAL_QC 高光溢出 3.2%', ruleIds: ['qc_rollback_rule'], state: 'pending' },
    { id: 'r2', photoName: 'DSC_5310.NEF', reason: 'face region unreliable', ruleIds: ['face_rule'], state: 'pending' },
  ],
  filter: '全部',
  search: '',

  setPage: (page) => set({ page }),
  setPhotos: (photos, backend) =>
    set({
      photos,
      backend,
      activePhotoId: photos[0]?.id ?? null,
    }),
  selectPhoto: (photoId) => set({ activePhotoId: photoId }),
  setViewMode: (viewMode) => set({ viewMode }),
  setSplitPos: (splitPos) => set({ splitPos }),
  setZoom: (zoom) => set({ zoom }),
  setInspectorTab: (inspectorTab) => set({ inspectorTab }),
  setFilter: (filter) => set({ filter }),
  setSearch: (search) => set({ search }),

  patchParam: async (patch, source = 'user') => {
    const result = await patchParams(patch, source);
    set({
      params: result.params,
      generation: result.generation,
    });
  },

  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),

  applySuggestion: async (suggestion) => {
    await get().patchParam(suggestion.patch, 'agent');
    set((state) => ({
      suggestions: state.suggestions.filter((s) => s.id !== suggestion.id),
      messages: [
        ...state.messages,
        {
          id: `apply-${suggestion.id}`,
          role: 'system',
          text: `已应用建议：${suggestion.title}`,
        },
      ],
    }));
  },

  ignoreSuggestion: (id) =>
    set((state) => ({
      suggestions: state.suggestions.filter((s) => s.id !== id),
    })),

  markReview: (id, nextState) =>
    set((appState) => ({
      reviewItems: appState.reviewItems.map((item) =>
        item.id === id ? { ...item, state: nextState } : item,
      ),
    })),
}));
