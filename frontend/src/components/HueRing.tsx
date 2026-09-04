/**
 * HueRing —— OKLCh 色相环（UI_OKLCH_SPEC §3.2，P1：只读 + 点击选带 + 键盘调 center）。
 *
 * - 谱环：CSS conic-gradient（零角 12 点钟、顺时针 = CSS 零角，零换算），
 *   停靠每 10°、oklch(0.70 0.12 h)；@supports 不满足时回退 36 停靠内核同法 hex。
 * - 双刻度：主刻度每 30° 标数字（环外圈）；副刻度 = 表 B 12 锚点（环内圈，
 *   「旧 HSV 参考」，相邻 <14° 只画 tick、完整数值入 title）。
 * - 8 手柄：各 band hue_center 角、环带中线半径；P1 点击选中带（父面板联动展开），
 *   键盘 ←/→ ±1°、Shift ±10°、Home/End 回带默认 center（防抖提交，对齐 SliderParam 节律）。
 *   P2（环上拖拽）本版不实装。
 * - 折叠：默认折叠（§6.1），localStorage 记忆。
 */

import { useEffect, useRef, useState } from 'react';
import { Group, Text, Tooltip } from '@mantine/core';
import { DESIGN_TOKENS } from '../theme/tokens';
import type { ColorDomain, HslBand } from '../types';
import {
  BAND_META_BY_NAME,
  HSV_REF_TICKS,
  hsvRefFromOklch,
  ringGradient,
  supportsOklchCss,
  tickHasNumber,
} from '../theme/oklchScale';

const RING_SIZE = 204;          // 容器外径（含环外主刻度数字）
const BAND_OUTER = 88;          // 谱环外半径
const BAND_WIDTH = 28;          // 环带宽（§3.2）
const CENTER = RING_SIZE / 2;
const HANDLE_MID_R = BAND_OUTER - BAND_WIDTH / 2;   // 手柄半径（环带中线）
const MAIN_NUM_R = BAND_OUTER + 7;                  // 主刻度数字半径（环外）
const TICK_IN_R = 58;           // 副刻度线内端半径（内圈盘边）
const TICK_OUT_R = 52;          // 副刻度线外端半径
const SEC_NUM_R = 45;           // 副刻度数字半径

const COLLAPSE_KEY = 'pixo.hueRingCollapsed';

/** 极角 → 容器内 xy（0°=12 点钟、顺时针递增）。 */
function polar(r: number, deg: number): { x: number; y: number } {
  const rad = (deg * Math.PI) / 180;
  return { x: CENTER + r * Math.sin(rad), y: CENTER - r * Math.cos(rad) };
}

interface HueRingProps {
  bands: HslBand[];
  domain: ColorDomain;
  selected: string | null;
  onSelect: (name: string) => void;
  /** 键盘/复位改 center 的提交口（父面板走 buildBandFieldPatch 同款防抖）。 */
  onCenterCommit: (name: string, deg: number) => void;
}

