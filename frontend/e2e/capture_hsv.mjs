// t8 hsv 域截图对比工具：抓取「调整」面板区域 + 整页截图。
// 用法：
//   node e2e/capture_hsv.mjs <输出目录前缀>   如 `node e2e/capture_hsv.mjs baseline`
// 产  frontend/screenshots/oklch/<前缀>_panel.png 与 <前缀>_full.png。
// 面板截图是像素对比基线（hsv 域零变化验收的唯一口径）。
import { chromium } from 'playwright';
import { fileURLToPath } from 'url';
import path from 'path';
import fs from 'fs';

const URL = process.env.PIXO_UI_URL || 'http://localhost:5173';
const prefix = process.argv[2] || 'shot';
const outDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../screenshots/oklch');
fs.mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(URL, { waitUntil: 'networkidle' });
await page.waitForTimeout(800);

// 进「调整」Tab（右侧面板），与 smoke.mjs 的导航方式一致。
await page.locator('text=调整').first().click().catch(() => {});
await page.locator('text=基本').first().waitFor({ timeout: 5000 });
await page.waitForTimeout(600);

const panel = page.locator('.adjustments-panel');
await panel.screenshot({ path: path.join(outDir, `${prefix}_panel.png`) });
await page.screenshot({ path: path.join(outDir, `${prefix}_full.png`), fullPage: true });
console.log(`saved ${prefix}_panel.png / ${prefix}_full.png -> ${outDir}`);
await browser.close();
