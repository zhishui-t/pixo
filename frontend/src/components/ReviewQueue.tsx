import { Badge, Button, Card, Group, Stack, Text, Title } from '@mantine/core';
import { useAppStore } from '../store/useAppStore';

export function ReviewQueue() {
  const items = useAppStore((s) => s.reviewItems);
  const markReview = useAppStore((s) => s.markReview);
  const setPage = useAppStore((s) => s.setPage);

  return (
    <Stack gap="md">
      <Title order={3}>人工复核队列</Title>
      <Group align="flex-start" gap="md">
        <Stack gap="sm" w={360}>
          {items.map((item) => (
            <Card key={item.id} radius="md" withBorder>
              <Text fw={600}>{item.photoName}</Text>
              <Text size="sm" c="orange.4" mt={4}>{item.reason}</Text>
              <Group gap={4} mt={4}>
                {item.ruleIds.map((rule) => (
                  <Badge key={rule} size="xs" variant="light" color="orange">{rule}</Badge>
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
        <Card radius="md" withBorder style={{ flex: 1 }}>
          <Text c="dimmed">对比视图（原图 / 处理图）占位</Text>
        </Card>
      </Group>
    </Stack>
  );
}
