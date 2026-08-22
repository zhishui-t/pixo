import { useMemo } from 'react';
import { ActionIcon, Badge, Group, NumberInput, Paper, ScrollArea, Select, Text, UnstyledButton } from '@mantine/core';
import { useAppStore } from '../store/useAppStore';
import type { ColorLabel, Photo } from '../types';

const COLORS: Array<{ id: ColorLabel; label: string; bg: string }> = [
  { id: 'red', label: '红', bg: '#e03131' },
  { id: 'yellow', label: '黄', bg: '#f59f00' },
  { id: 'green', label: '绿', bg: '#2f9e44' },
  { id: 'blue', label: '蓝', bg: '#1971c2' },
  { id: 'purple', label: '紫', bg: '#9c36b5' },
];

export function Filmstrip() {
  const activeProjectId = useAppStore((s) => s.activeProjectId);
  const photos = useAppStore((s) => s.photosByProject[s.activeProjectId] ?? []);
  const activePhotoId = useAppStore((s) => s.activePhotoId);
  const filmFilter = useAppStore((s) => s.filmFilter);
  const sortBy = useAppStore((s) => s.sortBy);
  const setFilmFilter = useAppStore((s) => s.setFilmFilter);
  const setSortBy = useAppStore((s) => s.setSortBy);
  const selectPhoto = useAppStore((s) => s.selectPhoto);
  const setPhotoRating = useAppStore((s) => s.setPhotoRating);
  const setPhotoColor = useAppStore((s) => s.setPhotoColor);

  const visible = useMemo(() => {
    const filtered = photos.filter((photo) => {
      if (filmFilter.rating !== null && (photo.rating ?? 0) !== filmFilter.rating) return false;
      if (filmFilter.color && photo.colorLabel !== filmFilter.color) return false;
      if (filmFilter.status !== '全部' && photo.status !== filmFilter.status) return false;
      if (filmFilter.scene && photo.scene !== filmFilter.scene) return false;
      return true;
    });
    const list = [...filtered];
    if (sortBy === 'name') list.sort((a, b) => a.name.localeCompare(b.name));
    if (sortBy === 'rating') list.sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0));
    if (sortBy === 'date') list.sort((a, b) => (b.takenAt ?? '').localeCompare(a.takenAt ?? ''));
    return list;
  }, [photos, filmFilter, sortBy]);

  const toggleColor = (photo: Photo, color: ColorLabel) => {
    const next = photo.colorLabel === color ? undefined : color;
    setPhotoColor(activeProjectId, photo.id, next);
  };

  return (
    <Paper radius="md" withBorder p="xs" style={{ height: 205 }}>
      <Group gap="xs" mb="xs">
        <NumberInput
          size="xs"
          placeholder="星级"
          min={0}
          max={5}
          value={filmFilter.rating ?? ''}
          onChange={(value) => setFilmFilter({ rating: typeof value === 'number' ? value : null })}
          w={80}
        />
        <Select
          size="xs"
          placeholder="颜色"
          value={filmFilter.color || null}
          onChange={(value) => setFilmFilter({ color: (value as ColorLabel | null) ?? '' })}
          data={COLORS.map((c) => ({ value: c.id, label: c.label }))}
          w={90}
        />
        <Select
          size="xs"
          value={filmFilter.status}
          onChange={(value) => setFilmFilter({ status: value ?? '全部' })}
          data={['全部', 'pending', 'processing', 'accepted', 'review'].map((v) => ({ value: v, label: v }))}
          w={110}
        />
        <Select
          size="xs"
          placeholder="场景"
          value={filmFilter.scene || null}
          onChange={(value) => setFilmFilter({ scene: value ?? '' })}
          data={['portrait', 'landscape', 'night', 'street'].map((v) => ({ value: v, label: v }))}
          w={110}
        />
        <Select
          size="xs"
          value={sortBy}
          onChange={(value) => setSortBy((value as 'name' | 'rating' | 'date') ?? 'name')}
          data={[{ value: 'name', label: '文件名' }, { value: 'rating', label: '星级' }, { value: 'date', label: '时间' }]}
          w={95}
        />
      </Group>
      <ScrollArea style={{ height: 140 }}>
        <Group gap="sm" wrap="nowrap" align="flex-start">
          {visible.map((photo) => (
            <UnstyledButton key={photo.id} onClick={() => selectPhoto(photo.id)}>
              <Paper
                radius="md"
                withBorder
                p={6}
                w={140}
                style={{
                  borderColor: activePhotoId === photo.id ? 'var(--mantine-color-indigo-5)' : undefined,
                  background: activePhotoId === photo.id ? 'rgba(99,102,241,0.10)' : undefined,
                }}
              >
                <img src={photo.thumbnail} alt={photo.name} style={{ width: '100%', borderRadius: 6, aspectRatio: '3/2', objectFit: 'cover' }} />
                <Group gap={4} mt={6}>
                  {COLORS.map((c) => (
                    <ActionIcon
                      key={c.id}
                      size="xs"
                      variant="transparent"
                      onClick={(e) => { e.stopPropagation(); toggleColor(photo, c.id); }}
                      style={{ border: '1px solid var(--mantine-color-dark-4)' }}
                    >
                      <span style={{ width: 8, height: 8, borderRadius: 4, background: c.bg }} />
                    </ActionIcon>
                  ))}
                </Group>
                <Group gap={2} mt={4}>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <ActionIcon key={n} size="xs" variant="transparent" onClick={(e) => { e.stopPropagation(); setPhotoRating(activeProjectId, photo.id, n); }}>
                      <Text size="xs" c={(photo.rating ?? 0) >= n ? 'yellow.4' : 'dark.3'}>★</Text>
                    </ActionIcon>
                  ))}
                </Group>
                <Text size="xs" truncate>{photo.name}</Text>
                {photo.burstGroup && <Badge size="xs" variant="light" color="indigo" mt={4}>{photo.burstGroup}</Badge>}
              </Paper>
            </UnstyledButton>
          ))}
          {visible.length === 0 && <Text c="dimmed" size="sm">当前项目暂无照片</Text>}
        </Group>
      </ScrollArea>
    </Paper>
  );
}
