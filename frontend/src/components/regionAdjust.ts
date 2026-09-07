/**
 * regionAdjust —— region_adjust 面板的前端镜像与纯函数（R14, M1）。
 *
 * 职责（沿 hslBands.ts 纯模块先例，逻辑与 JSX 分离以便 node --test 直测）：
 *  - 滑杆域定义（exposure EV ±2 / saturation ±1 / warmth ±1，后端
 *    region_adjust._regions 白名单镜像，勿在此扩键）；
 *  - 感知均匀滑杆传递（oklchScale 同款 γ=1.6 幂函数的有符号推广，
 *    沿 13.1 惯例：中心 0 附近高分辨率，行程端点为满量纲）；
 *  - canonical 回读（params.region_adjust.regions[prompt]，含 decide
 *    规则/卡建议写入的值——数值化 + 白名单过滤 + 容错回退 0）；
 *  - patch 构造（{region_adjust:{regions:{prompt:{param:value}}}}，
 *    PUT params 深合并：仅提交被改动的 prompt/参数键）；
 *  - 掩码状态 → UI 渲染模型（可用 = 控件可操作；不可用 = 禁用 + 提示
 *    文案，杜绝静默失效）。
 */
import type { ParamPatch, RegionAdjustment, RegionMaskStatus, SessionParams } from '../types';

/**
 * 感知均匀指数 —— 同源值 = theme/oklchScale.ts C_SLIDER_GAMMA（oklch 色度
 * 滑杆 §4.4）。此处不直接 import（node --test 类型剥离要求显式 .ts 后缀，
 * 与 tsc bundler 解析互斥），相等性由 tests/regionSection.test.mjs 钉死
 * （单源漂移防护在测试层）。
 */
const PERCEPTUAL_GAMMA = 1.6;

/** region_adjust 三滑杆定义（后端 region_adjust._regions 白名单镜像）。 */
export const REGION_PARAM_KEYS = ['exposure', 'saturation', 'warmth'] as const;
export type RegionParamKey = (typeof REGION_PARAM_KEYS)[number];

export interface RegionSliderDef {
  key: RegionParamKey;
  label: string;
  min: number;
  max: number;
  step: number;
  unit?: string;
  helper: string;
}

export const REGION_SLIDER_DEFS: readonly RegionSliderDef[] = [
  { key: 'exposure', label: '区域曝光', min: -2, max: 2, step: 0.01, unit: 'EV', helper: '±2 EV，中心 0 = 不调整（感知均匀刻度）' },
  { key: 'saturation', label: '区域饱和', min: -1, max: 1, step: 0.01, helper: '±1，中心 0 = 不调整（感知均匀刻度）' },
  { key: 'warmth', label: '区域色温', min: -1, max: 1, step: 0.01, helper: '±1，负=偏冷 / 正=偏暖（感知均匀刻度）' },
];

// ---------------------------------------------------------------------------
// 感知均匀滑杆传递（oklchScale 同款 γ 幂函数的有符号推广）
// ---------------------------------------------------------------------------

/**
 * 参数值 → 滑杆位置 [0,1]。有符号量纲：位置 0.5 = 0（不调整），
 * 向两端按 |t|^γ 展开到 min/max —— 0 附近滑杆分辨率最高（小幅微调
 * 是区域调整主场景），端点为满量纲。γ 取 oklchScale 同款 C_SLIDER_GAMMA。
 */
export function signedPerceptualToSlider(value: number, min: number, max: number): number {
  const half = Math.max(Math.abs(min), Math.abs(max));
  if (half <= 0) return 0.5;
  const t = Math.max(-1, Math.min(1, value / half));
  // 指数取 1/γ（<1）：0 附近 |Δp| 随 |v| 增长更慢 → 中心（不调整档）分辨率最高
  return 0.5 + Math.sign(t) * Math.pow(Math.abs(t), 1 / PERCEPTUAL_GAMMA) * 0.5;
}

/** 滑杆位置 [0,1] → 参数值（signedPerceptualToSlider 的精确逆）。 */
export function signedPerceptualFromSlider(pos: number, min: number, max: number): number {
  const half = Math.max(Math.abs(min), Math.abs(max));
  const p = Math.max(0, Math.min(1, pos));
  const t = (p - 0.5) * 2;
  return Math.sign(t) * Math.pow(Math.abs(t), PERCEPTUAL_GAMMA) * half;
}

// ---------------------------------------------------------------------------
// canonical 回读（含 decide 规则 / 卡建议写入的值）
// ---------------------------------------------------------------------------

const isFiniteNumber = (v: unknown): v is number =>
  typeof v === 'number' && Number.isFinite(v);

/**
 * 读取某区域的当前调整值。数据面宽松：canonical 回读（含 decide 写入）、
 * mock、形状异常（非对象/未知键/非有限数值）一律容错——未知键丢弃、
 * 非法值回退 0（0 = no-op，与后端缺省语义一致）。
 */
export function readRegionAdjustment(params: SessionParams | ParamPatch, prompt: string): RegionAdjustment {
  const regions = (params as Record<string, unknown>).region_adjust as
    | { regions?: Record<string, unknown> }
    | undefined;
  const entry = regions?.regions?.[prompt];
  const out: RegionAdjustment = {};
  if (entry === null || typeof entry !== 'object') {
    return { exposure: 0, saturation: 0, warmth: 0 };
  }
  for (const key of REGION_PARAM_KEYS) {
    const v = (entry as Record<string, unknown>)[key];
    out[key] = isFiniteNumber(v) ? v : 0;
  }
  return out;
}

