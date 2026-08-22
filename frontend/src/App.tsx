import { AppShell, Badge, Button, Group, Text } from '@mantine/core';
import { useAppStore } from './store/useAppStore';
import { ProjectList } from './components/ProjectList';
import { PreviewViewer } from './components/PreviewViewer';
import { Filmstrip } from './components/Filmstrip';
import { StyleAiPanel } from './components/StyleAiPanel';
import { AdjustmentsPanel } from './components/AdjustmentsPanel';
import { ReviewQueue } from './components/ReviewQueue';
import { SettingsPanel } from './components/SettingsPanel';

export default function App() {
  const page = useAppStore((s) => s.page);
  const setPage = useAppStore((s) => s.setPage);
  const rightTab = useAppStore((s) => s.rightTab);
  const setRightTab = useAppStore((s) => s.setRightTab);
  const backend = useAppStore((s) => s.backend);

  const header = (
    <AppShell.Header>
      <Group h="100%" px="md" justify="space-between">
        <Group gap="sm">
          <Text fw={700} size="lg" c="indigo.4">Pixo</Text>
          <Button variant="subtle" size="xs" onClick={() => setPage('workspace')}>工作区</Button>
          <Button variant="subtle" size="xs" onClick={() => setPage('review')}>复核队列</Button>
          <Button variant="subtle" size="xs" onClick={() => setPage('settings')}>设置</Button>
        </Group>
        <Group gap="sm">
          <Badge color={backend ? 'green' : 'orange'} variant="light">
            {backend ? 'pixo-service' : 'mock 数据'}
          </Badge>
          <Button size="xs">导出</Button>
        </Group>
      </Group>
    </AppShell.Header>
  );

  if (page !== 'workspace') {
    return (
      <AppShell header={{ height: 52 }} padding="md">
        {header}
        <AppShell.Main>
          {page === 'review' ? <ReviewQueue /> : <SettingsPanel />}
        </AppShell.Main>
      </AppShell>
    );
  }

  return (
    <AppShell
      header={{ height: 52 }}
      navbar={{ width: 240, breakpoint: 'sm' }}
      aside={{ width: 380, breakpoint: 'md' }}
      padding="md"
    >
      {header}
      <AppShell.Navbar p="xs">
        <ProjectList />
      </AppShell.Navbar>
      <AppShell.Main>
        <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 100px)', gap: 12 }}>
          <div style={{ flex: 1, minHeight: 0 }}>
            <PreviewViewer />
          </div>
          <Filmstrip />
        </div>
      </AppShell.Main>
      <AppShell.Aside p="xs">
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
      </AppShell.Aside>
    </AppShell>
  );
}
