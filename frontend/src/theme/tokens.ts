/**
 * DESIGN_TOKENS —— 暗房主题设计令牌（t74 基座，后续 UI 任务的唯一取色来源）。
 * 表面语义：canvas=应用画布(最深)；panel=面板/卡片；overlay=浮层(下拉/弹窗/分段容器)。
 * accent=暖金主强调（摄影暗房质感，弃默认蓝）；hairline=全局发丝边框。
 * 后续任务引用方式：import { DESIGN_TOKENS } from '../theme/tokens';
 */
export const DESIGN_TOKENS = {
  colorScheme: 'dark',
  canvas: '#101214',
  canvasDeep: '#0b0d10',
  panel: '#17191c',
  overlay: '#1f2328',
  textPrimary: '#e8eaed',
  textSecondary: '#9aa0a6',
  textDisabled: '#6b7076',
  accent: '#e8a33d',
  accentHover: '#f0b45a',
  onAccent: '#101214',
  hairline: 'rgba(255, 255, 255, 0.06)',
  radius: '10px',
  shadowMd: '0 4px 16px rgba(0, 0, 0, 0.40)',
  shadowLg: '0 12px 32px rgba(0, 0, 0, 0.50)',
  selection: 'rgba(232, 163, 61, 0.32)',
  focusRing: 'rgba(232, 163, 61, 0.60)',
  scrollbarThumb: '#2a2f36',
  scrollbarThumbHover: '#3a4149',
  semantic: {
    success: '#57c785',
    warning: '#d99a2b',
    error: '#e0565b',
    info: '#58a6ff',
  },
} as const;

/** 复核警示语义色（t81）：与主按钮琥珀 accent=#e8a33d 刻意分离。 */
export const WARNING_COLOR = DESIGN_TOKENS.semantic.warning;

/**
 * Mantine dark 色阶覆写（索引语义）：
 *   0-3 文字灰阶（主→次）；4 边框/disabled 文本；
 *   5 浮层 overlay；6 面板 panel；7 body=画布 canvas；
 *   8-9 更深压边。供 createTheme({ colors: { dark: DARK_RAMP } }) 使用。
 */
export const DARK_RAMP: [string, string, string, string, string, string, string, string, string, string] = [
  DESIGN_TOKENS.textPrimary,
  '#cdd1d6',
  '#b4b9bf',
  DESIGN_TOKENS.textSecondary,
  DESIGN_TOKENS.textDisabled,
  DESIGN_TOKENS.overlay,
  DESIGN_TOKENS.panel,
  DESIGN_TOKENS.canvas,
  DESIGN_TOKENS.canvasDeep,
  '#07080a',
];

/** 暖金强调色 10 阶（index 5 = 基准 #e8a33d，配合 primaryShade 5）。 */
export const ACCENT_RAMP: [string, string, string, string, string, string, string, string, string, string] = [
  '#fbf1dd',
  '#f7e0ba',
  '#f2cd92',
  '#edbb6c',
  '#e9ae4e',
  '#e8a33d',
  '#c9882f',
  '#a56e26',
  '#7c521c',
  '#593a14',
];
