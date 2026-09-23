"""F10 #3b 精确取证：DCP IFD0 逐 tag 解析（确认 'RawLab fitted profile' 落在哪个 tag）。

DNG 标签：0xC6F8 ProfileName / 0xC6FE ProfileCopyright / 0xC614 UniqueCameraModel
         0x8298 Copyright / 0xC6F9 ProfileHueSatMapDims。
"""
from __future__ import annotations

import struct
from pathlib import Path

DCP_DIR = Path(r"K:\work\project\pixo\resources\dcp")
TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4,
             10: 8, 11: 4, 12: 8}
TAGS = {
    0x010F: "Make", 0x0110: "Model", 0x0111: "StripOffsets",
    0x0131: "Software", 0x013B: "Artist", 0x8298: "Copyright",
    0x8769: "ExifIFD", 0xC614: "UniqueCameraModel",
    0xC6F8: "ProfileName", 0xC6FE: "ProfileCopyright",
    0xC6FF: "ProfileEmbedPolicy", 0xC7A5: "BaselineExposureOffset",
}


def dump(path: Path) -> None:
    data = path.read_bytes()
    endian = "<" if data[:2] == b"II" else ">"
    (ifd0,) = struct.unpack_from(endian + "I", data, 4)
    (count,) = struct.unpack_from(endian + "H", data, ifd0)
    print(f"\n### {path.name} IFD0 @{ifd0} entries={count}")
    base = ifd0 + 2
    for i in range(count):
        e = base + i * 12
        tag, typ, cnt = struct.unpack_from(endian + "HHI", data, e)
        size = TYPE_SIZE.get(typ, 1) * cnt
        inline = data[e + 8:e + 8 + size]
        (voff,) = struct.unpack_from(endian + "I", data, e + 8)
        name = TAGS.get(tag, "")
        if typ == 2:
            raw = inline if size <= 4 else data[voff:voff + size]
            val = raw.split(b"\x00")[0].decode("latin1", "replace")
            print(f"    tag=0x{tag:04X} {name:<22} type=2 cnt={cnt:<4} "
                  f"offset={voff if size > 4 else '-'} value={val!r}")
        elif name:
            print(f"    tag=0x{tag:04X} {name:<22} type={typ} cnt={cnt} "
                  f"value={inline[:8].hex()}")


for p in sorted(DCP_DIR.glob("*.dcp")):
    dump(p)
