import { useState, type ReactNode } from 'react';
import { useAppStore } from '../store/useAppStore';
import { SliderParam } from './SliderParam';

const HISTOGRAM = [12, 28, 45, 62, 90, 120, 96, 70, 48, 32, 18, 10, 6];

function Section({
  title,
  open,
  onToggle,
  children,
}: {
  title: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <section className={`adjust-section ${open ? 'open' : ''}`}>
      <button className="section-toggle" onClick={onToggle}>
        <span>{title}</span>
        <span>{open ? '−' : '+'}</span>
      </button>
      {open && <div className="section-body">{children}</div>}
    </section>
  );
}

export function AdjustmentsPanel() {
  const activeProjectId = useAppStore((s) => s.activeProjectId);
  const params = useAppStore((s) => s.paramsByProject[s.activeProjectId] ?? {});
  const patchProjectParam = useAppStore((s) => s.patchProjectParam);
  const [open, setOpen] = useState<string[]>([
    'basic', 'curve', 'hsl', 'calibration', 'detail', 'split',
  ]);

  const toggle = (id: string) => {
    setOpen((cur) => cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]);
  };

  const value = (stage: string, param: string, fallback = 0): number => {
    const v = params[stage]?.[param] ?? fallback;
    return typeof v === 'number' ? v : Number(v) || fallback;
  };

  const patch = (projectId: string, patchObj: Record<string, Record<string, unknown>>) => {
    patchProjectParam(projectId, patchObj, 'user');
  };

  return (
    <div className="adjustments-panel">
      <div className="panel-title">调整</div>

      <div className="histogram">
        {HISTOGRAM.map((h, i) => (
          <div key={i} className="hist-bar" style={{ height: `${h * 0.6}px` }} />
        ))}
      </div>

      <Section title="基本" open={open.includes('basic')} onToggle={() => toggle('basic')}>
        <SliderParam label="曝光" stage="exposure" param="ev" value={value('exposure', 'ev', 0.28)} min={-2.5} max={2.5} step={0.01} unit="EV" onPatch={(p) => patch(activeProjectId, p)} />
        <SliderParam label="高光" stage="tone" param="highlights" value={value('tone', 'highlights', -20)} min={-100} max={100} step={1} onPatch={(p) => patch(activeProjectId, p)} />
        <SliderParam label="阴影" stage="tone" param="shadows" value={value('tone', 'shadows', 10)} min={-100} max={100} step={1} onPatch={(p) => patch(activeProjectId, p)} />
        <SliderParam label="色温" stage="whitebalance" param="temp" value={value('whitebalance', 'temp', 5200)} min={1000} max={50000} step={50} unit="K" onPatch={(p) => patch(activeProjectId, p)} />
        <SliderParam label="色调" stage="whitebalance" param="tint" value={value('whitebalance', 'tint', 0)} min={-150} max={150} step={1} onPatch={(p) => patch(activeProjectId, p)} />
        <SliderParam label="清晰度" stage="clarity" param="strength" value={value('clarity', 'strength', 0.1)} min={-1} max={1} step={0.01} onPatch={(p) => patch(activeProjectId, p)} />
      </Section>

      <Section title="曲线" open={open.includes('curve')} onToggle={() => toggle('curve')}>
        <div className="curve-placeholder">RGB / R / G / B / 亮度 曲线编辑器占位（后续接入 Canvas）</div>
      </Section>

      <Section title="HSL" open={open.includes('hsl')} onToggle={() => toggle('hsl')}>
        {['红', '橙', '黄', '绿', '青', '蓝', '紫', '品红'].map((color, idx) => (
          <div key={color} className="hsl-row">
            <span>{color}</span>
            <SliderParam label="色相" stage={`hsl`} param={`band${idx}`} value={0} min={-180} max={180} step={1} onPatch={(p) => patch(activeProjectId, p)} />
          </div>
        ))}
      </Section>

      <Section title="色彩校准" open={open.includes('calibration')} onToggle={() => toggle('calibration')}>
        <SliderParam label="红-色相" stage="calibration" param="red_hue" value={0} min={-180} max={180} step={1} onPatch={(p) => patch(activeProjectId, p)} />
        <SliderParam label="红-饱和度" stage="calibration" param="red_sat" value={0} min={-100} max={100} step={1} onPatch={(p) => patch(activeProjectId, p)} />
        <SliderParam label="绿-色相" stage="calibration" param="green_hue" value={0} min={-180} max={180} step={1} onPatch={(p) => patch(activeProjectId, p)} />
        <SliderParam label="蓝-色相" stage="calibration" param="blue_hue" value={0} min={-180} max={180} step={1} onPatch={(p) => patch(activeProjectId, p)} />
      </Section>

      <Section title="细节" open={open.includes('detail')} onToggle={() => toggle('detail')}>
        <SliderParam label="锐化" stage="refine" param="sharpen" value={value('refine', 'sharpen', 0.2)} min={0} max={1} step={0.01} onPatch={(p) => patch(activeProjectId, p)} />
        <SliderParam label="降噪" stage="refine" param="chroma_denoise" value={value('refine', 'chroma_denoise', 0.5)} min={0} max={5} step={0.1} onPatch={(p) => patch(activeProjectId, p)} />
        <SliderParam label="去朦胧" stage="dehaze" param="strength" value={0} min={0} max={1} step={0.01} onPatch={(p) => patch(activeProjectId, p)} />
      </Section>

      <Section title="分离色调" open={open.includes('split')} onToggle={() => toggle('split')}>
        <SliderParam label="高光色相" stage="split_tone" param="highlights_hue" value={0} min={0} max={360} step={1} onPatch={(p) => patch(activeProjectId, p)} />
        <SliderParam label="高光饱和度" stage="split_tone" param="highlights_sat" value={0} min={0} max={100} step={1} onPatch={(p) => patch(activeProjectId, p)} />
        <SliderParam label="阴影色相" stage="split_tone" param="shadows_hue" value={0} min={0} max={360} step={1} onPatch={(p) => patch(activeProjectId, p)} />
        <SliderParam label="阴影饱和度" stage="split_tone" param="shadows_sat" value={0} min={0} max={100} step={1} onPatch={(p) => patch(activeProjectId, p)} />
      </Section>
    </div>
  );
}
