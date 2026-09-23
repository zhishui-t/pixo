"""tech_debt.md 编号审计：主序号重复/缺号/子序号（只读）。"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

p = Path(r"K:\work\project\pixo\docs\tech_debt.md")
lines = p.read_text(encoding="utf-8").splitlines()
main, sub = [], []
for i, line in enumerate(lines, 1):
    m = re.match(r"^(\d+[a-z]?)\.\s", line)
    if m:
        main.append((i, m.group(1), line[:70]))
    m2 = re.match(r"^\s+(\d+\.\d+)\s", line)
    if m2:
        sub.append((i, m2.group(1)))
print("== 主序号 ==")
for i, n, txt in main:
    print(f"  :{i:<4} {n:<4} {txt}")
cnt = Counter(n for _, n, _ in main)
print("== 重复 ==")
for n, c in cnt.items():
    if c > 1:
        print(f"  {n} x{c}: {[i for i, m, _ in main if m == n]}")
print("== 子序号 ==")
print("  ", [f":{i}={n}" for i, n in sub])
print("== 正文引用 10b / 条目编号引用 ==")
for i, line in enumerate(lines, 1):
    if re.search(r"条目\s*10b|条目\s*3\b|#2[0-9]\b", line):
        print(f"  :{i} {line[:100]}")
