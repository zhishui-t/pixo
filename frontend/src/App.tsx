import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchPhotos } from './api';
import { useAppStore } from './store/useAppStore';
import { TopBar } from './components/TopBar';
import { PhotoLibrary } from './components/PhotoLibrary';
import { PreviewViewer } from './components/PreviewViewer';
import { InspectorTabs } from './components/InspectorTabs';
import { Timeline } from './components/Timeline';
import { ReviewQueue } from './components/ReviewQueue';
import { SettingsPanel } from './components/SettingsPanel';

export default function App() {
  const page = useAppStore((s) => s.page);
  const setPhotos = useAppStore((s) => s.setPhotos);
  const { data } = useQuery({
    queryKey: ['photos'],
    queryFn: fetchPhotos,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (data) {
      setPhotos(data.photos, data.backend);
    }
  }, [data, setPhotos]);

  return (
    <div className="app-shell">
      <TopBar />
      {page === 'workspace' && (
        <div className="workspace">
          <PhotoLibrary />
          <div className="center-column">
            <PreviewViewer />
            <Timeline />
          </div>
          <InspectorTabs />
        </div>
      )}
      {page === 'review' && <ReviewQueue />}
      {page === 'settings' && <SettingsPanel />}
    </div>
  );
}
