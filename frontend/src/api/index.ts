import type {
  HealthInfo,
  ParamPatch,
  RegionMaskStatus,
  Photo,
  PhotoView,
  Project,
  Source,
  StyleCardData,
  StyleCardDetail,
} from '../types';
import {
  createSession as createSessionRemote,
  getExportStatus as getExportStatusRemote,
  getHealth as getHealthRemote,
  getRegionMasks as getRegionMasksRemote,
  PixoApiError,
  getStyle as getStyleRemote,
  listPhotos as listPhotosRemote,
  listStyles as listStylesRemote,
  originalUrl as remoteOriginalUrl,
  updateParams as updateParamsRemote,
  previewUrl as remotePreviewUrl,
  submitExport as submitExportRemote,
} from './client';
import {
  mockGetPhotos,
  mockGetProjects,
  mockGetRegionMaskStatus,
  mockGetStyleCards,
  mockPatchParams,
  mockPreviewDataUrl,
  mockScanDirectory,
} from './mock';

let backendAvailable: boolean | null = null;

export async function fetchPhotos(): Promise<{ photos: Photo[]; backend: boolean }> {
  try {
    const photos = await listPhotosRemote();
    backendAvailable = true;
    return { photos, backend: true };
  } catch {
    backendAvailable = false;
    return { photos: mockGetPhotos(), backend: false };
  }
}

/**
 * 后端 Photo → 前端 PhotoView：补齐 Filmstrip 依赖的展示字段。
 * - name：path 的文件名（去目录分隔符，兼容 / 与 \）。
 * - takenAt：created_at（排序键 'date' 用）。
 * - status：state（Filmstrip 状态过滤的数据源，见 types.ts STATUS_FILTER_SETS）。
 * - thumbnail：有会话时用首会话当前 generation 预览（gen 省略，服务端按会话
 *   当前代渲染）；无会话（RAW_PENDING 尚未建会话）时留 undefined，Filmstrip
 *   渲染 CSS 占位卡片。
 */
export function toPhotoView(photo: Photo): PhotoView {
  const name = photo.path.split(/[\\/]/).pop() ?? photo.photo_id;
  return {
    ...photo,
    name,
    takenAt: photo.created_at,
    status: photo.state,
    thumbnail: photo.sessions[0]
      ? remotePreviewUrl(photo.sessions[0], null, 512, 80)
      : undefined,
  };
}

export async function health(): Promise<HealthInfo & { backend: boolean }> {
  try {
    const result = await getHealthRemote();
    backendAvailable = true;
    return { ...result, backend: true };
  } catch {
    backendAvailable = false;
    // 后端不可达时用最小形状占位（UI 只读 status/segmenter 等字段）
    return {
      status: 'degraded',
      service: 'pixo-service',
      version: 'unknown',
      vision: {},
      segmenter: { router: 'mock', part_prompts: [] },
      photos: 0,
      sessions: 0,
      backend: false,
    };
  }
}

/** 为照片创建真实会话（后端可用时）；返回 session_id。 */
export async function ensureSession(photoId: string): Promise<string> {
  if (backendAvailable !== false) {
    try {
      const session = await createSessionRemote(photoId);
      backendAvailable = true;
      return session.session_id;
    } catch {
      backendAvailable = false;
    }
  }
  return getMockSessionId();
}

function regionUnavailable(reason: string): RegionMaskStatus {
  return { available: false, prompts: [], reason };
}

/**
 * 区域掩码状态（R14 B1 收紧语义）：
 *  1. 真离线（backendAvailable === false）→ mock 恒可用（离线开发态，
 *     唯一装可用的分支）；
 *  2. 无会话（sessionId=null，尚未 ensureSession）→ 未激活态
 *     （session_not_ready），不装可用；
 *  3. 后端在线：真实会话 GET——404（会话不存在/过期）→ 显式错误态
 *     （session_not_found）；其余失败（网络/5xx/端点未实施）→ 显式错误态
 *     （fetch_failed）。两种错误态均不回退 mock 恒可用——真实后端语义
 *     必须到达 UI（tester B1 回归面）。
 * backendAvailable 全局信号不被本函数修改（子端点失败 ≠ 后端不在线）。
 */
export async function fetchRegionMaskStatus(
  sessionId: string | null,
): Promise<RegionMaskStatus> {
  if (backendAvailable === false) {
    return mockGetRegionMaskStatus();          // 真离线：mock（唯一可用分支）
  }
  if (!sessionId) {
    return regionUnavailable('session_not_ready');
  }
  try {
    return await getRegionMasksRemote(sessionId);
  } catch (err) {
    if (err instanceof PixoApiError && err.status === 404) {
      return regionUnavailable('session_not_found');
    }
    return regionUnavailable('fetch_failed');
  }
}

