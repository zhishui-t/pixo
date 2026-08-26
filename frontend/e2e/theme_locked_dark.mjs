// t82 裁定落地的防回归断言：暗房单主题=最终形态。
// 对 workspace/review/settings 三页：先取原生暗态截图，再模拟亮色覆写
// （html data-mantine-color-scheme=light + localStorage），断言：
//   1) 覆写前后截图逐字节一致（像素级不变量，t78 实测结论的永久守护）；
//   2) html 属性被 forceColorScheme 重新钳回 dark；
//   3) body 计算背景仍为画布色 #101214。
// 任一失败 exit 1 —— 主题锁被破坏（如有人移除 forceColorScheme）即红。
import { chromium } from 'playwright';
import { fileURLToPath } from 'url';
import path from 'path';
import fs from 'fs';

const URL = process.env.PIXO_UI_URL || 'http://localhost:5173';
const OUT_DIR = process.env.PIXO_LOCK_DIR
  || path.resolve(path.dirname(fileURLToPath(import.meta.url)), 'screenshots/theme_lock');
fs.mkdirSync(OUT_DIR, { recursive: true });

const PAGES = [
  { name: 'workspace', testid: null },
  { name: 'review', testid: 'nav-review' },
  { name: 'settings', testid: 'nav-settings' },
];

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({
  viewport: { width: 1440, height: 900 },
  reducedMotion: 'reduce',
});
await page.goto(URL, { waitUntil: 'networkidle' });
await page.waitForTimeout(1000);

let failed = 0;
for (const pg of PAGES) {
  if (pg.testid) {
    await page.click(`[data-testid="${pg.testid}"]`);
    await page.waitForTimeout(600);
  }
  const a = await page.screenshot({ fullPage: true, animations: 'disabled' });

  // 亮色覆写模拟（旧 light_forced 的生成方式）
  await page.evaluate(() => {
    document.documentElement.setAttribute('data-mantine-color-scheme', 'light');
    document.documentElement.style.colorScheme = 'light';
    try { localStorage.setItem('mantine-color-scheme-value', 'light'); } catch {}
  });
  await page.waitForTimeout(400);
  const b = await page.screenshot({ fullPage: true, animations: 'disabled' });

  const scheme = await page.getAttribute('html', 'data-mantine-color-scheme');
  const bodyBg = await page.evaluate(
    () => getComputedStyle(document.body).backgroundColor);
  const bodyBgOk = bodyBg.replace(/\s/g, '') === 'rgb(16,18,20)';

  const same = a.equals(b);
  const ok = same && scheme === 'dark' && bodyBgOk;
  if (!ok) failed += 1;
  fs.writeFileSync(path.join(OUT_DIR, `${pg.name}_native.png`), a);
  fs.writeFileSync(path.join(OUT_DIR, `${pg.name}_override.png`), b);
  console.log(`${ok ? 'PASS' : 'FAIL'} ${pg.name}: pixels=${same ? 'identical' : 'DIFF'}`
    + ` scheme=${scheme} bodyBg=${bodyBg}${bodyBgOk ? '' : ' (期望 rgb(16,18,20))'}`);
}

await browser.close();
if (failed) {
  console.error(`theme_locked_dark failed: ${failed}/${PAGES.length}`);
  process.exit(1);
}
console.log('theme_locked_dark: 单主题锁死不变量成立');
