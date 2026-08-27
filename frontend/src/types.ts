/**
 * types —— 与 pixo-service 后端响应对齐的类型。
 * 事实来源：src/pixo/service/app.py（路由）与 runtime.py（响应形状）、
 * src/pixo/state/machine.py（状态机）、src/pixo/render/modules/*（stage 参数）。
 * 纯前端本地概念（项目/风格卡/推荐/用户标记）单独分组，不与后端字段混用。
 */

/** 参数来源（PUT params 的 __source，见 runtime.update_params）。 */
export type Source = 'user' | 'agent' | 'decide' | 'preset' | 'locked';

/** 用户标记色（Lightroom 惯例，纯前端数据，后端无此概念）。 */
export type ColorLabel = 'red' | 'yellow' | 'green' | 'blue' | 'purple';

// ---------- 后端响应 ----------

/** PhotoStateMachine STATES（src/pixo/state/machine.py）。 */
export type PhotoState =
  | 'RAW_PENDING'
  | 'SCREENED'
  | 'BASE_RENDERED'
  | 'EXPOSURE_ALIGNING'
  | 'COLOR_CORRECTING'
  | 'STYLE_APPLIED'
  | 'FINAL_QC'
  | 'ACCEPTED'
  | 'MANUAL_REVIEW'
  | 'REJECTED';

/**
 * Filmstrip 状态过滤词（UI 选项）→ PhotoState 集合的映射。
 * 过滤词是粗分组，与后端状态机枚举一一不对应，故按集合判断：
 * pending=未处理（含筛图完成）、processing=管线中、accepted=终态通过、
 * review=需人工处理（含拒绝终态）。'全部' 由调用方短路，不进表。
 */
export const STATUS_FILTER_SETS: Readonly<Record<string, ReadonlySet<PhotoState>>> = {
  pending: new Set<PhotoState>(['RAW_PENDING', 'SCREENED']),
  processing: new Set<PhotoState>([
    'BASE_RENDERED',
    'EXPOSURE_ALIGNING',
    'COLOR_CORRECTING',
    'STYLE_APPLIED',
    'FINAL_QC',
  ]),
  accepted: new Set<PhotoState>(['ACCEPTED']),
  review: new Set<PhotoState>(['MANUAL_REVIEW', 'REJECTED']),
};

/** GET /api/photos、GET /api/photos/{id} 的 photo 对象（runtime.photo_dict）。 */
export interface Photo {
  photo_id: string;
  path: string;
  metadata: Record<string, unknown>;
  created_at: string;
  sessions: string[];
  last_measurement: MeasurementReport | null;
  state: PhotoState;
  iteration: number;
  next_action: string | null;
}

/**
 * 前端本地视图扩展：Photo（后端形状）+ 仅前端 UI 概念（Lightroom 式
 * 星级/色标/场景标记）。后端不存这些字段，UI 读写走本地状态。
 */
export interface PhotoView extends Photo {
  /** 0-5 星用户标记。 */
  rating?: number;
  colorLabel?: ColorLabel;
  /** 旧版展示字段（mock/本地派生）。 */
  name?: string;
  takenAt?: string;
  status?: string;
  scene?: string;
  burstGroup?: string;
  thumbnail?: string;
}

/** POST /api/photos/{id}/sessions 的 session 对象（runtime.session_dict）。 */
export interface SessionInfo {
  session_id: string;
  photo_id: string | null;
  generation: number;
  raw_path: string;
}

/** GET /api/health（runtime.health）。 */
export interface HealthInfo {
  status: string;
  service: string;
  version: string;
  vision: Record<string, unknown>;
  /** t91：部位掩码路由能力。 */
  segmenter: { router: string; part_prompts: string[] };
  photos: number;
  sessions: number;
}

/** 导出任务状态（ExportManager._run 的 status 流转）。 */
export type ExportTaskStatus = 'pending' | 'running' | 'completed' | 'failed';

/** GET /api/exports/{task_id} 的 task 对象（ExportManager.status）。 */
export interface ExportTask {
  task_id: string;
  status: ExportTaskStatus;
  raw_path: string;
  fmt: string;
  quality: number | null;
  output_dir: string;
  output_path: string | null;
  error: string | null;
}

/** POST /api/sessions/{id}/exports 的受理响应（runtime.submit_export）。 */
export interface ExportSubmission {
  task_id: string;
  status: ExportTaskStatus;
}

