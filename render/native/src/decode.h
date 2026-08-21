#pragma once

// pixo.render CFA 2×2 分箱快速解码（P1 预览 decode 内核）。
// 输入 rawpy raw_image_visible (uint16 CFA)，输出 (H/2, W/2, 3) float32。

#include <cstdint>

#include "abi.h"

struct PixoRenderCfaDecodeParams {
    int patternR;          // R 在 2x2 中的线性位置 0..3
    int patternG0;         // 两个 G 位置
    int patternG1;
    int patternB;
    float black[4];        // 按 2x2 线性位置对应的 black level（Python 侧换算）
    float whiteLevel;      // raw.white_level
    float outputScale;     // 调试缩放，通常 1.0
};

// cfa: HxW uint16 C 连续；rgbOut: floor(H/2)*floor(W/2)*3 float32。
// 成功返回 PixoRenderOk；参数非法返回 PixoRenderInvalidArgs。
PIXO_RENDER_NATIVE_API int PixoRenderDecodeCfaHalf(
    const uint16_t* cfa, float* rgbOut, int width, int height,
    const struct PixoRenderCfaDecodeParams* params);
