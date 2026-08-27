import type {
  HealthInfo,
  ParamPatch,
  Photo,
  PhotoView,
  Project,
  Source,
  StyleCardData,
} from '../types';
import {
  createPhoto as createPhotoRemote,
  createSession as createSessionRemote,
  getExportStatus as getExportStatusRemote,
  getHealth as getHealthRemote,
  listPhotos as listPhotosRemote,
  originalUrl as remoteOriginalUrl,
  updateParams as updateParamsRemote,
  previewUrl as remotePreviewUrl,
  submitExport as submitExportRemote,
} from './client';
import {
  mockCreatePhoto,
  mockGetPhotos,
  mockGetProjects,
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

export async function createPhotoRaw(path: string): Promise<Photo> {
  if (backendAvailable !== false) {
    try {
      return await createPhotoRemote(path);
    } catch {
      backendAvailable = false;
    }
  }
  return mockCreatePhoto(path);
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

export function fetchStyleCards(): StyleCardData[] {
  return mockGetStyleCards();
}
