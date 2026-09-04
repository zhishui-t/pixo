import { useEffect, useRef, useState } from 'react';
import { Accordion, Paper, Text, Badge } from '@mantine/core';
import { DESIGN_TOKENS } from '../theme/tokens';
import { SectionLabel } from './SectionLabel';
import { useAppStore } from '../store/useAppStore';
import { health } from '../api';
import { SliderParam } from './SliderParam';
import { DomainToggle } from './DomainToggle';
import { HslBandRow } from './HslBandRow';
import { HueRing } from './HueRing';
import { HueSpectrumBar } from './HueSpectrumBar';
import type { ColorDomain, ParamPatch } from '../types';
import { buildBandFieldPatch, readColorDomain, readHslBands } from './hslBands';

const HISTOGRAM = [12, 28, 45, 62, 90, 120, 96, 70, 48, 32, 18, 10, 6];

/**
 * t8 色彩编辑域双轨（UI_OKLCH_SPEC）：hsl / split_tone 面板按
 * params.hsl.color_domain（缺省 'hsv'）分派——hsv 模式 = 现版 UI（控件集合/
 * 文案/量纲逐像素一致），oklch 专属控件（DomainToggle 之外的 HueRing、双刻度、
 * 色度文案、band 展开行、谱轨）一律条件渲染。切域只提交 color_domain 键，
 * bands 数值原样保留（往返无损）。
 */
