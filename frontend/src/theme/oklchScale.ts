/**
 * oklchScale —— OKLCh 编辑域的双刻度映射与谱色生成（UI_OKLCH_SPEC §2/§3.2/§5.2）。
 *
 * 全部映射数字冻结自 docs/UI_OKLCH_SPEC.md §2.2（2026-08-28 内核实测，
 * 复现脚本 .artifacts/ui_oklch_probe.py），禁止按"固定偏移"估算：
 * HSV 度→OKLCh 度偏移非均匀（+15°~+50°），唯一合法实现 = 锚点表 + 分段线性插值。
 * 插值结果**只用于显示**（helper 小字 / 环 tooltip），不参与提交数学。
 *
 * oklchToHex：Ottosson 2020 正向常数（与内核 src/pixo/render/core/oklab.py 同源），
 * 逆程用原文公布矩阵——仅作 CSS oklch() 不可用时的 UI 兜底色板，非逐位场景；
 * 8 带中心与 §5.2 两示例已与内核输出逐一对照（#df8073…#c683c5 / #e97c48 / #00b6d1）。
 */

import type { ColorDomain } from '../types';

/** 表 A · 8 带中心对照（DEFAULT_BANDS vs DEFAULT_BANDS_OKLCH，UI 显示名/参考色板）。 */
export interface BandMeta {
  name: string;
  zh: string;
  hsvCenter: number;
  oklchCenter: number;
  /** oklch(0.70 0.12 中心°) → sRGB，内核实测（表 A 色板列）。 */
  swatch: string;
}

export const BAND_TABLE_A: readonly BandMeta[] = [
  { name: 'red', zh: '红', hsvCenter: 0, oklchCenter: 29, swatch: '#df8073' },
  { name: 'orange', zh: '橙', hsvCenter: 30, oklchCenter: 55, swatch: '#d78951' },
  { name: 'yellow', zh: '黄', hsvCenter: 60, oklchCenter: 100, swatch: '#b0a03c' },
  { name: 'green', zh: '绿', hsvCenter: 120, oklchCenter: 145, swatch: '#6cb26f' },
  { name: 'aqua', zh: '青', hsvCenter: 180, oklchCenter: 195, swatch: '#00b5b5' },
  { name: 'blue', zh: '蓝', hsvCenter: 240, oklchCenter: 264, swatch: '#789de9' },
  { name: 'purple', zh: '紫', hsvCenter: 270, oklchCenter: 295, swatch: '#a48fe1' },
  { name: 'magenta', zh: '品红', hsvCenter: 300, oklchCenter: 327, swatch: '#c683c5' },
] as const;

/** band name → 表 A 行（O(1) 查显示名/中心/色板）。 */
export const BAND_META_BY_NAME: Readonly<Record<string, BandMeta>> = Object.fromEntries(
  BAND_TABLE_A.map((m) => [m.name, m]),
);

/**
 * 表 B · 正向锚点：HSV 纯色 (S=V=100%) → OKLCh 角（12 锚点，内核实测）。
 * 末锚点 HSV 330° 落 OKLCh 2.6°（环绕），解环绕后存 362.6 保单调。
 */
const HSV_TO_OKLCH_ANCHORS: ReadonlyArray<readonly [hsv: number, oklch: number]> = [
  [0, 29.2], [30, 52.8], [60, 109.8], [90, 135.9], [120, 142.5], [150, 151.1],
  [180, 194.8], [210, 256.2], [240, 264.1], [270, 293.8], [300, 328.4], [330, 362.6],
] as const;

/** 反查用解环绕单调序列的端点（§2.2：候选 {h, h+360} 落入 [29.2, 362.6]）。 */
const OKLCH_UNWRAP_LO = HSV_TO_OKLCH_ANCHORS[0][1];
const OKLCH_UNWRAP_HI = HSV_TO_OKLCH_ANCHORS[HSV_TO_OKLCH_ANCHORS.length - 1][1];

/**
 * oklch h → ≈旧 HSV 度（表 B 反查 + 分段线性 + 取整）。
 * 候选 {h, h+360} 取落在解环绕区间内者；都在区间外时钳到更近端点
 * （例：h=29 距首锚点 0.2° → ≈0°）。调用方显示时加「≈」前缀。
 */
