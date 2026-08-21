import { useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { useAppStore } from '../store/useAppStore';
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
  const onWheel = (e: React.WheelEvent) => {
    const next = Math.max(0.1, Math.min(4, zoom + (e.deltaY < 0 ? 0.1 : -0.1)));
    setZoom(next);
  };

  return (
    <section className="preview">
      <div className="preview-toolbar">
        <div className="seg">
          <button className={viewMode === 'original' ? 'seg-active' : ''} onClick={() => setViewMode('original')}>
            原图
          </button>
          <button className={viewMode === 'split' ? 'seg-active' : ''} onClick={() => setViewMode('split')}>
            Split
          </button>
          <button className={viewMode === 'processed' ? 'seg-active' : ''} onClick={() => setViewMode('processed')}>
            处理
          </button>
        </div>
        <div className="preview-meta">
          <span>gen #{generation}</span>
          <span>zoom {Math.round(zoom * 100)}%</span>
        </div>
      </div>

      <div
        className="preview-stage"
        style={{ cursor: drag.current ? 'grabbing' : 'grab' }}
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
                  const rect = (e.currentTarget as HTMLElement).parentElement?.getBoundingClientRect();
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

      <div className="preview-footer">
        <button className="btn" onClick={() => setZoom(Math.max(0.1, zoom - 0.1))}>−</button>
        <button className="btn" onClick={() => setZoom(Math.min(4, zoom + 0.1))}>＋</button>
        <button className="btn" onClick={() => setZoom(1)}>适应</button>
        <button className="btn" onClick={() => setZoom(1)}>1:1</button>
        <span className="hint">滚轮缩放 / 拖拽平移 / 分屏拖动分界线</span>
      </div>
    </section>
  );
}
