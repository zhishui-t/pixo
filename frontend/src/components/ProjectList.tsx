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
        <Text fw={700} c="dark.5" style={{ letterSpacing: '.04em', textTransform: 'uppercase', fontSize: 11 }}>Projects</Text>
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
                  radius="md"
                  style={{
                    position: 'relative',
                    overflow: 'hidden',
                    background: active ? 'linear-gradient(135deg, rgba(86,134,254,0.12), rgba(86,134,254,0.03))' : '#fff',
                    boxShadow: active ? '0 8px 24px rgba(86,134,254,0.12)' : '0 2px 10px rgba(0,0,0,0.04)',
                    border: active ? '1px solid rgba(86,134,254,0.22)' : '1px solid rgba(0,0,0,0.06)',
                  }}
                >
                  {active && (
                    <div style={{ position: 'absolute', left: 0, top: 8, bottom: 8, width: 3, borderRadius: 4, background: '#5686FE' }} />
                  )}
                  <Text size="sm" fw={600}>{project.name}</Text>
                  <Text size="xs" c="dark.4" mt={2}>{project.photoIds.length} 张 · {project.createdAt}</Text>
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
