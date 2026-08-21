// P1 预览 stage 内核：Exposure / MatrixApply3 / ToneApplyLut1D / Clarity。
// 与 pixo.render/modules/*.py 的 float32 路径对齐；OpenMP 并行逐像素循环。
#include "stage_kernels.h"

#include "abi.h"

#include <algorithm>
#include <cmath>
#include <cstddef>

namespace pixo_render_native {

int ApplyExposure(const float* rgb, float* out, int width, int height,
                  const ExposureParams& params)
{
    if (rgb == nullptr || out == nullptr || width <= 0 || height <= 0) {
        return -1;
    }
    const int pixelCount = width * height;
    const float gain = std::pow(2.0f, params.ev);
    const float knee = params.rolloffKnee;
    const float vignette = std::max(params.vignette, 0.0f);
    const bool hasVignette = vignette > 0.0f;

#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (int i = 0; i < pixelCount; ++i) {
        const int y = i / width;
        const int x = i % width;
        float r = rgb[i * 3 + 0];
        float g = rgb[i * 3 + 1];
        float b = rgb[i * 3 + 2];

        if (hasVignette) {
            const float cx = static_cast<float>(width) / 2.0f;
            const float cy = static_cast<float>(height) / 2.0f;
            const float nx = (static_cast<float>(x) - cx) / std::max(cx, 1.0f);
            const float ny = (static_cast<float>(y) - cy) / std::max(cy, 1.0f);
            float r2 = nx * nx + ny * ny;
            r2 = std::clamp(r2 / 2.0f, 0.0f, 1.0f);
            const float vg = 1.0f + vignette * r2;
            r *= vg;
            g *= vg;
            b *= vg;
        }

        if (params.ev != 0.0f) {
            r *= gain;
            g *= gain;
            b *= gain;
        }

        if (knee >= 1.0f || knee < 0.0f) {
            // 无滚降：只钳下界，与 Python soft_highlight_rolloff 返回原图一致。
            out[i * 3 + 0] = std::max(r, 0.0f);
            out[i * 3 + 1] = std::max(g, 0.0f);
            out[i * 3 + 2] = std::max(b, 0.0f);
        } else {
            const float scale = 1.0f - knee;
            auto roll = [knee, scale](float v) {
                if (v <= knee) {
                    return v;
                }
                const float t = (v - knee) / scale;
                return knee + scale * std::tanh(t);
            };
            r = roll(r);
            g = roll(g);
            b = roll(b);
            out[i * 3 + 0] = std::min(std::max(r, 0.0f), 1.0f);
            out[i * 3 + 1] = std::min(std::max(g, 0.0f), 1.0f);
            out[i * 3 + 2] = std::min(std::max(b, 0.0f), 1.0f);
        }
    }
    return 0;
}

int ApplyMatrix3(const float* rgb, float* out, int width, int height,
                 const MatrixApply3Params& params)
{
    if (rgb == nullptr || out == nullptr || params.matrix == nullptr ||
        width <= 0 || height <= 0) {
        return -1;
    }
    const int pixelCount = width * height;
    const float* m = params.matrix;
#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (int i = 0; i < pixelCount; ++i) {
        const float r = rgb[i * 3 + 0];
        const float g = rgb[i * 3 + 1];
        const float b = rgb[i * 3 + 2];
        out[i * 3 + 0] = r * m[0] + g * m[1] + b * m[2];
        out[i * 3 + 1] = r * m[3] + g * m[4] + b * m[5];
        out[i * 3 + 2] = r * m[6] + g * m[7] + b * m[8];
    }
    return 0;
}

int ApplyToneLut1D(const float* rgb, float* out, int width, int height,
                   const ToneApplyLut1DParams& params)
{
    if (rgb == nullptr || out == nullptr || params.lut == nullptr ||
        params.lutSize < 2 || width <= 0 || height <= 0) {
        return -1;
    }
    const int pixelCount = width * height;
    const int n = params.lutSize - 1;
    const float* lut = params.lut;
#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (int i = 0; i < pixelCount * 3; ++i) {
        const float x = std::clamp(rgb[i], 0.0f, 1.0f);
        int idx = static_cast<int>(x * static_cast<float>(n) + 0.5f);
        if (idx > n) {
            idx = n;
        }
        out[i] = lut[idx];
    }
    return 0;
}

int ApplyClarity(const float* rgb, float* out, int width, int height,
                 const ClarityParams& params)
{
    if (rgb == nullptr || out == nullptr || params.gray == nullptr ||
        params.smallBlur == nullptr || params.largeBlur == nullptr ||
        width <= 0 || height <= 0) {
        return -1;
    }
    const int pixelCount = width * height;
    const float s = params.strength;
    const float gainLo = 1.0f - 2.0f * s;
    const float gainHi = 1.0f + 2.0f * s;
#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (int i = 0; i < pixelCount; ++i) {
        const float gray = params.gray[i];
        const float mid = params.smallBlur[i] - params.largeBlur[i];
        const float denom = std::max(gray, 1e-4f);
        float gain = (gray + s * 3.0f * mid) / denom;
        gain = std::clamp(gain, gainLo, gainHi);
        out[i * 3 + 0] = std::clamp(rgb[i * 3 + 0] * gain, 0.0f, 1.0f);
        out[i * 3 + 1] = std::clamp(rgb[i * 3 + 1] * gain, 0.0f, 1.0f);
        out[i * 3 + 2] = std::clamp(rgb[i * 3 + 2] * gain, 0.0f, 1.0f);
    }
    return 0;
}

} // namespace pixo_render_native

// ---- C ABI 导出 ----

PIXO_RENDER_NATIVE_API int PixoRenderExposureApply(
    const float* rgb, float* out, int width, int height,
    const struct PixoRenderExposureParams* params)
{
    if (params == nullptr) {
        return -1;
    }
    pixo_render_native::ExposureParams p;
    p.ev = params->ev;
    p.rolloffKnee = params->rolloffKnee;
    p.vignette = params->vignette;
    return pixo_render_native::ApplyExposure(rgb, out, width, height, p);
}

PIXO_RENDER_NATIVE_API int PixoRenderMatrixApply3(
    const float* rgb, float* out, int width, int height,
    const struct PixoRenderMatrixApply3Params* params)
{
    if (params == nullptr) {
        return -1;
    }
    pixo_render_native::MatrixApply3Params p;
    p.matrix = params->matrix;
    return pixo_render_native::ApplyMatrix3(rgb, out, width, height, p);
}

PIXO_RENDER_NATIVE_API int PixoRenderToneApplyLut1D(
    const float* rgb, float* out, int width, int height,
    const struct PixoRenderToneApplyLut1DParams* params)
{
    if (params == nullptr) {
        return -1;
    }
    pixo_render_native::ToneApplyLut1DParams p;
    p.lut = params->lut;
    p.lutSize = params->lutSize;
    return pixo_render_native::ApplyToneLut1D(rgb, out, width, height, p);
}

PIXO_RENDER_NATIVE_API int PixoRenderClarityApply(
    const float* rgb, float* out, int width, int height,
    const struct PixoRenderClarityParams* params)
{
    if (params == nullptr) {
        return -1;
    }
    pixo_render_native::ClarityParams p;
    p.strength = params->strength;
    p.gray = params->gray;
    p.smallBlur = params->smallBlur;
    p.largeBlur = params->largeBlur;
    return pixo_render_native::ApplyClarity(rgb, out, width, height, p);
}
