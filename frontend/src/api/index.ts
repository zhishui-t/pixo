import type { ParamPatch, Photo, Project, StyleCardData } from '../types';
import {
  createPhoto as createPhotoRemote,
  getExportStatus as getExportStatusRemote,
  getHealth as getHealthRemote,
  getPhotos as getPhotosRemote,
  patchParams as patchParamsRemote,
  previewUrl as remotePreviewUrl,
  submitExport as submitExportRemote,
  type HealthResponse,
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
    const photos = await getPhotosRemote();
    backendAvailable = true;
    return { photos, backend: true };
  } catch {
    backendAvailable = false;
    return { photos: mockGetPhotos(), backend: false };
  }
}

export async function health(): Promise<HealthResponse & { backend: boolean }> {
  try {
    const result = await getHealthRemote();
    backendAvailable = true;
    return { ...result, backend: true };
  } catch {
    backendAvailable = false;
    return { ok: true, native: true, backend: false };
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

export async function patchParams(
  patch: ParamPatch,
  source: string,
): Promise<{ generation: number; params: ParamPatch; canonical: ParamPatch }> {
  if (backendAvailable !== false) {
    try {
      return await patchParamsRemote('demo-session', patch, source);
    } catch {
      backendAvailable = false;
    }
  }
  return mockPatchParams(patch);
}

export async function submitExport(
  fmt = 'jpeg',
  quality = 88,
): Promise<{ task_id: string; status: string }> {
  if (backendAvailable !== false) {
    try {
      return await submitExportRemote('demo-session', fmt, quality);
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
      const data = await getExportStatusRemote(taskId);
      const task = data.task as Record<string, unknown>;
      return { task, progress: Number(task.progress ?? 0) };
    } catch {
      backendAvailable = false;
    }
  }
  return { task: { task_id: taskId, status: 'completed' }, progress: 1 };
}

export function getMockSessionId(): string {
  return 'demo-session';
}

export function getPreviewSource(generation: number): string {
  if (backendAvailable) {
    return remotePreviewUrl('demo-session', generation);
  }
  return mockPreviewDataUrl(generation, true);
}

export function getOriginalSource(): string {
  return mockPreviewDataUrl(0, false);
}

export function getMockCandidateList(): Array<{ path: string; name: string; size: number }> {
  return mockScanDirectory();
}

export function getMockPhotoList(): Photo[] {
  return mockGetPhotos();
}

export function fetchProjects(): Project[] {
  return mockGetProjects();
}

export function fetchStyleCards(): StyleCardData[] {
  return mockGetStyleCards();
}
