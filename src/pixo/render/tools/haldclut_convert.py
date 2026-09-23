"""HaldCLUT(png) → .cube 转换工具 (R32-T3, 格式适配路线)。

把 RawTherapee 兼容的 HaldCLUT PNG (level 布局: 边长 = level³, 网格 = level²,
8/16 位) 转换为我方 LUT 卡库的 .cube 形态 (stylize Stage 经 core.lut 直接
消费, 零引擎改动)。引擎侧数学不移植: 我方 LUT3D 用四面体插值 (Kasson 1993),
RT clutstore.cc 用三线性 —— 四面体无三线性的"扇形"误差, RT 侧无精度优势
(取舍依据见 .agent-team/dev1-r32-t3.md)。

用法:
  python -m pixo.render.tools.haldclut_convert <in.png> [out.cube] [--title T]

布局/位深: 自动识别 level³ 边长; uint8 按 255、uint16 按 65535 归一化
(与 RT clutstore 的 uint16 载入同口径); 浮点 png 按 [0,1] 直读。
色彩域: 像素值原样搬运 —— 应用域由消费方 (stylize, DOMAIN_GAMMA_RGB,
即 sRGB gamma 显示域) 决定; RT 包内多数社区 CLUT 为显示域制作, 与该域
匹配; RT 官方按文件名后缀区分工作域的惯例 (如 *ProPhoto.png) 见
.agent-team/dev1-r32-t3.md 许可/规格节, 转换时不做色彩变换。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def load_hald_png(path: str | Path) -> np.ndarray:
    """读 HaldCLUT png → (S,S,3) float32 [0,1] (cv2 IMREAD_UNCHANGED)。"""
    import cv2

    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"无法读取图像: {path}")
    if img.ndim == 2:
        raise ValueError(f"Hald 图须为 3 通道 (实得灰度): {path}")
    if img.shape[2] == 4:
        img = img[..., :3]
    # cv2 BGR → RGB
    img = img[..., ::-1]
    if img.dtype == np.uint8:
        img = img.astype(np.float32) / 255.0
    elif img.dtype == np.uint16:
        img = img.astype(np.float32) / 65535.0
    else:
        img = np.clip(img.astype(np.float32), 0.0, 1.0)
    return np.ascontiguousarray(img)


def convert(hald_png: str | Path, out_cube: str | Path,
            title: str | None = None) -> tuple[int, int]:
    """png → .cube; 返回 (level, grid_n)。"""
    from ..core.lut3d import hald_level_to_lut, write_cube

    img = load_hald_png(hald_png)
    side = img.shape[0]
    level = int(round(side ** (1.0 / 3.0)))
    if level <= 1 or level ** 3 != side:
        raise ValueError(
            f"Hald 边长 {side} 不是 level³ (RT level 布局): {hald_png}")
    lut = hald_level_to_lut(img)
    if title is None:
        title = Path(hald_png).stem
    write_cube(lut.data, out_cube, title=title)
    return level, lut.n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="HaldCLUT png → .cube (R32-T3 格式适配)")
    ap.add_argument("input", help="HaldCLUT png (level 布局, 8/16 位)")
    ap.add_argument("output", nargs=None, default=None,
                    help="输出 .cube (缺省 = 同名 .cube)")
    ap.add_argument("--title", default=None, help=".cube TITLE (缺省 = 文件名)")
    args = ap.parse_args(argv)
    out = args.output or str(Path(args.input).with_suffix(".cube"))
    level, n = convert(args.input, out, title=args.title)
    print(f"[OK] {args.input} (level {level}, grid {n}^3) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