/** PUT /api/sessions/{id}/params 响应（runtime.update_params）。 */
export interface ParamsUpdateResult {
  session_id: string;
  generation: number;
  params: SessionParams;
  canonical: SessionParams;
}

/** GET /api/sessions/{id}/measurements 响应（runtime.measure_session）。 */
export interface MeasurementsResult {
  session_id: string;
  photo_id?: string | null;
  generation: number;
  measurement: MeasurementReport | null;
  error?: string;
}

/** VisionMeasure.measure 报告（global + regions + 溯源版本）。 */
export interface MeasurementReport {
  global: Record<string, unknown>;
  regions: Record<string, Record<string, unknown>>;
  image_id?: string | null;
  render_version?: string;
  detection_version?: string;
  mask_version?: string;
}

/** GET|POST /api/photos/{id}/decide 响应（runtime.decide_photo）。 */
export interface DecideResult {
  photo_id: string;
  state: PhotoState;
  iteration: number;
  measurement: Record<string, unknown>;
  decision: Record<string, unknown>;
}

/** GET /api/photos/{id}/timeline 响应（runtime.timeline）。 */
export interface TimelineInfo {
  photo_id: string;
  state: PhotoState;
  iteration: number;
  events: Array<Record<string, unknown>>;
}

// ---------- 渲染参数 ----------

/** hsl 单个色段（render/core/hsl.py DEFAULT_BANDS；五字段必填带界）。 */
export interface HslBand {
  name: string;
  hue_center: number;
  width: number;
  hue_shift: number;
  saturation: number;
  luminance: number;
}

/**
 * 参数读取模型：stage -> param -> value。
 * 后端 params/canonical 是动态 dict（default_params + 用户覆盖），读取端保持宽松。
 */
export type SessionParams = Record<string, Record<string, unknown>>;

/**
 * 参数写入 patch：仅已知 stage 的联合类型，不开放索引签名。
 * 键名与各 stage param_schema 对齐（src/pixo/render/modules/*.py）。
 */
export interface ParamPatch {
  /** mode: "auto"|"off"|数值（数值 = EV 偏移，exposure stage 无独立 ev 键）。 */
  exposure?: { mode?: number | string };
  /** temp 单位 K（1000-50000），tint -150..150；缺省 as_shot。 */
  whitebalance?: { mode?: string; temp?: number; tint?: number };
  /** highlights/shadows/whites/blacks ∈ -1..1（0=no-op），contrast 0..1。 */
  tone?: {
    highlights?: number;
    shadows?: number;
    whites?: number;
    blacks?: number;
    contrast?: number;
  };
  colorcal?: { saturation?: number; vibrance?: number };
  clarity?: { enabled?: boolean; strength?: number };
  dehaze?: { enabled?: boolean; strength?: number };
  skin?: { enabled?: boolean; strength?: number };
  refine?: {
    sharpen?: number;
    chroma_denoise?: number;
    highlight_desat?: number;
  };
  /** bands 为 8 个色段 dict 的列表（后端 float_or_str 也接受 JSON 字符串）。 */
  hsl?: { enabled?: boolean; bands?: HslBand[]; smooth?: number };
  calibration?: {
    enabled?: boolean;
    shadow_tint?: number;
    red_hue?: number;
    red_sat?: number;
    green_hue?: number;
    green_sat?: number;
    blue_hue?: number;
    blue_sat?: number;
  };
  split_tone?: {
    enabled?: boolean;
    shadows_hue?: number;
    shadows_sat?: number;
    highlights_hue?: number;
    highlights_sat?: number;
    balance?: number;
    strength?: number;
  };
}

// ---------- 前端本地概念（暂无后端端点） ----------

export interface Project {
  id: string;
  name: string;
  createdAt: string;
  photoIds: string[];
}

/** 用户对照片的本地标记（星级/颜色），后端无此数据。 */
export interface PhotoMarks {
  rating?: number;
  colorLabel?: ColorLabel;
}

export interface StyleCardData {
  styleId: string;
  name: string;
  description: string;
  /** 胶片卡分组键（品牌/系列，t86）；缺省归入"其他"。 */
  family?: string;
  tags: Record<string, string[]>;
  colorFingerprint?: Record<string, unknown>;
  toneFingerprint?: Record<string, unknown>;
  recommendedAdjustments?: Record<string, unknown>;
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

/** 导出设置（SettingsPanel 编辑，localStorage 持久化）。 */
export interface ExportSettings {
  previewLongEdge: number;
  bitDepth: 8 | 16;
  format: string;
  quality: number;
  stripGps: boolean;
}
