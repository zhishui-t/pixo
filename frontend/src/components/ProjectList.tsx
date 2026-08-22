import { useState } from 'react';
import { useAppStore } from '../store/useAppStore';

export function ProjectList() {
  const projects = useAppStore((s) => s.projects);
  const activeProjectId = useAppStore((s) => s.activeProjectId);
  const selectProject = useAppStore((s) => s.selectProject);
  const addProject = useAppStore((s) => s.addProject);
  const [name, setName] = useState('');
  const [query, setQuery] = useState('');

  const create = () => {
    const value = name.trim();
    if (!value) return;
    addProject(value);
    setName('');
  };

  const visible = projects.filter((p) => p.name.toLowerCase().includes(query.toLowerCase()));

  return (
    <aside className="project-list">
      <div className="project-list-header">
        <span>项目</span>
        <button className="btn btn-mini" onClick={create}>新建</button>
      </div>
      <input
        className="project-search"
        placeholder="搜索项目"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="project-items">
        {visible.map((project) => (
          <button
            key={project.id}
            className={`project-item ${activeProjectId === project.id ? 'active' : ''}`}
            onClick={() => selectProject(project.id)}
          >
            <span className="project-name">{project.name}</span>
            <span className="project-meta">{project.photoIds.length} 张 · {project.createdAt}</span>
          </button>
        ))}
      </div>
      <div className="new-project-row">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && create()}
          placeholder="新项目名称"
        />
        <button className="btn btn-mini" onClick={create}>+</button>
      </div>
    </aside>
  );
}
