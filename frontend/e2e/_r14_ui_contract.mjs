/**
 * R14 tester 跨端契约实测 —— 真实后端(:8000) + 真实前端(:5173) 联调空档验证。
 *
 * 目的：队长把 client.ts URL 对齐为 GET /region 后从未做过真实跨端请求，
 * 本脚本在浏览器里走真实路径并抓取网络层证据：
 *   1. 后端预置真实 RAW 照片（HTTP API）
 *   2. 打开 UI → 选中照片 → 调整 Tab → 区域调整节
 *   3. 抓取前端发出的所有 sessions/region 与 sessions/params 请求（URL+状态+响应体）
 *   4. 读取 region-mask-badge 徽标文案（可用态 vs 不可用态）
 *   5. 拖动【全局曝光】滑杆建真实会话 → GET /region 用真实 sid 重查
 *   6. 复核：真实会话的后端 GET /region 语义 vs UI 徽标是否矛盾
 *      （B1 修复后另断言：会话前零请求 / region 滑杆锁定 / 零 region PUT）
 *
 * 运行（需先起后端 8000 + vite dev 5173）:
 *   node e2e/_r14_ui_contract.mjs
 */
import { chromium } from 'playwright';

const UI = process.env.PIXO_UI_URL || 'http://localhost:5173';
const API = process.env.PIXO_API_URL || 'http://localhost:8000';
const RAW = 'K:/data/photo/0711/raw/DSC_5236.NEF';

const results = [];
async function check(name, fn) {
  try {
    const detail = await fn();
    results.push({ name, ok: true });
    console.log(`PASS  ${name}${detail ? '  [' + detail + ']' : ''}`);
  } catch (err) {
    results.push({ name, ok: false });
    console.log(`FAIL  ${name}: ${err?.message || err}`);
  }
}

// ---- 0. 后端预置照片（避免 UI 首屏空列表） ------------------------------
const createResp = await fetch(`${API}/api/photos`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ path: RAW }),
});
if (createResp.status !== 201) {
  console.error(`后端预置照片失败: ${createResp.status} ${await createResp.text()}`);
  process.exit(2);
}
const { photo } = await createResp.json();
console.log(`# 预置照片 photo_id=${photo.photo_id} path=${photo.path}`);

