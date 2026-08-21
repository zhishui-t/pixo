// M3: refine 热点内核 (C++20)。
// 与 pixo.render/modules/refine.py 的 float32 路径对齐:
//   - 饱和度保护 (HSV S 平面)
//   - 灰空间 unsharp 锐化
//   - 1/4 降采样色度替换 (cv2 中间图由 Python 提供)
//   - 高光去色
//   - gamma 域暖色饱和/色相补强 (uint8 HSV in-place)
#include "refine.h"
#include "abi.h"
#include "refine_sat_lut.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <vector>

namespace pixo_render_native {

namespace {

constexpr float RgbWeightR = 0.2126f;
constexpr float RgbWeightG = 0.7152f;
constexpr float RgbWeightB = 0.0722f;

constexpr float SatLo = 0.08f;
constexpr float SatHi = 0.32f;

constexpr float HueLo = 5.0f;
constexpr float HueHi = 38.0f;
constexpr float SatLutLo = 80.0f;
constexpr float SatLutSpan = 30.0f;
constexpr float ValLutLo = 100.0f;
constexpr float ValLutSpan = 40.0f;

float Clamp01(float x)
{
    return std::clamp(x, 0.0f, 1.0f);
}

float SmoothStep(float x)
{
    x = Clamp01(x);
    return x * x * (3.0f - 2.0f * x);
}

const std::array<float, 256>& HueLut()
{
    static const std::array<float, 256> lut = [] {
        std::array<float, 256> a{};
        for (int i = 0; i < 180; ++i) {
            const float left = std::clamp((static_cast<float>(i) - HueLo) / 6.0f, 0.0f, 1.0f);
            const float right = std::clamp((HueHi - static_cast<float>(i)) / 6.0f, 0.0f, 1.0f);
            a[static_cast<std::size_t>(i)] = SmoothStep(left * right);
        }
        return a;
    }();
    return lut;
}

const std::array<float, 256>& SatLut()
{
    static const std::array<float, 256> lut = [] {
        std::array<float, 256> a{};
        for (int i = 0; i < 256; ++i) {
            const float x = (static_cast<float>(i) - SatLutLo) / SatLutSpan;
            a[static_cast<std::size_t>(i)] = SmoothStep(x);
        }
        return a;
    }();
    return lut;
}

const std::array<float, 256>& ValLut()
{
    static const std::array<float, 256> lut = [] {
        std::array<float, 256> a{};
        for (int i = 0; i < 256; ++i) {
            const float x = (static_cast<float>(i) - ValLutLo) / ValLutSpan;
            a[static_cast<std::size_t>(i)] = SmoothStep(x);
        }
        return a;
    }();
    return lut;
}

void RefineSharpenCore(const float* rgb, float* out, int width, int height,
                       const RefineSharpenParams& params)
{
    const int pixelCount = width * height;
    const float strength = params.sharpen * 12.0f;

    bool overAny = false;
#ifdef _OPENMP
    #pragma omp parallel for reduction(||:overAny) schedule(static)
#endif
    for (int i = 0; i < pixelCount; ++i) {
        const float gray = params.gray[i];
        const float blur = params.grayBlur[i];
        const float sat = params.satProtect[i];
        const float detail = gray - blur;
        const float l = Clamp01(gray + strength * detail * (1.0f - sat));

        const float c0 = rgb[i * 3 + 0] - gray;
        const float c1 = rgb[i * 3 + 1] - gray;
        const float c2 = rgb[i * 3 + 2] - gray;
        overAny = overAny || (l + c0 > 1.0f) || (l + c1 > 1.0f) || (l + c2 > 1.0f);
    }

    bool underAny = false;
    if (overAny) {
#ifdef _OPENMP
        #pragma omp parallel for reduction(||:underAny) schedule(static)
#endif
        for (int i = 0; i < pixelCount; ++i) {
            const float gray = params.gray[i];
            const float sat = params.satProtect[i];
            const float blur = params.grayBlur[i];
            const float detail = gray - blur;
            const float l = Clamp01(gray + strength * detail * (1.0f - sat));
            const float c0 = rgb[i * 3 + 0] - gray;
            const float c1 = rgb[i * 3 + 1] - gray;
            const float c2 = rgb[i * 3 + 2] - gray;
            const float pos = std::max(c0, 0.0f) + std::max(c1, 0.0f) + std::max(c2, 0.0f);
            const float scale = (pos > 1e-6f)
                ? std::min(1.0f, (1.0f - l) / std::max(pos, 1e-6f))
                : 1.0f;
            const float o0 = l + c0 * scale;
            const float o1 = l + c1 * scale;
            const float o2 = l + c2 * scale;
            out[i * 3 + 0] = o0;
            out[i * 3 + 1] = o1;
            out[i * 3 + 2] = o2;
            underAny = underAny || (o0 < 0.0f) || (o1 < 0.0f) || (o2 < 0.0f);
        }
    } else {
#ifdef _OPENMP
        #pragma omp parallel for reduction(||:underAny) schedule(static)
#endif
        for (int i = 0; i < pixelCount; ++i) {
            const float gray = params.gray[i];
            const float sat = params.satProtect[i];
            const float blur = params.grayBlur[i];
            const float detail = gray - blur;
            const float l = Clamp01(gray + strength * detail * (1.0f - sat));
            const float o0 = l + rgb[i * 3 + 0] - gray;
            const float o1 = l + rgb[i * 3 + 1] - gray;
            const float o2 = l + rgb[i * 3 + 2] - gray;
            out[i * 3 + 0] = o0;
            out[i * 3 + 1] = o1;
            out[i * 3 + 2] = o2;
            underAny = underAny || (o0 < 0.0f) || (o1 < 0.0f) || (o2 < 0.0f);
        }
    }

    if (underAny) {
#ifdef _OPENMP
        #pragma omp parallel for schedule(static)
#endif
        for (int i = 0; i < pixelCount; ++i) {
            const float gray = params.gray[i];
            const float sat = params.satProtect[i];
            const float blur = params.grayBlur[i];
            const float detail = gray - blur;
            const float l = Clamp01(gray + strength * detail * (1.0f - sat));
            const float c0 = rgb[i * 3 + 0] - gray;
            const float c1 = rgb[i * 3 + 1] - gray;
            const float c2 = rgb[i * 3 + 2] - gray;
            const float neg = std::max(-c0, 0.0f) + std::max(-c1, 0.0f) + std::max(-c2, 0.0f);
            const float scale = (neg > 1e-6f)
                ? std::min(1.0f, l / std::max(neg, 1e-6f))
                : 1.0f;
            out[i * 3 + 0] = Clamp01(l + c0 * scale);
            out[i * 3 + 1] = Clamp01(l + c1 * scale);
            out[i * 3 + 2] = Clamp01(l + c2 * scale);
        }
    }
}

} // namespace

void RefineSatProtection(const float* rgb, float* satProtect, int width, int height,
                         const RefineSatProtectionParams& params)
{
    const int pixelCount = width * height;
    const float lo = params.lo;
    const float hi = std::max(params.hi, params.lo + 1e-9f);
    const float span = hi - lo;
#ifdef _OPENMP
    #pragma omp parallel for schedule(static)
#endif
    for (int i = 0; i < pixelCount; ++i) {
        const int r = static_cast<int>(Clamp01(rgb[i * 3 + 0]) * 255.0f + 0.5f);
        const int g = static_cast<int>(Clamp01(rgb[i * 3 + 1]) * 255.0f + 0.5f);
        const int b = static_cast<int>(Clamp01(rgb[i * 3 + 2]) * 255.0f + 0.5f);
        const int maxValue = std::max(r, std::max(g, b));
        const int minValue = std::min(r, std::min(g, b));
        const int satInt = pixo_render_native::RefineSatLut[maxValue * 256 + minValue];
        const float sat = static_cast<float>(satInt) / 255.0f;
        const float x = std::clamp((sat - lo) / span, 0.0f, 1.0f);
        satProtect[i] = x * x * (3.0f - 2.0f * x);
    }
}

void RefineSharpen(const float* rgb, float* out, int width, int height,
                   const RefineSharpenParams& params)
{
    RefineSharpenCore(rgb, out, width, height, params);
}

void RefineChroma(const float* rgb, float* out, int width, int height,
                  const RefineChromaParams& params)
{
    const int pixelCount = width * height;
#ifdef _OPENMP
    #pragma omp parallel for schedule(static)
#endif
    for (int i = 0; i < pixelCount; ++i) {
        const float gray = params.gray[i];
        const float sat = params.satProtect[i];
        for (int c = 0; c < 3; ++c) {
            const float chromaOrig = rgb[i * 3 + c] - gray;
            const float chromaBlur = params.blurUp[i * 3 + c] - params.grayBlurUp[i];
            const float value = gray + (chromaBlur + sat * (chromaOrig - chromaBlur));
            out[i * 3 + c] = Clamp01(value);
        }
    }
}

void RefineHighlight(const float* rgb, float* out, int width, int height,
                     const RefineHighlightParams& params)
{
    const int pixelCount = width * height;
#ifdef _OPENMP
    #pragma omp parallel for schedule(static)
#endif
    for (int i = 0; i < pixelCount; ++i) {
        const float gray = params.gray[i];
        const float sat = params.satProtect[i];
        const float x = std::clamp((gray - 0.55f) / 0.30f, 0.0f, 1.0f);
        const float wLum = x * x * (3.0f - 2.0f * x);
        const float w = wLum * (1.0f - sat) * params.highlightDesat;
        out[i * 3 + 0] = rgb[i * 3 + 0] * (1.0f - w) + gray * w;
        out[i * 3 + 1] = rgb[i * 3 + 1] * (1.0f - w) + gray * w;
        out[i * 3 + 2] = rgb[i * 3 + 2] * (1.0f - w) + gray * w;
    }
}

void RefineApply(const float* rgb, float* out, int width, int height,
                 const RefineApplyParams& params)
{
    if (params.sharpen > 0.0f) {
        RefineSharpenParams sharpenParams;
        sharpenParams.sharpen = params.sharpen;
        sharpenParams.gray = params.gray;
        sharpenParams.satProtect = params.satProtect;
        sharpenParams.grayBlur = params.grayBlur;
        RefineSharpenCore(rgb, out, width, height, sharpenParams);
    } else if (params.chromaDenoise <= 0.0f && params.highlightDesat <= 0.0f) {
        std::copy(rgb, rgb + static_cast<std::size_t>(width) * height * 3, out);
    }

    if (params.chromaDenoise > 0.0f) {
        RefineChromaParams chromaParams;
        chromaParams.chromaDenoise = params.chromaDenoise;
        chromaParams.gray = params.gray;
        chromaParams.satProtect = params.satProtect;
        chromaParams.blurUp = params.blurUp;
        chromaParams.grayBlurUp = params.grayBlurUp;
        const float* src = (params.sharpen > 0.0f) ? out : rgb;
        RefineChroma(src, out, width, height, chromaParams);
    }

    if (params.highlightDesat > 0.0f) {
        RefineHighlightParams highlightParams;
        highlightParams.highlightDesat = params.highlightDesat;
        highlightParams.gray = params.gray;
        highlightParams.satProtect = params.satProtect;
        const float* src = (params.sharpen > 0.0f || params.chromaDenoise > 0.0f)
            ? out : rgb;
        RefineHighlight(src, out, width, height, highlightParams);
    }

    const int total = width * height * 3;
    for (int i = 0; i < total; ++i) {
        out[i] = Clamp01(out[i]);
    }
}

void WarmSatGammaU8(std::uint8_t* hsv, int width, int height,
                    float gain, float hueShiftDeg)
{
    const int pixelCount = width * height;
    const std::array<float, 256>& hLut = HueLut();
    const std::array<float, 256>& sLut = SatLut();
    const std::array<float, 256>& vLut = ValLut();
#ifdef _OPENMP
    #pragma omp parallel for schedule(static)
#endif
    for (int i = 0; i < pixelCount; ++i) {
        const int idx = i * 3;
        const int h0 = hsv[idx + 0];
        const int s0 = hsv[idx + 1];
        const int v0 = hsv[idx + 2];
        const float hw = hLut[static_cast<std::size_t>(h0)];

        if (gain > 0.0f) {
            const float s2 = std::clamp(static_cast<float>(s0) * (1.0f + gain * hw),
                                        0.0f, 255.0f);
            hsv[idx + 1] = static_cast<std::uint8_t>(s2);
        }
        if (hueShiftDeg != 0.0f) {
            const float sw = sLut[static_cast<std::size_t>(s0)];
            const float vw = vLut[static_cast<std::size_t>(v0)];
            const float hueW = hw * sw * vw;
            float h2 = std::fmod(static_cast<float>(h0) + hueShiftDeg * hueW, 180.0f);
            if (h2 < 0.0f) {
                h2 += 180.0f;
            }
            hsv[idx + 0] = static_cast<std::uint8_t>(h2);
        }
    }
}

} // namespace pixo_render_native

