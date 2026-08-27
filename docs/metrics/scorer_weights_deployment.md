# 美学评分器权重部署记录（t52）

日期：2026-08-25 ｜ 执行：开发4 ｜ 结论：**部署成功（真评分器已可用）**

## 1. 许可核验
| 组件 | 渠道 | 许可 | 证据 |
|---|---|---|---|
| aesthetic_scorer.pt | HF `rsinema/aesthetic-scorer`（model.pt 直存） | **MIT** | 模型卡 tag `license:mit` + README front-matter `license: mit` |
| openai/clip-vit-base-patch32（backbone） | HF hub 自动下载 | **MIT** | OpenAI 官方 CLIP 仓库许可 |

两条目均已登记进仓库根 `model_licenses.json`（usage=redistribution_allowed_with_license_notice，
发布需附 MIT 声明；无 internal_development_only 隔离要求）。
GitHub 侧 `rsinema/aesthetic-scorer` 仓库已 404（API 另受限流），权威渠道为 Hugging Face。

## 2. 权重获取
- 来源：`https://huggingface.co/rsinema/aesthetic-scorer/resolve/main/model.pt`
- 落盘：`resources/models/aesthetic/aesthetic_scorer.pt`，**333.7 MB / 26.2s**
- 完整性：torch.load(weights_only 默认) 通过；OrderedDict 213 键 =
  backbone(CLIP ViT-B/32 vision tower,199) + 7×Linear(768→1) 头
  （aesthetic/quality/composition/light/color/dof/content）——与
  `pixo/vision/aesthetic.py::_Scorer` 键名形状逐一对应（load_state_dict strict=False 全命中）

## 3. 代码变更
- `_default_model_path()` 默认路径 src/models/aesthetic_scorer.pt → **resources/models/aesthetic/aesthetic_scorer.pt**；
  `PIXO_AESTHETIC_MODEL` env 覆盖保留。
- 打包口径：wheel 不捆绑权重（沿既定先例）；安装态用 env 或随发行版分发该文件。

## 4. CLIP backbone 首跑
- transformers 经 HF 缓存自动下载 `models--openai--clip-vit-base-patch32`
  （缓存实测约 600MB 级，含 fp32 权重）；本机已在缓存，首次推理加载 12s、首图前向 29.6s、后续 0.4s/张。
- Windows 无符号链接警告仅影响缓存去重，不影响功能（可用 Developer Mode 消除）。

## 5. 验证
- 探针：`make_default_scorer()` → `_PixoScorerAdapter`（health available=True）
- 真实渲染非 Mock 分：
  - DSC_5236（golden tone/output_u8.npy 341×512）：overall=0.000（color 0.951/lighting 0.23）
  - DSC_0355（rawpy 显影 4040×6064）：overall=0.119（lighting 1.05/color 1.148）
  - 两图 source 均为 "pixo"，维度分域 [0,5] 内
- 回归：test_aesthetic_wiring + test_vision_extras 全绿

## 6. 备注
- 输出量纲整体偏低（多维度贴近 0）：系该模型头原始输出分布，t20 已注明"钳制映射未标定"；
  后续如需参与阈值决策须先做分布标定（参考 docs/metrics/proxy_distribution.md 方法论）。
