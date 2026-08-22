# Pixo Vision 模型与数据集清单

本目录仅登记元数据，不复制任何大文件。

- `vision_models.json`：Pixo Vision 相关模型/依赖（YOLOE、MobileCLIP、Aesthetic Scorer、FairFace、YuNet、MediaPipe 等）。
- `vision_datasets.json`：guanlan 校准集、景观数据集、Pixo 金样本及真实 RAW 占位等标注/数据资源。
- `__init__.py`：加载与字段完整性校验函数。

校验：

```bash
python - <<'PY'
from pixo.manifests import load_all_manifests
print(load_all_manifests()['vision_models']['schema_version'])
PY
python -m pytest src/render/tests/test_vision_manifests.py -q
```
