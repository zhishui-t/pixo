import { Badge, Button, Card, Group, Stack, Text, Title } from '@mantine/core';
import { DESIGN_TOKENS as T, WARNING_COLOR } from '../theme/tokens';
import { useAppStore } from '../store/useAppStore';

export function ReviewQueue() {
  const items = useAppStore((s) => s.reviewItems);
  const markReview = useAppStore((s) => s.markReview);
  const setPage = useAppStore((s) => s.setPage);

  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.hairline}`,
        borderRadius: 12,
        padding: 24,
        maxWidth: 1080,
        margin: '0 auto',
        boxShadow: T.shadowMd,
      }}
    >
      <Stack gap="md">
        <Title order={3} c={T.textPrimary}>人工复核队列</Title>
      {items.length === 0 && (
        <div className="empty-note" style={{ marginBottom: 16 }}>
          队列已清空：所有照片均完成人工复核。可前往工作台继续修图，
          或回资料库挑选下一批照片。
        </div>
      )}
      <Group align="flex-start" gap="md">
        <Stack gap="sm" w={360}>
          {items.map((item) => (
            <Card key={item.id} radius="md" withBorder style={{ background: T.overlay, borderColor: T.hairline }}>
              <Text fw={600}>{item.photoName}</Text>
              <Text size="sm" style={{ color: WARNING_COLOR }} mt={4}>{item.reason}</Text>
              <Group gap={4} mt={4}>
                {item.ruleIds.map((rule) => (
                  <Badge key={rule} size="xs" variant="light"
                    style={{ backgroundColor: 'rgba(217,154,43,0.15)', color: WARNING_COLOR }}
                  >{rule}</Badge>
                ))}
              </Group>
              <Group mt="sm">
                <Button size="xs" onClick={() => markReview(item.id, 'accepted')}>接受</Button>
                <Button size="xs" variant="light" onClick={() => markReview(item.id, 'rejected')}>拒绝</Button>
                <Button size="xs" variant="subtle" onClick={() => setPage('workspace')}>编辑</Button>
              </Group>
            </Card>
          ))}
        </Stack>
      </Group>
      </Stack>
    </div>
  );
}
