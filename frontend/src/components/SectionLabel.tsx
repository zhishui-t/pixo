import type { ReactNode } from 'react';

/** 小节微标签：大写 + 宽字距（t76 参数分组小节标题）。 */
export function SectionLabel({ children }: { children: ReactNode }) {
  return <div className="section-label">{children}</div>;
}
