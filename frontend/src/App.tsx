import { ActionIcon, AppShell, Group, Text, Tooltip } from '@mantine/core';
import { Download, Inbox, LayoutGrid, Settings, SlidersHorizontal, Sparkles } from 'lucide-react';
import { DESIGN_TOKENS as T } from './theme/tokens';
import { pollExport, submitExport } from './api';
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

  const handleExport = async () => {
    const submitted = await submitExport('jpeg', 88);
    const result = await pollExport(submitted.task_id);
    window.alert(`导出任务 ${submitted.task_id}：${Math.round(result.progress * 100)}%`);
  };

  // t75 三段式 TopBar: 左品牌 / 中 pill 导航 / 右全局动作。
  // grid 1fr auto 1fr 保证导航在任意侧宽下视觉居中; 暗色玻璃配方 rgba(16,18,20,.8)。
  const header = (
    <AppShell.Header style={{ background: 'rgba(16,18,20,0.8)', backdropFilter: 'blur(14px)', borderBottom: `1px solid ${T.hairline}` }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', alignItems: 'center', height: '100%', padding: '0 20px' }}>
        <Group gap="sm" wrap="nowrap" justify="flex-start">
          <span aria-hidden style={{ width: 4, height: 22, borderRadius: 2, background: T.accent, boxShadow: `0 0 10px ${T.focusRing}` }} />
          <Text fw={800} size="lg" c="accent" style={{ letterSpacing: '-0.01em' }}>Pixo</Text>
        </Group>
        <Group gap={6} wrap="nowrap" style={{ background: T.overlay, borderRadius: 12, padding: 4, border: `1px solid ${T.hairline}` }}>
          <button
            className={`modern-pill ${page === 'workspace' ? 'active' : ''}`}
            style={{ flex: 'none', padding: '6px 14px' }}
            data-testid="nav-workspace"
            onClick={() => setPage('workspace')}
          >
            <LayoutGrid size={14} /> 工作区
          </button>
          <button
            className={`modern-pill ${page === 'review' ? 'active' : ''}`}
            style={{ flex: 'none', padding: '6px 14px' }}
            data-testid="nav-review"
            onClick={() => setPage('review')}
          >
            <Inbox size={14} /> 审核队列
          </button>
        </Group>
        <Group gap="sm" wrap="nowrap" justify="flex-end">
          <Tooltip label={backend ? 'pixo-service 已连接' : '演示数据模式（未连接后端）'}>
            <span
              data-testid="backend-status"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'default' }}
            >
              <span
                aria-hidden
                style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: backend ? T.semantic.success : T.semantic.warning,
                  boxShadow: `0 0 6px ${backend ? 'rgba(87,199,133,.5)' : 'rgba(217,154,43,.5)'}`,
                }}
              />
              <Text size="xs" c="dimmed">{backend ? '已连接' : '演示模式'}</Text>
            </span>
          </Tooltip>
          <Tooltip label="导出当前结果">
            <ActionIcon variant="default" size="lg" onClick={handleExport}>
              <Download size={16} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label={page === 'settings' ? '返回工作区' : '设置'}>
            <ActionIcon 
              variant={page === 'settings' ? 'light' : 'default'}
              color={page === 'settings' ? 'accent' : undefined}
              size="lg"
              data-testid="nav-settings"
              onClick={() => setPage(page === 'settings' ? 'workspace' : 'settings')}
            >
              <Settings size={16} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </div>
    </AppShell.Header>
  );

  if (page !== 'workspace') {
    return (
      <AppShell header={{ height: 56 }} padding="xl">
        {header}
        <AppShell.Main style={{ background: T.canvas }}>
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
      padding="xl"
    >
      {header}
      <AppShell.Navbar p="lg" style={{ background: T.panel, borderRight: `1px solid ${T.hairline}` }}>
        <ProjectList />
      </AppShell.Navbar>
      <AppShell.Main style={{ background: T.canvas }}>
        <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 112px)', gap: 24 }}>
          <div style={{ flex: 1, minHeight: 0 }}>
            <PreviewViewer />
          </div>
          <Filmstrip />
        </div>
      </AppShell.Main>
      <AppShell.Aside p="lg" style={{ background: T.panel, borderLeft: `1px solid ${T.hairline}` }}>
        <Group gap={4} mb="md" style={{ background: T.overlay, borderRadius: 12, padding: 4 }}>
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
