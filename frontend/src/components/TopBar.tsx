import { useAppStore } from '../store/useAppStore';
import { createPhotoRaw, getMockCandidateList, pollExport, submitExport } from '../api';

export function TopBar() {
  const page = useAppStore((s) => s.page);
  const setPage = useAppStore((s) => s.setPage);
  const backend = useAppStore((s) => s.backend);

  const handleImport = async () => {
    const candidates = getMockCandidateList();
    const first = candidates[0];
    if (first) {
      await createPhotoRaw(first.path);
      const photo = getMockCandidateList()[0];
      // 导入入口在本地 demo 中先反馈状态；真实后端接入后走 /api/import。
      window.alert(`已导入 ${photo.name}`);
    }
  };

  const handleExport = async () => {
    const submitted = await submitExport('jpeg', 88);
    const result = await pollExport(submitted.task_id);
    window.alert(`导出任务 ${submitted.task_id}：${Math.round(result.progress * 100)}%`);
  };

  return (
    <header className="topbar">
      <div className="topbar-left">
        <span className="brand">Pixo</span>
        <button className="btn" onClick={handleImport}>导入</button>
        <button
          className={`btn ${page === 'review' ? 'btn-active' : ''}`}
          onClick={() => setPage('review')}
        >
          复核队列
        </button>
        <button
          className={`btn ${page === 'settings' ? 'btn-active' : ''}`}
          onClick={() => setPage('settings')}
        >
          设置
        </button>
      </div>
      <div className="topbar-right">
        <button className="btn" onClick={handleExport}>导出</button>
        <span className={`status-dot ${backend ? 'online' : 'mock'}`} />
        <span>{backend ? 'pixo-service' : 'mock 数据'}</span>
        <button className="btn" onClick={() => setPage('workspace')}>返回工作区</button>
      </div>
    </header>
  );
}