export function hsvRefFromOklch(hDeg: number): number {
  const h = ((hDeg % 360) + 360) % 360;
  const candidates = [h, h + 360];
  let u: number;
  const inLo = candidates.filter((c) => c >= OKLCH_UNWRAP_LO && c <= OKLCH_UNWRAP_HI);
  if (inLo.length > 0) {
    u = inLo[0];
  } else {
    // 两候选都在区间外：钳到距端点更近者（§2.2 反查规则）
    const distLo = Math.abs(h - OKLCH_UNWRAP_LO);
    const distHi = Math.abs(OKLCH_UNWRAP_HI - (h + 360));
    u = distLo <= distHi ? OKLCH_UNWRAP_LO : OKLCH_UNWRAP_HI;
  }
  for (let i = 0; i < HSV_TO_OKLCH_ANCHORS.length - 1; i++) {
    const [h0, o0] = HSV_TO_OKLCH_ANCHORS[i];
    const [h1, o1] = HSV_TO_OKLCH_ANCHORS[i + 1];
    if (u <= o1) {
      const t = o1 === o0 ? 0 : (u - o0) / (o1 - o0);
      return Math.round(h0 + t * (h1 - h0));
    }
  }
  return HSV_TO_OKLCH_ANCHORS[HSV_TO_OKLCH_ANCHORS.length - 1][0];
}

/** ≈旧 HSV {x}°（参考）——helper/tooltip 统一拼装（显示专用，禁止回写参数）。 */
export function hsvRefText(oklchDeg: number): string {
  return `≈旧 HSV ${hsvRefFromOklch(oklchDeg)}°（参考）`;
}

/** 旧 HSV 度 → ≈OKLCh 度（表 B 正向插值；hsv 定义域 [0,330]，越界按端点钳制）。 */
export function oklchFromHsvRef(hsvDeg: number): number {
  const v = Math.max(0, Math.min(330, hsvDeg));
  for (let i = 0; i < HSV_TO_OKLCH_ANCHORS.length - 1; i++) {
    const [h0, o0] = HSV_TO_OKLCH_ANCHORS[i];
    const [h1, o1] = HSV_TO_OKLCH_ANCHORS[i + 1];
    if (v <= h1) {
      const t = h1 === h0 ? 0 : (v - h0) / (h1 - h0);
      return (o0 + t * (o1 - o0)) % 360;
    }
  }
  return HSV_TO_OKLCH_ANCHORS[HSV_TO_OKLCH_ANCHORS.length - 1][1] % 360;
}

/** 副刻度数据：表 B 12 锚点的 OKLCh 放置角 + 旧 HSV 读数（环内圈 / 谱条小尺共用）。 */
export const HSV_REF_TICKS: ReadonlyArray<readonly [oklchDeg: number, hsvDeg: number]> =
  HSV_TO_OKLCH_ANCHORS.map(([h, o]) => [o % 360, h] as const);

/**
 * 副刻度是否标数字：相邻锚点任一侧间距 <14° 时只画 tick（§2.3 拥挤规则；
 * 实测绿区 135.9/142.5/151.1 间距 6.6~8.6° 必然触发）。
 */
export function tickHasNumber(index: number): boolean {
  const n = HSV_TO_OKLCH_ANCHORS.length;
  const cur = HSV_TO_OKLCH_ANCHORS[index][1];
  const prev = HSV_TO_OKLCH_ANCHORS[(index + n - 1) % n][1];
  const next = HSV_TO_OKLCH_ANCHORS[(index + 1) % n][1];
  const gapPrev = (cur - prev + 360) % 360 || 360;
  const gapNext = (next - cur + 360) % 360 || 360;
  return gapPrev >= 14 && gapNext >= 14;
}

// ---------------------------------------------------------------------------
// OKLCh → sRGB hex（CSS oklch() 不可用时的兜底；正向常数 Ottosson 2020）
// ---------------------------------------------------------------------------

const C1 = 0.0031308;

function gammaEncode(c: number): number {
  const v = c <= C1 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
  return Math.max(0, Math.min(255, Math.round(v * 255)));
}

