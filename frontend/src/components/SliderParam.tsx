import type { ParamPatch, Source } from '../types';

interface SliderParamProps {
  label: string;
  stage: string;
  param: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit?: string;
  source?: Source;
  locked?: boolean;
  onPatch: (patch: ParamPatch) => void;
}

export function SliderParam({
  label,
  stage,
  param,
  value,
  min,
  max,
  step,
  unit,
  source = 'user',
  locked = false,
  onPatch,
}: SliderParamProps) {
  const update = (next: number) => {
    if (locked) return;
    const clamped = Math.max(min, Math.min(max, next));
    onPatch({ [stage]: { [param]: clamped } });
  };

  return (
    <div className={`slider-row ${locked ? 'locked' : ''}`}>
      <div className="slider-label">
        <span>{label}</span>
        {source !== 'user' && <span className={`source-badge source-${source}`}>{source}</span>}
        {locked && <span className="lock-badge">🔒</span>}
      </div>
      <div className="slider-controls">
        <input
          type="range"
          value={value}
          min={min}
          max={max}
          step={step}
          disabled={locked}
          onChange={(e) => update(Number(e.target.value))}
        />
        <input
          className="number-input"
          type="number"
          value={value}
          min={min}
          max={max}
          step={step}
          disabled={locked}
          onChange={(e) => update(Number(e.target.value))}
        />
        {unit && <span className="unit">{unit}</span>}
      </div>
    </div>
  );
}
