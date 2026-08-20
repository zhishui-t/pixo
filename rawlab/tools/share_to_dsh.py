"""share_to_dsh —— 把渲染产物复制到 DSH 分享目录, 文件名带时间戳。

用途: DSH 聊天客户端按 URL 缓存图片, 同名覆盖会导致用户看到旧图。
约定: 分享图统一命名 {base}_{YYYYMMDD_HHMMSS}.jpg, 每次生成都是新 URL,
缓存失效。文件本体可重复(允许 base 相同), 但分享时永远给新名字。

用法:
    python -m rawlab.tools.share_to_dsh <src1> [src2 ...] [--base NAME]
    默认分享目录 = $DSH_HOME/share (本机 C:\\Users\\10042\\.dsh\\share)
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

SHARE_DIR = Path.home() / ".dsh" / "share"


def share(src: str | Path, base: str | None = None, share_dir: Path | None = None) -> Path:
    """复制 src 到分享目录, 返回带时间戳的目标路径。"""
    src = Path(src)
    share_dir = share_dir or SHARE_DIR
    share_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    stem = base or src.stem
    dst = share_dir / f"{stem}_{ts}{src.suffix.lower() or '.jpg'}"
    shutil.copy2(src, dst)
    return dst


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--base")]
    base = None
    for a in argv:
        if a.startswith("--base="):
            base = a.split("=", 1)[1]
    if not args:
        print(__doc__)
        return 1
    for src in args:
        dst = share(src, base=base)
        print(f"{src} -> http://dsh.local/share/{dst.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
