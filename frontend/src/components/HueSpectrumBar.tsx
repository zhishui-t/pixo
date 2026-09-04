/**
 * HueSpectrumBar —— 分离色调 hue 拾色行（UI_OKLCH_SPEC §5.2，仅 oklch 模式渲染；
 * hsv 模式由父面板渲染现版纯灰轨滑杆行，双轨零变化）。
 *
 * - 行首 20×20 染色色板（圆角 4px hairline 描边，装饰性 aria-hidden，值在滑杆）。
 * - 谱轨：linear-gradient 停靠每 15°、oklch(0.70 0.15 h)；无 CSS oklch 支持时
 *   回退内核同法预生成 hex（§3.2 兜底法同源）。
 * - 轨道下方双刻度小尺（12px）：主刻度 0/90/180/270/360 标数字；副刻度 = 表 B
 *   锚点细 tick（旧 HSV 参考，title 出完整值，拥挤规则同 §2.3）。
 * - helper：≈旧 HSV {x}°（参考）。色板 tooltip：{区名}染色 · OKLCh h={n}° C≈0.15（≈旧 HSV {x}°）。
 */

import { Group, Text, Tooltip } from '@mantine/core';
import { SliderParam } from './SliderParam';
import type { ParamPatch } from '../types';
import {
  HSV_REF_TICKS,
  hsvRefFromOklch,
  spectrumGradient,
  supportsOklchCss,
  tickHasNumber,
  tintSwatchColor,
} from '../theme/oklchScale';
import { DESIGN_TOKENS } from '../theme/tokens';

interface HueSpectrumBarProps {
  /** 区名（高光/阴影），用于 label 与 tooltip。 */
  zoneZh: string;
  hueValue: number;
  onPatch: (patch: Record<string, Record<string, unknown>>) => void;
  buildPatch: (v: number) => Record<string, Record<string, unknown>>;
  testId: string;
}

export function HueSpectrumBar({ zoneZh, hueValue, onPatch, buildPatch, testId }: HueSpectrumBarProps) {
  const oklchCss = supportsOklchCss();
  const swatch = tintSwatchColor('oklch', hueValue);

  return (
    <div data-testid={testId}>
      <Group gap={6} wrap="nowrap" align="flex-end">
        <Tooltip
          label={`${zoneZh}染色 · OKLCh h=${Math.round(hueValue)}° C≈0.15（≈旧 HSV ${hsvRefFromOklch(hueValue)}°）`}
          withArrow
          withinPortal
        >
          <span
            aria-hidden
            style={{
              width: 20,
              height: 20,
              borderRadius: 4,
              flexShrink: 0,
              marginBottom: 8,
              background: swatch,
              border: `1px solid ${DESIGN_TOKENS.hairline}`,
              cursor: 'help',
            }}
          />
        </Tooltip>
        <div style={{ flex: 1, minWidth: 0 }}>
          <SliderParam
            label={`${zoneZh}色相`}
            stage="split_tone"
            param={testId === 'split-hue-highlights' ? 'highlights_hue' : 'shadows_hue'}
            value={hueValue}
            min={0}
            max={360}
            step={1}
            unit="°"
            onPatch={onPatch}
            buildPatch={buildPatch}
            trackBackground={spectrumGradient('oklch', oklchCss)}
            helper={`≈旧 HSV ${hsvRefFromOklch(hueValue)}°（参考）`}
          />
          {/* 双刻度小尺：主 0/90/180/270/360 标数字；副 = 表 B 锚点 tick
              （旧 HSV 参考，title 出完整值）；图例右对齐独立行（§5.2）。 */}
          <div aria-hidden style={{ position: 'relative', height: 22, marginInline: 4 }}>
            {HSV_REF_TICKS.map(([okDeg, hsvDeg], i) => (
              <div
                key={`sec-${i}`}
                title={`旧 HSV ${hsvDeg}°（OKLCh ${okDeg}°）`}
                style={{
                  position: 'absolute',
                  left: `${(okDeg / 360) * 100}%`,
                  top: 0,
                  width: 1,
                  height: tickHasNumber(i) ? 5 : 3,
                  background: DESIGN_TOKENS.textSecondary,
                }}
              />
            ))}
            {[0, 90, 180, 270].map((deg) => (
              <Text
                key={`main-${deg}`}
                span
                size="8px"
                c="dimmed"
                style={{
                  position: 'absolute',
                  left: `${(deg / 360) * 100}%`,
                  top: 5,
                  transform: 'translateX(-50%)',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {deg}
              </Text>
            ))}
            <Text
              span
              size="8px"
              c="dimmed"
              style={{ position: 'absolute', right: 0, top: 5, fontVariantNumeric: 'tabular-nums' }}
            >
              360
            </Text>
            <Text
              size="8px"
              c="dimmed"
              style={{ position: 'absolute', right: 0, top: 14 }}
            >
              副刻度：旧 HSV 参考
            </Text>
          </div>
        </div>
      </Group>
    </div>
  );
}
