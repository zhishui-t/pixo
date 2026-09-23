"""F10 #25：在 .gitignore 的 `build/` 行后就地插入「明确排除」注释（按字节插入，保留原编码）。

.gitignore 是**混合编码**文件（含非 UTF-8 字节，read 工具会报 invalid UTF-8），故按字节
操作、只插入 ASCII 注释；插入前备份、插入后校验除新增行外逐字节不变。
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

GI = Path(r"K:\work\project\pixo\.gitignore")
BAK = Path(r"K:\work\project\pixo\.agent-team\tmp-r22b2-gitignore.bak")
NOTE = (
    b"# build/ \xe6\x8e\x92\xe9\x99\xa4\xe8\xaf\xb4\xe6\x98\x8e (R22 docs/tech_debt.md "
    b"\xe6\x9d\xa1\xe7\x9b\xae 23, F10 #25):\n"
    b"# setuptools build/lib/pixo \xe6\x98\xaf\xe6\x9e\x84\xe5\xbb\xba\xe4\xb8\xad\xe9\x97\xb4"
    b"\xe4\xba\xa7\xe7\x89\xa9 (\xe6\x97\xa7\xe5\x89\xaf\xe6\x9c\xac, \xe4\xb8\x8e src/ "
    b"\xe6\xbc\x82\xe7\xa7\xbb), \xe9\x9d\x9e\xe5\x8f\x91\xe5\xb8\x83\xe6\xba\x90.\n"
    b"# git \xe5\xb7\xb2\xe6\x8e\x92\xe9\x99\xa4; \xe6\x89\x93\xe5\x8c\x85 packages.find "
    b"where=\"src\" \xe4\xb8\x8d\xe5\x90\xab\xe5\xae\x83; \xe8\xbf\x90\xe8\xa1\x8c\xe6\x97\xb6"
    b"\xe6\x8b\x89 src (tests/conftest.py:21-22).\n"
    b"# \xe6\x98\x8e\xe7\xa1\xae\xe6\x8e\x92\xe9\x99\xa4 + \xe6\x96\x87\xe6\xa1\xa3\xe8\xaf\xb4"
    b"\xe6\x98\x8e, \xe4\xb8\x8d\xe5\x88\xa0\xe9\x99\xa4 (build \xe6\xb5\x81\xe7\xa8\x8b\xe5"
    b"\x8f\xaf\xe8\x83\xbd\xe4\xbe\x9d\xe8\xb5\x96).\n"
)
MARK = b"\nbuild/\n"

before = GI.read_bytes()
if b"R22 docs/tech_debt.md" in before:
    print("已存在注释，跳过（幂等）")
    raise SystemExit(0)
shutil.copyfile(GI, BAK)
idx = before.find(MARK)
assert idx >= 0, "未找到 '\\nbuild/\\n' 锚点"
out = before[:idx + len(MARK)] + NOTE + before[idx + len(MARK):]
GI.write_bytes(out)
after = GI.read_bytes()
print(f"before bytes={len(before)} sha256={hashlib.sha256(before).hexdigest()[:16]}")
print(f"after  bytes={len(after)}  sha256={hashlib.sha256(after).hexdigest()[:16]}")
print(f"delta bytes={len(after) - len(before)} (插入注释 {len(NOTE)} 字节)")
print("除插入行外逐字节不变:", before[:idx + len(MARK)] == after[:idx + len(MARK)]
      and before[idx + len(MARK):] == after[idx + len(MARK) + len(NOTE):])
print("backup:", BAK)
print("--- 插入后 build/ 邻域 ---")
txt = after.decode("utf-8", "replace").splitlines()
for i, line in enumerate(txt, 1):
    if 88 <= i <= 97:
        print(f"{i}: {line}")