// ---- C ABI 导出 ----

namespace {

bool RefineCheckArgs(const void* a, const void* b, int width, int height)
{
    return a != nullptr && b != nullptr && width > 0 && height > 0;
}

} // namespace

PIXO_RENDER_NATIVE_API int PixoRenderRefineSatProtection(
    const float* rgb, float* satProtect, int width, int height,
    const struct PixoRenderRefineSatProtectionParams* params)
{
    if (!RefineCheckArgs(rgb, satProtect, width, height) || params == nullptr) {
        return -1;
    }
    try {
        pixo_render_native::RefineSatProtectionParams p;
        p.lo = params->lo;
        p.hi = params->hi;
        pixo_render_native::RefineSatProtection(rgb, satProtect, width, height, p);
        return 0;
    } catch (...) {
        return -3;
    }
}

PIXO_RENDER_NATIVE_API int PixoRenderRefineSharpen(
    const float* rgb, float* out, int width, int height,
    const struct PixoRenderRefineSharpenParams* params)
{
    if (!RefineCheckArgs(rgb, out, width, height) || params == nullptr ||
        params->gray == nullptr || params->satProtect == nullptr ||
        params->grayBlur == nullptr) {
        return -1;
    }
    try {
        pixo_render_native::RefineSharpenParams p;
        p.sharpen = params->sharpen;
        p.gray = params->gray;
        p.satProtect = params->satProtect;
        p.grayBlur = params->grayBlur;
        pixo_render_native::RefineSharpen(rgb, out, width, height, p);
        return 0;
    } catch (...) {
        return -3;
    }
}

