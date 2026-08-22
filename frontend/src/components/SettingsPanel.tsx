import { useState } from 'react';
import { Card, Checkbox, Group, NumberInput, Select, Stack, Text, Title } from '@mantine/core';

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
    <Stack gap="md">
      <Title order={3}>设置</Title>
      <Card radius="md" withBorder>
        <Text fw={700} mb="sm">渲染</Text>
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
      <Card radius="md" withBorder>
        <Text fw={700} mb="sm">输出</Text>
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
      <Card radius="md" withBorder>
        <Text fw={700} mb="sm">DSH / 模型</Text>
        <Text size="sm" c="dimmed">DSH 地址与 YOLOE 模型可用性状态为 P2 接入占位。</Text>
      </Card>
    </Stack>
  );
}
