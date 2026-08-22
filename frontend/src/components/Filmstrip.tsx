import { useMemo } from 'react';
import { useAppStore } from '../store/useAppStore';
import type { ColorLabel, Photo } from '../types';

const COLOR_OPTIONS: Array<{ id: ColorLabel; label: string }> = [
  { id: 'red', label: '红' },
  { id: 'yellow', label: '黄' },
  { id: 'green', label: '绿' },
  { id: 'blue', label: '蓝' },
  { id: 'purple', label: '紫' },
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

  const renderStars = (photo: Photo) => (
    <span className="film-stars" onClick={(e) => e.stopPropagation()}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          className={`star ${(photo.rating ?? 0) >= n ? 'star-on' : ''}`}
          onClick={() => setPhotoRating(activeProjectId, photo.id, n)}
        >
          ★
        </button>
      ))}
    </span>
  );

  return (
    <div className="filmstrip">
      <div className="filmstrip-tools">
        <input
          type="number"
          placeholder="星级"
          min={0}
          max={5}
          value={filmFilter.rating ?? ''}
          onChange={(e) => setFilmFilter({ rating: e.target.value ? Number(e.target.value) : null })}
        />
        <select value={filmFilter.color} onChange={(e) => setFilmFilter({ color: e.target.value as ColorLabel | '' })}>
          <option value="">颜色</option>
          {COLOR_OPTIONS.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
        </select>
        <select value={filmFilter.status} onChange={(e) => setFilmFilter({ status: e.target.value })}>
          <option>全部</option>
          <option value="pending">待处理</option>
          <option value="processing">处理中</option>
          <option value="accepted">已接受</option>
          <option value="review">需复核</option>
        </select>
        <select value={filmFilter.scene} onChange={(e) => setFilmFilter({ scene: e.target.value })}>
          <option value="">场景</option>
          <option value="portrait">人像</option>
          <option value="landscape">风光</option>
          <option value="night">夜景</option>
          <option value="street">街拍</option>
        </select>
        <select value={sortBy} onChange={(e) => setSortBy(e.target.value as 'name' | 'rating' | 'date')}>
          <option value="name">文件名</option>
          <option value="rating">星级</option>
          <option value="date">时间</option>
        </select>
      </div>
      <div className="filmstrip-track">
        {visible.map((photo) => (
          <button
            key={photo.id}
            className={`film-item ${activePhotoId === photo.id ? 'active' : ''}`}
            onClick={() => selectPhoto(photo.id)}
          >
            <img src={photo.thumbnail} alt={photo.name} />
            <span className="film-color-row">
              {COLOR_OPTIONS.map((c) => (
                <span
                  key={c.id}
                  className={`color-dot color-${c.id} ${photo.colorLabel === c.id ? 'color-active' : ''}`}
                  onClick={(e) => { e.stopPropagation(); toggleColor(photo, c.id); }}
                  title={c.label}
                />
              ))}
            </span>
            {renderStars(photo)}
            <span className="film-name">{photo.name}</span>
            {photo.burstGroup && <span className="burst-tag">{photo.burstGroup}</span>}
          </button>
        ))}
        {visible.length === 0 && <div className="empty-note">当前项目暂无照片</div>}
      </div>
    </div>
  );
}
