import { Badge, Group, NumberInput, Slider, Text } from '@mantine/core';
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
  onPatch,
}: SliderParamProps) {
  const update = (next: number) => {
    if (locked) return;
    const clamped = Math.max(min, Math.min(max, next));
    onPatch({ [stage]: { [param]: clamped } });
  };

  return (
    <div style={{ opacity: locked ? 0.55 : 1, marginBottom: 10 }}>
      <Group justify="space-between" mb={4}>
        <Group gap={6}>
          <Text size="xs">{label}</Text>
          {source !== 'user' && <Badge size="xs" variant="light" color="indigo">{source}</Badge>}
          {locked && <Badge size="xs" variant="light" color="red">🔒</Badge>}
        </Group>
        {unit && <Text size="xs" c="dimmed">{unit}</Text>}
      </Group>
      <Group gap="xs" align="center">
        <Slider
          style={{ flex: 1 }}
          value={value}
          min={min}
          max={max}
          step={step}
          disabled={locked}
          onChange={update}
          size="sm"
          label={(v) => v.toFixed(2)}
        />
        <NumberInput
          w={76}
          size="xs"
          value={value}
          min={min}
          max={max}
          step={step}
          disabled={locked}
          onChange={(v) => update(Number(v) || 0)}
          hideControls
        />
      </Group>
    </div>
  );
}
