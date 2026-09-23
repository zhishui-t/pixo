"""R22 stream-2b 探针: resources/dcp/*.dcp 来源/许可标注逐项盘点 (只读)。

输出: 每个 .dcp 的 sha256/大小 + 可读 ASCII 串中命中关键字者 + DCP 内嵌
ProfileName / Copyright(0x8298) / CameraModelName / UniqueCameraModel /
ProfileCopyright (0xC6FE) 等 TIFF-IFD 标签值。
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

ROOT = Path(r"K:\work\project\pixo")
DCP_DIR = ROOT / "resources" / "dcp"

# DNG/EXIF 相关标签号 -> 名称
TAGS = {
    0x010F: "Make",
    0x0110: "Model",
    0x0131: "Software",
    0x013B: "Artist",
    0x8298: "Copyright",
    0xC614: "UniqueCameraModel",
    0xC6F8: "ProfileName",
    0xC6F9: "ProfileCopyright" if False else "ProfileHueSatMapDims",
    0xC6FC: "ProfileName(?)",
    0xC6FD: "ProfileEmbedPolicy",
    0xC6FE: "ProfileCopyright",
}
TAG_STR = {0x010F, 0x0110, 0x0131, 0x013B, 0x8298, 0xC614, 0xC6FE}
# DNG 私有标签实际号(以 DNG 规范为准): ProfileName=0xC6F8, ProfileCopyright=0xC6FE
DNG_TAGS = {
    0xC6F8: "ProfileName",
    0xC6FE: "ProfileCopyright",
    0xC614: "UniqueCameraModel",
}


def type_size(t: int) -> int:
    return {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}.get(t, 1)


def read_tags(data: bytes) -> list[tuple[str, str]]:
    out = []
    if data[:2] not in (b"II", b"MM"):
        return out
    endian = "<" if data[:2] == b"II" else ">"
    (magic,) = struct.unpack_from(endian + "H", data, 2)
    if magic != 42:
        return out
    (ifd0,) = struct.unpack_from(endian + "I", data, 4)
    seen = set()
    todo = [ifd0]
    while todo:
        off = todo.pop(0)
        if off in seen or off <= 0 or off + 2 > len(data):
            continue
        seen.add(off)
        (count,) = struct.unpack_from(endian + "H", data, off)
        base = off + 2
        for i in range(count):
            e = base + i * 12
            if e + 12 > len(data):
                break
            tag, typ, cnt = struct.unpack_from(endian + "HHI", data, e)
            size = type_size(typ) * cnt
            if size <= 4:
                raw = data[e + 8:e + 8 + size]
            else:
                (voff,) = struct.unpack_from(endian + "I", data, e + 8)
                raw = data[voff:voff + size] if voff + size <= len(data) else b""
            name = DNG_TAGS.get(tag)
            if name and typ == 2:
                out.append((name, raw.split(b"\x00")[0].decode("utf-8", "replace")))
            elif tag in TAG_STR and typ == 2:
                label = {0x010F: "Make", 0x0110: "Model", 0x0131: "Software",
                         0x013B: "Artist", 0x8298: "Copyright"}.get(tag, hex(tag))
                out.append((label, raw.split(b"\x00")[0].decode("utf-8", "replace")))
            if tag == 0x8769:  # ExifIFD
                if size == 4:
                    (v,) = struct.unpack_from(endian + "I", data, e + 8)
                    todo.append(v)
        if off + 2 + count * 12 + 4 <= len(data):
            (nxt,) = struct.unpack_from(endian + "I", data, off + 2 + count * 12)
            if nxt:
                todo.append(nxt)
    return out


KEYS = re.compile(rb"rawlab|copyright|\xa9|license|adobe|nikon|profil",
                  re.IGNORECASE)


def main() -> None:
    manifest = json.loads((DCP_DIR / "manifest.json").read_text("utf-8"))
    dcps = sorted(DCP_DIR.glob("*.dcp"))
    print(f"manifest targets={len(manifest['targets'])} "
          f"默认预设={manifest['default_lr_preset']}")
    for name, tgt in manifest["targets"].items():
        print(f"  target {name}: dcp={tgt['dcp']} preset={tgt['preset']} "
              f"exists={(ROOT / tgt['dcp']).exists()}")
    print(f"目录 .dcp 数量={len(dcps)}")
    print("-" * 70)
    for p in dcps:
        b = p.read_bytes()
        print(f"\n### {p.name}  size={len(b)}  sha256={hashlib.sha256(b).hexdigest()[:16]}")
        tags = read_tags(b)
        for k, v in tags:
            print(f"    tag {k} = {v!r}")
        hits = sorted({m.group(0).decode("latin1") for m in KEYS.finditer(b)})
        print(f"    关键字命中 = {hits}")
        # 打印命中串的上下文
        for m in list(KEYS.finditer(b))[:8]:
            s = max(0, m.start() - 40)
            ctx = b[s:m.end() + 60]
            printable = "".join(chr(c) if 32 <= c < 127 else "." for c in ctx)
            print(f"    ctx@{m.start()}: ...{printable}...")
        # manifest 引用交叉
        ref = [k for k, t in manifest["targets"].items()
               if Path(t["dcp"]).name == p.name]
        print(f"    manifest 引用 = {ref or '未引用'}")


if __name__ == "__main__":
    main()
