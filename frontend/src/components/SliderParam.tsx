import { useEffect, useState } from 'react';
import { Badge, Group, NumberInput, Slider, Text } from '@mantine/core';
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
    >
      <Group justify="space-between" mb={4}>
        <Group gap={6}>
          <Text size="xs" c={dragging ? undefined : 'dimmed'} fw={dragging ? 600 : 400}>
            {label}
          </Text>
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
          className="slider-param-track"
          style={{ flex: 1 }}
          value={shown}
          min={min}
          max={max}
          step={step}
          disabled={locked}
          onChange={(v) => setPending(v)}
          onChangeEnd={(v) => commit(v)}
          size="sm"
          label={(v) => v.toFixed(2)}
          styles={{
            track: { backgroundColor: 'rgba(255, 255, 255, 0.08)' },
            bar: { backgroundColor: DESIGN_TOKENS.accent },
            thumb: {
              backgroundColor: DESIGN_TOKENS.panel,
              borderColor: DESIGN_TOKENS.accent,
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
    </div>
  );
}