/**
 * 构造 region_adjust patch（PUT params 深合并形态）：仅携带被改动的
 * prompt/参数键，其余区域与其余参数键后端原样保留。
 * value 先钳制到该滑杆域（防越界值触发后端 _regions ValueError）。
 */
export function buildRegionPatch(
  prompt: string,
  param: RegionParamKey,
  value: number,
): ParamPatch {
  const def = REGION_SLIDER_DEFS.find((d) => d.key === param);
  const clamped = def
    ? Math.max(def.min, Math.min(def.max, value))
    : value;
  return {
    region_adjust: {
      regions: { [prompt]: { [param]: clamped } },
    },
  };
}

// ---------------------------------------------------------------------------
// 掩码状态 → UI 渲染模型（可用 / 不可用双态）
// ---------------------------------------------------------------------------

export interface RegionSectionUiModel {
  /** true = 区域调整可操作；false = 控件禁用 + 提示文案。 */
  enabled: boolean;
  /** 可选区域 prompt（enabled=false 时为空数组）。 */
  prompts: string[];
  /** 状态徽标文案（如 "掩码就绪 · 3 个区域" / "掩码不可用"）。 */
  badgeText: string;
  /** 提示文案（enabled=false 时展示，杜绝静默失效）。 */
  hint: string;
  /** 原因（状态 API 数据面直出，可能为空）。 */
  reason: string | null;
}

const DEFAULT_UNAVAILABLE_HINT = '运行分析后可用区域调整';

/** 容错归一状态 API 响应（端点以 dev-2 实施为准，形状漂移在此吸收）。 */
export function normalizeRegionMaskStatus(raw: unknown): RegionMaskStatus {
  if (raw === null || typeof raw !== 'object') {
    return { available: false, prompts: [], reason: '状态不可读' };
  }
  const obj = raw as Record<string, unknown>;
  const prompts = Array.isArray(obj.prompts)
    ? obj.prompts.filter((p): p is string => typeof p === 'string' && p.length > 0)
    : [];
  const available = obj.available === true && prompts.length > 0;
  const reason = typeof obj.reason === 'string' && obj.reason.length > 0 ? obj.reason : null;
  return { available, prompts, reason };
}

/**
 * 状态 API reason 机器码 → 中文提示（B1）：已知码给可行动文案；
 * 未知码回退通用文案 + 原因码透传（不吞诊断信息）。
 */
const REASON_TEXT: Readonly<Record<string, string>> = {
  masks_not_injected: DEFAULT_UNAVAILABLE_HINT,
  session_not_ready: '会话未建立：开始调整或运行分析后可用区域调整',
  session_not_found: '会话已失效：将随下次操作自动重建',
  fetch_failed: '区域状态获取失败，可点击重试',
  // R16 四分（runtime.py _region_status_of）：
  segmenter_warming: '模型加载中，稍候自动重试',   // 非阻塞预热/推理锁——前端定时重查
  segmenter_no_masks: '此图未检出可调区域',         // 分割成功但掩码全零——如实呈现
  segmenter_error: '分割服务异常，可点击重试',       // 分割异常降级——手动重试
};

// ---------------------------------------------------------------------------
// segmenter_warming 自动重试策略（R17）：纯函数便于 node --test 直测。
// 固定间隔无抖动（锁死不闪断——UI 文案全程恒定，静默后台重查）；封顶后
// 交还手动重试（避免无限轮询打后端）。
// ---------------------------------------------------------------------------

export const WARMING_REASON = 'segmenter_warming';
export const WARMING_AUTO_RETRY_MAX = 5;
export const WARMING_RETRY_DELAY_MS = 2000;

/**
 * warming 第 retryCount 次重查（0 起）的延时；≥MAX 返回 null（停止自动，
 * UI 转手动重试）。固定间隔、无指数退避——预热是秒级确定性过程，抖动
 * 只会拉长感知等待。
 */
export function warmingRetryDelayMs(retryCount: number): number | null {
  return retryCount < WARMING_AUTO_RETRY_MAX ? WARMING_RETRY_DELAY_MS : null;
}

/** 手动重试按钮可见性：warming 自动重试期间不显示（避免与自动重查打架），其余可手动。 */
export function showManualRetry(reason: string | null | undefined, warmingAttempts: number): boolean {
  if (reason === WARMING_REASON && warmingAttempts < WARMING_AUTO_RETRY_MAX) {
    return false;
  }
  return true;
}

/** reason 机器码 → 提示文案（已知码映射；未知码 = 通用文案 + 原因码）。 */
export function regionReasonText(reason: string | null | undefined): string {
  if (!reason) return DEFAULT_UNAVAILABLE_HINT;
  return REASON_TEXT[reason] ?? `${DEFAULT_UNAVAILABLE_HINT}（${reason}）`;
}

/** 状态 → UI 模型（组件渲染的唯一数据面；双态断言锚点）。 */
export function maskStatusToUi(status: RegionMaskStatus): RegionSectionUiModel {
  if (!status.available || status.prompts.length === 0) {
    return {
      enabled: false,
      prompts: [],
      badgeText: '区域掩码不可用',
      hint: regionReasonText(status.reason),
      reason: status.reason ?? null,
    };
  }
  return {
    enabled: true,
    prompts: [...status.prompts],
    badgeText: `掩码就绪 · ${status.prompts.length} 个区域`,
    hint: '调整仅作用于所选掩码区域（软边界过渡）',
    reason: null,
  };
}
