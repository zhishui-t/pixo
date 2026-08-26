import { useMemo } from 'react';
import { useAppStore } from '../store/useAppStore';
import type { Photo } from '../types';

const FILTERS = ['全部', '待处理', '处理中', '已接受', '需复核', '废片'];

function statusLabel(status: Photo['status']): string {
  const map: Record<Photo['status'], string> = {
    pending: '待处理',
    processing: '处理中',
    accepted: '已接受',
    review: '需复核',
    rejected: '废片',
    imported: '未导入',
  };
  return map[status] ?? status;
}

export function PhotoLibrary() {
  const photos = useAppStore((s) => s.photos);
  const activePhotoId = useAppStore((s) => s.activePhotoId);
  const filter = useAppStore((s) => s.filter);
  const search = useAppStore((s) => s.search);
  const setFilter = useAppStore((s) => s.setFilter);
  const setSearch = useAppStore((s) => s.setSearch);
  const selectPhoto = useAppStore((s) => s.selectPhoto);

  const filtered = useMemo(() => {
    return photos.filter((photo) => {
      const okFilter =
        filter === '全部' ||
        (filter === '需复核' && photo.status === 'review') ||
        (filter === '待处理' && photo.status === 'pending') ||
        (filter === '处理中' && photo.status === 'processing') ||
        (filter === '已接受' && photo.status === 'accepted') ||
        (filter === '废片' && photo.status === 'rejected');
      const okSearch =
        !search ||
        photo.name.toLowerCase().includes(search.toLowerCase()) ||
        photo.camera?.toLowerCase().includes(search.toLowerCase());
      return okFilter && okSearch;
    });
  }, [photos, filter, search]);

  const burstGroups = useMemo(() => {
    const groups = new Map<string, Photo[]>();
    for (const p of filtered) {
      if (!p.burstGroup) continue;
      const list = groups.get(p.burstGroup) ?? [];
      list.push(p);
      groups.set(p.burstGroup, list);
    }
    return Array.from(groups.entries());
  }, [filtered]);

  return (
    <aside className="library">
      <div className="library-search">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索文件名 / 相机"
        />
      </div>
      <div className="filter-chips">
        {FILTERS.map((f) => (
          <button
            key={f}
            className={`chip ${filter === f ? 'chip-active' : ''}`}
            onClick={() => setFilter(f)}
          >
            {f}
          </button>
        ))}
      </div>
      <div className="photo-grid">
        {filtered.length === 0 && (
          <div className="empty-note">暂无匹配照片</div>
        )}
        {filtered.map((photo) => (
          <button
            key={photo.id}
            className={`photo-card ${activePhotoId === photo.id ? 'active' : ''}`}
            onClick={() => selectPhoto(photo.id)}
          >
            <img src={photo.thumbnail} alt={photo.name} />
            <span className="photo-name">{photo.name}</span>
            <span className={`status-badge status-${photo.status}`}>
              {statusLabel(photo.status)}
            </span>
          </button>
        ))}
      </div>
      {burstGroups.length > 0 && (
        <div className="burst-section">
          <div className="section-title">连拍分组</div>
          {burstGroups.map(([groupId, items]) => (
            <details key={groupId} className="burst-group">
              <summary>
                {groupId} · {items.length} 张
              </summary>
              <div className="burst-mini">
                {items.map((p) => (
                  <img key={p.id} src={p.thumbnail} alt={p.name} />
                ))}
              </div>
            </details>
          ))}
        </div>
      )}
    </aside>
  );
}
