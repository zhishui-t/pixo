import { useAppStore } from '../store/useAppStore';

const STAGES = [
  'RAW_PENDING',
  'SCREENED',
  'BASE_RENDERED',
  'EXPOSURE_ALIGNING',
  'COLOR_CORRECTING',
  'STYLE_APPLIED',
  'FINAL_QC',
] as const;

export function Timeline() {
  const generation = useAppStore((s) => s.generation);
  return (
    <div className="timeline">
      <div className="timeline-stages">
        {STAGES.map((stage, i) => (
          <span key={stage} className={`stage ${i < 5 ? 'done' : ''}`}>
            {stage}
          </span>
        ))}
      </div>
      <div className="timeline-meta">
        迭代 2 / 3 · gen #{generation} · 预览 1024 · 0.41s
      </div>
    </div>
  );
}
