import { useState } from 'react';
import { Badge, Button, Card, Divider, Group, ScrollArea, Stack, Text, TextInput } from '@mantine/core';
import { Check, MessageCircle, Send, Sparkles, Wand2, X } from 'lucide-react';
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
    <Stack gap="lg" p={4}>
      <Card radius="xl" p="md" style={{ background: 'rgba(22,29,40,0.94)', boxShadow: '0 10px 30px rgba(0,0,0,0.3)' }}>
        <Group justify="space-between" mb="sm">
          <Text fw={700}>风格卡片</Text>
          <Wand2 size={16} color="#6C8CFF" />
        </Group>
        <Stack gap="sm">
          {styleCards.map((card) => (
            <Card key={card.styleId} radius="lg" padding="sm" style={{ background: 'linear-gradient(135deg, rgba(108,140,255,0.12), rgba(22,29,40,0.9))', border: '1px solid rgba(108,140,255,0.14)' }}>
              <Group justify="space-between">
                <Text fw={600}>{card.name}</Text>
                <Badge variant="light" color="indigo">风格</Badge>
              </Group>
              <Text size="xs" c="dimmed" mt={4}>{card.description}</Text>
              <Group gap={4} mt={6}>
                {Object.entries(card.tags).map(([group, tags]) => (
                  <Badge key={group} variant="outline" size="xs" color="gray">{group}: {tags.join('/')}</Badge>
                ))}
              </Group>
            </Card>
          ))}
        </Stack>
      </Card>

      <Card radius="xl" p="md" style={{ background: 'rgba(22,29,40,0.94)', boxShadow: '0 10px 30px rgba(0,0,0,0.3)' }}>
        <Group justify="space-between" mb="sm">
          <Text fw={700}>AI 推荐</Text>
          <Sparkles size={16} color="#9AB8FF" />
        </Group>
        <Stack gap="sm">
          {suggestions.map((s) => (
            <Card key={s.id} radius="lg" padding="sm" style={{ background: 'linear-gradient(135deg, rgba(108,140,255,0.18), rgba(22,29,40,0.92))', border: '1px solid rgba(108,140,255,0.18)' }}>
              <Text fw={600}>{s.title}</Text>
              <Text size="xs" c="dimmed" mt={2}>{s.reason}</Text>
              <Badge color="grape" variant="light" mt={4}>置信度 {Math.round(s.confidence * 100)}%</Badge>
              <Group mt={10}>
                <Button size="xs" leftSection={<Check size={13} />} onClick={() => applyProjectSuggestion(activeProjectId, s)}>应用</Button>
                <Button size="xs" variant="light" leftSection={<X size={13} />} onClick={() => ignoreProjectSuggestion(activeProjectId, s.id)}>忽略</Button>
                <Button size="xs" variant="subtle">编辑</Button>
              </Group>
            </Card>
          ))}
          {suggestions.length === 0 && <Text c="dimmed" size="sm">暂无推荐</Text>}
        </Stack>
      </Card>

      <Card radius="xl" p="md" style={{ display: 'flex', flexDirection: 'column', flex: 1, background: 'rgba(22,29,40,0.94)', boxShadow: '0 10px 30px rgba(0,0,0,0.3)' }}>
        <Group justify="space-between" mb="sm">
          <Text fw={700}>当前项目对话</Text>
          <MessageCircle size={16} color="#6C8CFF" />
        </Group>
        <Divider mb="sm" />
        <ScrollArea style={{ flex: 1, maxHeight: 340, minHeight: 140 }} mb="sm">
          <Stack gap={8}>
            {messages.map((m) => (
              <Text
                key={m.id}
                size="sm"
                style={{
                  alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                  background: m.role === 'user' ? 'linear-gradient(135deg, #6C8CFF, #4f6ef0)' : 'rgba(11,15,20,0.75)',
                  color: m.role === 'user' ? 'white' : 'var(--mantine-color-dark-1)',
                  padding: '8px 12px',
                  borderRadius: 14,
                  borderBottomRightRadius: m.role === 'user' ? 4 : 14,
                  borderBottomLeftRadius: m.role === 'agent' ? 4 : 14,
                  maxWidth: '92%',
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
            size="sm"
            value={text}
            onChange={(e) => setText(e.currentTarget.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
            placeholder="询问修图建议…"
            radius="lg"
          />
          <Button size="sm" variant="light" leftSection={<Send size={14} />} onClick={send}>发送</Button>
        </Group>
      </Card>
    </Stack>
  );
}
