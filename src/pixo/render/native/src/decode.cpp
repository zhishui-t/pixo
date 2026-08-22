// pixo.render CFA 2×2 分箱快速解码。
//
// 每个 2×2 quad 输出一个 RGB 像素：
//   R = cfa@R, B = cfa@B, G = (G0+G1)/2；
//   归一化 v = max((raw - black[pos]) / max(white - black[pos], 1), 0) * outputScale。
// black[4] 在 Python 侧已按 2x2 线性位置换算好，避免在 C++ 里依赖 raw_pattern。
#include "decode.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>

PIXO_RENDER_NATIVE_API int PixoRenderDecodeCfaHalf(
    const uint16_t* cfa, float* rgbOut, int width, int height,
    const struct PixoRenderCfaDecodeParams* params)
{
    if (cfa == nullptr || rgbOut == nullptr || params == nullptr) {
        return PixoRenderInvalidArgs;
    }
    if (width < 2 || height < 2) {
        return PixoRenderInvalidArgs;
    }

    const int positions[4] = {
        params->patternR,
        params->patternG0,
        params->patternG1,
        params->patternB,
    };
    bool seen[4] = {false, false, false, false};
    for (int i = 0; i < 4; ++i) {
        const int pos = positions[i];
        if (pos < 0 || pos > 3 || seen[pos]) {
            return PixoRenderInvalidArgs;
        }
        seen[pos] = true;
    }

    const int outW = width / 2;
    const int outH = height / 2;
    const float scale = params->outputScale;
    float invRange[4];
    for (int i = 0; i < 4; ++i) {
        invRange[i] = 1.0f / std::max(params->whiteLevel - params->black[i], 1.0f);
    }

    for (int oy = 0; oy < outH; ++oy) {
        const int y0 = oy * 2;
        float* dst = rgbOut + static_cast<std::size_t>(oy) * outW * 3;
        for (int ox = 0; ox < outW; ++ox) {
            const int x0 = ox * 2;
            float r = 0.0f;
            float g = 0.0f;
            float b = 0.0f;
            int gCount = 0;

            for (int pos = 0; pos < 4; ++pos) {
                const int row = pos >> 1;
                const int col = pos & 1;
                const std::size_t idx =
                    static_cast<std::size_t>(y0 + row) * width + (x0 + col);
                const float v = static_cast<float>(cfa[idx]);
                const float norm =
                    std::max((v - params->black[pos]) * invRange[pos], 0.0f) * scale;
                if (pos == params->patternR) {
                    r = norm;
                } else if (pos == params->patternG0 || pos == params->patternG1) {
                    g += norm;
                    ++gCount;
                } else if (pos == params->patternB) {
                    b = norm;
                }
            }

            if (gCount > 0) {
                g /= static_cast<float>(gCount);
            }
            dst[ox * 3 + 0] = r;
            dst[ox * 3 + 1] = g;
            dst[ox * 3 + 2] = b;
        }
    }
    return PixoRenderOk;
}
