import { useState } from 'react';

const INITIAL = {
  previewLongEdge: 1024,
  bitDepth: 8,
  format: 'jpeg',
  quality: 88,
  stripGps: true,
};

export function SettingsPanel() {
  const [settings, setSettings] = useState(INITIAL);

  return (
    <main className="page settings-page">
      <h1>设置</h1>
      <section className="settings-section">
        <h2>渲染</h2>
        <label>
          预览长边
          <select value={settings.previewLongEdge} onChange={(e) => setSettings({ ...settings, previewLongEdge: Number(e.target.value) })}>
            <option value={512}>512</option>
            <option value={1024}>1024</option>
            <option value={2048}>2048</option>
          </select>
        </label>
        <label>
          输出位深
          <select value={settings.bitDepth} onChange={(e) => setSettings({ ...settings, bitDepth: Number(e.target.value) })}>
            <option value={8}>8-bit</option>
            <option value={16}>16-bit</option>
          </select>
        </label>
      </section>
      <section className="settings-section">
        <h2>输出</h2>
        <label>
          格式
          <select value={settings.format} onChange={(e) => setSettings({ ...settings, format: e.target.value })}>
            <option value="jpeg">JPEG</option>
            <option value="webp">WebP</option>
            <option value="png16">PNG16</option>
            <option value="tiff16">TIFF16</option>
          </select>
        </label>
        <label>
          质量
          <input
            type="number"
            value={settings.quality}
            min={1}
            max={100}
            onChange={(e) => setSettings({ ...settings, quality: Number(e.target.value) })}
          />
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={settings.stripGps}
            onChange={(e) => setSettings({ ...settings, stripGps: e.target.checked })}
          />
          导出时剥离 GPS
        </label>
      </section>
      <section className="settings-section">
        <h2>DSH / 模型</h2>
        <p className="muted">DSH 地址与 YOLOE 模型可用性状态为 P2 接入占位。</p>
      </section>
    </main>
  );
}
