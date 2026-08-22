import { useState } from 'react';
import { Button, Divider, Group, Paper, ScrollArea, Stack, Text, TextInput, UnstyledButton } from '@mantine/core';
import { FolderPlus, Plus, Search } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';

export function ProjectList() {
  const projects = useAppStore((s) => s.projects);
  const activeProjectId = useAppStore((s) => s.activeProjectId);
  const selectProject = useAppStore((s) => s.selectProject);
  const addProject = useAppStore((s) => s.addProject);
  const [name, setName] = useState('');
  const [query, setQuery] = useState('');

  const create = () => {
    const value = name.trim();
    if (!value) return;
    addProject(value);
    setName('');
  };

  const visible = projects.filter((p) => p.name.toLowerCase().includes(query.toLowerCase()));

  return (
    <Stack gap="md" h="100%">
      <Group justify="space-between">
        <Text fw={700} c="dimmed" style={{ letterSpacing: '.04em', textTransform: 'uppercase', fontSize: 11 }}>Projects</Text>
        <Button size="compact-xs" variant="light" leftSection={<FolderPlus size={13} />} onClick={create}>
          新建
        </Button>
      </Group>
      <TextInput
        placeholder="搜索项目"
        value={query}
        onChange={(e) => setQuery(e.currentTarget.value)}
        size="sm"
        leftSection={<Search size={14} />}
        radius="md"
      />
      <ScrollArea style={{ flex: 1 }}>
        <Stack gap={8}>
          {visible.map((project) => {
            const active = activeProjectId === project.id;
            return (
              <UnstyledButton key={project.id} onClick={() => selectProject(project.id)} w="100%">
                <Paper
                  p="sm"
                  radius="lg"
                  style={{
                    position: 'relative',
                    overflow: 'hidden',
                    background: active ? 'linear-gradient(135deg, rgba(108,140,255,0.16), rgba(108,140,255,0.04))' : 'rgba(18,24,33,0.82)',
                    boxShadow: active ? '0 12px 28px rgba(108,140,255,0.14)' : '0 6px 18px rgba(0,0,0,0.22)',
                    border: active ? '1px solid rgba(108,140,255,0.24)' : '1px solid rgba(255,255,255,0.04)',
                  }}
                >
                  {active && (
                    <div style={{ position: 'absolute', left: 0, top: 8, bottom: 8, width: 3, borderRadius: 4, background: 'linear-gradient(180deg, #6C8CFF, #9AB8FF)' }} />
                  )}
                  <Text size="sm" fw={600}>{project.name}</Text>
                  <Text size="xs" c="dimmed" mt={2}>{project.photoIds.length} 张 · {project.createdAt}</Text>
                </Paper>
              </UnstyledButton>
            );
          })}
        </Stack>
      </ScrollArea>
      <Divider />
      <Group gap="xs">
        <TextInput
          flex={1}
          size="sm"
          placeholder="新项目名称"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          onKeyDown={(e) => e.key === 'Enter' && create()}
          radius="md"
        />
        <Button size="sm" variant="light" onClick={create} aria-label="创建项目"><Plus size={15} /></Button>
      </Group>
    </Stack>
  );
}
