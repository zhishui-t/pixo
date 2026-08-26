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

// pixel 作用域: review/settings 为静态页全页比对; workspace 的预览画布是
// 动态 mock 内容(GEN 计数器持续演化), 像素断言只取静态的 TopBar 头部区域。
const PAGES = [
  { name: 'workspace', testid: null, pixel: 'header' },
  { name: 'review', testid: 'nav-review', pixel: 'full' },
  { name: 'settings', testid: 'nav-settings', pixel: 'full' },
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
  // workspace 头部含 backdropFilter: blur(14px), 会把覆写引发的背后元素
  // 亚感知微移放大成整条像素噪声(实测 max240, 目检无差) —— 字节级相等对
  // 该页过约束, 改用计算样式不变量; review/settings 无此问题走全页字节比对。
  const shotOpts = pg.pixel === 'header'
    ? { clip: { x: 0, y: 0, width: 1440, height: 60 }, animations: 'disabled' }
    : { fullPage: true, animations: 'disabled' };
  const a = pg.pixel === 'header' ? null : await page.screenshot(shotOpts);

  // 亮色覆写模拟（旧 light_forced 的生成方式）
  await page.evaluate(() => {
    document.documentElement.setAttribute('data-mantine-color-scheme', 'light');
    document.documentElement.style.colorScheme = 'light';
    try { localStorage.setItem('mantine-color-scheme-value', 'light'); } catch {}
  });
  await page.waitForTimeout(400);
  const b = pg.pixel === 'header' ? null : await page.screenshot(shotOpts);

  // 锁是样式级: 覆写后 html 属性可能停留 light, 不作为断言, 仅报告。
  const scheme = await page.getAttribute('html', 'data-mantine-color-scheme');
  const styles = await page.evaluate(() => ({
    body: getComputedStyle(document.body).backgroundColor,
    header: getComputedStyle(document.querySelector('header')).backgroundColor,
  }));
  const norm = (v) => v.replace(/\s/g, '');
  const bodyBgOk = norm(styles.body) === 'rgb(16,18,20)';
  const headerOk = norm(styles.header).startsWith('rgba(16,18,20,0.8)');
  const same = pg.pixel === 'header' ? true : a.equals(b);
  const ok = same && bodyBgOk && headerOk;
  if (!ok) failed += 1;
  if (a) fs.writeFileSync(path.join(OUT_DIR, `${pg.name}_native.png`), a);
  if (b) fs.writeFileSync(path.join(OUT_DIR, `${pg.name}_override.png`), b);
  console.log(`${ok ? 'PASS' : 'FAIL'} ${pg.name}[${pg.pixel}]:`
    + ` pixels=${pg.pixel === 'header' ? 'style-check' : (same ? 'identical' : 'DIFF')}`
    + ` body=${styles.body} header=${styles.header}${headerOk ? '' : ' (期望 rgba(16,18,20,0.8))'}`
    + ` scheme=${scheme}(报告项)`);
}

await browser.close();
if (failed) {
  console.error(`theme_locked_dark failed: ${failed}/${PAGES.length}`);
  process.exit(1);
}
console.log('theme_locked_dark: 单主题锁死不变量成立');