export function HueRing({ bands, domain, selected, onSelect, onCenterCommit }: HueRingProps) {
  // §6.1：默认折叠；localStorage 记忆（显式展开过 = '0'）。
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) !== '0');
  // 键盘调角的本地 pending（防抖提交，避免连打键盘打爆 patch 通道）。
  const [pendingCenter, setPendingCenter] = useState<Record<string, number> | null>(null);
  const debounceRef = useRef<number | null>(null);

  const oklchCss = supportsOklchCss();

  useEffect(() => () => {
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
  }, []);

  if (domain !== 'oklch') return null;   // 双轨：hsv 模式整组件不渲染

  const toggleCollapsed = () => {
    setCollapsed((c) => {
      localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1');
      return !c;
    });
  };
  const centerOf = (band: HslBand): number =>
    pendingCenter && band.name in pendingCenter ? pendingCenter[band.name] : band.hue_center;

  const commitCenter = (name: string, deg: number) => {
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      setPendingCenter((p) => {
        const next = { ...(p ?? {}) };
        delete next[name];
        return Object.keys(next).length ? next : null;
      });
      onCenterCommit(name, ((deg % 360) + 360) % 360);
    }, 500);
  };

  const nudgeCenter = (band: HslBand, delta: number) => {
    const raw = centerOf(band) + delta;
    const deg = ((Math.round(raw) % 360) + 360) % 360;
    setPendingCenter((p) => ({ ...(p ?? {}), [band.name]: deg }));
    commitCenter(band.name, deg);
  };

  return (
    <div style={{ marginBottom: 8 }}>
      <Group justify="space-between" gap={4} mb={4}>
        <Text size="xs" c="dimmed">色相环</Text>
        <Text
          component="button"
          type="button"
          size="xs"
          c="dimmed"
          onClick={toggleCollapsed}
          aria-expanded={!collapsed}
          data-testid="hue-ring-toggle"
          style={{
            background: 'transparent', border: 0, cursor: 'pointer', padding: '0 4px',
          }}
        >
          {collapsed ? '展开 ▸' : '收起 ▾'}
        </Text>
      </Group>
      {!collapsed && (
        <>
          <div style={{ display: 'flex', justifyContent: 'center' }}>
            <div
              role="img"
              aria-label="OKLCh 色相环，内圈为旧 HSV 参考刻度"
              data-testid="hue-ring"
              style={{
                position: 'relative',
                width: RING_SIZE,
                height: RING_SIZE,
                flexShrink: 0,
              }}
            >
              {/* 谱环（conic 零角 = 12 点钟，零换算） */}
              <div
                aria-hidden
                style={{
                  position: 'absolute',
                  left: CENTER - BAND_OUTER,
                  top: CENTER - BAND_OUTER,
                  width: BAND_OUTER * 2,
                  height: BAND_OUTER * 2,
                  borderRadius: '50%',
                  background: ringGradient(oklchCss),
                }}
              />
              {/* 内圈盘（盖出环带） */}
              <div
                aria-hidden
                style={{
                  position: 'absolute',
                  left: CENTER - TICK_OUT_R - 2,
                  top: CENTER - TICK_OUT_R - 2,
                  width: (TICK_OUT_R + 2) * 2,
                  height: (TICK_OUT_R + 2) * 2,
                  borderRadius: '50%',
                  background: DESIGN_TOKENS.panel,
                  border: `1px solid ${DESIGN_TOKENS.hairline}`,
                }}
              />
              {/* 主刻度数字：every 30°（0…330），环外圈 */}
              {Array.from({ length: 12 }, (_, i) => i * 30).map((deg) => {
                const { x, y } = polar(MAIN_NUM_R, deg);
                return (
                  <Text
                    key={`main-${deg}`}
                    aria-hidden
                    span
                    size="9px"
                    c="dimmed"
                    style={{
                      position: 'absolute',
                      left: x,
                      top: y,
                      transform: 'translate(-50%, -50%)',
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    {deg}
                  </Text>
                );
              })}
              {/* 副刻度：表 B 12 锚点（内圈；相邻 <14° 只画 tick，完整值入 title） */}
              {HSV_REF_TICKS.map(([okDeg, hsvDeg], i) => {
                const a = polar(TICK_IN_R, okDeg);
                const b = polar(TICK_OUT_R, okDeg);
                const nm = polar(SEC_NUM_R, okDeg);
                const withNum = tickHasNumber(i);
                return (
                  <div
                    key={`sec-${i}`}
                    title={`旧 HSV ${hsvDeg}°（OKLCh ${okDeg}°）`}
                    style={{ position: 'absolute', inset: 0 }}
                  >
                    <svg
                      width={RING_SIZE}
                      height={RING_SIZE}
                      style={{ position: 'absolute', inset: 0 }}
                      aria-hidden
                    >
                      <line
                        x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                        stroke={DESIGN_TOKENS.textSecondary} strokeWidth={1}
                      />
                    </svg>
                    {withNum && (
                      <Text
                        aria-hidden
                        span
                        size="8px"
                        c="dimmed"
                        style={{
                          position: 'absolute', left: nm.x, top: nm.y,
                          transform: 'translate(-50%, -50%)',
                          fontVariantNumeric: 'tabular-nums',
                        }}
                      >
                        {hsvDeg}
                      </Text>
                    )}
                  </div>
                );
              })}
              {/* 环心读数：选中带 h={center}° + ≈旧 HSV 参考（§3.2） */}
              <div
                aria-hidden
                style={{
                  position: 'absolute', inset: 0, display: 'flex',
                  flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                  pointerEvents: 'none', maxWidth: SEC_NUM_R * 2 - 16,
                  margin: '0 auto',
                }}
              >
                {(() => {
                  const sel = bands.find((b) => b.name === selected) ?? bands[0];
                  if (!sel) return null;
                  const meta = BAND_META_BY_NAME[sel.name];
                  const c = centerOf(sel);
                  return (
                    <>
                      <Text size="10px" style={{ whiteSpace: 'nowrap' }}>
                        {meta?.zh ?? sel.name} h={Math.round(c)}°
                      </Text>
                      <Text size="8px" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                        ≈旧 HSV {hsvRefFromOklch(c)}°（参考）
                      </Text>
                    </>
                  );
                })()}
              </div>
              {/* 8 带手柄：点击选中带；键盘 ±1°/±10°、Home/End 回默认 */}
              {bands.map((band, idx) => {
                const meta = BAND_META_BY_NAME[band.name];
                const c = centerOf(band);
                const { x, y } = polar(HANDLE_MID_R, c);
                const isSel = band.name === selected;
                // 相邻手柄 <6° 时 tooltip 上下错位（§6.4 带重叠条目）。
                const neighbor = bands
                  .filter((b) => b.name !== band.name)
                  .map((b) => {
                    const d = Math.abs(b.hue_center - band.hue_center);
                    return Math.min(d, 360 - d);
                  })
                  .sort((p, q) => p - q)[0];
                const crowded = neighbor !== undefined && neighbor < 6;
                return (
                  <Tooltip
                    key={band.name}
                    label={`${meta?.zh ?? band.name} · OKLCh ${Math.round(c)}°（≈旧 HSV ${hsvRefFromOklch(c)}°）`}
                    withArrow
                    withinPortal
                    position={crowded ? (idx % 2 === 0 ? 'bottom' : 'top') : 'top'}
                  >
                    <div
                      role="slider"
                      tabIndex={0}
                      aria-label={`${meta?.zh ?? band.name}带中心`}
                      aria-valuemin={0}
                      aria-valuemax={360}
                      aria-valuenow={Math.round(c)}
                      aria-valuetext={`${meta?.zh ?? band.name}中心 OKLCh ${Math.round(c)}°（≈旧 HSV ${hsvRefFromOklch(c)}°）`}
                      data-testid={`hue-ring-handle-${band.name}`}
                      onClick={() => onSelect(band.name)}
                      onKeyDown={(e) => {
                        const step = e.shiftKey ? 10 : 1;
                        if (e.key === 'ArrowLeft') { e.preventDefault(); nudgeCenter(band, -step); }
                        else if (e.key === 'ArrowRight') { e.preventDefault(); nudgeCenter(band, step); }
                        else if (e.key === 'Home') { e.preventDefault(); nudgeCenter(band, (meta?.oklchCenter ?? 0) - c); }
                        else if (e.key === 'End') { e.preventDefault(); nudgeCenter(band, (meta?.oklchCenter ?? 0) - c); }
                      }}
                      style={{
                        position: 'absolute',
                        left: x,
                        top: y,
                        width: 24,
                        height: 24,
                        transform: 'translate(-50%, -50%)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        outline: 'none',
                      }}
                    >
                      <span
                        aria-hidden
                        style={{
                          width: 12,
                          height: 12,
                          borderRadius: 6,
                          background: DESIGN_TOKENS.panel,
                          border: `2px solid ${isSel ? DESIGN_TOKENS.focusRing : DESIGN_TOKENS.textPrimary}`,
                          boxShadow: isSel ? `0 0 0 2px ${DESIGN_TOKENS.focusRing}` : 'none',
                          display: 'block',
                        }}
                      />
                    </div>
                  </Tooltip>
                );
              })}
            </div>
          </div>
          <Text size="xs" c="dimmed" ta="center" mt={2}>
            内圈：旧 HSV 参考
          </Text>
        </>
      )}
    </div>
  );
}
