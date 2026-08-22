import { useAppStore } from './store/useAppStore';
import { TopBar } from './components/TopBar';
import { ProjectList } from './components/ProjectList';
import { PreviewViewer } from './components/PreviewViewer';
import { Filmstrip } from './components/Filmstrip';
import { StyleAiPanel } from './components/StyleAiPanel';
import { AdjustmentsPanel } from './components/AdjustmentsPanel';
import { ReviewQueue } from './components/ReviewQueue';
import { SettingsPanel } from './components/SettingsPanel';

export default function App() {
  const page = useAppStore((s) => s.page);
  const rightTab = useAppStore((s) => s.rightTab);
  const setRightTab = useAppStore((s) => s.setRightTab);

  return (
    <div className="app-shell">
      <TopBar />
      {page === 'workspace' && (
        <div className="workspace-v2">
          <ProjectList />
          <div className="center-v2">
            <PreviewViewer />
            <Filmstrip />
          </div>
          <aside className="right-v2">
            <div className="right-tabs">
              <button
                className={`right-tab ${rightTab === 'style' ? 'active' : ''}`}
                onClick={() => setRightTab('style')}
              >
                风格 / AI
              </button>
              <button
                className={`right-tab ${rightTab === 'adjust' ? 'active' : ''}`}
                onClick={() => setRightTab('adjust')}
              >
                调整
              </button>
            </div>
            {rightTab === 'style' ? <StyleAiPanel /> : <AdjustmentsPanel />}
          </aside>
        </div>
      )}
      {page === 'review' && <ReviewQueue />}
      {page === 'settings' && <SettingsPanel />}
    </div>
  );
}
