import { useState } from 'react';
import { Alert, Badge, Button, Card, Divider, Group, ScrollArea, Stack, Text, TextInput } from '@mantine/core';
import { Check, ChevronDown, MessageCircle, Send, Sparkles, Wand2, X } from 'lucide-react';
import { fetchStyleDetail } from '../api';
import { SCENE_PRESETS } from '../constants/scenePresets';
import type { ParamPatch, StyleCardDetail } from '../types';
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
  const applyPresetPatch = useAppStore((s) => s.applyPresetPatch);

  // t60 接线：点击卡选中 → 拉完整卡（GET /api/styles/{id}）展开详情；
  // 离线（后端不可达）时详情显示占位说明。
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<StyleCardDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  // R22 F04：应用态/错误态必须显式（用户偏好：失败不能静默无效）。
  const [applying, setApplying] = useState<string | null>(null);
  const [applied, setApplied] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);

  /**
   * 应用装配 patch（`__scene` 场景预设 / `__style` 风格卡）。
   * 服务层按 id 取预设/卡参数深合并；失败（400 栅栏拒绝、离线）显式提示。
   */
  const applyPatch = async (key: string, patch: ParamPatch, label: string) => {
    setApplying(key);
    setApplyError(null);
    setApplied(null);
    try {
      await applyPresetPatch(patch, 'preset');
      setApplied(label);
    } catch (err) {
      setApplied(null);
      setApplyError(`${label} 应用失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setApplying(null);
    }
  };

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
    <Stack gap="lg" p={4}>
      {applyError && (
        <Alert
          color="red"
          variant="light"
          title="应用失败"
          withCloseButton
          onClose={() => setApplyError(null)}
          data-testid="style-apply-error"
        >
          <Text size="xs">{applyError}</Text>
        </Alert>
      )}
      {applied && !applyError && (
        <Text size="xs" c="dark.2" data-testid="style-applied">
          <Check size={12} style={{ verticalAlign: -2 }} /> 已应用：{applied}
        </Text>
      )}

      <Card radius="md" p="md" style={{ background: T.panel, border: `1px solid ${T.hairline}` }}>
        <Group justify="space-between" mb="sm">
          <Text fw={700}>风格卡片</Text>
          <Wand2 size={16} color={T.accent} />
        </Group>

        {/* R22 F05：场景预设（6 个）置风格选择器上方，紧凑 chip，不用大卡片。
            预设为叠加式覆盖：只写自己声明的参数键，不重置其它调整。 */}
        <Text size="xs" fw={700} c="dark.2" mb={6}
              style={{ letterSpacing: '0.05em', textTransform: 'uppercase' }}>
          场景预设
        </Text>
        <Group gap={6} mb={4}>
          {SCENE_PRESETS.map((scene) => (
            <Button
              key={scene.id}
              size="compact-xs"
              variant={applied === scene.label ? 'filled' : 'default'}
              title={scene.hint}
              loading={applying === `scene:${scene.id}`}
              disabled={applying !== null}
              onClick={() => void applyPatch(`scene:${scene.id}`, { __scene: scene.id }, scene.label)}
              data-testid={`scene-${scene.id}`}
            >
              {scene.label}
            </Button>
          ))}
        </Group>
        <Text size="xs" c="dark.3" mb="md">
          预设叠加生效（不清空其它调整），所选 id 与后端 configs/styles/scenes.json 一一对应。
        </Text>

        <Stack gap={4}>
          {families.map(([family, cards]) => (
            <Stack key={family} gap={4}>
              <Text size="xs" fw={700} c="dark.2" mt={4}
                    style={{ letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                {family}
              </Text>
              {cards.map((card) => {
                const selected = card.styleId === selectedId;
                return (
                  <div
                    key={card.styleId}
                    data-testid={`style-row-${card.styleId}`}
                    style={{
                      border: `1px solid ${selected ? accentA(0.45) : T.hairline}`,
                      borderRadius: 8,
                      padding: '6px 8px',
                      background: selected ? T.overlay : 'transparent',
                    }}
                  >
                    <Group justify="space-between" wrap="nowrap" gap={6}>
                      <div
                        role="button"
                        tabIndex={0}
                        onClick={() => toggleCard(card.styleId)}
                        onKeyDown={(e) => e.key === 'Enter' && toggleCard(card.styleId)}
                        style={{ cursor: 'pointer', flex: 1, minWidth: 0 }}
                      >
                        <Group gap={6} wrap="nowrap">
                          <Text fw={600} size="sm" truncate>{card.name}</Text>
                          {card.year != null && (
                            <Badge variant="light" color="gray" size="xs">{card.year}</Badge>
                          )}
                          <ChevronDown size={12} color={T.accent} />
                        </Group>
                      </div>
                      <Button
                        size="compact-xs"
                        variant={applied === card.name ? 'filled' : 'light'}
                        loading={applying === `style:${card.styleId}`}
                        disabled={applying !== null}
                        onClick={() => void applyPatch(
                          `style:${card.styleId}`, { __style: card.styleId }, card.name)}
                        data-testid={`apply-${card.styleId}`}
                      >
                        应用
                      </Button>
                    </Group>
                    {selected && (
                      <Stack gap={2} mt={6}>
                        {detailLoading && <Text size="xs" c="dark.3">加载完整卡…</Text>}
                        {!detailLoading && !detail && (
                          <Text size="xs" c="dark.3">
                            离线模式：启动后端查看完整卡（stages/params）；离线时「应用」会显式报错。
                          </Text>
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
                  </div>
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
