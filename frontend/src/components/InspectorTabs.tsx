import type { ReactNode } from 'react';
import { useAppStore } from '../store/useAppStore';
import { SliderParam } from './SliderParam';
import { AgentPanel } from './AgentPanel';

const TABS = [
  { id: 'params', label: '参数' },
  { id: 'measure', label: '测量' },
  { id: 'trace', label: '溯源' },
  { id: 'agent', label: 'Agent' },
] as const;

function ParamGroup({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="param-group">
      <div className="param-group-title">{title}</div>
      {children}
    </section>
  );
}

export function InspectorTabs() {
  const tab = useAppStore((s) => s.inspectorTab);
  const setTab = useAppStore((s) => s.setInspectorTab);
  const params = useAppStore((s) => s.params);
  const patchParam = useAppStore((s) => s.patchParam);

  const value = (stage: string, param: string, fallback = 0): number => {
    const val = params[stage]?.[param] ?? fallback;
    return typeof val === 'number' ? val : Number(val) || fallback;
  };

  return (
    <aside className="inspector">
      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab ${tab === t.id ? 'tab-active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'params' && (
        <div className="inspector-content">
          <ParamGroup title="曝光">
            <SliderParam
              label="EV"
              stage="exposure"
              param="ev"
              value={value('exposure', 'ev', 0.28)}
              min={-2.5}
              max={2.5}
              step={0.01}
              unit="EV"
              source="decide"
              onPatch={patchParam}
            />
          </ParamGroup>
          <ParamGroup title="白平衡">
            <SliderParam
              label="色温"
              stage="whitebalance"
              param="temp"
              value={value('whitebalance', 'temp', 5200)}
              min={1000}
              max={50000}
              step={50}
              unit="K"
              source="preset"
              onPatch={patchParam}
            />
            <SliderParam
              label="色调"
              stage="whitebalance"
              param="tint"
              value={value('whitebalance', 'tint', 0)}
              min={-150}
              max={150}
              step={1}
              onPatch={patchParam}
            />
          </ParamGroup>
          <ParamGroup title="影调">
            <SliderParam
              label="高光"
              stage="tone"
              param="highlights"
              value={value('tone', 'highlights', -20)}
              min={-100}
              max={100}
              step={1}
              source="agent"
              onPatch={patchParam}
            />
            <SliderParam
              label="阴影"
              stage="tone"
              param="shadows"
              value={value('tone', 'shadows', 10)}
              min={-100}
              max={100}
              step={1}
              onPatch={patchParam}
            />
            <SliderParam
              label="对比度"
              stage="tone"
              param="contrast"
              value={value('tone', 'contrast', 0.1)}
              min={-1}
              max={1}
              step={0.01}
              onPatch={patchParam}
            />
          </ParamGroup>
          <ParamGroup title="色彩">
            <SliderParam
              label="饱和度"
              stage="colorcal"
              param="saturation"
              value={value('colorcal', 'saturation', 0.05)}
              min={-1}
              max={1}
              step={0.01}
              onPatch={patchParam}
            />
            <SliderParam
              label="鲜艳度"
              stage="colorcal"
              param="vibrance"
              value={value('colorcal', 'vibrance', 0.1)}
              min={-1}
              max={1}
              step={0.01}
              onPatch={patchParam}
            />
          </ParamGroup>
          <ParamGroup title="细节">
            <SliderParam
              label="锐化"
              stage="refine"
              param="sharpen"
              value={value('refine', 'sharpen', 0.2)}
              min={0}
              max={1}
              step={0.01}
              onPatch={patchParam}
            />
            <SliderParam
              label="色度降噪"
              stage="refine"
              param="chroma_denoise"
              value={value('refine', 'chroma_denoise', 0.5)}
              min={0}
              max={5}
              step={0.1}
              onPatch={patchParam}
            />
          </ParamGroup>
        </div>
      )}

      {tab === 'measure' && (
        <div className="inspector-content">
          <div className="measure-card">
            <div className="measure-title">全局</div>
            <div className="measure-line">mean luminance：112</div>
            <div className="measure-line">highlight clip：0.4%</div>
            <div className="measure-line">shadow clip：2.0%</div>
            <div className="measure-line">contrast：0.24</div>
          </div>
          <div className="measure-card">
            <div className="measure-title">区域</div>
            <div className="measure-line">face conf .87 · 可靠</div>
            <div className="measure-line">sky conf .92 · 可靠</div>
            <div className="measure-line">plant conf .61 · 决策跳过</div>
          </div>
          <div className="measure-card">
            <div className="measure-title">美学（仅参考）</div>
            <div className="measure-line">3.8 / 5</div>
          </div>
        </div>
      )}

      {tab === 'trace' && (
        <div className="inspector-content">
          <div className="measure-card">
            <div className="measure-line">14:22 Exposure 0.0 → +0.28 EV · decide</div>
            <div className="measure-line">14:21 Agent 提亮人脸 · 已采纳</div>
            <div className="measure-line">14:20 preset portrait · 已应用</div>
            <button className="btn">导出 Trace JSON</button>
          </div>
        </div>
      )}

      {tab === 'agent' && <AgentPanel />}
    </aside>
  );
}
