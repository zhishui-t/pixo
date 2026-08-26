import {
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from 'react';
import { ActionIcon, Badge, Group, Paper, SegmentedControl, Text } from '@mantine/core';
import { Image as ImageIcon, Maximize2, Move, ZoomIn, ZoomOut } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import { DESIGN_TOKENS as T } from '../theme/tokens';
import { getOriginalSource, getPreviewSource } from '../api';

export function PreviewViewer() {
  const viewMode = useAppStore((s) => s.viewMode);
  const setViewMode = useAppStore((s) => s.setViewMode);
  const splitPos = useAppStore((s) => s.splitPos);
  const setSplitPos = useAppStore((s) => s.setSplitPos);
  const zoom = useAppStore((s) => s.zoom);
  const setZoom = useAppStore((s) => s.setZoom);
  const generation = useAppStore((s) => s.generation);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(null);

  const original = getOriginalSource();
  const processed = getPreviewSource(generation);

  const onPointerDown = (e: ReactPointerEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: ReactPointerEvent) => {
    if (!drag.current) return;
    setPan({
      x: drag.current.px + (e.clientX - drag.current.x),
      y: drag.current.py + (e.clientY - drag.current.y),
    });
  };
  const onPointerUp = () => {
    drag.current = null;
  };
  const onWheel = (e: ReactWheelEvent) => {
    const next = Math.max(0.1, Math.min(4, zoom + (e.deltaY < 0 ? 0.1 : -0.1)));
    setZoom(next);
  };

  return (
    <Paper
      radius="lg"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
        background: T.panel,
        border: `1px solid ${T.hairline}`,
        boxShadow: T.shadowMd,
      }}
    >
      <Group justify="space-between" p="sm" style={{ background: T.overlay, borderBottom: `1px solid ${T.hairline}` }}>
        <SegmentedControl
          size="xs"
          value={viewMode}
          onChange={(value) => setViewMode(value as 'original' | 'split' | 'processed')}
          data={[{ value: 'original', label: '原图' }, { value: 'split', label: 'Split' }, { value: 'processed', label: '处理' }]}
          radius="md"
        />
        <Group gap="xs">
          <Badge variant="light" color="indigo" size="sm">gen #{generation}</Badge>
          <Text size="xs" c="dark.4">{Math.round(zoom * 100)}%</Text>
        </Group>
      </Group>

      <div
        className="preview-stage"
        style={{ flex: 1, cursor: drag.current ? 'grabbing' : 'grab' }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onWheel={onWheel}
      >
        <div
          className="preview-transform"
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          }}
        >
          <img className="preview-img original-layer" src={original} alt="original" draggable={false} />
          {viewMode !== 'original' && (
            <img
              key={generation}
              className="preview-img processed-layer"
              src={processed}
              alt="processed"
              draggable={false}
              style={viewMode === 'split' ? { clipPath: `inset(0 0 0 ${splitPos * 100}%)` } : undefined}
            />
          )}
          {viewMode === 'processed' && (
            <div className="processed-only-badge">Processed</div>
          )}
        </div>

        {viewMode === 'split' && (
          <>
            <div
              className="split-divider"
              style={{ left: `${splitPos * 100}%` }}
              onPointerDown={(e) => {
                e.stopPropagation();
                const move = (ev: PointerEvent) => {
                  const rect = e.currentTarget.parentElement?.getBoundingClientRect();
                  if (!rect) return;
                  setSplitPos(Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width)));
                };
                const up = () => {
                  window.removeEventListener('pointermove', move);
                  window.removeEventListener('pointerup', up);
                };
                window.addEventListener('pointermove', move);
                window.addEventListener('pointerup', up);
              }}
            />
            <div className="split-left-label">原图</div>
            <div className="split-right-label">处理图</div>
          </>
        )}
      </div>

      <Group p="sm" gap="xs" justify="center" style={{ background: T.overlay, borderTop: `1px solid ${T.hairline}` }}>
        <ActionIcon variant="light" radius="md" onClick={() => setZoom(Math.max(0.1, zoom - 0.1))}><ZoomOut size={15} /></ActionIcon>
        <ActionIcon variant="light" radius="md" onClick={() => setZoom(Math.min(4, zoom + 0.1))}><ZoomIn size={15} /></ActionIcon>
        <ActionIcon variant="light" radius="md" onClick={() => setZoom(1)}><Maximize2 size={15} /></ActionIcon>
        <ActionIcon variant="light" radius="md" onClick={() => setZoom(1)}><Move size={15} /></ActionIcon>
        <ActionIcon variant="light" radius="md"><ImageIcon size={15} /></ActionIcon>
      </Group>
    </Paper>
  );
}