// ---- 1. 浏览器 + 网络抓包 ------------------------------------------------
// 已知前置缺口（另报 bug）：后端无 CORS 中间件 + vite 无代理 → 浏览器跨源
// fetch 一律被拦、前端静默回 mock。为隔离该缺口、实测前端真实请求代码
// （client.ts → api 层 → RegionSection）与后端的线路契约，此处关闭 web security。
const browser = await chromium.launch({
  channel: 'msedge',
  headless: true,
  args: ['--disable-web-security'],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

const sessionApiLog = [];   // 前端发出的 /api/sessions/*/(region|params) 请求
page.on('request', (req) => {
  const m = req.url().match(/\/api\/sessions\/([^/]+)\/(region|params)/);
  if (m) {
    sessionApiLog.push({
      method: req.method(),
      kind: m[2],
      sessionId: m[1],
      url: req.url(),
      body: req.postData() ?? '',
    });
  }
});
const regionRespLog = [];
page.on('response', async (res) => {
  if (/\/api\/sessions\/[^/]+\/region/.test(res.url())) {
    let body = '';
    try { body = (await res.text()).slice(0, 300); } catch { /* ignore */ }
    regionRespLog.push({ status: res.status(), url: res.url(), body });
  }
});

await page.goto(UI, { waitUntil: 'networkidle' });

// ---- 2. 选中照片 → 调整 Tab → 区域调整节 ---------------------------------
await page.locator('text=DSC_5236.NEF').first().waitFor({ timeout: 8000 });
await page.locator('text=DSC_5236.NEF').first().click();
await page.locator('text=调整').first().click();
await page.locator('[data-testid="region-section"]').waitFor({ timeout: 8000 });
await page.locator('[data-testid="region-section"]').scrollIntoViewIfNeeded();
await page.waitForTimeout(1200);   // 等 fetchRegionMaskStatus 完成渲染

const badgeText1 = (
  await page.locator('[data-testid="region-mask-badge"]').innerText()
).trim();
const hint1 = (await page.locator('[data-testid="region-unavailable-hint"]')
  .count()) ? (await page.locator('[data-testid="region-unavailable-hint"]').innerText()).trim()
  : '(无不可用提示)';
console.log(`# 首屏 region 徽标: "${badgeText1}"`);
console.log(`# 首屏 region 提示: "${hint1}"`);
await check('会话未建立时零 /region 请求（B1: 不触达状态面，无 mock 兜底）', () => {
  const n = regionRespLog.length;
  if (n) throw new Error(`会话前不应发 /region 请求，实际 ${n} 个: `
    + regionRespLog.map((r) => r.url).join(' | '));
  return '0 个请求（符合预期）';
});
await check('会话未建立时区域滑杆不渲染（禁用态无静默操作面）', async () => {
  const sliders = await page.locator('[data-testid="region-exposure"] [role="slider"]').count();
  const hint = await page.locator('[data-testid="region-unavailable-hint"]').count();
  if (sliders > 0 || hint === 0) {
    throw new Error(`滑杆 ${sliders} 个（应 0），不可用提示 ${hint} 个（应 1）`);
  }
  return '滑杆 0 个（禁用态）, 不可用提示 1 个';
});

// ---- 3. 拖动【全局曝光】滑杆（基本节）→ ensureSession 建真实会话 ---------
// B1 收紧后：region 滑杆在掩码不可用+无会话时锁定，不能再用它建会话；
// 会话由全局参数交互创建（真实用户路径），RegionSection 随 sessionId
// 变化自动重查真实会话的掩码状态。
const globalSlider = page.locator('.slider-param [role="slider"]').first();
await globalSlider.scrollIntoViewIfNeeded();
await globalSlider.click();
await globalSlider.press('ArrowRight');
await page.waitForTimeout(3000);   // 等 ensureSession + GET /region 重查完成

const badgeText2 = (
  await page.locator('[data-testid="region-mask-badge"]').innerText()
).trim();
console.log(`# 全局交互后 region 徽标: "${badgeText2}"`);

await check('会话建立后 /region 用真实 sid 重查（B1 断链回归面）', () => {
  const n = regionRespLog.length;
  if (!n) throw new Error('未捕获任何 /region 请求');
  const demo = regionRespLog.filter((r) => r.url.includes('demo-session'));
  if (demo.length) throw new Error(`仍存在 demo-session 请求 ${demo.length} 个（B1 断链未修）`);
  return regionRespLog.map((r) => r.url).join(' | ');
});

await check('掩码不可用期间零 region_adjust PUT（不静默提交无效调整）', () => {
  const puts = sessionApiLog.filter(
    (r) => r.method === 'PUT' && r.kind === 'params' && r.body.includes('region_adjust'));
  if (puts.length) {
    throw new Error('不可用态仍发出 region_adjust PUT: ' + JSON.stringify(puts));
  }
  return '0 个（符合预期）';
});
// ---- 4. 真实会话的后端语义 vs UI 徽标 ------------------------------------
// 真实 sid 从前端实际发出的 PUT params 请求中提取（该会话由 ensureSession 创建）
const putLog = sessionApiLog.filter((r) => r.method === 'PUT' && r.kind === 'params');
const realSid = putLog.length ? putLog[putLog.length - 1].sessionId : null;
let realRegion = null;
if (realSid) {
  realRegion = await fetch(`${API}/api/sessions/${realSid}/region`).then((r) => r.json());
}
console.log(`# 真实会话=${realSid} 后端 GET /region → ${JSON.stringify(realRegion)}`);
// R17：reason → UI 文案映射的联调观测（segmenter 四码的文案断言在 unit 矩阵
// tests/regionSection.test.mjs；warming 需 in-process 注入，e2e 不强触达）。
if (realRegion?.reason) {
  console.log(`# 后端 reason=${realRegion.reason}（UI 不可用提示见上方徽标/提示行）`);
}

await check('UI 徽标与真实后端状态一致性', () => {
  if (!realRegion) throw new Error('未取得真实会话 region 状态');
  const backendReady = realRegion.available === true;
  const uiReady = badgeText2.includes('掩码就绪');
  if (backendReady !== uiReady) {
    throw new Error(`矛盾: 后端 available=${realRegion.available}`
      + ` reason=${realRegion.reason} 但 UI 徽标="${badgeText2}"`);
  }
  return '一致';
});

await page.screenshot({
  path: 'e2e/screenshots/r14_ui_contract.png', fullPage: false });
console.log('# 截图: e2e/screenshots/r14_ui_contract.png');

console.log('\n# 前端会话 API 请求全量日志:');
for (const r of sessionApiLog) {
  console.log(`#   ${r.method} /${r.kind} sid=${r.sessionId.slice(0, 16)} ${r.body.slice(0, 140)}`);
}

await browser.close();

const failed = results.filter((r) => !r.ok);
console.log(`\nR14 UI contract: ${results.length - failed.length}/${results.length} passed`
  + `, ${failed.length} failed`);
process.exit(failed.length ? 1 : 0);