/** oklch(L, C, h°) → '#rrggbb'（h 环绕；负线性分量裁 0，同内核 oklab_to_srgb 语义）。 */
export function oklchToHex(L: number, C: number, hDeg: number): string {
  const hr = (hDeg * Math.PI) / 180;
  const a = C * Math.cos(hr);
  const b = C * Math.sin(hr);
  // Oklab → LMS'（cbrt 逆 = 立方）→ LMS → linear sRGB（Ottosson 公布常数）
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.291485548 * b;
  const l = l_ * l_ * l_;
  const m = m_ * m_ * m_;
  const s = s_ * s_ * s_;
  const r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
  const g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
  const bl = -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s;
  const cl = (x: number) => Math.max(0, x);
  return `#${[cl(r), cl(g), cl(bl)].map(gammaEncode).map((v) => v.toString(16).padStart(2, '0')).join('')}`;
}

/** 浏览器是否支持 CSS oklch()（§3.2 @supports 探测；SSR/老环境回 false 走 hex 兜底）。 */
export function supportsOklchCss(): boolean {
  return typeof CSS !== 'undefined' && typeof CSS.supports === 'function'
    && CSS.supports('color', 'oklch(50% 0.1 100)');
}

/** 谱环/谱条停靠色：oklch() 可用返回 CSS 渐变片段，否则预生成 hex（§3.2 兜底法）。 */
export function oklchStopColor(L: number, C: number, hDeg: number, oklchCss: boolean): string {
  return oklchCss ? `oklch(${L} ${C} ${hDeg})` : oklchToHex(L, C, hDeg);
}

/** OKLCh 谱停靠序列（step° 间隔，h 0..360-step），谱环/谱条渐变共用。 */
export function oklchSpectrumStops(L: number, C: number, step: number): Array<{ deg: number; pct: number }> {
  const stops: Array<{ deg: number; pct: number }> = [];
  for (let deg = 0; deg < 360; deg += step) {
    stops.push({ deg, pct: (deg / 360) * 100 });
  }
  return stops;
}

/** HSV 六段谱停靠（hsl(h 100% 50%)），分离色调 hsv 域备用（当前按双轨不渲染）。 */
export function hsvSpectrumCss(): string {
  const stops: string[] = [];
  for (let deg = 0; deg <= 360; deg += 15) {
    stops.push(`hsl(${deg} 100% 50%) ${((deg % 360) / 360) * 100}%`);
  }
  return `linear-gradient(to right, ${stops.join(', ')})`;
}

/** 域对应谱条 CSS 渐变（HueSpectrumBar 轨道；oklchCss=false 时自动 hex 兜底）。 */
export function spectrumGradient(domain: ColorDomain, oklchCss: boolean): string {
  if (domain === 'hsv') return hsvSpectrumCss();
  const stops = oklchSpectrumStops(0.7, 0.15, 15).map(
    ({ deg, pct }) => `${oklchStopColor(0.7, 0.15, deg, oklchCss)} ${pct}%`,
  );
  stops.push(`${oklchStopColor(0.7, 0.15, 0, oklchCss)} 100%`);
  return `linear-gradient(to right, ${stops.join(', ')})`;
}

/** 谱环 conic-gradient（HueRing；0° 在 12 点钟、顺时针 = CSS 零角，零换算）。 */
export function ringGradient(oklchCss: boolean): string {
  const stops = oklchSpectrumStops(0.7, 0.12, 10).map(
    ({ deg }) => `${oklchStopColor(0.7, 0.12, deg, oklchCss)} ${deg}deg`,
  );
  stops.push(`${oklchStopColor(0.7, 0.12, 0, oklchCss)} 360deg`);
  return `conic-gradient(${stops.join(', ')})`;
}

/** 分离色调染色色板：oklch 域 C 固定 0.15（§5.2），hsv 域纯色。 */
export function tintSwatchColor(domain: ColorDomain, hueDeg: number): string {
  return domain === 'oklch' ? oklchStopColor(0.7, 0.15, hueDeg, supportsOklchCss()) : `hsl(${hueDeg} 100% 50%)`;
}
