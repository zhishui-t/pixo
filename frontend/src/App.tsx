import { AppShell, Badge, Button, Group, Text, Tooltip } from '@mantine/core';
import { Download, Inbox, LayoutGrid, Settings, SlidersHorizontal, Sparkles } from 'lucide-react';
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
    <AppShell.Header style={{ background: 'rgba(255,255,255,0.88)', backdropFilter: 'blur(14px)', borderBottom: '1px solid rgba(0,0,0,0.06)' }}>
      <Group h="100%" px="lg" justify="space-between">
        <Group gap="sm">
          <Text fw={800} size="lg" c="dark.9" style={{ letterSpacing: '-0.02em' }}>Pixo</Text>
          <Button variant="subtle" size="xs" leftSection={<LayoutGrid size={14} />} onClick={() => setPage('workspace')}>工作区</Button>
          <Button variant="subtle" size="xs" leftSection={<Inbox size={14} />} onClick={() => setPage('review')}>复核</Button>
          <Button variant="subtle" size="xs" leftSection={<Settings size={14} />} onClick={() => setPage('settings')}>设置</Button>
        </Group>
        <Group gap="sm">
          <Badge color={backend ? 'green' : 'yellow'} variant="light" size="sm">
            {backend ? 'pixo-service' : 'mock'}
          </Badge>
          <Tooltip label="导出当前结果">
            <Button size="xs" color="dark.9" variant="light" leftSection={<Download size={14} />}>导出</Button>
          </Tooltip>
        </Group>
      </Group>
    </AppShell.Header>
  );

  if (page !== 'workspace') {
    return (
      <AppShell header={{ height: 56 }} padding="xl">
        {header}
        <AppShell.Main>
          {page === 'review' ? <ReviewQueue /> : <SettingsPanel />}
        </AppShell.Main>
      </AppShell>
    );
  }

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 224, breakpoint: 'sm' }}
      aside={{ width: 390, breakpoint: 'md' }}
      padding="lg"
    >
      {header}
      <AppShell.Navbar p="md" style={{ background: '#fff', borderRight: '1px solid rgba(0,0,0,0.06)' }}>
        <ProjectList />
      </AppShell.Navbar>
      <AppShell.Main style={{ background: '#f7f8fa' }}>
        <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 104px)', gap: 20 }}>
          <div style={{ flex: 1, minHeight: 0 }}>
            <PreviewViewer />
          </div>
          <Filmstrip />
        </div>
      </AppShell.Main>
      <AppShell.Aside p="md" style={{ background: '#fff', borderLeft: '1px solid rgba(0,0,0,0.06)' }}>
        <Group gap={4} mb="md" style={{ background: '#f1f3f5', borderRadius: 12, padding: 4 }}>
          <button
            className={`modern-pill ${rightTab === 'style' ? 'active' : ''}`}
            onClick={() => setRightTab('style')}
          >
            <Sparkles size={14} /> 风格 / AI
          </button>
          <button
            className={`modern-pill ${rightTab === 'adjust' ? 'active' : ''}`}
            onClick={() => setRightTab('adjust')}
          >
            <SlidersHorizontal size={14} /> 调整
          </button>
        </Group>
        {rightTab === 'style' ? <StyleAiPanel /> : <AdjustmentsPanel />}
      </AppShell.Aside>
    </AppShell>
  );
}
