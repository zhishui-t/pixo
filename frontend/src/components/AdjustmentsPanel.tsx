import { Accordion, Paper, Text, Badge } from '@mantine/core';
import { DESIGN_TOKENS } from '../theme/tokens';
import { SectionLabel } from './SectionLabel';
import { useAppStore } from '../store/useAppStore';
import { health } from '../api';
import { useEffect } from 'react';
import { SliderParam } from './SliderParam';
import type { HslBand, ParamPatch } from '../types';

const HISTOGRAM = [12, 28, 45, 62, 90, 120, 96, 70, 48, 32, 18, 10, 6];

const HSL_BAND_LABELS = ['红', '橙', '黄', '绿', '青', '蓝', '紫', '品红'];

/**
 * 后端 render/core/hsl.py DEFAULT_BANDS 的镜像：
 * hsl stage 只认 enabled/bands/smooth，bands 是 8 元素数组
 * （每段 {name,hue_center,width,hue_shift,saturation,luminance}，字段全部必填带界）。
 * 此常量作为 bands 未设置时的编辑起点，避免悬空键 patch。
 */
const DEFAULT_HSL_BANDS: HslBand[] = [
  { name: 'red', hue_center: 0, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
  { name: 'orange', hue_center: 30, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
  { name: 'yellow', hue_center: 60, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
  { name: 'green', hue_center: 120, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
  { name: 'aqua', hue_center: 180, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
  { name: 'blue', hue_center: 240, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
  { name: 'purple', hue_center: 270, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
  { name: 'magenta', hue_center: 300, width: 45, hue_shift: 0, saturation: 0, luminance: 0 },
];

/** 读取当前 bands（后端回读优先；形状不完整时回退 DEFAULT_HSL_BANDS）。 */
function readHslBands(params: ParamPatch): HslBand[] {
  const bands = params.hsl?.bands;
  const valid =
    Array.isArray(bands) &&
    bands.length === 8 &&
    bands.every(
      (b) =>
        typeof b === 'object' &&
        b !== null &&
        typeof b.hue_shift === 'number' &&
        typeof b.hue_center === 'number' &&
        typeof b.width === 'number' &&
        typeof b.saturation === 'number' &&
        typeof b.luminance === 'number',
    );
  return valid ? (bands as HslBand[]) : DEFAULT_HSL_BANDS;
}

export function AdjustmentsPanel() {
  const activeProjectId = useAppStore((s) => s.activeProjectId);
  const params = useAppStore((s) => s.paramsByProject[s.activeProjectId] ?? {});
  // t91：skin 掩码路由能力信号（后端 /api/health 的 segmenter 节）。
  const skinMaskReady = useAppStore((s) => s.skinMaskReady);
  const setSkinMaskReady = useAppStore((s) => s.setSkinMaskReady);
  useEffect(() => {
    let alive = true;
    health()
      .then((h) => {
        if (!alive) return;
        setSkinMaskReady(Boolean(h.backend && h.segmenter?.part_prompts?.includes('skin')));
      })
      .catch(() => alive && setSkinMaskReady(false));
    return () => {
      alive = false;
    };
  }, [setSkinMaskReady]);
  const patchProjectParam = useAppStore((s) => s.patchProjectParam);

  const value = (stage: keyof ParamPatch, param: string, fallback = 0): number => {
    const bucket = params[stage];
    if (bucket === undefined || typeof bucket !== 'object') return fallback;
    const v = (bucket as Record<string, unknown>)[param] ?? fallback;
    return typeof v === 'number' ? v : Number(v) || fallback;
  };

  const patch = (patchObj: Record<string, Record<string, unknown>>) => {
    patchProjectParam(activeProjectId, patchObj as ParamPatch, 'user');
  };

  return (
    <Paper radius="md" withBorder p="md" className="adjustments-panel">
      <Text fw={700} mb="sm">调整</Text>

      <Paper radius="md" p="xs" mb="sm" withBorder style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 64 }}>
        {HISTOGRAM.map((h, i) => (
          <div key={i} style={{ flex: 1, height: h, background: 'var(--mantine-color-indigo-4)', borderRadius: 1 }} />
        ))}
      </Paper>

      <Accordion
          multiple
          defaultValue={['basic', 'curve', 'hsl', 'calibration', 'detail', 'split']}
          className="adjustments-accordion"
          styles={{
            item: { backgroundColor: DESIGN_TOKENS.panel, borderWidth: 0 },
            control: { fontSize: 13, paddingInline: 10 },
            panel: { paddingInline: 6, paddingBottom: 10 },
          }}
        >
        <Accordion.Item value="basic">
          <Accordion.Control>基本</Accordion.Control>
          <Accordion.Panel>
            <SectionLabel>曝光 · 白平衡</SectionLabel>
            {/* exposure stage 无独立 ev 键：mode 即 EV 偏移（"auto"|"off"|数值），
                数值化辅助对非数值（如 'auto'）回退 0。 */}
            <SliderParam label="曝光" stage="exposure" param="mode" value={value('exposure', 'mode', 0)} min={-2.5} max={2.5} step={0.01} unit="EV" onPatch={patch} />
            {/* tone.highlights/shadows 后端域为 ±1.0（tone_map.py schema），非 ±100。 */}
            <SliderParam label="高光" stage="tone" param="highlights" value={value('tone', 'highlights', -0.2)} min={-1} max={1} step={0.01} onPatch={patch} />
            <SliderParam label="阴影" stage="tone" param="shadows" value={value('tone', 'shadows', 0.1)} min={-1} max={1} step={0.01} onPatch={patch} />
            <SliderParam label="色温" stage="whitebalance" param="temp" value={value('whitebalance', 'temp', 5200)} min={1000} max={50000} step={50} unit="K" onPatch={patch} />
            <SliderParam label="色调" stage="whitebalance" param="tint" value={value('whitebalance', 'tint', 0)} min={-150} max={150} step={1} onPatch={patch} />
            <SliderParam label="清晰度" stage="clarity" param="strength" value={value('clarity', 'strength', 0.1)} min={-1} max={1} step={0.01} onPatch={patch} />

            {/* t91：skin 掩码就绪时磨皮限定皮肤区域（精准磨皮）；hair 掩码为人像抠图预留通道。 */}
            <SliderParam label="皮肤磨皮" stage="skin" param="strength" value={value('skin', 'strength', 0.4)} min={0} max={1} step={0.01} onPatch={patch} />
            <Badge size="xs" variant="light" color={skinMaskReady ? 'accent' : 'gray'}>
              {skinMaskReady ? 'skin 掩码就绪 · 磨皮限定皮肤区' : 'skin 掩码未加载 · 全局磨皮回退'}
            </Badge>
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="curve">
          <Accordion.Control>曲线</Accordion.Control>
          <Accordion.Panel>
            <SectionLabel>曲线</SectionLabel>
            <Text size="xs" c="dimmed">曲线编辑器正在开发中，敬请期待</Text>
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="hsl">
          <Accordion.Control>HSL</Accordion.Control>
          <Accordion.Panel>
            <SectionLabel>HSL · 八通道色相</SectionLabel>
            {/* hsl.bands 是 8 元素数组：每个色段一个 hue_shift 滑杆，
                提交时构造完整 bands 数组 patch（只改对应段的 hue_shift）。 */}
            {readHslBands(params).map((band, idx) => (
              <SliderParam
                key={band.name}
                label={`${HSL_BAND_LABELS[idx]} 色相`}
                stage="hsl"
                param="hue_shift"
                value={band.hue_shift}
                min={-30}
                max={30}
                step={1}
                onPatch={patch}
                buildPatch={(v) => ({
                  hsl: {
                    bands: readHslBands(params).map((b, i) =>
                      i === idx ? { ...b, hue_shift: v } : b,
                    ),
                  },
                })}
              />
            ))}
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="calibration">
          <Accordion.Control>色彩校准</Accordion.Control>
          <Accordion.Panel>
            <SectionLabel>色彩校准 · 三轴 HSL</SectionLabel>
            <SliderParam label="红-色相" stage="calibration" param="red_hue" value={value('calibration', 'red_hue', 0)} min={-180} max={180} step={1} onPatch={patch} />
            <SliderParam label="红-饱和度" stage="calibration" param="red_sat" value={value('calibration', 'red_sat', 0)} min={-100} max={100} step={1} onPatch={patch} />
            <SliderParam label="绿-色相" stage="calibration" param="green_hue" value={value('calibration', 'green_hue', 0)} min={-180} max={180} step={1} onPatch={patch} />
            <SliderParam label="蓝-色相" stage="calibration" param="blue_hue" value={value('calibration', 'blue_hue', 0)} min={-180} max={180} step={1} onPatch={patch} />
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="detail">
          <Accordion.Control>细节</Accordion.Control>
          <Accordion.Panel>
            <SectionLabel>细节 · 锐化 / 降噪 / 去朦胧</SectionLabel>
            <SliderParam label="锐化" stage="refine" param="sharpen" value={value('refine', 'sharpen', 0.2)} min={0} max={1} step={0.01} onPatch={patch} />
            <SliderParam label="降噪" stage="refine" param="chroma_denoise" value={value('refine', 'chroma_denoise', 0.5)} min={0} max={5} step={0.1} onPatch={patch} />
            <SliderParam label="去朦胧" stage="dehaze" param="strength" value={value('dehaze', 'strength', 0)} min={0} max={1} step={0.01} onPatch={patch} />
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="split">
          <Accordion.Control>分离色调</Accordion.Control>
          <Accordion.Panel>
            <SectionLabel>分离色调 · 高光 / 阴影</SectionLabel>
            <SliderParam label="高光色相" stage="split_tone" param="highlights_hue" value={value('split_tone', 'highlights_hue', 0)} min={0} max={360} step={1} onPatch={patch} />
            <SliderParam label="高光饱和度" stage="split_tone" param="highlights_sat" value={value('split_tone', 'highlights_sat', 0)} min={0} max={100} step={1} onPatch={patch} />
            <SliderParam label="阴影色相" stage="split_tone" param="shadows_hue" value={value('split_tone', 'shadows_hue', 0)} min={0} max={360} step={1} onPatch={patch} />
            <SliderParam label="阴影饱和度" stage="split_tone" param="shadows_sat" value={value('split_tone', 'shadows_sat', 0)} min={0} max={100} step={1} onPatch={patch} />
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Paper>
  );
}
