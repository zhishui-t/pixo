/**
 * regionSection 单测（node --test 原生跑 TS：Node ≥22.18 类型剥离，零新依赖，
 * 沿 oklchScale.test.mjs 模式）。覆盖 R14 验收：
 *  - 掩码状态双态 UI 模型（可用 = 控件可操作；不可用 = 禁用 + 提示文案）；
 *  - canonical 回读（含 decide 规则写入值；形状容错）；
 *  - patch 形态（{region_adjust:{regions:{prompt:{param}}}} + 域钳制）；
 *  - 感知均匀滑杆传递（oklchScale 同款 γ 幂函数的有符号推广：锚点/互逆/
 *    单调/中心高分辨率）；
 *  - mock 深合并（prompt 级累积不整桶替换）。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  regionReasonText,
  REGION_PARAM_KEYS,
  REGION_SLIDER_DEFS,
  buildRegionPatch,
  maskStatusToUi,
  normalizeRegionMaskStatus,
  readRegionAdjustment,
  signedPerceptualFromSlider,
  signedPerceptualToSlider,
} from '../src/components/regionAdjust.ts';
import { C_SLIDER_GAMMA } from '../src/theme/oklchScale.ts';
import { mockGetRegionMaskStatus, mockPatchParams } from '../src/api/mock.ts';

const close = (a, b, eps, label) =>
  assert.ok(Math.abs(a - b) <= eps, `${label}: got ${a}, want ${b} (±${eps})`);

// ---------------------------------------------------------------------------
// 掩码状态双态（渲染模型的唯一数据面）
// ---------------------------------------------------------------------------

test('掩码可用态：enabled + prompts 直出 + 就绪徽标文案', () => {
  const ui = maskStatusToUi(normalizeRegionMaskStatus({
    available: true, prompts: ['sky', 'face', 'plant'], reason: null,
  }));
  assert.equal(ui.enabled, true);
  assert.deepEqual(ui.prompts, ['sky', 'face', 'plant']);
  assert.match(ui.badgeText, /掩码就绪 · 3 个区域/);
  assert.doesNotMatch(ui.hint, /运行分析/);
});

test('掩码不可用态：禁用 + 提示文案（杜绝静默失效）', () => {
  for (const raw of [
    { available: false, prompts: [], reason: '尚未运行分割' },
    { available: true, prompts: [] },            // available 但无区域 → 不可用
    { available: false, prompts: ['sky'] },       // available=false 优先
    null, undefined, 'garbage', 42,               // 形状漂移容错
  ]) {
    const ui = maskStatusToUi(normalizeRegionMaskStatus(raw));
    assert.equal(ui.enabled, false, `raw=${JSON.stringify(raw)}`);
    assert.deepEqual(ui.prompts, []);
    assert.match(ui.badgeText, /不可用/);
    assert.match(ui.hint, /运行分析后可用区域调整/);
  }
});

test('不可用原因透传到提示文案（状态 API 数据面）', () => {
  const ui = maskStatusToUi(normalizeRegionMaskStatus({
    available: false, prompts: [], reason: '分割模型未加载',
  }));
  assert.match(ui.hint, /分割模型未加载/);
});

test('normalizeRegionMaskStatus：prompts 非字符串元素过滤 + reason 类型守卫', () => {
  const s = normalizeRegionMaskStatus({
    available: true, prompts: ['sky', 42, null, 'face', ''], reason: 7,
  });
  assert.deepEqual(s.prompts, ['sky', 'face']);
  assert.equal(s.reason, null);
  assert.equal(normalizeRegionMaskStatus(undefined).available, false);
});

// ---------------------------------------------------------------------------
// canonical 回读（含 decide 规则写入值）
// ---------------------------------------------------------------------------

test('回读：canonical 的 region_adjust.regions 值正确渲染到控件数据面', () => {
  const params = {
    region_adjust: { regions: { sky: { exposure: -0.75, saturation: 0.2, warmth: 0.1 } } },
  };
  const v = readRegionAdjustment(params, 'sky');
  assert.equal(v.exposure, -0.75);
  assert.equal(v.saturation, 0.2);
  assert.equal(v.warmth, 0.1);
});

test('回读：decide 规则写入的值与用户写入值同面渲染（来源无关）', () => {
  // decide 引擎写 flat "region.sky.exposure" → loop 映射进嵌套桶（F14 闭环），
  // canonical 回读后即为本形状——来源（user/decide/style_card）不改变读取路径。
  const params = {
    exposure: { mode: 'auto' },
    region_adjust: { regions: { plant: { exposure: 0.1 } } },
  };
  assert.equal(readRegionAdjustment(params, 'plant').exposure, 0.1);
  assert.equal(readRegionAdjustment(params, 'sky').exposure, 0);   // 未设置区域回 0
});

test('回读容错：缺桶/坏形状/非有限值 → 0（no-op 与后端缺省语义一致）', () => {
  assert.deepEqual(readRegionAdjustment({}, 'sky'),
    { exposure: 0, saturation: 0, warmth: 0 });
  assert.deepEqual(readRegionAdjustment({ region_adjust: {} }, 'sky'),
    { exposure: 0, saturation: 0, warmth: 0 });
  assert.deepEqual(readRegionAdjustment({ region_adjust: { regions: { sky: 'garbage' } } }, 'sky'),
    { exposure: 0, saturation: 0, warmth: 0 });
  assert.equal(
    readRegionAdjustment({ region_adjust: { regions: { sky: { exposure: 'x', saturation: NaN } } } }, 'sky').exposure, 0);
  assert.equal(
    readRegionAdjustment({ region_adjust: { regions: { sky: { exposure: 'x', saturation: NaN } } } }, 'sky').saturation, 0);
});

// ---------------------------------------------------------------------------
// patch 形态与钳制
// ---------------------------------------------------------------------------

test('patch 形态：{region_adjust:{regions:{prompt:{param:value}}}} 精确形状', () => {
  assert.deepEqual(
    buildRegionPatch('sky', 'exposure', -0.5),
    { region_adjust: { regions: { sky: { exposure: -0.5 } } } },
  );
  assert.deepEqual(
    buildRegionPatch('face', 'warmth', 0.3),
    { region_adjust: { regions: { face: { warmth: 0.3 } } } },
  );
});

test('patch 钳制：越界值压回滑杆域（防触发后端 _regions ValueError）', () => {
  const p = buildRegionPatch('sky', 'exposure', 5);
  assert.equal(p.region_adjust.regions.sky.exposure, 2);
  const q = buildRegionPatch('sky', 'saturation', -3);
  assert.equal(q.region_adjust.regions.sky.saturation, -1);
});

test('滑杆域定义与后端 _regions 白名单镜像（exposure ±2 / saturation ±1 / warmth ±1）', () => {
  assert.deepEqual([...REGION_PARAM_KEYS], ['exposure', 'saturation', 'warmth']);
  const byKey = Object.fromEntries(REGION_SLIDER_DEFS.map((d) => [d.key, d]));
  assert.deepEqual([byKey.exposure.min, byKey.exposure.max], [-2, 2]);
  assert.deepEqual([byKey.saturation.min, byKey.saturation.max], [-1, 1]);
  assert.deepEqual([byKey.warmth.min, byKey.warmth.max], [-1, 1]);
});

// ---------------------------------------------------------------------------
// 感知均匀滑杆传递（oklchScale 同款 γ 幂函数的有符号推广）
// ---------------------------------------------------------------------------

test('传递函数复用 oklchScale 同款 γ=1.6（13.1 惯例单源）', () => {
  assert.equal(C_SLIDER_GAMMA, 1.6);
});

test('有符号锚点：pos 0→min，0.5→0，1→max（中心 0 = 不调整）', () => {
  close(signedPerceptualToSlider(-2, -2, 2), 0, 1e-12, 'to(-2)');
  assert.equal(signedPerceptualToSlider(0, -2, 2), 0.5);
  close(signedPerceptualToSlider(2, -2, 2), 1, 1e-12, 'to(2)');
  close(signedPerceptualFromSlider(0, -2, 2), -2, 1e-12, 'from(0)');
  assert.equal(signedPerceptualFromSlider(0.5, -2, 2), 0);
  close(signedPerceptualFromSlider(1, -2, 2), 2, 1e-12, 'from(1)');
});

test('感知均匀：中心段分辨率高于线性（|v(0.55)| < 线性映射值）', () => {
  const perceptual = signedPerceptualFromSlider(0.55, -2, 2);
  const linear = (0.55 - 0.5) * 2 * 2;                    // 线性: t*half
  assert.ok(Math.abs(perceptual) < Math.abs(linear),
    `中心段应更精细: ${perceptual} vs ${linear}`);
  // 量级符合幂律: |t|^γ 半程
  close(Math.abs(perceptual), Math.pow(0.1, C_SLIDER_GAMMA) * 2, 1e-9, '幂律');
});

test('双向精确互逆（[0,1]×2001 位置网格 + ±2×2001 值网格，exposure 域）', () => {
  for (let i = 0; i <= 2000; i++) {
    const p = i / 2000;                                    // 位置域 [0,1]
    const v = signedPerceptualFromSlider(p, -2, 2);
    close(signedPerceptualToSlider(v, -2, 2), p, 1e-9, `to∘from(p=${p})`);
  }
  for (let i = -1000; i <= 1000; i++) {
    const v = (i / 1000) * 2;                              // 值域 [-2, 2]
    const pos = signedPerceptualToSlider(v, -2, 2);
    close(signedPerceptualFromSlider(pos, -2, 2), v, 1e-9, `from∘to(v=${v})`);
  }
});

test('单调递增 + 0 处精确（步长 0.001 全程扫描）', () => {
  let prev = -Infinity;
  for (let i = 0; i <= 1000; i++) {
    const v = signedPerceptualFromSlider(i / 1000, -1, 1);
    assert.ok(v >= prev, `非单调 @ pos=${i / 1000}`);
    assert.ok(v >= -1 && v <= 1, '值域逃逸');
    prev = v;
  }
  assert.equal(signedPerceptualToSlider(0, -1, 1), 0.5);
  assert.equal(signedPerceptualFromSlider(0.5, -1, 1), 0);
});

test('B1 reason 机器码 → 可行动提示文案（已知码映射）', () => {
  assert.equal(regionReasonText('masks_not_injected'), '运行分析后可用区域调整');
  assert.match(regionReasonText('session_not_ready'), /会话未建立/);
  assert.match(regionReasonText('session_not_found'), /会话已失效/);
  assert.match(regionReasonText('fetch_failed'), /重试/);
  // null/undefined → 通用文案（后端 available=false 且无 reason 的形状）
  assert.equal(regionReasonText(null), '运行分析后可用区域调整');
  assert.equal(regionReasonText(undefined), '运行分析后可用区域调整');
});

test('B1 未知 reason 码回退通用文案 + 原因码透传（不吞诊断信息）', () => {
  const hint = regionReasonText('some_future_code');
  assert.match(hint, /运行分析后可用区域调整/);
  assert.match(hint, /some_future_code/);
});

// ---------------------------------------------------------------------------
// mock 深合并（前端 mock 模式不崩 + prompt 级累积）
// ---------------------------------------------------------------------------

test('mock patch 深合并：不同 prompt 的 patch 累积（不整桶替换）', () => {
  mockPatchParams({ region_adjust: { regions: { sky: { exposure: -0.5 } } } });
  const r = mockPatchParams({ region_adjust: { regions: { face: { saturation: 0.2 } } } });
  const regions = r.params.region_adjust.regions;
  assert.equal(regions.sky.exposure, -0.5, '既有 prompt 被整桶替换');
  assert.equal(regions.face.saturation, 0.2);
  // 同 prompt 不同参数键也累积
  const r2 = mockPatchParams({ region_adjust: { regions: { sky: { warmth: 0.1 } } } });
  assert.equal(r2.params.region_adjust.regions.sky.exposure, -0.5);
  assert.equal(r2.params.region_adjust.regions.sky.warmth, 0.1);
  assert.equal(r2.canonical.region_adjust.regions.face.saturation, 0.2);
});

test('mock 掩码状态：恒 available（离线开发态不呈现禁用面）', () => {
  const s = mockGetRegionMaskStatus();
  assert.equal(s.available, true);
  assert.ok(Array.isArray(s.prompts) && s.prompts.length > 0);
});
