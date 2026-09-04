/**
 * hslBands —— hsl stage bands 的前端镜像与读取/校验/盖戳（UI_OKLCH_SPEC §7.2）。
 * DEFAULT_HSL_BANDS = 后端 render/core/hsl.py DEFAULT_BANDS 的镜像；
 * DEFAULT_HSL_BANDS_OKLCH = render/core/hsl_oklch.py DEFAULT_BANDS_OKLCH 的镜像
 * （表 A 中心 + domain:'oklch' 戳）。域读取端宽松：回读形状非法时按当前域回退。
 */

import type { ColorDomain, HslBand, ParamPatch } from '../types';
import { BAND_TABLE_A } from '../theme/oklchScale';

/** 8 带中文显示名（顺序即 band 数组顺序，后端 DEFAULT_BANDS 同序）。 */
export const HSL_BAND_LABELS = BAND_TABLE_A.map((m) => m.zh);

/** 旧 HSV 域默认带（后端 DEFAULT_BANDS 镜像；bands 未设置时的 hsv 编辑起点）。 */
export const DEFAULT_HSL_BANDS: HslBand[] = [
  { name: 'red', hue_center: 0, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
  { name: 'orange', hue_center: 30, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
  { name: 'yellow', hue_center: 60, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
  { name: 'green', hue_center: 120, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
  { name: 'aqua', hue_center: 180, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
  { name: 'blue', hue_center: 240, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
  { name: 'purple', hue_center: 270, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
  { name: 'magenta', hue_center: 300, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
];

/** OKLCh 域默认带（后端 DEFAULT_BANDS_OKLCH 镜像：表 A 中心 + domain:'oklch' 戳）。 */
export const DEFAULT_HSL_BANDS_OKLCH: HslBand[] = [
  { name: 'red', hue_center: 29, width: 45, hue_shift: 0, saturation: 0, luminance: 0, domain: 'oklch' },
  { name: 'orange', hue_center: 55, width: 45, hue_shift: 0, saturation: 0, luminance: 0, domain: 'oklch' },
  { name: 'yellow', hue_center: 100, width: 45, hue_shift: 0, saturation: 0, luminance: 0, domain: 'oklch' },
  { name: 'green', hue_center: 145, width: 45, hue_shift: 0, saturation: 0, luminance: 0, domain: 'oklch' },
  { name: 'aqua', hue_center: 195, width: 45, hue_shift: 0, saturation: 0, luminance: 0, domain: 'oklch' },
  { name: 'blue', hue_center: 264, width: 45, hue_shift: 0, saturation: 0, luminance: 0, domain: 'oklch' },
  { name: 'purple', hue_center: 295, width: 45, hue_shift: 0, saturation: 0, luminance: 0, domain: 'oklch' },
  { name: 'magenta', hue_center: 327, width: 45, hue_shift: 0, saturation: 0, luminance: 0, domain: 'oklch' },
];

/** 单一事实来源：Stage 级 color_domain（params.hsl），缺省/回读形状非法回 'hsv'。 */
export function readColorDomain(params: ParamPatch): ColorDomain {
  const d = params.hsl?.color_domain;
  return d === 'oklch' ? 'oklch' : 'hsv';
}

/** 当前域的默认带常量（回退/重置基准）。 */
export function defaultBandsFor(domain: ColorDomain): HslBand[] {
  return domain === 'oklch' ? DEFAULT_HSL_BANDS_OKLCH : DEFAULT_HSL_BANDS;
}

/** 读取当前 bands（后端回读优先；形状不完整时回退所在域的默认带镜像）。 */
export function readHslBands(params: ParamPatch, domain: ColorDomain = 'hsv'): HslBand[] {
  const bands = params.hsl?.bands;
  const valid =
    Array.isArray(bands) &&
    bands.length === 8 &&
    bands.every(
      (b) =>
        typeof b === 'object' &&
        b !== null &&
        typeof b.hue_shift === 'number' &&
        typeof b.hue_center === 'number' &&
        typeof b.width === 'number' &&
        typeof b.saturation === 'number' &&
        typeof b.luminance === 'number',
    );
  return valid ? (bands as HslBand[]) : defaultBandsFor(domain);
}

/**
 * bands 是否全默认（§6.3 切域弹窗触发条件）：
 * 任一 band 任一参数 ≠0，或 center ≠ 所在域默认中心 → 非默认。
 */
export function bandsAreDefault(bands: HslBand[], domain: ColorDomain): boolean {
  const defaults = defaultBandsFor(domain);
  if (bands.length !== defaults.length) return false;
  return bands.every((b) => {
    const d = defaults.find((x) => x.name === b.name);
    if (!d) return false;
    return (
      b.hue_center === d.hue_center &&
      b.width === d.width &&
      b.hue_shift === d.hue_shift &&
      b.saturation === d.saturation &&
      b.luminance === d.luminance
    );
  });
}

/**
 * 单带字段 patch（展开行 5 滑杆 / 环手柄共用）：整体数组替换，
 * 全部 band 盖戳当前域（§1.1-4），只改目标段的目标字段。
 */
export function buildBandFieldPatch(
  bands: HslBand[],
  domain: ColorDomain,
  bandName: string,
  field: keyof Pick<HslBand, 'hue_center' | 'width' | 'hue_shift' | 'saturation' | 'luminance'>,
  value: number,
): { hsl: { bands: HslBand[] } } {
  return {
    hsl: {
      bands: bands.map((b) =>
        b.name === bandName ? { ...b, domain, [field]: value } : { ...b, domain },
      ),
    },
  };
}
