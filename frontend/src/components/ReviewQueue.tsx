import { useAppStore } from '../store/useAppStore';

export function ReviewQueue() {
  const items = useAppStore((s) => s.reviewItems);
  const markReview = useAppStore((s) => s.markReview);
  const setPage = useAppStore((s) => s.setPage);

  return (
    <main className="page review-page">
      <h1>人工复核队列</h1>
      <div className="review-layout">
        <div className="review-list">
          {items.map((item) => (
            <div key={item.id} className={`review-card review-${item.state}`}>
              <div className="review-name">{item.photoName}</div>
              <div className="review-reason">{item.reason}</div>
              <div className="review-rules">rules: {item.ruleIds.join(', ')}</div>
              <div className="review-actions">
                <button className="btn btn-primary" onClick={() => markReview(item.id, 'accepted')}>接受</button>
                <button className="btn" onClick={() => markReview(item.id, 'rejected')}>拒绝</button>
                <button className="btn" onClick={() => setPage('workspace')}>编辑</button>
              </div>
            </div>
          ))}
        </div>
        <div className="review-detail">
          <div className="detail-placeholder">对比视图（原图 / 处理图）占位</div>
          <div className="detail-placeholder">原因、rule_hits、Agent 建议展示区</div>
        </div>
      </div>
    </main>
  );
}
