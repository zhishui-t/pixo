import { useState } from 'react';
import { Button, Divider, Group, Paper, ScrollArea, Stack, Text, TextInput, UnstyledButton } from '@mantine/core';
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
    <Stack gap="sm" h="100%">
      <Group justify="space-between">
        <Text fw={700} c="dimmed">项目</Text>
        <Button size="compact-xs" onClick={create}>新建</Button>
      </Group>
      <TextInput
        placeholder="搜索项目"
        value={query}
        onChange={(e) => setQuery(e.currentTarget.value)}
        size="xs"
      />
      <ScrollArea style={{ flex: 1 }}>
        <Stack gap={4}>
          {visible.map((project) => (
            <UnstyledButton
              key={project.id}
              onClick={() => selectProject(project.id)}
              w="100%"
            >
              <Paper
                p="xs"
                radius="md"
                withBorder
                style={{
                  background: activeProjectId === project.id ? 'rgba(99,102,241,0.12)' : undefined,
                  borderColor: activeProjectId === project.id ? 'var(--mantine-color-indigo-5)' : undefined,
                }}
              >
                <Text size="sm" fw={600}>{project.name}</Text>
                <Text size="xs" c="dimmed">{project.photoIds.length} 张 · {project.createdAt}</Text>
              </Paper>
            </UnstyledButton>
          ))}
        </Stack>
      </ScrollArea>
      <Divider />
      <Group gap="xs">
        <TextInput
          flex={1}
          size="xs"
          placeholder="新项目名称"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          onKeyDown={(e) => e.key === 'Enter' && create()}
        />
        <Button size="xs" onClick={create}>+</Button>
      </Group>
    </Stack>
  );
}
