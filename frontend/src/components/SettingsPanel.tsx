import { useState } from 'react';
import { Card, Checkbox, Group, NumberInput, Select, Stack, Text, Title } from '@mantine/core';
import { Boxes, Download, SlidersHorizontal } from 'lucide-react';
import { DESIGN_TOKENS as T } from '../theme/tokens';

const INITIAL = {
  previewLongEdge: 1024,
  bitDepth: 8,
  format: 'jpeg',
  quality: 88,
  stripGps: true,
};

export function SettingsPanel() {
  const [settings, setSettings] = useState(INITIAL);

  return (
    <Stack gap="xl">
      <Title order={3}>设置</Title>
      <Card radius="md" withBorder style={{ background: T.panel, borderColor: T.hairline }}>
        <Group gap={8} mb="sm">
          <SlidersHorizontal size={15} color={T.accent} />
          <Text fw={700} mb={0}>渲染</Text>
        </Group>
        <Group gap="md">
          <Select
            label="预览长边"
            value={String(settings.previewLongEdge)}
            onChange={(value) => setSettings({ ...settings, previewLongEdge: Number(value ?? 1024) })}
            data={['512', '1024', '2048'].map((v) => ({ value: v, label: v }))}
            w={160}
          />
          <Select
            label="输出位深"
            value={String(settings.bitDepth)}
            onChange={(value) => setSettings({ ...settings, bitDepth: Number(value ?? 8) })}
            data={[{ value: '8', label: '8-bit' }, { value: '16', label: '16-bit' }]}
            w={160}
          />
        </Group>
      </Card>
      <Card radius="md" withBorder style={{ background: T.panel, borderColor: T.hairline }}>
        <Group gap={8} mb="sm">
          <Download size={15} color={T.accent} />
          <Text fw={700} mb={0}>输出</Text>
        </Group>
        <Group gap="md">
          <Select
            label="格式"
            value={settings.format}
            onChange={(value) => setSettings({ ...settings, format: value ?? 'jpeg' })}
            data={['jpeg', 'webp', 'png16', 'tiff16'].map((v) => ({ value: v, label: v }))}
            w={160}
          />
          <NumberInput
            label="质量"
            value={settings.quality}
            min={1}
            max={100}
            onChange={(value) => setSettings({ ...settings, quality: Number(value) || 88 })}
            w={120}
          />
          <Checkbox
            mt="lg"
            label="导出时剥离 GPS"
            checked={settings.stripGps}
            onChange={(e) => setSettings({ ...settings, stripGps: e.currentTarget.checked })}
          />
        </Group>
      </Card>
      <Card radius="md" withBorder style={{ background: T.panel, borderColor: T.hairline }}>
        <Group gap={8} mb="sm">
          <Boxes size={15} color={T.accent} />
          <Text fw={700} mb={0}>DSH / 模型</Text>
        </Group>
        <Text size="sm" c="dimmed">DSH 服务与模型连接状态将在后续版本提供。</Text>
      </Card>
    </Stack>
  );
}
