import { useState } from 'react';
import { Badge, Button, Card, Divider, Group, ScrollArea, Stack, Text, TextInput } from '@mantine/core';
import { useAppStore } from '../store/useAppStore';

export function StyleAiPanel() {
  const activeProjectId = useAppStore((s) => s.activeProjectId);
  const styleCards = useAppStore((s) => s.styleCards);
  const conversations = useAppStore((s) => s.conversations);
  const suggestions = useAppStore((s) => s.suggestionsByProject[s.activeProjectId] ?? []);
  const addProjectMessage = useAppStore((s) => s.addProjectMessage);
  const applyProjectSuggestion = useAppStore((s) => s.applyProjectSuggestion);
  const ignoreProjectSuggestion = useAppStore((s) => s.ignoreProjectSuggestion);
  const messages = conversations[activeProjectId] ?? [];
  const [text, setText] = useState('');

  const send = () => {
    const value = text.trim();
    if (!value) return;
    addProjectMessage(activeProjectId, { id: `u-${Date.now()}`, role: 'user', text: value });
    addProjectMessage(activeProjectId, {
      id: `a-${Date.now()}`,
      role: 'agent',
      text: '收到。当前为本地 mock 对话，接入后端后这里会返回真实 AI 建议。',
    });
    setText('');
  };

  return (
    <Stack gap="md" p="xs">
      <Card radius="md" withBorder>
        <Text fw={700} mb="sm">风格卡片</Text>
        <Stack gap="sm">
          {styleCards.map((card) => (
            <Card key={card.styleId} radius="md" withBorder padding="sm">
              <Group justify="space-between">
                <Text fw={600}>{card.name}</Text>
                <Badge variant="light" color="indigo">风格</Badge>
              </Group>
              <Text size="xs" c="dimmed" mt={4}>{card.description}</Text>
              <Group gap={4} mt={6}>
                {Object.entries(card.tags).map(([group, tags]) => (
                  <Badge key={group} variant="outline" size="xs">{group}: {tags.join('/')}</Badge>
                ))}
              </Group>
            </Card>
          ))}
        </Stack>
      </Card>

      <Card radius="md" withBorder>
        <Text fw={700} mb="sm">AI 推荐</Text>
        <Stack gap="sm">
          {suggestions.map((s) => (
            <Card key={s.id} radius="md" withBorder padding="sm">
              <Text fw={600}>{s.title}</Text>
              <Text size="xs" c="dimmed" mt={2}>{s.reason}</Text>
              <Badge color="grape" variant="light" mt={4}>置信度 {Math.round(s.confidence * 100)}%</Badge>
              <Group mt={8}>
                <Button size="xs" onClick={() => applyProjectSuggestion(activeProjectId, s)}>应用</Button>
                <Button size="xs" variant="light" onClick={() => ignoreProjectSuggestion(activeProjectId, s.id)}>忽略</Button>
                <Button size="xs" variant="subtle">编辑</Button>
              </Group>
            </Card>
          ))}
          {suggestions.length === 0 && <Text c="dimmed" size="sm">暂无推荐</Text>}
        </Stack>
      </Card>

      <Card radius="md" withBorder style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
        <Text fw={700} mb="sm">当前项目对话</Text>
        <Divider mb="sm" />
        <ScrollArea style={{ flex: 1, maxHeight: 320, minHeight: 120 }} mb="sm">
          <Stack gap={6}>
            {messages.map((m) => (
              <Text
                key={m.id}
                size="sm"
                style={{
                  alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                  background: m.role === 'user' ? 'var(--mantine-color-indigo-6)' : 'var(--mantine-color-dark-6)',
                  color: m.role === 'user' ? 'white' : undefined,
                  padding: '6px 10px',
                  borderRadius: 10,
                  maxWidth: '90%',
                }}
              >
                {m.text}
              </Text>
            ))}
          </Stack>
        </ScrollArea>
        <Group gap="xs">
          <TextInput
            flex={1}
            size="xs"
            value={text}
            onChange={(e) => setText(e.currentTarget.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
            placeholder="询问修图建议…"
          />
          <Button size="xs" onClick={send}>发送</Button>
        </Group>
      </Card>
    </Stack>
  );
}
