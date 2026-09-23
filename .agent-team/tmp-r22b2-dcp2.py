"""F10 #3b DCP×6 再分发核验：二进制内嵌可读串提取（只读）。

逐 .dcp 打印：sha256 / 全部 >=4 字符可读 ASCII 串中含
(rawlab|copyr|licen|http|permission|reserved|©|fitted|profil) 者及其上下文，
用于判定「文件内是否自带再分发许可/版权声明」。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

DCP_DIR = Path(r"K:\work\project\pixo\resources\dcp")
KEY = re.compile(rb"rawlab|copyr|licen|http|permission|reserved|\xa9|fitted|"
                 rb"profil|adobe", re.IGNORECASE)
STR = re.compile(rb"[\x20-\x7e]{4,}")


def main() -> None:
    for p in sorted(DCP_DIR.glob("*.dcp")):
        b = p.read_bytes()
        print(f"\n### {p.name}")
        print(f"    size={len(b)} sha256={hashlib.sha256(b).hexdigest()}")
        seen = set()
        for m in STR.finditer(b):
            s = m.group(0)
            if not KEY.search(s):
                continue
            txt = s.decode("latin1")
            if txt in seen:
                continue
            seen.add(txt)
            print(f"    @{m.start():>7}: {txt!r}")
        if not seen:
            print("    (无可读许可/版权线索)")
        # 显式检查许可语汇
        for kw in (b"copyright", b"license", b"permission", b"reserved",
                   b"http", b"creativecommons", b"CC BY"):
            cnt = b.lower().count(kw.lower())
            if cnt:
                print(f"    关键字 {kw.decode()!r}: {cnt} 次")


if __name__ == "__main__":
    main()
