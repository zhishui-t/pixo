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
  // TODO(backend)：后端目前只有 /api/sessions/{id}/image（处理图），
  // 没有 original 原图端点。接入前统一返回 mock 原图占位，
  // 避免把处理图误当原图接进对比视图（Split 左侧/原图模式）。
  void sessionId;
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
