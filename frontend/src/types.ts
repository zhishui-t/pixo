export type Source = 'user' | 'agent' | 'decide' | 'preset' | 'locked';

export type PhotoStatus =
  | 'pending'
  | 'processing'
  | 'accepted'
  | 'review'
  | 'rejected'
  | 'imported';

export type ColorLabel = 'red' | 'yellow' | 'green' | 'blue' | 'purple';

export interface Photo {
  id: string;
  name: string;
  path: string;
  camera?: string;
  takenAt?: string;
  status: PhotoStatus;
  burstGroup?: string;
  scene?: string;
  rating?: number; // 0-5 星
  colorLabel?: ColorLabel;
  thumbnail?: string;
}

export interface Project {
  id: string;
  name: string;
  createdAt: string;
  photoIds: string[];
}

export interface StyleCardData {
  styleId: string;
  name: string;
  description: string;
  tags: Record<string, string[]>;
  colorFingerprint?: Record<string, unknown>;
  toneFingerprint?: Record<string, unknown>;
  recommendedAdjustments?: Record<string, unknown>;
}

export interface ParamPatch {
  [stage: string]: Record<string, unknown>;
}

export interface AgentSuggestion {
  id: string;
  title: string;
  reason: string;
  confidence: number;
  patch: ParamPatch;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'agent' | 'system';
  text: string;
  suggestion?: AgentSuggestion;
}

export interface ReviewItem {
  id: string;
  photoName: string;
  reason: string;
  ruleIds: string[];
  state: 'pending' | 'accepted' | 'rejected';
}

export interface HealthInfo {
  ok: boolean;
  native: boolean;
  vision: boolean;
  version: string;
}

export interface ParamDef {
  key: string;
  label: string;
  min: number;
  max: number;
  step: number;
  unit?: string;
  source: Source;
  locked?: boolean;
}
