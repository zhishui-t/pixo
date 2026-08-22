# Pixo Vision 模型清单

本目录只登记模型元数据，不复制任何大文件。

- `vision_models.json`：Pixo Vision 当前实际使用的模型/依赖清单。
- `__init__.py`：加载与字段完整性校验函数。

校验：

```bash
python - <<'PY'
from pixo.manifests import load_all_manifests
print(load_all_manifests()['vision_models']['schema_version'])
