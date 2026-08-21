import type { ParamPatch, Photo } from '../types';

export const API_BASE: string =
  import.meta.env.VITE_PIXO_API_URL ?? 'http://localhost:8000';

export interface ApiResponse<T> {
  data?: T;
  error?: string;
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers ?? {}) },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`pixo-service ${res.status}: ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

export async function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/api/health');
}

export async function getPhotos(): Promise<Photo[]> {
  const data = await request<{ photos: Photo[] }>('/api/photos');
  return data.photos;
}

export async function getPhotoDetail(photoId: string): Promise<Photo> {
  const data = await request<{ photo: Photo }>(`/api/photos/${photoId}`);
  return data.photo;
}

export async function createPhoto(path: string): Promise<Photo> {
  const data = await request<{ photo: Photo }>('/api/photos', {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
  return data.photo;
}

export async function patchParams(
  sessionId: string,
  patch: ParamPatch,
  source: string,
): Promise<{ generation: number; params: ParamPatch; canonical: ParamPatch }> {
  return request(`/api/sessions/${sessionId}/params`, {
    method: 'PUT',
    body: JSON.stringify({ ...patch, __source: source }),
  });
}

export async function submitExport(
  sessionId: string,
  fmt = 'jpeg',
  quality = 88,
): Promise<{ task_id: string; status: string }> {
  return request(`/api/sessions/${sessionId}/exports`, {
    method: 'POST',
    body: JSON.stringify({ fmt, quality }),
  });
}

export async function getExportStatus(taskId: string): Promise<{ task: Record<string, unknown> }> {
  return request(`/api/exports/${taskId}`);
}

export interface HealthResponse {
  ok: boolean;
  native: boolean;
  versions?: Record<string, string>;
}

export function previewUrl(
  sessionId: string,
  generation: number,
  longEdge = 1024,
): string {
  return `${API_BASE}/api/sessions/${sessionId}/image?gen=${generation}&long_edge=${longEdge}&fmt=jpeg`;
}
