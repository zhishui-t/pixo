import { Accordion, Paper, Text } from '@mantine/core';
import { useAppStore } from '../store/useAppStore';
import { SliderParam } from './SliderParam';

const HISTOGRAM = [12, 28, 45, 62, 90, 120, 96, 70, 48, 32, 18, 10, 6];

export function AdjustmentsPanel() {
  const activeProjectId = useAppStore((s) => s.activeProjectId);
  const params = useAppStore((s) => s.paramsByProject[s.activeProjectId] ?? {});
  const patchProjectParam = useAppStore((s) => s.patchProjectParam);

  const value = (stage: string, param: string, fallback = 0): number => {
    const v = params[stage]?.[param] ?? fallback;
    return typeof v === 'number' ? v : Number(v) || fallback;
  };

  const patch = (patchObj: Record<string, Record<string, unknown>>) => {
    patchProjectParam(activeProjectId, patchObj, 'user');
  };

  return (
    <Paper radius="md" withBorder p="sm">
      <Text fw={700} mb="sm">调整</Text>

      <Paper radius="md" p="xs" mb="sm" withBorder style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 64 }}>
        {HISTOGRAM.map((h, i) => (
          <div key={i} style={{ flex: 1, height: h, background: 'var(--mantine-color-indigo-4)', borderRadius: 1 }} />
        ))}
      </Paper>

      <Accordion multiple defaultValue={['basic', 'curve', 'hsl', 'calibration', 'detail', 'split']}>
        <Accordion.Item value="basic">
          <Accordion.Control>基本</Accordion.Control>
          <Accordion.Panel>
            <SliderParam label="曝光" stage="exposure" param="ev" value={value('exposure', 'ev', 0.28)} min={-2.5} max={2.5} step={0.01} unit="EV" onPatch={patch} />
            <SliderParam label="高光" stage="tone" param="highlights" value={value('tone', 'highlights', -20)} min={-100} max={100} step={1} onPatch={patch} />
            <SliderParam label="阴影" stage="tone" param="shadows" value={value('tone', 'shadows', 10)} min={-100} max={100} step={1} onPatch={patch} />
            <SliderParam label="色温" stage="whitebalance" param="temp" value={value('whitebalance', 'temp', 5200)} min={1000} max={50000} step={50} unit="K" onPatch={patch} />
            <SliderParam label="色调" stage="whitebalance" param="tint" value={value('whitebalance', 'tint', 0)} min={-150} max={150} step={1} onPatch={patch} />
            <SliderParam label="清晰度" stage="clarity" param="strength" value={value('clarity', 'strength', 0.1)} min={-1} max={1} step={0.01} onPatch={patch} />
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="curve">
          <Accordion.Control>曲线</Accordion.Control>
          <Accordion.Panel>
            <Text size="xs" c="dimmed">RGB / R / G / B / 亮度 曲线编辑器占位</Text>
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="hsl">
          <Accordion.Control>HSL</Accordion.Control>
          <Accordion.Panel>
            {['红', '橙', '黄', '绿', '青', '蓝', '紫', '品红'].map((color, idx) => (
              <SliderParam
                key={color}
                label={`${color} 色相`}
                stage="hsl"
                param={`band${idx}`}
                value={0}
                min={-180}
                max={180}
                step={1}
                onPatch={patch}
              />
            ))}
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="calibration">
          <Accordion.Control>色彩校准</Accordion.Control>
          <Accordion.Panel>
            <SliderParam label="红-色相" stage="calibration" param="red_hue" value={0} min={-180} max={180} step={1} onPatch={patch} />
            <SliderParam label="红-饱和度" stage="calibration" param="red_sat" value={0} min={-100} max={100} step={1} onPatch={patch} />
            <SliderParam label="绿-色相" stage="calibration" param="green_hue" value={0} min={-180} max={180} step={1} onPatch={patch} />
            <SliderParam label="蓝-色相" stage="calibration" param="blue_hue" value={0} min={-180} max={180} step={1} onPatch={patch} />
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="detail">
          <Accordion.Control>细节</Accordion.Control>
          <Accordion.Panel>
            <SliderParam label="锐化" stage="refine" param="sharpen" value={value('refine', 'sharpen', 0.2)} min={0} max={1} step={0.01} onPatch={patch} />
            <SliderParam label="降噪" stage="refine" param="chroma_denoise" value={value('refine', 'chroma_denoise', 0.5)} min={0} max={5} step={0.1} onPatch={patch} />
            <SliderParam label="去朦胧" stage="dehaze" param="strength" value={0} min={0} max={1} step={0.01} onPatch={patch} />
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="split">
          <Accordion.Control>分离色调</Accordion.Control>
          <Accordion.Panel>
            <SliderParam label="高光色相" stage="split_tone" param="highlights_hue" value={0} min={0} max={360} step={1} onPatch={patch} />
            <SliderParam label="高光饱和度" stage="split_tone" param="highlights_sat" value={0} min={0} max={100} step={1} onPatch={patch} />
            <SliderParam label="阴影色相" stage="split_tone" param="shadows_hue" value={0} min={0} max={360} step={1} onPatch={patch} />
            <SliderParam label="阴影饱和度" stage="split_tone" param="shadows_sat" value={0} min={0} max={100} step={1} onPatch={patch} />
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Paper>
  );
}
