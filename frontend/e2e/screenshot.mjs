// t83 门禁截图（唯一口径）：暗房为单主题最终形态，仅产原生暗态截图。
// 前置状态由应用锁死（forceColorScheme="dark"），脚本按 data-testid
// 确定性导航并固定等待，保证 workspace/review/settings 三页状态一致。
import { chromium } from 'playwright';
import { fileURLToPath } from 'url';
import path from 'path';

const URL = process.env.PIXO_UI_URL || 'http://localhost:5173';
const OUT_DIR = process.env.PIXO_SHOT_DIR
  || path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../docs/ui');

const SHOTS = [
  { name: 'workspace_dark', testid: null },            // 默认首屏
  { name: 'review_dark', testid: 'nav-review' },
  { name: 'settings_dark', testid: 'nav-settings' },
];

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(URL, { waitUntil: 'networkidle' });
await page.waitForTimeout(1000);

for (const shot of SHOTS) {
  if (shot.testid) {
    await page.click(`[data-testid="${shot.testid}"]`);
    await page.waitForTimeout(600);
  }
  const out = path.join(OUT_DIR, `${shot.name}.png`);
  await page.screenshot({ path: out, fullPage: true });
  console.log('saved', out);
}

await browser.close();
