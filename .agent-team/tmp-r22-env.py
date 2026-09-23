"""R22 dev-1 环境探测（一次性；输出重定向到文件再读）。"""
import importlib
import sys
from pathlib import Path

print("python:", sys.version.replace("\n", " "))
for name in ("rawpy", "cv2", "numpy", "yaml", "pytest", "fastapi"):
    try:
        mod = importlib.import_module(name)
        print(f"{name}: {getattr(mod, '__version__', '?')}")
    except Exception as exc:  # noqa: BLE001
        print(f"{name}: MISSING ({type(exc).__name__}: {exc})")

corpus = Path(r"K:\data\photo\0711\raw")
print("corpus exists:", corpus.is_dir())
if corpus.is_dir():
    nefs = sorted(corpus.glob("*.NEF")) + sorted(corpus.glob("*.nef"))
    print("NEF count:", len(nefs))
    print("first5:", [p.name for p in nefs[:5]])