export function AdjustmentsPanel() {
  const activeProjectId = useAppStore((s) => s.activeProjectId);
  const params = useAppStore((s) => s.paramsByProject[s.activeProjectId] ?? {});
  // t91：skin 掩码路由能力信号（后端 /api/health 的 segmenter 节）。
  const skinMaskReady = useAppStore((s) => s.skinMaskReady);
  const setSkinMaskReady = useAppStore((s) => s.setSkinMaskReady);
  // t8：split_tone OKLCh 域能力（§5.3 门控，null=未探测）。
  const splitToneDomainReady = useAppStore((s) => s.splitToneDomainReady);
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

  // oklch 带展开手风琴（一次一个）；hsv 模式恒 null（无展开能力）。
  const [expandedBand, setExpandedBand] = useState<string | null>(null);
  const bandRowRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const value = (stage: keyof ParamPatch, param: string, fallback = 0): number => {
    const bucket = params[stage];
    if (bucket === undefined || typeof bucket !== 'object') return fallback;
    const v = (bucket as Record<string, unknown>)[param] ?? fallback;
    return typeof v === 'number' ? v : Number(v) || fallback;
  };

  const patch = (patchObj: Record<string, Record<string, unknown>>) => {
    patchProjectParam(activeProjectId, patchObj as ParamPatch, 'user');
  };

  const domain: ColorDomain = readColorDomain(params);
  const isOklch = domain === 'oklch';
  // §5.3 门控：探测为 false 时分离色调面板退回 hsv 标注形态（HSL 面板不受影响）。
  const splitEffective: ColorDomain =
    domain === 'oklch' && splitToneDomainReady === false ? 'hsv' : domain;
  const splitIsOklch = splitEffective === 'oklch';
  const hslBands = readHslBands(params, domain);

  const selectBandFromRing = (name: string) => {
    setExpandedBand(name);
    // 联动展开对应 band row 并滚动定位（§3.2 P1 交互）。
    requestAnimationFrame(() => {
      bandRowRefs.current[name]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
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
            {/* 域开关与 SectionLabel 同行（§1.2）。开关绝对定位不占流高——
                hsv 模式行高与现版一致（双轨零变化）；oklch 长标签让出右侧。 */}
            <div style={{ position: 'relative' }}>
              <div style={isOklch ? { paddingRight: 112 } : undefined}>
                <SectionLabel>{isOklch ? 'HSL · 八通道色相（OKLCh 感知域）' : 'HSL · 八通道色相'}</SectionLabel>
              </div>
              <div style={{ position: 'absolute', top: -6, right: 0 }}>
                <DomainToggle />
              </div>
            </div>
            {/* hsl.bands 是 8 元素数组：hsv 模式每色段一个 hue_shift 滑杆（现版形态）；
                oklch 模式经 HslBandRow 支持 ▸ 展开 5 滑杆量纲 + HueRing 双刻度选带。 */}
            {isOklch && (
              <HueRing
                bands={hslBands}
                domain={domain}
                selected={expandedBand}
                onSelect={selectBandFromRing}
                onCenterCommit={(name, deg) => {
                  patch(buildBandFieldPatch(hslBands, domain, name, 'hue_center', deg));
                }}
              />
            )}
            {hslBands.map((band) => (
              <div
                key={band.name}
                ref={(el) => {
                  bandRowRefs.current[band.name] = el;
                }}
              >
                <HslBandRow
                  band={band}
                  domain={domain}
                  expanded={isOklch && expandedBand === band.name}
                  onToggle={() => setExpandedBand((cur) => (cur === band.name ? null : band.name))}
                />
              </div>
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
            <div style={{ position: 'relative' }}>
              <div style={splitIsOklch ? { paddingRight: 112 } : undefined}>
                <SectionLabel>
                  {splitIsOklch ? '分离色调 · 高光 / 阴影（OKLCh 感知域）' : '分离色调 · 高光 / 阴影'}
                </SectionLabel>
              </div>
              <div style={{ position: 'absolute', top: -6, right: 0 }}>
                <DomainToggle />
              </div>
            </div>
            {/* §5.3 门控兜底：hsl/split_tone 双域后端均已就绪，正常链路探测为 true；
                仅当回读异常（如后端校验收紧剥除未知键，canonical.split_tone 缺
                color_domain 键）时，该面板退回 hsv 标注形态并挂灰 Badge；HSL 面板不受影响。 */}
            {domain === 'oklch' && splitToneDomainReady === false && (
              <Badge size="xs" variant="light" color="gray" mb={4} data-testid="split-domain-gate">
                分离色调 OKLCh 域待后端支持，暂按 HSV 语义
              </Badge>
            )}
            {splitIsOklch ? (
              <>
                <HueSpectrumBar
                  zoneZh="高光"
                  hueValue={value('split_tone', 'highlights_hue', 0)}
                  onPatch={patch}
                  buildPatch={(v) => ({ split_tone: { highlights_hue: v } })}
                  testId="split-hue-highlights"
                />
                <SliderParam label="高光色度 C" stage="split_tone" param="highlights_sat" value={value('split_tone', 'highlights_sat', 0)} min={0} max={100} step={1} unit="%" onPatch={patch} />
                <HueSpectrumBar
                  zoneZh="阴影"
                  hueValue={value('split_tone', 'shadows_hue', 0)}
                  onPatch={patch}
                  buildPatch={(v) => ({ split_tone: { shadows_hue: v } })}
                  testId="split-hue-shadows"
                />
                <SliderParam label="阴影色度 C" stage="split_tone" param="shadows_sat" value={value('split_tone', 'shadows_sat', 0)} min={0} max={100} step={1} unit="%" onPatch={patch} />
              </>
            ) : (
              <>
                <SliderParam label="高光色相" stage="split_tone" param="highlights_hue" value={value('split_tone', 'highlights_hue', 0)} min={0} max={360} step={1} onPatch={patch} />
                <SliderParam label="高光饱和度" stage="split_tone" param="highlights_sat" value={value('split_tone', 'highlights_sat', 0)} min={0} max={100} step={1} onPatch={patch} />
                <SliderParam label="阴影色相" stage="split_tone" param="shadows_hue" value={value('split_tone', 'shadows_hue', 0)} min={0} max={360} step={1} onPatch={patch} />
                <SliderParam label="阴影饱和度" stage="split_tone" param="shadows_sat" value={value('split_tone', 'shadows_sat', 0)} min={0} max={100} step={1} onPatch={patch} />
              </>
            )}
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Paper>
  );
}
