import { useEffect, useState } from 'react';
import { Badge, Group, NumberInput, Slider, Text, Tooltip } from '@mantine/core';
import { DESIGN_TOKENS } from '../theme/tokens';
import type { ParamPatch, Source } from '../types';

interface SliderParamProps {
  label: string;
  stage: string;
  param: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit?: string;
  source?: Source;
  locked?: boolean;
  /** 双击滑杆区域时的重置目标（缺省 0）。 */
  defaultValue?: number;
  /**
   * 自定义 patch 构造（如 hsl.bands 需要整体数组替换时）；
   * 缺省为 {stage: {param: value}}。
   */
  buildPatch?: (value: number) => Record<string, Record<string, unknown>>;
  /** 通用滑杆：stage/param 是运行时字符串，patch 用宽松形状，由调用方收窄。 */
  onPatch: (patch: Record<string, Record<string, unknown>>) => void;
  /** 刻度档（t8 oklch 色度滑杆五档用）；hsv 模式不传 → 渲染与现版一致。 */
  marks?: Array<{ value: number; label?: React.ReactNode }>;
  /** 滑杆下一行 xs 灰字说明（oklch 量纲 helper）；不传不渲染。 */
  helper?: string;
  /** label 右侧 ⓘ tooltip（oklch 语义说明）；不传不渲染。 */
  info?: string;
  /** 轨道背景（oklch 色谱条）；不传保持现版纯灰轨。 */
  trackBackground?: string;
  /**
   * 非线性滑杆传递（oklch 色度滑杆 §4.4）：参数值⇄滑杆位置的纯函数对。
   * Mantine Slider 恒在线性「位置域」上运行，本组件在边界做换算；
   * 数字输入框/提交值始终是参数域原值（后端契约不做任何换算）。
   * **不传（缺省）走现版线性路径，渲染与提交逐位不变**（双轨零变化）。
   */
  toSlider?: (value: number) => number;
  fromSlider?: (pos: number) => number;
  /** 测试钩子（e2e data-testid，挂根节点）。 */
  testId?: string;
}

