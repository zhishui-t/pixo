/**
 * HslBandRow —— HSL 单带行（UI_OKLCH_SPEC §3.1/§3.3）。
 *
 * 折叠态：hsv 模式 = 现版「{色名} 色相」hue_shift 滑杆行（逐像素一致）；
 * oklch 模式 = 同密度行 + 带名 6px 参考色点（表 A 色板）+ ▸ 展开钮（唯一新增行内元素），
 * 标签按 §3.1 线框改为「{色名} 色相平移」。
 *
 * 展开态（仅 oklch，hsv 模式无展开能力——双轨原则）：一次只展开一个带
 * （手风琴，展开态由父面板持有）。5 滑杆全复用 SliderParam，量纲/文案照抄 §3.3/§8：
 * hue_shift UI 区间维持 ±30（用户肌肉记忆/防误触大偏移）；后端硬界 ±180
 * （core/hsl.py _HS_MIN/_HS_MAX）不放开 UI，仅此注释存档。
 * 色度滑杆接 §4.4 非线性传递（增强方向幂 γ=1.6，提交值仍是原始 saturation）；
 * 提交契约不变：buildBandFieldPatch 整体数组替换 + 当前域盖戳。
 */

import { Group, Text } from '@mantine/core';
import { SliderParam } from './SliderParam';
import { useAppStore } from '../store/useAppStore';
import type { ColorDomain, HslBand, ParamPatch } from '../types';
import { buildBandFieldPatch, readHslBands } from './hslBands';
import { BAND_META_BY_NAME, chromaSliderPosToValue, chromaValueToSliderPos, hsvRefText, type BandMeta } from '../theme/oklchScale';

interface HslBandRowProps {
  band: HslBand;
  domain: ColorDomain;
  expanded: boolean;
  onToggle: () => void;
}

export function HslBandRow({ band, domain, expanded, onToggle }: HslBandRowProps) {
  const activeProjectId = useAppStore((s) => s.activeProjectId);
  const params: ParamPatch = useAppStore((s) => s.paramsByProject[s.activeProjectId] ?? {});
  const patchProjectParam = useAppStore((s) => s.patchProjectParam);
  const meta: BandMeta | undefined = BAND_META_BY_NAME[band.name];
  const zh = meta?.zh ?? band.name;

  const patch = (patchObj: Record<string, Record<string, unknown>>) => {
    patchProjectParam(activeProjectId, patchObj as ParamPatch, 'user');
  };

  /** 单带字段提交：整体 bands 数组替换 + 当前域盖戳（§1.1-4）。 */
  const bandField = (
    field: 'hue_center' | 'width' | 'hue_shift' | 'saturation' | 'luminance',
    value: number,
  ) => buildBandFieldPatch(readHslBands(params, domain), domain, band.name, field, value);

  const isOklch = domain === 'oklch';

  return (
    <div data-testid={`band-row-${band.name}`}>
      <Group gap={4} wrap="nowrap" align="flex-start" style={{ flexGrow: 1 }}>
        {isOklch && (
          <>
            {/* 展开钮：24px 命中区；手风琴单开（§3.1）。 */}
            <Text
              component="button"
              type="button"
              size="xs"
              c="dimmed"
              onClick={onToggle}
              aria-expanded={expanded}
              aria-label={`${zh}带 ${expanded ? '收起' : '展开'}详细滑杆`}
              data-testid={`band-row-${band.name}-expand`}
              style={{
                width: 24,
                height: 24,
                flexShrink: 0,
                background: 'transparent',
                border: 0,
                cursor: 'pointer',
                lineHeight: '24px',
                padding: 0,
                textAlign: 'center',
              }}
            >
              {expanded ? '▾' : '▸'}
            </Text>
            {/* 带参考色点：6px（表 A 色板 hex），颜色+文字双通道（色盲安全）。 */}
            <span
              aria-hidden
              style={{
                width: 6,
                height: 6,
                borderRadius: 3,
                flexShrink: 0,
                marginTop: 5,
                background: meta?.swatch ?? 'transparent',
              }}
            />
          </>
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <SliderParam
            label={isOklch ? `${zh} 色相平移` : `${zh} 色相`}
            stage="hsl"
            param="hue_shift"
            value={band.hue_shift}
            min={-30}
            max={30}
            step={1}
            unit={isOklch ? '°' : undefined}
            onPatch={patch}
            buildPatch={(v) => bandField('hue_shift', v)}
          />
        </div>
      </Group>
      {isOklch && expanded && (
        <div style={{ paddingLeft: 28 }}>
          <SliderParam
            label="中心色相角"
            stage="hsl"
            param="hue_center"
            value={band.hue_center}
            min={0}
            max={360}
            step={1}
            unit="°"
            defaultValue={meta?.oklchCenter ?? band.hue_center}
            onPatch={patch}
            buildPatch={(v) => bandField('hue_center', v)}
            helper={hsvRefText(band.hue_center)}
            testId={`band-${band.name}-center`}
          />
          <SliderParam
            label="带宽角"
            stage="hsl"
            param="width"
            value={band.width}
            min={5}
            max={180}
            step={1}
            unit="°"
            defaultValue={45}
            onPatch={patch}
            buildPatch={(v) => bandField('width', v)}
            helper={`影响跨度 ±${Math.round(band.width)}°（余弦缓入出）`}
            testId={`band-${band.name}-width`}
          />
          <SliderParam
            label="色相平移"
            stage="hsl"
            param="hue_shift"
            value={band.hue_shift}
            min={-30}
            max={30}
            step={1}
            unit="°"
            onPatch={patch}
            buildPatch={(v) => bandField('hue_shift', v)}
            helper="绕 OKLCh 色相环平移，0/360 环绕连续"
          />
          <SliderParam
            label="色度 C"
            stage="hsl"
            param="saturation"
            value={band.saturation}
            min={-100}
            max={100}
            step={1}
            unit="%"
            onPatch={patch}
            buildPatch={(v) => bandField('saturation', v)}
            /* 非线性传递（§4.4）：增强方向幂映射——行程 3/4 处 ≈ +33（常用增强区）
               低值细调展开，右端 +100 极限保留；调低方向精确线性。参数域提交原值。 */
            toSlider={chromaValueToSliderPos}
            fromSlider={chromaSliderPosToValue}
            marks={[
              { value: -100 },
              { value: -50 },
              { value: 0, label: <Text size="9px" fw={700}>原色</Text> },
              { value: 50 },
              { value: 100 },
            ]}
            helper="C=染色强度。增强方向幂传递：行程中段≈+33 落常用区，细调区加宽；调低精确线性，趋近边界软限幅平滑收敛"
            info="照片常见色 C≈0.06–0.18；C<0.02 视为中性灰，自动保护不动。增强方向按 C 域幂曲线（γ=1.6）传递：行程中段≈+33（常用增强），右端保留 +100 极端；软限幅仅在增强方向生效，调低色度精确线性"
            testId={`band-${band.name}-chroma`}
          />
          <SliderParam
            label="明度 L"
            stage="hsl"
            param="luminance"
            value={band.luminance}
            min={-100}
            max={100}
            step={1}
            unit="%"
            onPatch={patch}
            buildPatch={(v) => bandField('luminance', v)}
            helper="感知亮度轴；50% 灰实测 L≈0.60，与旧 HSV 明度(V)不同"
          />
        </div>
      )}
    </div>
  );
}
