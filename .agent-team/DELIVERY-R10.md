# 交付简报（DELIVERY-R10）— 第十轮：oklch 第二批切换 × JND 统一 × 打包修复

> 队长 2026-09-07；用户批准的四主项（打包类挂起）+ 质询引出的打包三连修。

## 交付清单
| 项 | 交付 | commit |
|----|------|--------|
| 打包三连修 | wheel 构建失败修复+films 卡补包+**scorer.pt 随 wheel 分发**（用户拍板开箱即用，安装态候选链）+golden 移出 | e09053f/efd0c72/4d5af5d |
| JND 单源化 | `JND_DELTA_E=2.3` 权威常量，早停零变化钉死 | baec4ec |
| colorcal native oklch | 15×→~2×（提速 11×），逐位/1 ULP 对齐，msun cbrt 复刻 | dca189c |
| skin 椭圆重拟合 | 三验收全过（腰斩 5→0/分叉 2→0/误伤守住），翻转「可切」 | dca189c |
| **oklch 第二批切换** | skin/colorcal 缺省翻 oklch——**四涉域 stage 全部完成 t52 渐进方案**；A1 23 卡字节级；film_pro_400h 盲区补钉 | 02a77b1 |
| huesat A 轨删除评估 | 有条件可行 2.5-3.5 人日，前置=补 5 个 DCP 点云（0.5 人日） | research/arail-removal-eval.md |

## 验证
- **全量 1484 passed / 0 failed**（R9 基线 1474+10 新增对账）
- 门禁 `.r10b_ok` PASS：A1 双基线 23/23 字节级；RAW 归因独立加严（colorcal 精确 0/skin 100%）；性能缺省 1.02×
- 三组基线队长重生成（RAW 24/gate v3/v2），其余 18 条目字节未动

## 遗留与拍板
- **待拍板**：huesat A 轨删除（推荐删，先补 5 个点云）——GPL 血缘釜底抽薪
- 观察窗（qa）：无人像高覆盖磨皮两代同在（scene 门控/覆盖率上限下轮）/双肤区强度尾部 9 张亚 JND/gate skin case 软边带探针增补
- tech_debt #18：椭圆常数双源（清偿=下次变更前参数化）
- 打包类挂起：四视觉模型（uniface/segformer/sapiens/rfdetr+CLIP）入包改造（HF 生态本地化，2.6GB）

## 用户验收
- 2026-09-07：待验收
