import { chromium } from 'playwright';

const URL = process.env.PIXO_UI_URL || 'http://localhost:5173';

const browser = await chromium.launch({
  channel: 'msedge',
  headless: true,
});
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

await check('页面标题包含 Pixo', async () => {
  const text = await page.locator('body').innerText();
  if (!text.includes('Pixo')) throw new Error('body 中未找到 Pixo');
});

await check('项目列表渲染', async () => {
  await page.locator('text=夏末人像').first().waitFor({ timeout: 5000 });
});

await check('Filmstrip 渲染', async () => {
  await page.locator('text=DSC_5236.NEF').first().waitFor({ timeout: 5000 });
});

await check('PreviewViewer 渲染', async () => {
  await page.locator('text=原图').first().waitFor({ timeout: 3000 });
  await page.locator('text=Split').first().waitFor({ timeout: 3000 });
  await page.locator('text=处理').first().waitFor({ timeout: 3000 });
});

await check('右侧 风格/AI 与 调整 Tab', async () => {
  await page.locator('text=风格 / AI').first().waitFor({ timeout: 3000 });
  await page.locator('text=调整').first().click().catch(() => {});
  await page.locator('text=基本').first().waitFor({ timeout: 3000 });
});

// t8：色彩编辑域双轨（hsv 默认零变化 / oklch 增量控件 / 往返无损）。
await check('t8 默认域 hsv：oklch 专属控件不渲染', async () => {
  if (await page.locator('[data-testid="hue-ring"]').count()) throw new Error('hue-ring 残留');
  if (await page.locator('[data-testid="band-row-yellow-expand"]').count()) throw new Error('band 展开钮残留');
  if (await page.locator('[data-testid="split-hue-highlights"]').count()) throw new Error('谱轨残留');
  await page.locator('text=高光饱和度').first().waitFor({ timeout: 3000 });
});

await check('t8 切 OKLCh：域标注/展开行/谱轨出现', async () => {
  await page.locator('[data-testid="domain-toggle"]').first().locator('text=OKLCh').click();
  await page.locator('text=HSL · 八通道色相（OKLCh 感知域）').first().waitFor({ timeout: 5000 });
  await page.locator('[data-testid="band-row-yellow-expand"]').click();
  await page.locator('[data-testid="band-yellow-center"]').waitFor({ timeout: 3000 });
  await page.locator('[data-testid="split-hue-highlights"]').scrollIntoViewIfNeeded();
  await page.locator('[data-testid="split-hue-highlights"]').waitFor({ timeout: 3000 });
});

await check('t8 切回 HSV：控件消失数值保留（往返无损）', async () => {
  await page.locator('[data-testid="domain-toggle"]').first().locator('text=HSV').click();
  await page.waitForTimeout(800);
  if (await page.locator('[data-testid="hue-ring"]').count()) throw new Error('hue-ring 残留');
  if (await page.locator('[data-testid="band-yellow-center"]').count()) throw new Error('center 滑杆残留');
  if (await page.locator('[data-testid="split-hue-highlights"]').count()) throw new Error('谱轨残留');
  await page.locator('text=高光饱和度').first().waitFor({ timeout: 3000 });
});
await page.waitForTimeout(400);

await page.screenshot({ path: 'screenshots/ui_v5.png', fullPage: true });

// t81：审核/设置页暗房主题化截图（存 docs/ui 供对比验收）
await page.getByTestId('nav-settings').click();
await page.waitForTimeout(400);
await page.screenshot({ path: '../docs/ui/t81_settings.png', fullPage: true });
await page.locator('button', { hasText: '审核队列' }).first().click();
await page.waitForTimeout(400);
await page.screenshot({ path: '../docs/ui/t81_review.png', fullPage: true });
console.log('t81 screenshots saved: docs/ui/t81_settings.png, docs/ui/t81_review.png');
console.log('Screenshot saved: screenshots/ui_v5.png');

await browser.close();

const failed = results.filter((r) => !r.ok);
if (failed.length) {
  console.error(`\nSmoke failed: ${failed.length}/${results.length}`);
  process.exit(1);
}
console.log(`\nSmoke passed: ${results.length}/${results.length}`);