export async function patchParams(
  patch: ParamPatch,
  source: Source,
  sessionId: string,
): Promise<{ generation: number; params: ParamPatch; canonical: ParamPatch }> {
  if (backendAvailable !== false) {
    try {
      return await updateParamsRemote(sessionId, patch, source);
    } catch {
      backendAvailable = false;
    }
  }
  return mockPatchParams(patch);
}

/**
 * R22 F04/F05 —— 应用「卡/场景装配 patch」的**严格**通道。
 *
 * 与 `patchParams` 的关键差别（用户偏好：失败不能静默无效）：
 *   - **不做 mock 回退**：在线失败绝不假装成功；
 *   - **保留后端错误**：400（参数栅栏拒绝，如未知 stage/键、数值域越界、
 *     lut_path）原样抛 PixoApiError，UI 能显示后端 detail；
 *   - 网络/5xx 也抛出（附离线标记），由调用方显式提示。
 */
export async function applyPresetPatch(
  patch: ParamPatch,
  source: Source,
  sessionId: string,
): Promise<{ generation: number; params: ParamPatch; canonical: ParamPatch }> {
  try {
    const result = await updateParamsRemote(sessionId, patch, source);
    backendAvailable = true;
    return result;
  } catch (err) {
    if (err instanceof PixoApiError) throw err;   // 保留 status/detail
    backendAvailable = false;
    throw new PixoApiError(0, `无法连接后端（未应用任何参数）：${String(err)}`);
  }
}

export async function submitExport(
  sessionId: string,
  fmt = 'jpeg',
  quality = 88,
): Promise<{ task_id: string; status: string }> {
  if (backendAvailable !== false) {
    try {
      const sub = await submitExportRemote(sessionId, fmt, quality);
      return { task_id: sub.task_id, status: sub.status };
    } catch {
      backendAvailable = false;
    }
  }
  return { task_id: 'mock-export', status: 'queued' };
}

export async function pollExport(
  taskId: string,
): Promise<{ task: Record<string, unknown>; progress: number }> {
  if (backendAvailable !== false && taskId !== 'mock-export') {
    try {
      const task = await getExportStatusRemote(taskId);
      // ExportTask 无 progress 字段：按状态推断（completed=100%）
      const progress = task.status === 'completed' ? 1 : 0;
      return { task: task as unknown as Record<string, unknown>, progress };
    } catch {
      backendAvailable = false;
    }
  }
  return { task: { task_id: taskId, status: 'completed' }, progress: 1 };
}

export function getMockSessionId(): string {
  return 'demo-session';
}

export function getPreviewSource(sessionId: string, generation: number): string {
  if (backendAvailable) {
    return remotePreviewUrl(sessionId, generation);
  }
  return mockPreviewDataUrl(generation, true);
}

export function getOriginalSource(sessionId: string): string {
  // 契约：GET /api/sessions/{id}/image?original=1&long_edge=...（decode-only、
  // 无调整的原图；无 gen 参数——原图与 generation 无关）。后端在线时直连该
  // URL；端点落地前线上会 404（或 demo-session 未建会话时 404），由
  // PreviewViewer 的 img onError 回退 getMockOriginalSource()，不闪断。
  if (backendAvailable) {
    return remoteOriginalUrl(sessionId);
  }
  return mockPreviewDataUrl(0, false);
}

/** 原图加载失败（在线契约端点 404 / 网络错误）时的本地占位，与离线模式同源。 */
export function getMockOriginalSource(): string {
  return mockPreviewDataUrl(0, false);
}

export function getMockCandidateList(): Array<{ path: string; name: string; size: number }> {
  return mockScanDirectory();
}

export function getMockPhotoList(): PhotoView[] {
  return mockGetPhotos();
}

export function fetchProjects(): Project[] {
  return mockGetProjects();
}

/** 风格卡列表（t60 接线）：后端 GET /api/styles 优先，离线回退 mock。 */
export async function fetchStyleCards(): Promise<StyleCardData[]> {
  try {
    const styles = await listStylesRemote();
    backendAvailable = true;
    return styles.map((s) => ({
      styleId: s.style_id,
      name: s.metadata.label,
      description: s.metadata.character,
      family: s.metadata.family,
      tags: s.metadata.tags,
      scenes: s.metadata.scenes,
      year: s.metadata.year ?? null,
    }));
  } catch {
    backendAvailable = false;
    return mockGetStyleCards();
  }
}

/** 完整风格卡（t60 接线）：后端在线时返回详情；离线（无后端）返回 null。 */
export async function fetchStyleDetail(styleId: string): Promise<StyleCardDetail | null> {
  try {
    return await getStyleRemote(styleId);
  } catch {
    return null;
  }
}
