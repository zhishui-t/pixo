import { chromium } from 'playwright';

const URL = process.env.PIXO_UI_URL || 'http://localhost:5173';

const browser = await chromium.launch({
  channel: 'msedge',
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

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

await check('TopBar 品牌显示', async () => {
  await page.locator('text=Pixo').first().waitFor({ timeout: 5000 });
});

await check('PhotoLibrary 渲染', async () => {
  const count = await page.locator('.photo-card').count();
  if (count < 1) throw new Error(`photo-card 数量为 ${count}`);
});

await check('PreviewViewer 渲染', async () => {
  await page.locator('text=原图').first().waitFor({ timeout: 3000 });
  await page.locator('text=Split').first().waitFor({ timeout: 3000 });
  await page.locator('text=处理').first().waitFor({ timeout: 3000 });
});

await check('参数面板/Agent 标签可切换', async () => {
  await page.locator('text=Agent').first().click().catch(() => {});
  await page.locator('text=DSH Agent').first().waitFor({ timeout: 3000 });
});

await page.screenshot({ path: 'screenshots/smoke.png', fullPage: true });
console.log('Screenshot saved: screenshots/smoke.png');

await browser.close();

const failed = results.filter(r => !r.ok);
if (failed.length) {
  console.error(`\nSmoke failed: ${failed.length}/${results.length}`);
  process.exit(1);
}
console.log(`\nSmoke passed: ${results.length}/${results.length}`);
