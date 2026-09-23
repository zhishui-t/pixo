#pragma once

// pixo.render RCD 去马赛克内核 (R32-T1, 移植自 RawTherapee, GPLv3)。
// 算法出处与适配说明见 rcd_demosaic_native.cpp 文件头。

#include <cstdint>

#include "abi.h"

// RCD (Ratio Corrected Demosaicing) 全分辨率去马赛克。
//
// mosaic : (H,W) float32 行主序, Python 侧已按 (v-black)/(white-black) 归一化
//          到 [0,1] (设计 v2 M3 定夺; native 内 LIM01 钳位保留 RT 原语义)。
// out    : (H,W,3) float32 HWC 交错, 线性相机 RGB, 白电平相对 [0,1]。
// width/height : mosaic 尺寸。
// pattern: 2x2 CFA 布局码, 行主序 4 元素 (pattern[0]=左上 ... pattern[3]=右下),
//          码值 0=R, 1=G, 2=B (由 rawpy raw_pattern/color_desc 推导, io.py 侧)。
//
// 返回 PixoRenderOk;
//      PixoRenderFallbackRequested (=1, abi.h 既有) = 非 RGBG Bayer 布局或
//      min(w,h) < 19 (RCD 最小可运行尺寸) → 调用方回落 AHD;
//      PixoRenderInvalidArgs = 空指针或非正尺寸。
PIXO_RENDER_NATIVE_API int PixoRenderDemosaicRCD(const float* mosaic,
                                                 float* out, int width,
                                                 int height,
                                                 const int* pattern);
