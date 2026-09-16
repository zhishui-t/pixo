/**
 * R22 F05 —— 场景预设常量（后端 `configs/styles/scenes.json` 的 6 个键）。
 *
 * 与后端的契约：
 *   - id 必须与 scenes.json 键集**逐一对应**。后端单测
 *     `tests/unit/test_f04_f05_injection.py::test_frontend_scene_ids_match_scenes_json`
 *     解析本文件校验同步——改 id 必须同时改后端配置（configs/** 不在
 *     本轮前端改动域内，需要时走独立变更单）。
 *   - 应用方式 = PUT /api/sessions/{session_id}/params，body `{__scene: id}`；
 *     服务层经 `apply_scene_preset` 展开为 stage 参数覆盖后**深合并**。
 *   - 叠加语义：预设只写自己声明的键（如 mono 只写 colorcal.saturation），
 *     不会重置其它参数；连续应用两个预设时后一个只覆盖重叠键。
 */
export interface ScenePreset {
  /** 后端 scenes.json 的键（scene_id）。 */
  id: string;
  /** 中文短标签（紧凑 chip 用）。 */
  label: string;
  /** 一句话说明（title 提示）。 */
  hint: string;
}

export const SCENE_PRESETS: ScenePreset[] = [
  { id: 'portrait', label: '人像', hint: '提亮影调 + 轻锐化 + 皮肤柔化（contrast 0.08）' },
  { id: 'landscape', label: '风光', hint: '加反差 + 提饱和（contrast 0.18 / saturation 0.15）' },
  { id: 'night', label: '夜景', hint: '低反差保高光（contrast 0.06）' },
  { id: 'street', label: '街拍', hint: '中等反差（contrast 0.12）' },
  { id: 'food', label: '美食', hint: '轻反差 + 轻饱和（contrast 0.10 / saturation 0.10）' },
  { id: 'mono', label: '黑白', hint: '去饱和（saturation -1.0）' },
];
