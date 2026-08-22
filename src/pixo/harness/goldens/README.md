# Pixo 金样本集 v0

不依赖真实 RAW 的金样本基础设施。

## 组成

- `manifest.py`：`GoldenManifest` / `GoldenSample`、schema 校验、load/save、哈希。
- `samples.py`：合成曝光/肤色/场景/连拍样本生成器 + 内置登记数据。
- `compare.py`：测量报告与期望指标带容差比对、合成样本运行。
- `golden_manifest.json`：内置 manifest（4 条合成 + 4 条真实占位）。
- `generate_manifest.py`：重新生成 manifest。

## 常用命令

```bash
# 生成/校验 manifest
python -m pixo.harness.goldens.generate_manifest

# 测试
python -m pytest src/render/tests/test_goldens_v0.py -q
```

真实 RAW 路径不存在时样本 `available=False`，回归接口自动 skip。
