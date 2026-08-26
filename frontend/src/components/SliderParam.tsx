import { useState } from 'react';
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
  onPatch: (patch: ParamPatch) => void;
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
  onPatch,
}: SliderParamProps) {
  const [dragging, setDragging] = useState(false);

  const update = (next: number) => {
    if (locked) return;
    const clamped = Math.max(min, Math.min(max, next));
    onPatch({ [stage]: { [param]: clamped } });
  };

  const reset = () => {
    if (locked) return;
    update(defaultValue ?? 0);
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
          value={value}
          min={min}
          max={max}
          step={step}
          disabled={locked}
          onChange={update}
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
          value={value}
          min={min}
          max={max}
          step={step}
          disabled={locked}
          onChange={(v) => update(Number(v) || 0)}
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
