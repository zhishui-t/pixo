"""修正 .gitignore 插入注释中的一处措辞（按字节替换，保留原编码）。"""
from __future__ import annotations

import hashlib
from pathlib import Path

GI = Path(r"K:\work\project\pixo\.gitignore")
OLD = ("\u8fd0\u884c\u65f6\u62c9 src").encode("utf-8")
NEW = ("\u8fd0\u884c\u65f6/\u6d4b\u8bd5 import \u8d70 src").encode("utf-8")
b = GI.read_bytes()
n = b.count(OLD)
print(f"命中 {n} 处: {OLD.decode()} -> {NEW.decode()}")
assert n == 1, "期望恰好 1 处"
before = hashlib.sha256(b).hexdigest()[:16]
GI.write_bytes(b.replace(OLD, NEW))
after = GI.read_bytes()
print(f"sha256 {before} -> {hashlib.sha256(after).hexdigest()[:16]} "
      f"bytes {len(b)} -> {len(after)}")
for i, line in enumerate(after.decode("utf-8", "replace").splitlines(), 1):
    if 90 <= i <= 94:
        print(f"{i}: {line}")
