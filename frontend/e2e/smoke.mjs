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

await check('ProjectList 渲染', async () => {
  const count = await page.locator('.project-item').count();
  if (count < 1) throw new Error(`project-item 数量为 ${count}`);
});

await check('Filmstrip 渲染', async () => {
  const count = await page.locator('.film-item').count();
  if (count < 1) throw new Error(`film-item 数量为 ${count}`);
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

await page.screenshot({ path: 'screenshots/ui_v2.png', fullPage: true });
console.log('Screenshot saved: screenshots/ui_v2.png');

await browser.close();

const failed = results.filter((r) => !r.ok);
if (failed.length) {
  console.error(`\nSmoke failed: ${failed.length}/${results.length}`);
  process.exit(1);
}
console.log(`\nSmoke passed: ${results.length}/${results.length}`);
