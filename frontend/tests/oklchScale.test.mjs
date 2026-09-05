/**
 * oklchScale 单测（node --test 原生跑 TS：Node ≥22.18 类型剥离，零新依赖）。
 * 覆盖 UI_OKLCH_SPEC §4.4 色度滑杆非线性传递的验收数字：
 * 锚点 / 双向互逆 / 单调 / 钳制 / 负向线性恒等（hsv 双轨的实现保证）。
 * 锚点出处：docs/UI_OKLCH_SPEC.md §4（内核实测 2026-08-28，探针 .artifacts/ui_oklch_probe.py F 节）。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  C_SLIDER_MAX,
  C_SLIDER_GAMMA,
  sliderToC,
  cToSlider,
  chromaValueToSliderPos,
  chromaSliderPosToValue,
} from '../src/theme/oklchScale.ts';

const close = (a, b, eps, label) =>
  assert.ok(Math.abs(a - b) <= eps, `${label}: got ${a}, want ${b} (±${eps})`);

test('冻结常数与 spec §4.4 一致（C 峰 0.33 / γ 1.6）', () => {
  assert.equal(C_SLIDER_MAX, 0.33);
  assert.equal(C_SLIDER_GAMMA, 1.6);
});

test('sliderToC 端点锚点：0→0，1→0.33（色域峰）', () => {
  assert.equal(sliderToC(0), 0);
  close(sliderToC(1), 0.33, 1e-12, 'sliderToC(1)');
});

test('任务验收：滑杆中段 t=0.5 落常用区 ~0.12', () => {
  const mid = sliderToC(0.5);
  close(mid, 0.33 * Math.pow(0.5, 1.6), 1e-12, '幂映射定义式');
  close(mid, 0.1089, 5e-4, '中段数值');
  // 常用区（照片内容 C≈0.06–0.18，spec §4.1）内，且距区中心锚点 0.12 在 10% 内
  assert.ok(mid > 0.06 && mid < 0.18, `中段 ${mid} 不在常用区 [0.06,0.18]`);
  close(mid, 0.12, 0.012, '锚点 0.12 容差 10%');
});

test('常用区骑跨行程中段：C=0.06→34.5%，C=0.18→68.5%（spec §4.4 表）', () => {
  close(cToSlider(0.06), 0.3445, 1e-3, 'cToSlider(0.06)');
  close(cToSlider(0.18), 0.6847, 1e-3, 'cToSlider(0.18)');
  assert.ok(cToSlider(0.06) < 0.5 && 0.5 < cToSlider(0.18), '常用区未骑跨中段');
});

test('双向精确互逆（[0,1]×1001 网格 + [0,0.33]×331 网格）', () => {
  for (let i = 0; i <= 1000; i++) {
    const t = i / 1000;
    close(cToSlider(sliderToC(t)), t, 1e-9, `cToSlider∘sliderToC(${t})`);
  }
  for (let i = 0; i <= 330; i++) {
    const c = i / 1000;
    close(sliderToC(cToSlider(c)), c, 1e-9, `sliderToC∘cToSlider(${c})`);
  }
});

test('单调递增（步长 0.001 全程扫描）', () => {
  let prev = -1;
  for (let i = 0; i <= 1000; i++) {
    const c = sliderToC(i / 1000);
    assert.ok(c > prev, `t=${i / 1000} 处非严格递增`);
    prev = c;
  }
});

test('越界输入钳制到定义域（防御式，不产生 NaN/越域）', () => {
  assert.equal(sliderToC(-0.5), 0);
  assert.equal(sliderToC(1.5), C_SLIDER_MAX);
  assert.equal(cToSlider(-1), 0);
  assert.equal(cToSlider(2), 1);
});

test('位置变换：负向恒等（调低色度精确线性，§4.2）', () => {
  for (const v of [-100, -73, -50, -1, 0]) {
    assert.equal(chromaValueToSliderPos(v), v, `pos(${v})`);
    assert.equal(chromaSliderPosToValue(v), v, `value(${v})`);
  }
});

test('位置变换锚点：增强半程中段（行程 3/4）≈ +33，端点精确落位', () => {
  // 精确锚点：s=50 → 100·0.5^1.6 = 32.988，UI 按 step=1 量化显示 +33
  close(chromaSliderPosToValue(50), 32.9878, 1e-3, '行程 3/4 处参数值');
  assert.equal(Math.round(chromaSliderPosToValue(50)), 33, '量化后应显示 +33');
  close(chromaValueToSliderPos(33), 50, 5e-2, 'pos(+33) 在增强半程中点近旁');
  assert.equal(chromaValueToSliderPos(0), 0);
  assert.equal(chromaValueToSliderPos(100), 100, '+100 极限保留在右端');
  assert.equal(chromaSliderPosToValue(100), 100);
  close(chromaValueToSliderPos(50), 64.8420, 1e-4, 'pos(+50)=100·0.5^(1/1.6)');
});

test('位置变换双向互逆 + 单调（[0,100] 整数扫描）', () => {
  for (let v = 0; v <= 100; v++) {
    const s = chromaValueToSliderPos(v);
    close(chromaSliderPosToValue(s), v, 1e-9, `round-trip(${v})`);
    assert.ok(s >= 0 && s <= 100);
  }
  let prev = -1;
  for (let s = 0; s <= 100; s++) {
    const v = chromaSliderPosToValue(s);
    assert.ok(v > prev, `s=${s} 处非严格递增`);
    prev = v;
  }
});

test('低值细调区展开：+1..+10 占增强半程前 ~24%（线性时 10%）', () => {
  const pos10 = chromaValueToSliderPos(10);
  assert.ok(pos10 > 20 && pos10 < 28, `pos(+10)=${pos10} 不在 (20,28)`);
  assert.ok(pos10 > 10, '展开后必须大于线性位置 10');
});