PIXO_RENDER_NATIVE_API int PixoRenderRefineChroma(
    const float* rgb, float* out, int width, int height,
    const struct PixoRenderRefineChromaParams* params)
{
    if (!RefineCheckArgs(rgb, out, width, height) || params == nullptr ||
        params->gray == nullptr || params->satProtect == nullptr ||
        params->blurUp == nullptr || params->grayBlurUp == nullptr) {
        return -1;
    }
    try {
        pixo_render_native::RefineChromaParams p;
        p.chromaDenoise = params->chromaDenoise;
        p.gray = params->gray;
        p.satProtect = params->satProtect;
        p.blurUp = params->blurUp;
        p.grayBlurUp = params->grayBlurUp;
        pixo_render_native::RefineChroma(rgb, out, width, height, p);
        return 0;
    } catch (...) {
        return -3;
    }
}

PIXO_RENDER_NATIVE_API int PixoRenderRefineHighlight(
    const float* rgb, float* out, int width, int height,
    const struct PixoRenderRefineHighlightParams* params)
{
    if (!RefineCheckArgs(rgb, out, width, height) || params == nullptr ||
        params->gray == nullptr || params->satProtect == nullptr) {
        return -1;
    }
    try {
        pixo_render_native::RefineHighlightParams p;
        p.highlightDesat = params->highlightDesat;
        p.gray = params->gray;
        p.satProtect = params->satProtect;
        pixo_render_native::RefineHighlight(rgb, out, width, height, p);
        return 0;
    } catch (...) {
        return -3;
    }
}

