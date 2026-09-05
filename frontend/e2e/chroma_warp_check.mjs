// §4.4 色度滑杆非线性传递 e2e 验收：
//   1) hsv 域零变化——面板截图与基线 baseline_panel.png 在浏览器 canvas 内逐像素 diff；
//   2) oklch 域新控件——展开黄带色度滑杆，值⇄拇指位置按幂映射放置（v=33 → 行程 75%）；
//   3) 交互回路——轨道点击 / End 键提交的参数值落位正确，NumberInput 显示参数原值。
// 前置：vite dev server（mock 模式）。运行：node e2e/chroma_warp_check.mjs
import { chromium } from 'playwright';
import { fileURLToPath } from 'url';
import path from 'path';
import fs from 'fs';

const URL = process.env.PIXO_UI_URL || 'http://localhost:5173';
const outDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../screenshots/oklch');
fs.mkdirSync(outDir, { recursive: true });
const baselinePath = path.join(outDir, 'baseline_panel.png');

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
await page.waitForTimeout(600);
const panel = page.locator('.adjustments-panel');

// ---- 1) hsv 域零变化：与基线逐像素 diff（canvas 在浏览器内解码，零外部依赖）----
await check('hsv 域面板与基线逐像素一致（双轨零变化）', async () => {
  if (!fs.existsSync(baselinePath)) throw new Error(`缺基线 ${baselinePath}`);
  const shot = await panel.screenshot();
  const baseline = fs.readFileSync(baselinePath);
  const diff = await page.evaluate(async ({ aB64, bB64 }) => {
    const load = (b64) => new Promise((res, rej) => {
      const img = new Image();
      img.onload = () => res(img);
      img.onerror = rej;
      img.src = `data:image/png;base64,${b64}`;
    });
    const [ia, ib] = await Promise.all([load(aB64), load(bB64)]);
    if (ia.width !== ib.width || ia.height !== ib.height) {
      return { error: `尺寸不同 ${ia.width}x${ia.height} vs ${ib.width}x${ib.height}` };
    }
    const cv = document.createElement('canvas');
    cv.width = ia.width; cv.height = ia.height;
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(ia, 0, 0);
    const da = ctx.getImageData(0, 0, cv.width, cv.height).data;
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.drawImage(ib, 0, 0);
    const db = ctx.getImageData(0, 0, cv.width, cv.height).data;
    let bad = 0;
    let maxDelta = 0;
    for (let i = 0; i < da.length; i += 4) {
      const d = Math.max(Math.abs(da[i] - db[i]), Math.abs(da[i + 1] - db[i + 1]), Math.abs(da[i + 2] - db[i + 2]));
      if (d > 8) bad++;
      if (d > maxDelta) maxDelta = d;
    }
    return { bad, maxDelta, total: da.length / 4 };
  }, { aB64: shot.toString('base64'), bB64: baseline.toString('base64') });
  if (diff.error) throw new Error(diff.error);
  // 渲染确定性：同机同浏览器应零差异；容忍极小抗锯齿噪声（<0.02% 像素、Δ≤8 已滤）
  if (diff.bad !== 0) {
    throw new Error(`差异像素 ${diff.bad}/${diff.total}（maxΔ=${diff.maxDelta}）`);
  }
});

// ---- 2) oklch：展开黄带，色度滑杆接线幂映射 ----
await page.locator('[data-testid="domain-toggle"]').first().locator('text=OKLCh').click();
await panel.locator('text=HSL · 八通道色相（OKLCh 感知域）').first().waitFor({ timeout: 5000 });
await page.locator('[data-testid="band-row-yellow-expand"]').click();
const chroma = page.locator('[data-testid="band-yellow-chroma"]');
await chroma.waitFor({ timeout: 3000 });
await panel.locator('text=行程中段≈+33').first().waitFor({ timeout: 3000 });

/** 色度滑杆拇指中心相对轨道的行程占比（0..1）。 */
async function thumbFraction() {
  return page.evaluate(() => {
    const root = document.querySelector('[data-testid="band-yellow-chroma"]');
    const track = root.querySelector('[class*="Slider-track"]');
    const thumb = root.querySelector('[class*="Slider-thumb"]');
    const tr = track.getBoundingClientRect();
    const th = thumb.getBoundingClientRect();
    return (th.x + th.width / 2 - tr.x) / tr.width;
  });
}

async function typeChromaValue(v) {
  const input = chroma.locator('.slider-param-value input');
  await input.fill(String(v));
  await input.press('Enter');
  await page.waitForTimeout(500); // mock patch 回读
}

await check('新控件：展开态色度滑杆渲染 §4.4 helper 文案', async () => {
  if (!(await chroma.count())) throw new Error('色度滑杆缺失');
});

