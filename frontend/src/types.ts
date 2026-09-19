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

/** 直方图计数（R25 F02：BT.709 luma + RGB 三通道，256 桶 0-255 值域）。 */
export interface HistogramCounts {
  lum: number[];
  r: number[];
  g: number[];
  b: number[];
}

export interface HistogramData {
  bins: number;
  pixels: number;
  counts: HistogramCounts;
}

/** GET /api/sessions/{id}/histogram 响应（runtime.histogram_session）。 */
export interface HistogramResult {
  session_id: string;
  generation: number;
  histogram: HistogramData | null;
  error?: string;
}

/**
 * 区域掩码状态（R14，dev-2 状态 API 契约：available + prompts + 原因；
 * 端点以其实施为准——前端经 api 层适配位接入，本类型为唯一消费面）。
 */
export interface RegionMaskStatus {
  /** 掩码可用（true = 区域调整控件可操作）。 */
  available: boolean;
  /** 可调区域 prompt 列表（如 ['sky','face','plant']）。 */
  prompts: string[];
  /** 不可用原因（available=false 时的数据面，UI 转提示文案）。 */
  reason?: string | null;
}

/**
 * region_adjust 单区域调整（prompt → 滑杆值；后端 _regions 白名单校验：
 * exposure EV -2..2 / saturation -1..1 / warmth -1..1，缺省 0 = no-op）。
 */
export interface RegionAdjustment {
  /** 区域曝光补偿（EV）。 */
  exposure?: number;
  /** 区域饱和度缩放偏置。 */
  saturation?: number;
  /** 区域色温偏置（dev-2 warmth 批）。 */
  warmth?: number;
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

/**
 * 色彩编辑域（设计 §1.2 双轨开关）：hsv=旧内核（缺省，存量行为逐位不变）、
 * oklch=OKLCh 感知域。Stage 级参数（hsl/split_tone 的 color_domain），
 * 前端只 patch 不换算——两域角度不可互相换算（UI_OKLCH_SPEC §2.1）。
 */
export type ColorDomain = 'hsv' | 'oklch';

/** hsl 单个色段（render/core/hsl.py DEFAULT_BANDS；五字段必填带界）。 */
export interface HslBand {
  name: string;
  hue_center: number;
  width: number;
  hue_shift: number;
  saturation: number;
  luminance: number;
  /** band schema v2（设计 §2.2）：UI 提交时盖戳当前域；缺省后端按 Stage color_domain 归属。 */
  domain?: ColorDomain;
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
  /**
   * bands 为 8 个色段 dict 的列表（后端 float_or_str 也接受 JSON 字符串）；
   * null = 恢复该域默认带（modules/hsl.py _resolve_bands 对 None 回 DEFAULT_BANDS /
   * DEFAULT_BANDS_OKLCH）。color_domain 为编辑域开关（设计 §1.2）。
   */
  hsl?: { enabled?: boolean; bands?: HslBand[] | null; smooth?: number; color_domain?: ColorDomain };
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
    /** 编辑域开关（设计 §2.3）：hsl/split_tone 双域后端均已就绪（modules/split_tone.py 与 HslStage 同枚举分派），patch 经 PUT params 深合并生效；UI 保留规格 §5.3 的回读门控作兜底。 */
    color_domain?: ColorDomain;
  };
  /**
   * 区域调整（R14，M1）：prompt → 三滑杆值。PUT params 深合并语义——
   * 仅提交被改动的 prompt/参数键，其余区域与其余参数键后端原样保留；
   * 回读含 decide 规则/卡建议写入的值（用户可见规则做了什么）。
   */
  region_adjust?: { regions?: Record<string, RegionAdjustment> };
  /**
   * R22 F04 —— 风格卡注入控制键：服务层按 style_id 取
   * `configs/styles/films/<id>.json` 的 params 并深合并进会话参数
   * （不是 LUT；仓内 0 个 .cube）。未知 id → 400。
   */
  __style?: string;
  /**
   * R22 F05 —— 场景预设控制键：服务层经 apply_scene_preset 展开
   * `configs/styles/scenes.json` 的 6 个预设之一（纯 params 覆盖）。
   * 未知 id / 与 __style 同时提交 → 400。
   */
  __scene?: string;
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
  /** 自由标签（扁平数组——后端 films 卡 metadata.tags 无分组语义，t60 接线对齐）。 */
  tags: string[];
  /** 适用场景（metadata.scenes）。 */
  scenes?: string[];
  year?: number | null;
  colorFingerprint?: Record<string, unknown>;
  toneFingerprint?: Record<string, unknown>;
  recommendedAdjustments?: Record<string, unknown>;
}

/** 后端 films 卡 metadata 节（from_films_dir 已补齐缺省，family 必有落点）。 */
export interface FilmCardMetadata {
  family: string;
  label: string;
  tags: string[];
  scenes: string[];
  character: string;
  year?: number | null;
}

/** GET /api/styles 列表项（降载：style_id + metadata，不含 stages/params）。 */
export interface StyleSummary {
  style_id: string;
  metadata: FilmCardMetadata;
}

/** GET /api/styles/{id} 完整卡（渲染卡三键 + metadata）。 */
export interface StyleCardDetail extends StyleCardData {
  stages: string[];
  params: Record<string, Record<string, unknown>>;
  output: Record<string, unknown>;
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
