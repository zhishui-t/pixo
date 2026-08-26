import { useMemo } from 'react';
import { DESIGN_TOKENS as T } from '../theme/tokens';
import { ActionIcon, Badge, Group, NumberInput, Paper, ScrollArea, Select, Text, UnstyledButton } from '@mantine/core';
import { Star } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import type { ColorLabel, Photo } from '../types';

// 域标签色板：红/黄/绿/蓝/紫为用户数据标记色（Lightroom 惯例），
// 属数据色而非主题色，故不纳入 DESIGN_TOKENS。
const COLORS: Array<{ id: ColorLabel; label: string; bg: string }> = [
  { id: 'red', label: '红', bg: '#ff6b6b' },
  { id: 'yellow', label: '黄', bg: '#ffd43b' },
  { id: 'green', label: '绿', bg: '#69db7c' },
  { id: 'blue', label: '蓝', bg: '#4dabf7' },
  { id: 'purple', label: '紫', bg: '#da77f2' },
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
    <Paper radius="lg" p="md" style={{ height: 240, background: T.panel, border: `1px solid ${T.hairline}`, boxShadow: T.shadowMd }}>
      <Group gap="sm" mb="sm">
        <NumberInput
          size="xs"
          placeholder="星级"
          min={0}
          max={5}
          value={filmFilter.rating ?? ''}
          onChange={(value) => setFilmFilter({ rating: typeof value === 'number' ? value : null })}
          w={78}
          radius="md"
        />
        <Select
          size="xs"
          placeholder="颜色"
          value={filmFilter.color || null}
          onChange={(value) => setFilmFilter({ color: (value as ColorLabel | null) ?? '' })}
          data={COLORS.map((c) => ({ value: c.id, label: c.label }))}
          w={90}
          radius="md"
        />
        <Select
          size="xs"
          value={filmFilter.status}
          onChange={(value) => setFilmFilter({ status: value ?? '全部' })}
          data={['全部', 'pending', 'processing', 'accepted', 'review'].map((v) => ({ value: v, label: v }))}
          w={105}
          radius="md"
        />
        <Select
          size="xs"
          placeholder="场景"
          value={filmFilter.scene || null}
          onChange={(value) => setFilmFilter({ scene: value ?? '' })}
          data={['portrait', 'landscape', 'night', 'street'].map((v) => ({ value: v, label: v }))}
          w={105}
          radius="md"
        />
        <Select
          size="xs"
          value={sortBy}
          onChange={(value) => setSortBy((value as 'name' | 'rating' | 'date') ?? 'name')}
          data={[{ value: 'name', label: '文件名' }, { value: 'rating', label: '星级' }, { value: 'date', label: '时间' }]}
          w={92}
          radius="md"
        />
      </Group>
      <ScrollArea style={{ height: 172 }}>
        <Group gap="md" wrap="nowrap" align="flex-start">
          {visible.map((photo) => {
            const active = activePhotoId === photo.id;
            return (
              <UnstyledButton key={photo.id} onClick={() => selectPhoto(photo.id)}>
                <Paper
                  className="film-card"
                  radius="md"
                  p={8}
                  w={164}
                  style={{
                    background: T.overlay,
                    border: active ? `1px solid ${T.accent}` : `1px solid ${T.hairline}`,
                    boxShadow: active ? `0 0 0 3px ${T.selection}, ${T.shadowLg}` : T.shadowMd,
                    transition: 'transform .15s ease, box-shadow .15s ease',
                  }}
                >
                  <img src={photo.thumbnail} alt={photo.name} style={{ width: '100%', borderRadius: 8, aspectRatio: '3/2', objectFit: 'cover' }} />
                  <Group gap={5} mt={8}>
                    {COLORS.map((c) => (
                      <ActionIcon
                        key={c.id}
                        size="xs"
                        variant="transparent"
                        onClick={(e) => { e.stopPropagation(); toggleColor(photo, c.id); }}
                      >
                        <span style={{ width: 10, height: 10, borderRadius: 5, background: c.bg, boxShadow: photo.colorLabel === c.id ? `0 0 8px ${c.bg}` : 'none', opacity: photo.colorLabel === c.id ? 1 : 0.65 }} />
                      </ActionIcon>
                    ))}
                  </Group>
                  <Group gap={1} mt={4}>
                    {[1, 2, 3, 4, 5].map((n) => (
                      <ActionIcon key={n} size="sm" variant="transparent" onClick={(e) => { e.stopPropagation(); setPhotoRating(activeProjectId, photo.id, n); }}>
                        <Star size={13} fill={(photo.rating ?? 0) >= n ? T.semantic.warning : 'transparent'} color={(photo.rating ?? 0) >= n ? T.semantic.warning : T.textSecondary} />
                      </ActionIcon>
                    ))}
                  </Group>
                  <Text size="xs" truncate mt={4}>{photo.name}</Text>
                  {photo.burstGroup && <Badge size="xs" variant="light" color="indigo" mt={4}>{photo.burstGroup}</Badge>}
                </Paper>
              </UnstyledButton>
            );
          })}
          {visible.length === 0 && <div className="empty-note">暂无照片</div>}
        </Group>
      </ScrollArea>
    </Paper>
  );
}