await check('v=0（原色）→ 拇指在行程 50%', async () => {
  await typeChromaValue(0);
  const f = await thumbFraction();
  if (Math.abs(f - 0.5) > 0.02) throw new Error(`拇指占比 ${f.toFixed(3)} ≠ 0.5`);
});

await check('v=+33（常用增强）→ 拇指在行程 75%（幂映射中段）', async () => {
  await typeChromaValue(33);
  const f = await thumbFraction();
  if (Math.abs(f - 0.75) > 0.02) throw new Error(`拇指占比 ${f.toFixed(3)} ≠ 0.75`);
});

await check('v=-50 → 拇指在行程 25%（负向线性，恒等）', async () => {
  await typeChromaValue(-50);
  const f = await thumbFraction();
  if (Math.abs(f - 0.25) > 0.02) throw new Error(`拇指占比 ${f.toFixed(3)} ≠ 0.25`);
});

await check('v=+50 → 拇指在行程 82.4%（100·0.5^(1/1.6)）', async () => {
  await typeChromaValue(50);
  const f = await thumbFraction();
  if (Math.abs(f - 0.8242) > 0.02) throw new Error(`拇指占比 ${f.toFixed(3)} ≠ 0.8242`);
});

await check('截图：展开态带行（色度幂映射滑杆）', async () => {
  await typeChromaValue(33);
  const row = page.locator('[data-testid="band-row-yellow"]');
  await row.scrollIntoViewIfNeeded();
  await row.screenshot({ path: path.join(outDir, 'chroma_warp_bandrow.png') });
  await panel.screenshot({ path: path.join(outDir, 'chroma_warp_panel.png') });
});

// ---- 3) 交互回路：位置 → 参数值（拖/点方向的提交值正确性）----
await check('End 键到右端 → 提交 +100（两端极端能力保留）', async () => {
  await typeChromaValue(0);
  await chroma.locator('[class*="Slider-thumb"]').focus();
  await page.keyboard.press('End');
  await page.waitForTimeout(500);
  const shown = await chroma.locator('.slider-param-value input').inputValue();
  if (Number(shown) !== 100) throw new Error(`提交值 ${shown} ≠ 100`);
});

await check('轨道 75% 处点击 → 提交 +33（§4.4 锚点：行程 3/4 = 位置域 +50 → 幂映射 33）', async () => {
  await typeChromaValue(0);
  const box = await page.evaluate(() => {
    const t = document.querySelector('[data-testid="band-yellow-chroma"] [class*="Slider-track"]');
    const r = t.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  });
  await page.mouse.click(box.x + box.w * 0.75, box.y + box.h / 2);
  await page.waitForTimeout(500);
  const shown = Number(await chroma.locator('.slider-param-value input').inputValue());
  // 物理行程 75% → 位置域 s=+50（[-100,100]）→ 100·0.5^1.6=32.99 → 量化 +33；线性直传会提交 +50
  if (Math.abs(shown - 33) > 1) throw new Error(`提交值 ${shown} ≠ 33±1`);
});

// ---- 往返无损：切回 hsv（oklch_check 已覆盖结构，此处确认参数保留）----
// §6.3：bands 非默认时切域弹确认窗 → 统一走「保留数值切换」（主按钮）。
async function switchDomain(target) {
  await page.locator('[data-testid="domain-toggle"]').first().locator(`text=${target}`).click();
  const keep = page.locator('button', { hasText: '保留数值切换' });
  try {
    await keep.waitFor({ timeout: 2500 });
    await keep.click();
  } catch {
    // bands 全默认时无弹窗（§6.3 免弹窗），直接继续
  }
  await page.waitForTimeout(800);
}

await check('切回 HSV：色度参数保留（往返无损）', async () => {
  await typeChromaValue(40);
  await switchDomain('HSV');
  await panel.locator('text=高光饱和度').first().waitFor({ timeout: 3000 });
  await switchDomain('OKLCh');
  await panel.locator('text=HSL · 八通道色相（OKLCh 感知域）').first().waitFor({ timeout: 3000 });
  // expandedBand 手风琴状态跨域保留：色度滑杆可能已展开，仅在折叠时点展开钮
  if (!(await chroma.count())) {
    await page.locator('[data-testid="band-row-yellow-expand"]').click();
  }
  await chroma.waitFor({ timeout: 3000 });
  const shown = Number(await chroma.locator('.slider-param-value input').inputValue());
  if (shown !== 40) throw new Error(`往返后色度 ${shown} ≠ 40`);
  await typeChromaValue(0); // 还原默认，避免污染后续基线
});

await browser.close();

const failed = results.filter((r) => !r.ok);
if (failed.length) {
  console.error(`\nChroma warp check failed: ${failed.length}/${results.length}`);
  process.exit(1);
}
console.log(`\nChroma warp check passed: ${results.length}/${results.length}`);
