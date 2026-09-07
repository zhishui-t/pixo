import { useEffect, useMemo, useState } from 'react';
import { Badge, Group, Paper, SegmentedControl, Text } from '@mantine/core';
import { SectionLabel } from './SectionLabel';
import { SliderParam } from './SliderParam';
import {
  REGION_SLIDER_DEFS,
  WARMING_AUTO_RETRY_MAX,
  WARMING_REASON,
  buildRegionPatch,
  maskStatusToUi,
  readRegionAdjustment,
  showManualRetry,
  signedPerceptualFromSlider,
  signedPerceptualToSlider,
  warmingRetryDelayMs,
} from './regionAdjust';
import { fetchRegionMaskStatus } from '../api';
import { useAppStore } from '../store/useAppStore';
import type { RegionMaskStatus } from '../types';

/**
 * RegionSection（R14, M1）—— 掩码驱动的区域调整控件节。
 *
 * 数据面：
 *  - 掩码状态来自 dev-2 状态 API（available + prompts + 原因；经 api 层
 *    适配位接入，端点以其实施为准）。不可用态 = 三滑杆禁用 + 提示文案
 *    （杜绝静默失效）；可用态 = prompt 胶囊选择 + 三滑杆。
 *  - 滑杆值经 oklchScale 同款 γ=1.6 感知均匀传递（13.1 惯例）：位置域
 *    0.5 = 0（不调整），中心附近分辨率最高；NumberInput/提交值恒为参数域
 *    原值（后端契约不做换算）。
 *  - patch 形态 {region_adjust:{regions:{prompt:{param:value}}}}（PUT
 *    深合并：仅提交被改动的 prompt/参数键）；回读含 decide 规则/卡建议
 *    写入的值（用户能看到规则做了什么）。
 */
export function RegionSection({
  params,
  onPatch,
}: {
  params: Record<string, Record<string, unknown>>;
  onPatch: (patch: Record<string, Record<string, unknown>>) => void;
}) {
  const [status, setStatus] = useState<RegionMaskStatus | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  // B1：掩码状态查询与照片/参数请求同源——用 store 的真实会话 id
  // （写死 demo-session 会让 404→mock 恒可用断链，真实语义到不了 UI）。
  const sessionId = useAppStore((s) => s.sessionId);
  // B1：显式错误态 + 重试（nonce 变化触发重新查询）。
  const [retryNonce, setRetryNonce] = useState(0);
  // R17：segmenter_warming 自动重查计数（0 起；封顶后转手动重试）。
  const [warmingAttempts, setWarmingAttempts] = useState(0);

  useEffect(() => {
    let alive = true;
    fetchRegionMaskStatus(sessionId)
      .then((s) => {
        if (!alive) return;
        setStatus(s);
        setSelected((cur) => cur ?? s.prompts[0] ?? null);
      })
      .catch(() => {
        if (alive) setStatus({ available: false, prompts: [], reason: 'fetch_failed' });
      });
    return () => {
      alive = false;
    };
  }, [sessionId, retryNonce]);

  // R17：warming 自动重查（锁死不闪断）——status 仍为 warming 且未封顶时，
  // 按固定间隔静默重查（仅 retryNonce 递增 → 复用既有查询 effect，不触碰
  // selected/徽标结构）；reason 变化或换会话即重置计数。封顶后停止自动，
  // 转手动重试按钮。
  useEffect(() => {
    if (status?.reason !== WARMING_REASON) return;
    const delay = warmingRetryDelayMs(warmingAttempts);
    if (delay === null) return;
    const timer = setTimeout(() => {
      setWarmingAttempts((n) => n + 1);
      setRetryNonce((n) => n + 1);
    }, delay);
    return () => clearTimeout(timer);
  }, [status?.reason, warmingAttempts]);

  // 计数与原因/会话解耦复位：离开 warming 或换会话即归零。
  useEffect(() => {
    if (status?.reason !== WARMING_REASON) setWarmingAttempts(0);
  }, [status?.reason, sessionId]);

  const ui = useMemo(
    () => maskStatusToUi(status ?? { available: false, prompts: [], reason: null }),
    [status],
  );
  const activePrompt =
    ui.enabled && selected && ui.prompts.includes(selected) ? selected : ui.prompts[0] ?? null;
  const current = activePrompt ? readRegionAdjustment(params, activePrompt) : null;

  return (
    <div data-testid="region-section">
      <div style={{ position: 'relative' }}>
        <SectionLabel>区域调整 · 掩码驱动</SectionLabel>
        <div style={{ position: 'absolute', top: -4, right: 0 }}>
          <Badge
            size="xs"
            variant="light"
            color={ui.enabled ? 'accent' : 'gray'}
            data-testid="region-mask-badge"
          >
            {ui.badgeText}
          </Badge>
        </div>
      </div>

      {!ui.enabled && (
        <Group gap={6} mb={4}>
          <Text size="xs" c="dimmed" data-testid="region-unavailable-hint">
            {ui.hint}
            {/* R17：warming 重查进度（每次重查才变化，全程文案恒定不闪断）。 */}
            {status?.reason === WARMING_REASON &&
              `（${warmingAttempts}/${WARMING_AUTO_RETRY_MAX}）`}
          </Text>
          {showManualRetry(status?.reason, warmingAttempts) && (
            <Text
              size="xs"
              c="accent"
              span
              style={{ cursor: 'pointer' }}
              onClick={() => setRetryNonce((n) => n + 1)}
              data-testid="region-retry"
            >
              重试
            </Text>
          )}
        </Group>
      )}

      {ui.enabled && activePrompt && current && (
        <>
          {ui.prompts.length > 1 ? (
            <SegmentedControl
              size="xs"
              fullWidth
              mb={6}
              data={ui.prompts}
              value={activePrompt}
              onChange={setSelected}
              data-testid="region-prompt-picker"
            />
          ) : (
            <Group gap={6} mb={6}>
              <Text size="xs" c="dimmed">
                区域
              </Text>
              <Badge size="xs" variant="light" color="accent">
                {activePrompt}
              </Badge>
            </Group>
          )}

          <Paper radius="sm" p="xs" withBorder style={{ opacity: ui.enabled ? 1 : 0.55 }}>
            {REGION_SLIDER_DEFS.map((def) => (
              <SliderParam
                key={def.key}
                label={def.label}
                stage="region_adjust"
                param={def.key}
                value={current[def.key] ?? 0}
                min={def.min}
                max={def.max}
                step={def.step}
                unit={def.unit}
                helper={def.helper}
                locked={!ui.enabled}
                toSlider={(v) => signedPerceptualToSlider(v, def.min, def.max)}
                fromSlider={(p) => signedPerceptualFromSlider(p, def.min, def.max)}
                buildPatch={(v) =>
                  buildRegionPatch(activePrompt, def.key, v) as unknown as Record<
                    string,
                    Record<string, unknown>
                  >
                }
                onPatch={onPatch}
                testId={`region-${def.key}`}
              />
            ))}
          </Paper>
        </>
      )}
    </div>
  );
}