export function SliderParam({
  label,
  stage,
  param,
  value,
  min,
  max,
  step,
  unit,
  source = 'user',
  locked = false,
  defaultValue,
  buildPatch,
  onPatch,
  marks,
  helper,
  info,
  trackBackground,
  toSlider,
  fromSlider,
  testId,
}: SliderParamProps) {
  const [dragging, setDragging] = useState(false);
  // 防抖：拖动/输入期间只更新本地 state，onChangeEnd / onBlur / Enter 才提交 patch。
  const [pending, setPending] = useState<number | null>(null);
  // NumberInput 编辑中的原始文本（允许中间态如空串）。
  const [editing, setEditing] = useState<string | null>(null);
  const shown = pending ?? value;

  // 提交后保留 pending 显示，直到 store 回读的 value 追上（patch 是异步链路），
  // 避免提交瞬间滑杆回跳旧值。
  useEffect(() => {
    setPending((p) => (p !== null && p === value ? null : p));
  }, [value]);

  const commit = (next: number) => {
    if (locked) return;
    const clamped = Math.max(min, Math.min(max, next));
    onPatch(buildPatch ? buildPatch(clamped) : { [stage]: { [param]: clamped } });
  };

  // 非线性传递（§4.4）：滑杆跑在位置域，边界换算到参数域；
  // toVal 为空 = 现版线性路径，posToValue 恒等（渲染/提交逐位不变）。
  const posValue = toSlider ? toSlider(shown) : shown;
  const posToValue = (p: number): number => {
    if (!fromSlider) return p;
    const v = fromSlider(p);
    return Math.round(v / step) * step;
  };
  // 拖动 label：线性路径维持现版 toFixed(2)；非线性路径显示换算后的参数值。
  const dragLabel = fromSlider
    ? (p: number) => Number(posToValue(p).toFixed(2)).toString()
    : (v: number) => v.toFixed(2);

  const reset = () => {
    if (locked) return;
    setPending(null);
    setEditing(null);
    commit(defaultValue ?? 0);
  };

  const commitEditing = () => {
    if (editing === null) return;
    const text = editing;
    setEditing(null);
    const parsed = Number(text);
    if (text.trim() !== '' && Number.isFinite(parsed)) {
      setPending(parsed);
      commit(parsed);
    }
  };

  return (
    <div
      className={`slider-param${dragging ? ' slider-param--dragging' : ''}`}
      style={{ opacity: locked ? 0.55 : 1 }}
      onDoubleClick={reset}
      onPointerDown={() => setDragging(true)}
      onPointerUp={() => setDragging(false)}
      onPointerLeave={() => setDragging(false)}
      {...(testId ? { 'data-testid': testId } : {})}
    >
      <Group justify="space-between" mb={4}>
        <Group gap={6}>
          <Text size="xs" c={dragging ? undefined : 'dimmed'} fw={dragging ? 600 : 400}>
            {label}
          </Text>
          {/* oklch 语义 ⓘ（§4.2）；hsv 模式不传 info 不渲染。 */}
          {info && (
            <Tooltip label={info} multiline w={240} withArrow position="top-start">
              <Text size="xs" c="dimmed" span aria-label={`${label}说明`} style={{ cursor: 'help' }}>
                ⓘ
              </Text>
            </Tooltip>
          )}
          {source !== 'user' && (
            <Badge size="xs" variant="light" color="orange">
              {source}
            </Badge>
          )}
          {locked && (
            <Badge size="xs" variant="light" color="red">
              🔒
            </Badge>
          )}
        </Group>
        {unit && (
          <Text size="xs" c="dimmed" className="slider-param-unit">
            {unit}
          </Text>
        )}
      </Group>
      <Group gap="xs" align="center">
        <Slider
          className={`slider-param-track${trackBackground ? ' slider-param-track--spectrum' : ''}`}
          style={{ flex: 1, ...(trackBackground ? ({ '--slider-spectrum': trackBackground } as React.CSSProperties) : {}) }}
          value={posValue}
          min={min}
          max={max}
          step={step}
          disabled={locked}
          onChange={(p) => setPending(posToValue(p))}
          onChangeEnd={(p) => commit(posToValue(p))}
          size="sm"
          label={dragLabel}
          marks={marks?.map((m) => ({ ...m, value: toSlider ? toSlider(m.value) : m.value }))}
          styles={{
            track: {
              backgroundColor: 'rgba(255, 255, 255, 0.08)',
              ...(trackBackground ? { backgroundImage: trackBackground } : {}),
            },
            bar: { backgroundColor: trackBackground ? 'transparent' : DESIGN_TOKENS.accent },
            thumb: {
              backgroundColor: DESIGN_TOKENS.panel,
              borderColor: trackBackground ? DESIGN_TOKENS.textPrimary : DESIGN_TOKENS.accent,
              borderWidth: 2,
            },
            label: {
              backgroundColor: DESIGN_TOKENS.overlay,
              color: DESIGN_TOKENS.textPrimary,
              fontVariantNumeric: 'tabular-nums',
            },
          }}
        />
        <NumberInput
          className="slider-param-value"
          w={84}
          size="xs"
          value={editing ?? shown}
          min={min}
          max={max}
          step={step}
          disabled={locked}
          onChange={(v) => setEditing(typeof v === 'number' ? String(v) : v)}
          onBlur={commitEditing}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commitEditing();
          }}
          hideControls
          styles={{
            input: {
              fontVariantNumeric: 'tabular-nums',
              textAlign: 'right',
              backgroundColor: DESIGN_TOKENS.panel,
            },
          }}
        />
      </Group>
      {/* oklch 量纲 helper（§3.3/§4.2）；hsv 模式不传不渲染 → 双轨零变化。 */}
      {helper && (
        <Text size="xs" c="dimmed" mt={2}>
          {helper}
        </Text>
      )}
    </div>
  );
}
