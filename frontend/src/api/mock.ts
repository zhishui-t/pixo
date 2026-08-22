import type {
  AgentSuggestion,
  ChatMessage,
  ParamPatch,
  Photo,
  Project,
  ReviewItem,
  StyleCardData,
} from '../types';

let generation = 12;
let sessionId = 'demo-session';
let params: ParamPatch = {
  exposure: { ev: 0.28, mode: 'auto' },
  whitebalance: { mode: 'as_shot', temp: 5200, tint: 0 },
  tone: { highlights: -20, shadows: 10, contrast: 0.1 },
  colorcal: { saturation: 0.05, vibrance: 0.1 },
  refine: { sharpen: 0.2, chroma_denoise: 0.5 },
};

export function resetMockSession(): void {
  generation = 12;
  sessionId = 'demo-session';
  params = {
    exposure: { ev: 0.28, mode: 'auto' },
    whitebalance: { mode: 'as_shot', temp: 5200, tint: 0 },
    tone: { highlights: -20, shadows: 10, contrast: 0.1 },
    colorcal: { saturation: 0.05, vibrance: 0.1 },
    refine: { sharpen: 0.2, chroma_denoise: 0.5 },
  };
}

function svgThumb(seed: number, label: string, processed = false): string {
  const hue = (seed * 47) % 360;
  const hue2 = (hue + 40) % 360;
  const brightness = processed ? 0.82 : 0.62;
  const c1 = `hsl(${hue},38%,${brightness * 100}%)`;
  const c2 = `hsl(${hue2},42%,${(brightness * 0.65) * 100}%)`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="160">
    <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="${c1}"/><stop offset="100%" stop-color="${c2}"/></linearGradient></defs>
    <rect width="240" height="160" fill="${processed ? '#2e3338' : '#22262b'}" />
    <rect x="20" y="20" width="200" height="120" rx="8" fill="url(#g)" opacity="0.9" />
    <text x="120" y="90" text-anchor="middle" fill="white" font-size="14" font-family="sans-serif">${label}</text>
  </svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

const mockPhotos: Photo[] = [
  { id: 'p1', name: 'DSC_5236.NEF', path: '/photos/DSC_5236.NEF', camera: 'Nikon Z 5', takenAt: '2026-08-18 17:32', status: 'processing', burstGroup: 'BURST_001', scene: 'portrait', rating: 4, colorLabel: 'yellow', thumbnail: svgThumb(1, '5236') },
  { id: 'p2', name: 'DSC_5237.NEF', path: '/photos/DSC_5237.NEF', camera: 'Nikon Z 5', takenAt: '2026-08-18 17:32', status: 'review', burstGroup: 'BURST_001', scene: 'portrait', rating: 5, colorLabel: 'red', thumbnail: svgThumb(2, '5237') },
  { id: 'p3', name: 'DSC_5238.NEF', path: '/photos/DSC_5238.NEF', camera: 'Nikon Z 5', takenAt: '2026-08-18 17:32', status: 'pending', burstGroup: 'BURST_001', scene: 'portrait', rating: 0, thumbnail: svgThumb(3, '5238') },
  { id: 'p4', name: 'DSC_5310.NEF', path: '/photos/DSC_5310.NEF', camera: 'Nikon Z 5', takenAt: '2026-08-19 09:02', status: 'accepted', burstGroup: 'BURST_002', scene: 'landscape', rating: 3, colorLabel: 'green', thumbnail: svgThumb(4, '5310') },
  { id: 'p5', name: 'DSC_5331.NEF', path: '/photos/DSC_5331.NEF', camera: 'Nikon Z 5', takenAt: '2026-08-19 19:11', status: 'pending', scene: 'night', rating: 2, colorLabel: 'blue', thumbnail: svgThumb(5, '5331') },
  { id: 'p6', name: 'IMG_2209.JPG', path: '/photos/IMG_2209.JPG', camera: 'iPhone 15 Pro', takenAt: '2026-08-20 12:40', status: 'imported', scene: 'street', rating: 1, colorLabel: 'purple', thumbnail: svgThumb(6, '2209') },
];

const mockProjects: Project[] = [
  { id: 'prj1', name: '夏末人像', createdAt: '2026-08-18', photoIds: ['p1', 'p2', 'p3'] },
  { id: 'prj2', name: '城市夜景', createdAt: '2026-08-20', photoIds: ['p4', 'p5', 'p6'] },
];

const mockStyleCards: StyleCardData[] = [
  {
    styleId: 'kodak_portra_400',
    name: 'Kodak Portra 400',
    description: '柔和低反差、肤色暖粉、高光软滚降的经典胶片感。',
    tags: { scene: ['portrait', 'wedding'], light: ['golden_hour'] },
    colorFingerprint: { skin_lab_target: { a: 18, b: 20 } },
    toneFingerprint: { contrast_tendency: 'low', highlight_rolloff: 'soft' },
    recommendedAdjustments: { exposure: -0.1, tone_contrast: 0.05 },
  },
  {
    styleId: 'fuji_pro_400h',
    name: 'Fuji Pro 400H',
    description: '柔和通透、空气感强，适合阴天与户外人像。',
    tags: { scene: ['landscape', 'portrait'], light: ['overcast'] },
    colorFingerprint: { skin_lab_target: { a: 14, b: 16 } },
    toneFingerprint: { contrast_tendency: 'medium', shadow_depth: 'airy' },
    recommendedAdjustments: { contrast: 0.05, clarity: 0.08 },
  },
];

export function mockGetPhotos(): Photo[] {
  return mockPhotos;
}

export function mockCreatePhoto(path: string): Photo {
  const id = `p${Date.now()}`;
  const name = path.split(/[\\/]/).pop() ?? path;
  const photo: Photo = {
    id,
    name,
    path,
    camera: 'Unknown',
    takenAt: '2026-08-21 00:00',
    status: 'imported',
    thumbnail: svgThumb(7, name.slice(0, 8)),
  };
  mockPhotos.unshift(photo);
  return photo;
}

export function mockScanDirectory(): Array<{ path: string; name: string; size: number }> {
  return mockPhotos.map((p) => ({ path: p.path, name: p.name, size: 1024 * 1024 * 24 }));
}

export function mockPatchParams(patch: ParamPatch): {
  generation: number;
  params: ParamPatch;
  canonical: ParamPatch;
} {
  generation += 1;
  params = {
    ...params,
    ...Object.fromEntries(
      Object.entries(patch).map(([stage, values]) => [
        stage,
        { ...(params[stage] ?? {}), ...values },
      ]),
    ),
  };
  return { generation, params, canonical: params };
}

export interface MockSession {
  sessionId: string;
  generation: number;
  params: ParamPatch;
}

export function mockSession(): MockSession {
  return { sessionId, generation, params };
}

export function mockPreviewDataUrl(generationValue: number, processed: boolean): string {
  return svgThumb(8 + (generationValue % 10), processed ? `P${generationValue}` : 'ORIGINAL', processed);
}

export const mockSuggestions: AgentSuggestion[] = [
  {
    id: 's1',
    title: '提亮人脸 +0.28 EV',
    reason: 'face_luminance 95 < target 115',
    confidence: 0.87,
    patch: { exposure: { ev: 0.28 } },
  },
  {
    id: 's2',
    title: '压暗高光 -20',
    reason: 'highlight_clip 0.4% within safe range',
    confidence: 0.72,
    patch: { tone: { highlights: -20 } },
  },
];

export const mockMessages: ChatMessage[] = [
  { id: 'm1', role: 'agent', text: '检测到人脸偏暗，建议提亮曝光。', suggestion: mockSuggestions[0] },
  { id: 'm2', role: 'user', text: '好的，先看效果。' },
];

export const mockReviewItems: ReviewItem[] = [
  { id: 'r1', photoName: 'DSC_5237.NEF', reason: 'FINAL_QC 高光溢出 3.2%', ruleIds: ['qc_rollback_rule'], state: 'pending' },
  { id: 'r2', photoName: 'DSC_5310.NEF', reason: 'face region unreliable', ruleIds: ['face_rule'], state: 'pending' },
];

export function mockGetProjects(): Project[] {
  return mockProjects;
}

export function mockGetStyleCards(): StyleCardData[] {
  return mockStyleCards;
}
