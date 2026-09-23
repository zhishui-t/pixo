"""检查 .gitignore 编码与关键行（只读）。"""
from pathlib import Path

b = Path(r"K:\work\project\pixo\.gitignore").read_bytes()
print("bytes:", len(b))
try:
    t = b.decode("utf-8")
    print("utf-8: OK, lines:", len(t.splitlines()))
except UnicodeDecodeError as e:
    print("utf-8: BAD", e.start, e.end, b[max(0, e.start - 10):e.end + 10])
    for enc in ("gbk", "utf-16", "cp1252"):
        try:
            b.decode(enc)
            print(f"  decodes as {enc}")
        except Exception as exc:
            print(f"  not {enc}: {exc}")
print("--- lines 84-95 ---")
for i, line in enumerate(b.decode("utf-8", "replace").splitlines(), 1):
    if 84 <= i <= 95:
        print(f"{i}: {line!r}")
