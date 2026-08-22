import { useState } from 'react';
import { useAppStore } from '../store/useAppStore';

export function StyleAiPanel() {
  const activeProjectId = useAppStore((s) => s.activeProjectId);
  const styleCards = useAppStore((s) => s.styleCards);
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
    <div className="style-ai-panel">
      <div className="panel-block">
        <div className="panel-title">风格卡片</div>
        <div className="style-cards">
          {styleCards.map((card) => (
            <div key={card.styleId} className="style-card">
              <div className="style-card-name">{card.name}</div>
              <div className="style-card-desc">{card.description}</div>
              <div className="style-card-tags">
                {Object.entries(card.tags).map(([group, tags]) => (
                  <span key={group} className="style-tag">{group}: {tags.join('/')}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel-block">
        <div className="panel-title">AI 推荐</div>
        {suggestions.map((s) => (
          <div key={s.id} className="suggestion-card">
            <div className="suggestion-title">{s.title}</div>
            <div className="suggestion-reason">{s.reason}</div>
            <div className="suggestion-conf">置信度 {Math.round(s.confidence * 100)}%</div>
            <div className="suggestion-actions">
              <button className="btn btn-primary" onClick={() => applyProjectSuggestion(activeProjectId, s)}>应用</button>
              <button className="btn" onClick={() => ignoreProjectSuggestion(activeProjectId, s.id)}>忽略</button>
              <button className="btn">编辑</button>
            </div>
          </div>
        ))}
        {suggestions.length === 0 && <div className="empty-note">暂无推荐</div>}
      </div>

      <div className="panel-block agent-conversation">
        <div className="panel-title">当前项目对话</div>
        <div className="agent-messages">
          {messages.map((m) => (
            <div key={m.id} className={`msg msg-${m.role}`}>{m.text}</div>
          ))}
        </div>
        <div className="agent-input">
          <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && send()} placeholder="询问修图建议…" />
          <button className="btn btn-primary" onClick={send}>发送</button>
        </div>
      </div>
    </div>
  );
}