PIXO_RENDER_NATIVE_API int PixoRenderRefineApply(
    const float* rgb, float* out, int width, int height,
    const struct PixoRenderRefineApplyParams* params)
{
    if (!RefineCheckArgs(rgb, out, width, height) || params == nullptr ||
        params->gray == nullptr || params->satProtect == nullptr) {
        return -1;
    }
    if (params->sharpen > 0.0f && params->grayBlur == nullptr) {
        return -1;
    }
    if (params->chromaDenoise > 0.0f &&
        (params->blurUp == nullptr || params->grayBlurUp == nullptr)) {
        return -1;
    }
    try {
        pixo_render_native::RefineApplyParams p;
        p.sharpen = params->sharpen;
        p.chromaDenoise = params->chromaDenoise;
        p.highlightDesat = params->highlightDesat;
        p.gray = params->gray;
        p.satProtect = params->satProtect;
        p.grayBlur = params->grayBlur;
        p.blurUp = params->blurUp;
        p.grayBlurUp = params->grayBlurUp;
        pixo_render_native::RefineApply(rgb, out, width, height, p);
        return 0;
    } catch (...) {
        return -3;
    }
}

PIXO_RENDER_NATIVE_API int PixoRenderWarmSatGammaU8(
    std::uint8_t* hsv, int width, int height,
    const struct PixoRenderWarmGammaParams* params)
{
    if (hsv == nullptr || width <= 0 || height <= 0 || params == nullptr) {
        return -1;
    }
    try {
        pixo_render_native::WarmSatGammaU8(hsv, width, height,
                                      params->gain, params->hueShiftDeg);
        return 0;
    } catch (...) {
        return -3;
    }
}
