"""发送 rawlab 成果图到飞书 (逐张, 文件名即说明)。"""
import subprocess
import sys
from pathlib import Path

FEISHU = r"C:\Users\10042\send-to-feishu.js"
DIR = Path(__file__).resolve().parent / "out" / "feishu"

files = sorted(DIR.glob("*.jpg"))
print(f"待发送 {len(files)} 张:")
for f in files:
    print(f"  {f.name}")

for f in files:
    try:
        r = subprocess.run(["node", FEISHU, str(f)],
                           capture_output=True, text=True, timeout=120)
        ok = r.returncode == 0
        out = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
        err = (r.stderr or "").strip().splitlines()[-1] if r.stderr else ""
        print(f"[{'OK' if ok else 'FAIL'}] {f.name}: {out or err}")
    except Exception as e:
        print(f"[ERR] {f.name}: {e}")
