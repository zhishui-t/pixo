import { useState } from 'react';
import { Badge, Button, Card, Divider, Group, ScrollArea, Stack, Text, TextInput } from '@mantine/core';
import { Check, ChevronDown, MessageCircle, Send, Sparkles, Wand2, X } from 'lucide-react';
import { fetchStyleDetail } from '../api';
import type { StyleCardDetail } from '../types';
import { useAppStore } from '../store/useAppStore';
import { DESIGN_TOKENS as T } from '../theme/tokens';

const hexToRgba = (hex: string, alpha: number): string => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
};
/** accent 透明度变体——单源取自 tokens，禁止再写 rgba 字面量。 */
const accentA = (alpha: number): string => hexToRgba(T.accent, alpha);

export function StyleAiPanel() {
  const activeProjectId = useAppStore((s) => s.activeProjectId);
  const styleCards = useAppStore((s) => s.styleCards);

  // t60 接线：点击卡选中 → 拉完整卡（GET /api/styles/{id}）展开详情；
  // 离线（后端不可达）时详情显示占位说明。
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<StyleCardDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const toggleCard = (styleId: string) => {
    if (selectedId === styleId) {
      setSelectedId(null);
      setDetail(null);
      return;
    }
    setSelectedId(styleId);
    setDetail(null);
    setDetailLoading(true);
    void fetchStyleDetail(styleId).then((card) => {
      setDetail(card);
      setDetailLoading(false);
    });
  };

  // t86：按胶片 family 分组浏览（缺 family 归入"其他"）。
  const families = Array.from(
    styleCards.reduce<Map<string, typeof styleCards>>((m, c) => {
      const key = c.family?.trim() || '其他';
      const bucket = m.get(key);
      if (bucket) bucket.push(c);
      else m.set(key, [c]);
      return m;
    }, new Map()),
  );
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
    <Stack gap="xl" p={4}>
      <Card radius="lg" p="md" style={{ background: T.panel, border: `1px solid ${T.hairline}`, boxShadow: T.shadowMd }}>
        <Group justify="space-between" mb="sm">
          <Text fw={700}>风格卡片</Text>
          <Wand2 size={16} color={T.accent} />
        </Group>
        <Stack gap="sm">
          {families.map(([family, cards]) => (
            <Stack key={family} gap="sm">
              <Text size="xs" fw={700} c="dark.2" style={{ letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                {family}
              </Text>
              {cards.map((card) => {
                const selected = card.styleId === selectedId;
                return (
                  <Card
                    key={card.styleId}
                    radius="md"
                    padding="sm"
                    onClick={() => toggleCard(card.styleId)}
                    style={{
                      cursor: 'pointer',
                      background: `linear-gradient(135deg, ${accentA(selected ? 0.22 : 0.10)}, ${T.overlay})`,
                      border: `1px solid ${accentA(selected ? 0.45 : 0.18)}`,
                    }}
                  >
                    <Group justify="space-between" wrap="nowrap">
                      <Text fw={600}>{card.name}</Text>
                      <Group gap={4} wrap="nowrap">
                        {card.year != null && (
                          <Badge variant="light" color="gray" size="xs">{card.year}</Badge>
                        )}
                        <Badge variant="light" color="accent">风格</Badge>
                        <ChevronDown
                          size={14}
                          color={T.accent}
                          style={{ transform: selected ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}
                        />
                      </Group>
                    </Group>
                    <Text size="xs" c="dark.2" mt={4}>{card.description}</Text>
                    <Group gap={4} mt={6}>
                      {card.tags.map((tag) => (
                        <Badge key={tag} variant="outline" size="xs" color="gray">{tag}</Badge>
                      ))}
                    </Group>
                    {selected && (
                      <Stack gap={4} mt="sm">
                        {detailLoading && <Text size="xs" c="dark.3">加载完整卡…</Text>}
                        {!detailLoading && !detail && (
                          <Text size="xs" c="dark.3">离线模式：启动后端查看完整卡（stages/params）。</Text>
                        )}
                        {detail && (
                          <>
                            {(detail.scenes?.length ?? 0) > 0 && (
                              <Text size="xs" c="dark.2">适用场景：{detail.scenes?.join(' / ')}</Text>
                            )}
                            <Text size="xs" c="dark.2">渲染链（{detail.stages.length} 段）：{detail.stages.join(' → ')}</Text>
                          </>
                        )}
                      </Stack>
                    )}
                  </Card>
                );
              })}
            </Stack>
          ))}
          {styleCards.length === 0 && <div className="empty-note">风格卡加载中…（后端不可达时显示离线占位）</div>}
        </Stack>
      </Card>

      <Card radius="lg" p="md" style={{ background: T.panel, border: `1px solid ${T.hairline}`, boxShadow: T.shadowMd }}>
        <Group justify="space-between" mb="sm">
          <Text fw={700}>AI 推荐</Text>
          <Sparkles size={16} color={T.accent} />
        </Group>
        <Stack gap="sm">
          {suggestions.map((s) => (
            <Card key={s.id} radius="md" padding="sm" style={{ background: `linear-gradient(135deg, ${accentA(0.12)}, ${T.overlay})`, border: `1px solid ${accentA(0.22)}` }}>
              <Text fw={600}>{s.title}</Text>
              <Text size="xs" c="dark.4" mt={2}>{s.reason}</Text>
              <Badge color="grape" variant="light" mt={4}>置信度 {Math.round(s.confidence * 100)}%</Badge>
              <Group mt={10}>
                <Button size="xs" leftSection={<Check size={13} />} onClick={() => applyProjectSuggestion(activeProjectId, s)}>应用</Button>
                <Button size="xs" variant="light" leftSection={<X size={13} />} onClick={() => ignoreProjectSuggestion(activeProjectId, s.id)}>忽略</Button>
                <Button size="xs" variant="subtle">编辑</Button>
              </Group>
            </Card>
          ))}
          {suggestions.length === 0 && <div className="empty-note">暂无 AI 推荐</div>}
        </Stack>
      </Card>

      <Card radius="lg" p="md" style={{ display: 'flex', flexDirection: 'column', flex: 1, background: T.panel, border: `1px solid ${T.hairline}`, boxShadow: T.shadowMd }}>
        <Group justify="space-between" mb="sm">
          <Text fw={700}>当前项目对话</Text>
          <MessageCircle size={16} color={T.accent} />
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
                  background: m.role === 'user' ? T.accent : T.overlay,
                  color: m.role === 'user' ? T.onAccent : T.textPrimary,
                  padding: '8px 12px',
                  borderRadius: 12,
                  borderBottomRightRadius: m.role === 'user' ? 4 : 12,
                  borderBottomLeftRadius: m.role === 'agent' ? 4 : 12,
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
            radius="md"
          />
          <Button size="sm" variant="light" leftSection={<Send size={14} />} onClick={send}>发送</Button>
        </Group>
      </Card>
    </Stack>
  );
}
