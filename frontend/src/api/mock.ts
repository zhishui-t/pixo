import type {
  ColorLabel,
  ParamPatch,
  Photo,
  PhotoView,
  Project,
  StyleCardData,
} from '../types';

let generation = 12;
let params: ParamPatch = {
  exposure: { mode: 'auto' },
  whitebalance: { mode: 'as_shot', temp: 5200, tint: 0 },
  tone: { highlights: -0.2, shadows: 0.1, contrast: 0.1 },
  colorcal: { saturation: 0.05, vibrance: 0.1 },
  refine: { sharpen: 0.2, chroma_denoise: 0.5 },
};

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

function mockPhoto(
  id: string,
  name: string,
  state: Photo['state'],
  iteration = 1,
  extra: Partial<PhotoView> = {},
): PhotoView {
  const seed = Array.from(id).reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
  return {
    photo_id: id,
    path: `/photos/${name}`,
    metadata: {},
    created_at: '2026-08-18T17:32:45',
    sessions: [],
    last_measurement: null,
    state,
    iteration,
    next_action: null,
    // PhotoView 展示字段（纯前端概念，后端 Photo 无这些键）：mock 模式下
    // Filmstrip 依赖 thumbnail/name 渲染卡片，并支撑星级/色标/状态/场景
    // 过滤与排序交互（见 components/Filmstrip.tsx）。
    name,
    thumbnail: svgThumb(seed, name),
    status: state,
    ...extra,
  };
}

const mockPhotos: PhotoView[] = [
  mockPhoto('p1', 'DSC_5236.NEF', 'BASE_RENDERED', 1, {
    rating: 4,
    colorLabel: 'yellow' as ColorLabel,
    scene: 'portrait',
    takenAt: '2026-08-18T17:32:45',
    burstGroup: 'BURST_001',
  }),
  mockPhoto('p2', 'DSC_5237.NEF', 'MANUAL_REVIEW', 1, {
    rating: 3,
    scene: 'portrait',
    takenAt: '2026-08-18T17:33:02',
    burstGroup: 'BURST_001',
  }),
  mockPhoto('p3', 'DSC_5238.NEF', 'SCREENED', 1, {
    rating: 5,
    colorLabel: 'blue' as ColorLabel,
    scene: 'portrait',
    takenAt: '2026-08-18T17:33:31',
  }),
  mockPhoto('p4', 'DSC_5310.NEF', 'ACCEPTED', 1, {
    rating: 4,
    scene: 'night',
    takenAt: '2026-08-20T21:14:10',
  }),
  mockPhoto('p5', 'DSC_5331.NEF', 'SCREENED', 1, {
    rating: 2,
    colorLabel: 'red' as ColorLabel,
    scene: 'night',
    takenAt: '2026-08-20T21:26:44',
  }),
  mockPhoto('p6', 'IMG_2209.JPG', 'RAW_PENDING', 0, {
    scene: 'street',
    takenAt: '2026-08-21T09:02:17',
  }),
];

const mockProjects: Project[] = [
  { id: 'prj1', name: '夏末人像', createdAt: '2026-08-18', photoIds: ['p1', 'p2', 'p3'] },
  { id: 'prj2', name: '城市夜景', createdAt: '2026-08-20', photoIds: ['p4', 'p5', 'p6'] },
];

const mockStyleCards: StyleCardData[] = [
  {
    styleId: 'kodak_portra_400',
    name: 'Kodak Portra 400',
    family: 'Kodak',
    description: '柔和低反差、肤色暖粉、高光软滚降的经典胶片感。',
    tags: { scene: ['portrait', 'wedding'], light: ['golden_hour'] },
    colorFingerprint: { skin_lab_target: { a: 18, b: 20 } },
    toneFingerprint: { contrast_tendency: 'low', highlight_rolloff: 'soft' },
    recommendedAdjustments: { exposure: -0.1, tone_contrast: 0.05 },
  },
  {
    styleId: 'fuji_pro_400h',
    name: 'Fuji Pro 400H',
    family: 'Fuji',
    description: '柔和通透、空气感强，适合阴天与户外人像。',
    tags: { scene: ['landscape', 'portrait'], light: ['overcast'] },
    colorFingerprint: { skin_lab_target: { a: 14, b: 16 } },
    toneFingerprint: { contrast_tendency: 'medium', shadow_depth: 'airy' },
    recommendedAdjustments: { contrast: 0.05, clarity: 0.08 },
  },
];

export function mockGetPhotos(): PhotoView[] {
  return mockPhotos;
}

export function mockCreatePhoto(path: string): PhotoView {
  const id = `p${Date.now()}`;
  const name = path.split(/[\\/]/).pop() ?? path;
  const photo: PhotoView = mockPhoto(id, name, 'RAW_PENDING', 0, {
    takenAt: new Date().toISOString(),
  });
  mockPhotos.unshift(photo);
  return photo;
}

export function mockScanDirectory(): Array<{ path: string; name: string; size: number }> {
  return mockPhotos.map((p) => ({
    path: p.path,
    name: p.path.split(/[\\/]/).pop() ?? p.photo_id,
    size: 1024 * 1024 * 24,
  }));
}

export function mockPatchParams(patch: ParamPatch): {
  generation: number;
  params: ParamPatch;
  canonical: ParamPatch;
} {
  generation += 1;
  // ParamPatch 是收紧的联合类型（无索引签名）：用宽松 Record 逐 stage 合并，
  // 最后整体断言回 ParamPatch（键名已在编译期由 ParamPatch 约束）。
  const next: Record<string, Record<string, unknown>> = {
    ...(params as Record<string, Record<string, unknown>>),
  };
  (Object.keys(patch) as Array<keyof ParamPatch>).forEach((stage) => {
    const incoming = patch[stage];
    if (incoming === undefined) return;
    const cur = next[stage] ?? {};
    next[stage] = {
      ...cur,
      ...(incoming as Record<string, unknown>),
    };
  });
  params = next as ParamPatch;
  return { generation, params, canonical: params };
}

export function mockPreviewDataUrl(generationValue: number, processed: boolean): string {
  return svgThumb(8 + (generationValue % 10), processed ? `P${generationValue}` : 'ORIGINAL', processed);
}

export function mockGetProjects(): Project[] {
  return mockProjects;
}

export function mockGetStyleCards(): StyleCardData[] {
  return mockStyleCards;
}
