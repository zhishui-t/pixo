# R27 · 风格卡复合语义审计 + 资产缺陷清偿

日期：2026-09-19 ｜ 上承：R24 profile_curve 复合修复（§3 预告"7 张卡输出变化
是语义修复预期后果"——本轮量化验证）

---

## 0. 结论速览

1. **7 张 profile_curve 卡在复合语义下全部健康**：cc 0.96-0.98、端点无病理、
   A 5.97~19.19。R24 修复改善了所有卡（V1 旧语义口径下该槽位 A≈36+），
   无需重标定。
2. **preview_baseline_v3 是对相机目标最强的卡**（A=5.97）；版本演化
   v1(8.21)→v2(13.43)→v3(5.97)——v2 曾回退、v3 收复并超越。
3. **两处资产缺陷清偿/入账**：preview_baseline 的 dcp 钉扎是失效绝对路径
   （双层 pixo 目录）——**已修**为仓库相对路径；`LR Camera Standard Baseline.dcp`
   与 `LR Baseline.dcp` **字节相同**（md5 5a23f967eeec）——lr_camera_standard
   卡输出恒等于 lr_baseline，其声称的 Camera Standard v2 目标未被资产代表
   ——**tech_debt #24 入账**（重出 DCP 需 LR 管线，本机无，数据侧待办）。
4. **lr_* 卡绝对判分被数据阻断**（truth=LR 导出，本机无）——vs 相机数字仅作
   相对参照，如实记录。

## 1. 审计数据（`.artifacts/_r27_style_card_audit.py` → `_r27_style_card_audit.json`）

n=24 采样（23 有效，1 张已知 LibRaw 坏文件跳过）；每卡用**自己的 DCP 钉扎 +
全量卡参数**渲染（生产同构），vs 相机内嵌 JPEG：

| 臂 | DCP | A | B | C_raw | cc | p05 | p995 |
|---|---|---:|---:|---:|---:|---:|---:|
| **VR recipe**（参照臂） | 默认 | **3.59** | 6.75 | 10.93 | 0.98 | 14 | 239 |
| preview_baseline_v3 | Preview v3 | **5.97** | 9.31 | 12.91 | 0.98 | 25 | 238 |
| preview_baseline | Preview（路径回退→已修） | 8.21 | 10.54 | 14.05 | 0.97 | 24 | 234 |
| lr_adobe_standard_baseline | LR Adobe Std | 12.73 | 13.99 | 16.58 | 0.96 | 14 | 232 |
| preview_baseline_v2 | Preview v2 | 13.43 | 15.74 | 19.11 | 0.98 | 23 | 235 |
| acr_standard | 默认（无钉扎） | 15.04 | 15.65 | 18.28 | 0.97 | 33 | 255 |
| lr_baseline | LR Baseline | 19.19 | 20.61 | 21.81 | 0.96 | 9 | 222 |
| lr_camera_standard_baseline | LR Cam Std（**字节同 LR Baseline**） | 19.19 | 20.61 | 21.81 | 0.96 | 9 | 222 |
| V0 中性（基线） | 默认 | 28.65 | 30.30 | 31.41 | 0.96 | 7 | 154 |

## 2. 处置与决策

| 项 | 处置 |
|---|---|
| preview_baseline dcp 坏路径 | **已修**：`K:\work\project\pixo\pixo\...` → `resources/dcp/Nikon Z 5 2 RawLab Preview Baseline.dcp`（1 行，git diff 干净） |
| 7 卡重标定 | **不需要**（数据健康；卡的 warmth trims/DCP 钉扎标定在复合语义下依然有效） |
| 卡是否改用 eotf=recipe | **不改**——卡是多阶段联合标定（DCP+warmth+trim 围绕 profile_curve），
  换影调来源会作废既有标定；recipe 是独立臂（`docs/metrics/r24_recipe_tone_fit.md`），
  两者并存按用途取用 |
| LR Cam Std DCP 字节重复 | **tech_debt #24 入账**（重出 DCP 属数据侧待办；期间两卡结论应视为同一臂） |
| lr_* 卡绝对判分 | 数据阻断（无 LR 导出语料）——记录在案，不作臆断 |

## 3. 改动清单

| 文件 | 改动 |
|---|---|
| `configs/styles/preview_baseline.json` | dcp 钉扎失效绝对路径 → 仓库相对路径（1 行） |
| `docs/tech_debt.md` | 新增 #24（LR Cam Std DCP 字节重复） |
| `.artifacts/_r27_style_card_audit.py` / 本文件 | 探针 + 轮报 |

渲染代码零改动。

## 4. 回归

配置改动 1 行（路径修复，不改渲染语义）——风格卡相关测试
（test_service_api 的 styles 端点用例等）+ 全量见 changelog。
