import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from 'react';
import { ActionIcon, Badge, Button, Group, Paper, SegmentedControl, Text } from '@mantine/core';
import { Image as ImageIcon, Maximize2, Move, ZoomIn, ZoomOut } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import { DESIGN_TOKENS as T } from '../theme/tokens';
import { getMockOriginalSource, getMockSessionId, getOriginalSource, getPreviewSource } from '../api';

export function PreviewViewer() {
  const viewMode = useAppStore((s) => s.viewMode);
  const setViewMode = useAppStore((s) => s.setViewMode);
  const splitPos = useAppStore((s) => s.splitPos);
  const setSplitPos = useAppStore((s) => s.setSplitPos);
  const zoom = useAppStore((s) => s.zoom);
  const setZoom = useAppStore((s) => s.setZoom);
  const generation = useAppStore((s) => s.generation);
  // 连接灯同源的在线标志：fetchPhotos 探测成功翻转 backendAvailable 发生在
  // 首渲染之后，原图 URL 的 useMemo 需依赖它重算，否则一直停留在 mock 占位。
  const backendOnline = useAppStore((s) => s.backend);
  // 后端在线时 store 会缓存 ensureSession 建立的真实会话 id；mock 模式回退 demo。
  const sessionId = useAppStore((s) => s.sessionId) ?? getMockSessionId();
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(null);

  // 原图层：在线模式指向契约端点 GET /api/sessions/{id}/image?original=1
  // （decode-only 原图，见 api.getOriginalSource 注释）；端点落地前会 404，
  // 由 onError 同帧回退 mock data URL 占位（不闪断，无网络往返）。
  // 离线模式 src 本就是 mock data URL，不触发回退。
  const original = useMemo(
    () => getOriginalSource(sessionId),
    [sessionId, backendOnline],
  );
  const [originalSrc, setOriginalSrc] = useState(original);
  useEffect(() => {
    setOriginalSrc(original);
  }, [original]);
  const processed = useMemo(
    () => getPreviewSource(sessionId, generation),
    [sessionId, generation],
  );

  // 处理图加载态：generation 变化时同一 img 元素切 src（不重挂载整层，避免闪烁）。
  const [src, setSrc] = useState(processed);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const imgRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    setSrc(processed);
    setLoading(true);
    setFailed(false);
  }, [processed]);

  const retry = () => {
    setFailed(false);
    setLoading(true);
    // src 内容相同时也强制重新加载（先置空再赋值）。
    const el = imgRef.current;
    if (!el) return;
    el.src = '';
    el.src = processed;
  };

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
        style={{ flex: 1, position: 'relative', cursor: drag.current ? 'grabbing' : 'grab' }}
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
          <img
            className="preview-img original-layer"
            src={originalSrc}
            alt="original"
            draggable={false}
            onError={() => {
              const fallback = getMockOriginalSource();
              if (originalSrc !== fallback) setOriginalSrc(fallback);
            }}
          />
          {viewMode !== 'original' && (
            <img
              ref={imgRef}
              className="preview-img processed-layer"
              src={src}
              alt="processed"
              draggable={false}
              onLoad={() => {
                setLoading(false);
                setFailed(false);
              }}
              onError={() => {
                setLoading(false);
                setFailed(true);
              }}
              style={viewMode === 'split' ? { clipPath: `inset(0 0 0 ${splitPos * 100}%)` } : undefined}
            />
          )}
          {viewMode === 'processed' && (
            <div className="processed-only-badge">Processed</div>
          )}
        </div>

        {viewMode !== 'original' && loading && !failed && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              pointerEvents: 'none',
            }}
          >
            <Text size="sm" c="dimmed">渲染中…（gen #{generation}）</Text>
          </div>
        )}
        {viewMode !== 'original' && failed && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
            }}
          >
            <Text size="sm" c="red">预览加载失败（gen #{generation}）</Text>
            <Button size="xs" variant="light" onClick={retry}>重试</Button>
          </div>
        )}

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
