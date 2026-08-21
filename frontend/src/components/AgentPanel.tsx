import { useState } from 'react';
import { useAppStore } from '../store/useAppStore';

export function AgentPanel() {
  const messages = useAppStore((s) => s.messages);
  const suggestions = useAppStore((s) => s.suggestions);
  const addMessage = useAppStore((s) => s.addMessage);
  const applySuggestion = useAppStore((s) => s.applySuggestion);
  const ignoreSuggestion = useAppStore((s) => s.ignoreSuggestion);
  const [text, setText] = useState('');

  const send = () => {
    const value = text.trim();
    if (!value) return;
    addMessage({ id: `u-${Date.now()}`, role: 'user', text: value });
    addMessage({
      id: `a-${Date.now()}`,
      role: 'agent',
      text: '已收到。当前为本地 mock 会话，接入 DSH 后这里会显示真实 Agent 回复。',
    });
    setText('');
  };

  return (
    <div className="agent-panel">
      <div className="agent-title">DSH Agent</div>
      <div className="agent-recommendations">
        {suggestions.map((s) => (
          <div key={s.id} className="suggestion-card">
            <div className="suggestion-title">{s.title}</div>
            <div className="suggestion-reason">{s.reason}</div>
            <div className="suggestion-conf">置信度 {Math.round(s.confidence * 100)}%</div>
            <div className="suggestion-actions">
              <button className="btn btn-primary" onClick={() => applySuggestion(s)}>应用并预览</button>
              <button className="btn" onClick={() => ignoreSuggestion(s.id)}>忽略</button>
              <button className="btn">编辑</button>
            </div>
          </div>
        ))}
        {suggestions.length === 0 && (
          <div className="empty-note">暂无待确认建议</div>
        )}
      </div>
      <div className="agent-messages">
        {messages.map((m) => (
          <div key={m.id} className={`msg msg-${m.role}`}>
            {m.text}
          </div>
        ))}
      </div>
      <div className="agent-input">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder="例如：把天空压暗一点…"
        />
        <button className="btn btn-primary" onClick={send}>发送</button>
      </div>
    </div>
  );
}
