/**
 * DomainToggle —— 色彩编辑域开关（UI_OKLCH_SPEC §1.2/§6.3，两面板共用）。
 *
 * - 数据源：params.hsl.color_domain ?? 'hsv'（单一事实来源，随项目参数各自记忆）。
 * - 异步往返期间沿用 SliderParam 的 pending 模式：提交后保留本地值直到回读追上，
 *   防开关回跳。
 * - 切域同时提交 hsl + split_tone 的 color_domain（两 stage 双域后端均已就绪，
 *   patch 经 PUT params 深合并生效；回读门控兜底见 AdjustmentsPanel / store 探测）。
 * - bands 非全默认时弹确认 Modal（§6.3）：切域是语义切换而非数值换算。
 * - 切换后向容器发 aria-live polite 通告（§8 文案）。
 */

import { useEffect, useState } from 'react';
import { Button, Group, Modal, SegmentedControl, Text } from '@mantine/core';
import { useAppStore } from '../store/useAppStore';
import type { ColorDomain } from '../types';
import { bandsAreDefault, readColorDomain, readHslBands } from './hslBands';

const DOMAIN_ITEMS = [
  { value: 'hsv', label: 'HSV' },
  { value: 'oklch', label: 'OKLCh' },
] as const;

/** 切域 aria 通告（§8：唯一出处照抄）。 */
function announceText(target: ColorDomain): string {
  return target === 'oklch'
    ? '已切换到 OKLCh 感知域：色相角度与 HSV 不同，各滑杆旁为参考读数'
    : '已切换到 HSV 域：界面恢复旧版量纲';
}

export function DomainToggle() {
  const activeProjectId = useAppStore((s) => s.activeProjectId);
  const params = useAppStore((s) => s.paramsByProject[s.activeProjectId] ?? {});
  const patchProjectParam = useAppStore((s) => s.patchProjectParam);

  const current = readColorDomain(params);
  // pending 显示模式：提交后保留本地值，直到 store 回读追上（防回跳）。
  const [pending, setPending] = useState<ColorDomain | null>(null);
  useEffect(() => {
    setPending((p) => (p !== null && p === current ? null : p));
  }, [current]);

  // §6.3 确认弹窗：目标域 + 是否「恢复该域默认带」由弹窗按钮决定。
  const [modalTarget, setModalTarget] = useState<ColorDomain | null>(null);
  const [announcement, setAnnouncement] = useState('');

  const shown = pending ?? current;
  const bands = readHslBands(params, current);
  const needsConfirm = !bandsAreDefault(bands, current);

  const apply = (target: ColorDomain, resetBands: boolean) => {
    setPending(target);
    setAnnouncement(announceText(target));
    patchProjectParam(
      activeProjectId,
      {
        hsl: { color_domain: target, ...(resetBands ? { bands: null } : {}) },
        split_tone: { color_domain: target },
      },
      'user',
    );
  };

  const requestSwitch = (target: ColorDomain) => {
    if (target === shown) return;
    if (needsConfirm) {
      setModalTarget(target);
    } else {
      apply(target, false);
    }
  };

  return (
    <Group gap={6} wrap="nowrap">
      <SegmentedControl
        size="xs"
        data={[...DOMAIN_ITEMS]}
        value={shown}
        onChange={(v) => requestSwitch(v as ColorDomain)}
        aria-label="色彩编辑域"
        data-testid="domain-toggle"
        styles={{
          root: { flexShrink: 0 },
        }}
      />
      {/* 切域 aria-live 通告（视觉隐藏） */}
      <span
        aria-live="polite"
        style={{
          position: 'absolute',
          width: 1,
          height: 1,
          overflow: 'hidden',
          clipPath: 'inset(50%)',
          whiteSpace: 'nowrap',
        }}
      >
        {announcement}
      </span>
      <Modal
        opened={modalTarget !== null}
        onClose={() => setModalTarget(null)}
        title={<Text fw={600}>切换色彩编辑域？</Text>}
        size={420}
        centered
        withinPortal
      >
        <Text size="sm" c="dimmed" mb="xs">
          OKLCh 按感知均匀划分色相，角度与 HSV 不同。例：旧&ldquo;黄 60°&rdquo;在 OKLCh 约 110°。
        </Text>
        <Text size="xs" c="dimmed" mb="md">
          附注：胶片卡自带的 HSV 色段数值将按 {modalTarget === 'oklch' ? 'OKLCh' : 'HSV'} 角度解释。
        </Text>
        <Group justify="flex-end" gap="xs">
          <Button variant="light" onClick={() => { setModalTarget(null); apply(modalTarget!, true); }}>
            恢复该域默认带后切换
          </Button>
          <Button onClick={() => { setModalTarget(null); apply(modalTarget!, false); }} data-testid="domain-switch-keep">
            保留数值切换
          </Button>
        </Group>
      </Modal>
    </Group>
  );
}
