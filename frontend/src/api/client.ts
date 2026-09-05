/**
 * client —— pixo-service REST 薄封装（路由见 src/pixo/service/app.py）。
 * 返回类型如实标注，不做 as 强转；失败直接抛错，降级策略由 api/index.ts 决定。
 */
import type {
  DecideResult,
  ExportSubmission,
  ExportTask,
  HealthInfo,
  MeasurementsResult,
  ParamPatch,
  ParamsUpdateResult,
  Photo,
  SessionInfo,
  Source,
  StyleCardDetail,
  StyleSummary,
  TimelineInfo,
} from '../types';

export const API_BASE: string =
  import.meta.env.VITE_PIXO_API_URL ?? 'http://localhost:8000';

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers ?? {}) },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`pixo-service ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

/** GET /api/health */
export function getHealth(): Promise<HealthInfo> {
  return request<HealthInfo>('/api/health');
}

/** GET /api/photos */
export async function listPhotos(): Promise<Photo[]> {
  const data = await request<{ photos: Photo[] }>('/api/photos');
  return data.photos;
}

/** POST /api/photos/{photo_id}/sessions（201） */
export async function createSession(photoId: string): Promise<SessionInfo> {
  const data = await request<{ session: SessionInfo }>(
    `/api/photos/${photoId}/sessions`,
    { method: 'POST' },
  );
  return data.session;
}

/** PUT /api/sessions/{session_id}/params（深合并 + generation+1） */
export function updateParams(
  sessionId: string,
  patch: ParamPatch,
  source: Source,
): Promise<ParamsUpdateResult> {
  return request<ParamsUpdateResult>(`/api/sessions/${sessionId}/params`, {
    method: 'PUT',
    body: JSON.stringify({ ...patch, __source: source }),
  });
}

/**
 * GET /api/sessions/{session_id}/measurements
 *
 * 未接线（t61 清理判定：保留）——后端端点在，是"调参反馈环"UI
 * （参数改动 → 测量指标变化）的既有数据入口；契约稳定，保留封装
 * 避免届时重写类型。
 */
export function getMeasurements(
  sessionId: string,
  gen?: number,
): Promise<MeasurementsResult> {
  const query = gen !== undefined ? `?gen=${gen}` : '';
  return request<MeasurementsResult>(
    `/api/sessions/${sessionId}/measurements${query}`,
  );
}

/** POST /api/sessions/{session_id}/exports（202 异步任务） */
export function submitExport(
  sessionId: string,
  fmt: string,
  quality: number,
): Promise<ExportSubmission> {
  return request<ExportSubmission>(`/api/sessions/${sessionId}/exports`, {
    method: 'POST',
    body: JSON.stringify({ fmt, quality }),
  });
}

/** GET /api/exports/{task_id} */
export async function getExportStatus(taskId: string): Promise<ExportTask> {
  const data = await request<{ task: ExportTask }>(`/api/exports/${taskId}`);
  return data.task;
}

/**
 * GET /api/photos/{photo_id}/timeline
 *
 * 未接线（t61 清理判定：保留）——t48 轨迹回放已交付后端数据层
 * （trace_events + timeline 端点），前端时间线/回放 UI 是明确的
 * 下一步接线对象。
 */
export function getTimeline(photoId: string): Promise<TimelineInfo> {
  return request<TimelineInfo>(`/api/photos/${photoId}/timeline`);
}

/** GET /api/styles —— 风格卡列表（降载：style_id + metadata）。 */
export async function listStyles(): Promise<StyleSummary[]> {
  const data = await request<{ styles: StyleSummary[] }>('/api/styles');
  return data.styles;
}

/** GET /api/styles/{style_id} —— 完整风格卡。 */
export async function getStyle(styleId: string): Promise<StyleCardDetail> {
  const data = await request<{ style: StyleCardDetail }>(
    `/api/styles/${encodeURIComponent(styleId)}`);
  return data.style;
}

/**
 * GET|POST /api/photos/{photo_id}/decide
 *
 * 未接线（t61 清理判定：保留）——决策闭环的 HTTP 入口（POST 触发 /
 * GET 读缓存），t46 影子模式落地后前端触发面更依赖它。
 */
export function decidePhoto(photoId: string): Promise<DecideResult> {
  return request<DecideResult>(`/api/photos/${photoId}/decide`, {
    method: 'POST',
  });
}

/**
 * GET /api/sessions/{session_id}/image —— 预览图 URL。
 * gen 传 null 时省略 gen 参数，由服务端按会话当前 generation 渲染
 * （照片缩略图等不知 generation 的场景）。
 */
export function previewUrl(
  sessionId: string,
  gen: number | null,
  longEdge = 1024,
  quality = 88,
): string {
  const genQuery = gen !== null ? `&gen=${gen}` : '';
  return `${API_BASE}/api/sessions/${sessionId}/image?long_edge=${longEdge}&fmt=jpeg&quality=${quality}${genQuery}`;
}

/**
 * GET /api/sessions/{session_id}/image?original=1 —— decode-only 原图 URL。
 * 契约端点（无调整、与 generation 无关，故不带 gen 参数）；端点落地前
 * 请求可能 404，由调用方（api/index.getOriginalSource）负责回退占位。
 */
export function originalUrl(
  sessionId: string,
  longEdge = 1024,
  quality = 88,
): string {
  return `${API_BASE}/api/sessions/${sessionId}/image?original=1&long_edge=${longEdge}&fmt=jpeg&quality=${quality}`;
}
