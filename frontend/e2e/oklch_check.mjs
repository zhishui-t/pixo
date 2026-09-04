// t8 oklch 域交互验证：切域 → 色相环/展开带/谱条出现 → 切回 hsv 往返无损。
// 前置：vite dev server（mock 模式即可，patch 走 mock 回读链路）。
import { chromium } from 'playwright';
import { fileURLToPath } from 'url';
import path from 'path';
import fs from 'fs';

const URL = process.env.PIXO_UI_URL || 'http://localhost:5173';
const outDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../screenshots/oklch');
fs.mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const results = [];
async function check(name, fn) {
  try {
    await fn();
    results.push({ name, ok: true });
    console.log(`PASS  ${name}`);
  } catch (err) {
    results.push({ name, ok: false, error: String(err?.message || err) });
    console.log(`FAIL  ${name}: ${err?.message || err}`);
  }
}

await page.goto(URL, { waitUntil: 'networkidle' });
await page.locator('text=调整').first().click().catch(() => {});
await page.locator('text=基本').first().waitFor({ timeout: 5000 });

const panel = page.locator('.adjustments-panel');

// 默认 hsv：oklch 专属元素一律不存在
await check('默认域：hue-ring 不渲染（双轨）', async () => {
  if (await page.locator('[data-testid="hue-ring"]').count()) throw new Error('hue-ring 在 hsv 模式出现');
});
await check('默认域：band 展开钮不渲染', async () => {
  if (await page.locator('[data-testid="band-row-yellow-expand"]').count()) throw new Error('展开钮在 hsv 模式出现');
});
await check('默认域：分离色调为「高光饱和度」旧文案', async () => {
  await panel.locator('text=高光饱和度').first().waitFor({ timeout: 3000 });
});

// 切 OKLCh（HSL 面板的 toggle）
await check('切到 OKLCh：SectionLabel 更新', async () => {
  await page.locator('[data-testid="domain-toggle"]').first().locator('text=OKLCh').click();
  await panel.locator('text=HSL · 八通道色相（OKLCh 感知域）').first().waitFor({ timeout: 5000 });
});
await check('oklch：黄带折叠行改标「色相平移」', async () => {
  await panel.locator('text=黄 色相平移').first().waitFor({ timeout: 3000 });
});
await check('oklch：展开黄带出现 5 滑杆（center/width/色度C/明度L）', async () => {
  await page.locator('[data-testid="band-row-yellow-expand"]').click();
  await page.locator('[data-testid="band-yellow-center"]').waitFor({ timeout: 3000 });
  await panel.locator('text=带宽角').first().waitFor({ timeout: 1000 });
  await panel.locator('text=色度 C').first().waitFor({ timeout: 1000 });
  await panel.locator('text=明度 L').first().waitFor({ timeout: 1000 });
  await panel.locator('text=≈旧 HSV 55°（参考）').first().waitFor({ timeout: 1000 });
});
await check('oklch：分离色调出现谱轨拾色行', async () => {
  await page.locator('[data-testid="split-hue-highlights"]').scrollIntoViewIfNeeded();
  await page.locator('[data-testid="split-hue-highlights"]').waitFor({ timeout: 3000 });
  await panel.locator('text=高光色度 C').first().waitFor({ timeout: 1000 });
});
await check('oklch：色相环展开出现手柄', async () => {
  await page.locator('[data-testid="hue-ring-toggle"]').click();
  await page.locator('[data-testid="hue-ring"]').waitFor({ timeout: 3000 });
  if ((await page.locator('[data-testid^="hue-ring-handle-"]').count()) !== 8) throw new Error('手柄数≠8');
});
await panel.screenshot({ path: path.join(outDir, 'oklch_panel.png') });

// 切回 hsv：oklch 专属元素全部消失，旧文案回来（往返无损）
await check('切回 HSV：oklch 专属控件全部消失', async () => {
  await page.locator('[data-testid="domain-toggle"]').first().locator('text=HSV').click();
  await page.waitForTimeout(800);
  if (await page.locator('[data-testid="hue-ring"]').count()) throw new Error('hue-ring 残留');
  if (await page.locator('[data-testid="band-yellow-center"]').count()) throw new Error('center 滑杆残留');
  if (await page.locator('[data-testid="split-hue-highlights"]').count()) throw new Error('谱轨残留');
  await panel.locator('text=高光饱和度').first().waitFor({ timeout: 3000 });
  await panel.locator('text=黄 色相').first().waitFor({ timeout: 3000 });
});

await panel.screenshot({ path: path.join(outDir, 'back_to_hsv_panel.png') });
await browser.close();

const failed = results.filter((r) => !r.ok);
if (failed.length) {
  console.error(`\nOklch check failed: ${failed.length}/${results.length}`);
  process.exit(1);
}
console.log(`\nOklch check passed: ${results.length}/${results.length}`);
