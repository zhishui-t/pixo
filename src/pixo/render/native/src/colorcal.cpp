// M2: colorcal 全量 Lab 路径 C++ 内核。
// 与 pixo.render/modules/color_cal.py 的 Lab 分支逐像素对齐；
// 一次计算 skinMask，供 skin_trim 与饱和度肤色保护共用（修复 Python 重复计算）。
#include "colorcal.h"

#include "abi.h"

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace pixo_render_native {

namespace {

constexpr double Pi = 3.14159265358979323846;

// 肤色椭圆常量（与 pixo.render/core/skin.py 完全一致）。
constexpr float SkinLabA = 140.0f;
constexpr float SkinLabB = 150.0f;
constexpr float SkinMajor = 22.0f;
constexpr float SkinMinor = 14.0f;
constexpr double SkinAngle = 0.65;
constexpr float SkinSoftBand = 0.25f;

// np.interp 的 7 点亮度节点（_NEUTRAL_CENTERS）。
constexpr double NeutralCenters[7] = {8.0, 32.0, 72.0, 128.0, 184.0, 224.0, 248.0};

// ---- float Lab 域常量 (cv2 float Lab: L∈[0,100], a/b 中心 0) ----
// 与 uint8 Lab 域 (L∈[0,255], a/b 中心 128) 的换算:
//   L_f = L_u8 * 100/255;  a_f = a_u8 - 128;  b_f = b_u8 - 128
// a/b 轴两域只差常数偏移 128, 单位长度相同 —— 椭圆半径/倾角、色度 C 及其
// 阈值 (plateau=12, sigma, vibrance 参考色度 128)、全部 a/b 偏移量
// (neutralA/B、曲线值、skinTrim) 数值不变; 只有 L 轴差 2.55 倍 (曲线节点)
// 与中心偏移 (椭圆中心、旋转中心) 需要换算。
constexpr float SkinLabAF32 = SkinLabA - 128.0f;   // 140-128 = 12
constexpr float SkinLabBF32 = SkinLabB - 128.0f;   // 150-128 = 22

// InterpCurveF32 的 7 点亮度节点 = uint8 域 _NEUTRAL_CENTERS * 100/255。
constexpr double NeutralCentersF32[7] = {
    8.0 * (100.0 / 255.0), 32.0 * (100.0 / 255.0), 72.0 * (100.0 / 255.0),
    128.0 * (100.0 / 255.0), 184.0 * (100.0 / 255.0), 224.0 * (100.0 / 255.0),
    248.0 * (100.0 / 255.0)};

float InterpCurve(float x, const float* curve)
{
    const double xd = static_cast<double>(x);
    if (xd <= NeutralCenters[0]) {
        return curve[0];
    }
    if (xd >= NeutralCenters[6]) {
        return curve[6];
    }
    int i = 0;
    while (i < 6 && xd >= NeutralCenters[i + 1]) {
        ++i;
    }
    const double t = (xd - NeutralCenters[i]) / (NeutralCenters[i + 1] - NeutralCenters[i]);
    const double value = static_cast<double>(curve[i]) * (1.0 - t)
                       + static_cast<double>(curve[i + 1]) * t;
    return static_cast<float>(value);
}

// Lab 椭圆肤色软掩码（float32 输出，与 skin.py::skin_mask 一致）。
float SkinMask(float a, float b)
{
    static const double cosA = std::cos(SkinAngle);
    static const double sinA = std::sin(SkinAngle);
    const float da = a - SkinLabA;
    const float db = b - SkinLabB;
    const double u = static_cast<double>(da) * cosA + static_cast<double>(db) * sinA;
    const double v = -static_cast<double>(da) * sinA + static_cast<double>(db) * cosA;
    const double d2 = (u / static_cast<double>(SkinMajor)) * (u / static_cast<double>(SkinMajor))
                    + (v / static_cast<double>(SkinMinor)) * (v / static_cast<double>(SkinMinor));
    const float d = static_cast<float>(std::sqrt(d2 > 0.0 ? d2 : 0.0));
    const float t = std::clamp((d - 1.0f) / SkinSoftBand, 0.0f, 1.0f);
    return 1.0f - t * t * (3.0f - 2.0f * t);
}

// float Lab 域 (a/b 中心 0) 的曲线插值: 与 InterpCurve 同式, 节点换到
// float L∈[0,100] 域 (NeutralCentersF32)。曲线值为 a/b 偏移, 域不变。
float InterpCurveF32(float x, const float* curve)
{
    const double xd = static_cast<double>(x);
    if (xd <= NeutralCentersF32[0]) {
        return curve[0];
    }
    if (xd >= NeutralCentersF32[6]) {
        return curve[6];
    }
    int i = 0;
    while (i < 6 && xd >= NeutralCentersF32[i + 1]) {
        ++i;
    }
    const double t = (xd - NeutralCentersF32[i])
                   / (NeutralCentersF32[i + 1] - NeutralCentersF32[i]);
    const double value = static_cast<double>(curve[i]) * (1.0 - t)
                       + static_cast<double>(curve[i + 1]) * t;
    return static_cast<float>(value);
}

// float Lab 域 (a/b 中心 0) 的肤色椭圆软掩码: 与 SkinMask 同式,
// 中心 (140,150)_u8 -> (12,22)_f; 半径/倾角/软边不变 (a/b 轴单位相同)。
float SkinMaskF32(float a, float b)
{
    static const double cosA = std::cos(SkinAngle);
    static const double sinA = std::sin(SkinAngle);
    const float da = a - SkinLabAF32;
    const float db = b - SkinLabBF32;
    const double u = static_cast<double>(da) * cosA + static_cast<double>(db) * sinA;
    const double v = -static_cast<double>(da) * sinA + static_cast<double>(db) * cosA;
    const double d2 = (u / static_cast<double>(SkinMajor)) * (u / static_cast<double>(SkinMajor))
                    + (v / static_cast<double>(SkinMinor)) * (v / static_cast<double>(SkinMinor));
    const float d = static_cast<float>(std::sqrt(d2 > 0.0 ? d2 : 0.0));
    const float t = std::clamp((d - 1.0f) / SkinSoftBand, 0.0f, 1.0f);
    return 1.0f - t * t * (3.0f - 2.0f * t);
}

} // namespace

int ApplyColorCalLab(const float* lab, std::uint8_t* labOut, int width, int height,
                     const ColorCalParams& params)
{
    if (lab == nullptr || labOut == nullptr || width <= 0 || height <= 0) {
        return -1;
    }
    const bool hasCurves = params.curveA != nullptr || params.curveB != nullptr;
    const bool neutralActive = params.neutralA != 0.0f || params.neutralB != 0.0f || hasCurves;
    const bool skinTrimActive = params.skinTrimA != 0.0f || params.skinTrimB != 0.0f;
    const bool needSkin = skinTrimActive || params.skinProtect > 0.0f;
    const bool hueActive = params.hueDeg != 0.0f;
    const double rad = hueActive ? static_cast<double>(params.hueDeg) * (Pi / 180.0) : 0.0;
    const double cosRad = std::cos(rad);
    const double sinRad = std::sin(rad);
    const float gainBase = 1.0f + params.saturation;
    const int pixelCount = width * height;

#ifdef _OPENMP
#pragma omp parallel for
#endif
    for (int i = 0; i < pixelCount; ++i) {
        const float L = lab[i * 3 + 0];
        const float aOrig = lab[i * 3 + 1];
        const float bOrig = lab[i * 3 + 2];
        const float a128 = aOrig - 128.0f;
        const float b128 = bOrig - 128.0f;
        const float C = std::sqrt(a128 * a128 + b128 * b128);
        float skinMaskValue = 0.0f;
        if (needSkin) {
            skinMaskValue = SkinMask(aOrig, bOrig);
        }

        float a = aOrig;
        float b = bOrig;

        if (neutralActive) {
            const float sigma = params.neutralSigma;
            // 平台+高斯尾权重 (S5 对齐): C <= plateau(12) 全量校正, 之后按
            // sigma 高斯衰减 —— 与 modules/color_cal.py 全量 Lab 路径及
            // _apply_neutral_fast 快速路径同一口径, 消除 native/Python 分歧。
            const float plateau = 12.0f;
            const float tail = std::max(C - plateau, 0.0f);
            const float w = std::exp(-(tail * tail) / (2.0f * sigma * sigma));
            if (hasCurves) {
                const float aOff = params.curveA != nullptr ? InterpCurve(L, params.curveA) : 0.0f;
                const float bOff = params.curveB != nullptr ? InterpCurve(L, params.curveB) : 0.0f;
                a = a + (params.neutralA + aOff) * w;
                b = b + (params.neutralB + bOff) * w;
            } else {
                a = a + params.neutralA * w;
                b = b + params.neutralB * w;
            }
        }

        if (skinTrimActive) {
            a = a + params.skinTrimA * skinMaskValue;
            b = b + params.skinTrimB * skinMaskValue;
        }

        if (hueActive) {
            const double ca = static_cast<double>(a) - 128.0;
            const double cb = static_cast<double>(b) - 128.0;
            double ad = 128.0 + ca * cosRad - cb * sinRad;
            double bd = 128.0 + ca * sinRad + cb * cosRad;
            if (params.vibrance != 0.0f || params.skinProtect > 0.0f) {
                float gain = gainBase;
                if (params.vibrance != 0.0f) {
                    gain = gain + params.vibrance * std::clamp(1.0f - C / 128.0f, 0.0f, 1.0f);
                }
                if (params.skinProtect > 0.0f) {
                    gain = 1.0f + (gain - 1.0f) * (1.0f - params.skinProtect * skinMaskValue);
                }
                ad = 128.0 + (ad - 128.0) * static_cast<double>(gain);
                bd = 128.0 + (bd - 128.0) * static_cast<double>(gain);
            } else {
                const double gain = static_cast<double>(gainBase);
                ad = 128.0 + (ad - 128.0) * gain;
                bd = 128.0 + (bd - 128.0) * gain;
            }
            const double Ld = static_cast<double>(L);
            labOut[i * 3 + 0] = static_cast<std::uint8_t>(std::clamp(Ld, 0.0, 255.0));
            labOut[i * 3 + 1] = static_cast<std::uint8_t>(std::clamp(ad, 0.0, 255.0));
            labOut[i * 3 + 2] = static_cast<std::uint8_t>(std::clamp(bd, 0.0, 255.0));
        } else {
            float gain = gainBase;
            if (params.vibrance != 0.0f) {
                gain = gain + params.vibrance * std::clamp(1.0f - C / 128.0f, 0.0f, 1.0f);
            }
            if (params.skinProtect > 0.0f) {
                gain = 1.0f + (gain - 1.0f) * (1.0f - params.skinProtect * skinMaskValue);
            }
            a = 128.0f + (a - 128.0f) * gain;
            b = 128.0f + (b - 128.0f) * gain;
            const float Lc = std::clamp(L, 0.0f, 255.0f);
            const float ac = std::clamp(a, 0.0f, 255.0f);
            const float bc = std::clamp(b, 0.0f, 255.0f);
            labOut[i * 3 + 0] = static_cast<std::uint8_t>(Lc);
            labOut[i * 3 + 1] = static_cast<std::uint8_t>(ac);
            labOut[i * 3 + 2] = static_cast<std::uint8_t>(bc);
        }
    }
    return 0;
}

// float Lab 域全量内核 (L∈[0,100], a/b 中心 0)。与上面 ApplyColorCalLab
// 逐式对应, 差异仅: 域常量换算 (见文件头注释)、色相旋转/增益绕中心 0、
// 输出 float 限幅 [0,100]/[-128,127] (等价 uint8 域 [0,255] 限幅, 无截断)。
int ApplyColorCalLabF32(const float* lab, float* labOut, int width, int height,
                        const ColorCalParams& params)
{
    if (lab == nullptr || labOut == nullptr || width <= 0 || height <= 0) {
        return -1;
    }
    const bool hasCurves = params.curveA != nullptr || params.curveB != nullptr;
    const bool neutralActive = params.neutralA != 0.0f || params.neutralB != 0.0f || hasCurves;
    const bool skinTrimActive = params.skinTrimA != 0.0f || params.skinTrimB != 0.0f;
    const bool needSkin = skinTrimActive || params.skinProtect > 0.0f;
    const bool hueActive = params.hueDeg != 0.0f;
    const double rad = hueActive ? static_cast<double>(params.hueDeg) * (Pi / 180.0) : 0.0;
    const double cosRad = std::cos(rad);
    const double sinRad = std::sin(rad);
    const float gainBase = 1.0f + params.saturation;
    const int pixelCount = width * height;

#ifdef _OPENMP
#pragma omp parallel for
#endif
    for (int i = 0; i < pixelCount; ++i) {
        const float L = lab[i * 3 + 0];
        const float aOrig = lab[i * 3 + 1];
        const float bOrig = lab[i * 3 + 2];
        // C 与 uint8 域同单位同值 (u8 域为 |a-128,b-128|)
        const float C = std::sqrt(aOrig * aOrig + bOrig * bOrig);
        float skinMaskValue = 0.0f;
        if (needSkin) {
            skinMaskValue = SkinMaskF32(aOrig, bOrig);
        }

        float a = aOrig;
        float b = bOrig;

        if (neutralActive) {
            const float sigma = params.neutralSigma;
            // 平台+高斯尾权重: 与 uint8 域内核同口径 (plateau=12 不变, C 同单位)
            const float plateau = 12.0f;
            const float tail = std::max(C - plateau, 0.0f);
            const float w = std::exp(-(tail * tail) / (2.0f * sigma * sigma));
            if (hasCurves) {
                const float aOff = params.curveA != nullptr ? InterpCurveF32(L, params.curveA) : 0.0f;
                const float bOff = params.curveB != nullptr ? InterpCurveF32(L, params.curveB) : 0.0f;
                a = a + (params.neutralA + aOff) * w;
                b = b + (params.neutralB + bOff) * w;
            } else {
                a = a + params.neutralA * w;
                b = b + params.neutralB * w;
            }
        }

        if (skinTrimActive) {
            a = a + params.skinTrimA * skinMaskValue;
            b = b + params.skinTrimB * skinMaskValue;
        }

        if (hueActive) {
            // 旋转绕中心 0 (u8 域绕 128), double 精度同 u8 内核
            const double ca = static_cast<double>(a);
            const double cb = static_cast<double>(b);
            double ad = ca * cosRad - cb * sinRad;
            double bd = ca * sinRad + cb * cosRad;
            if (params.vibrance != 0.0f || params.skinProtect > 0.0f) {
                float gain = gainBase;
                if (params.vibrance != 0.0f) {
                    gain = gain + params.vibrance * std::clamp(1.0f - C / 128.0f, 0.0f, 1.0f);
                }
                if (params.skinProtect > 0.0f) {
                    gain = 1.0f + (gain - 1.0f) * (1.0f - params.skinProtect * skinMaskValue);
                }
                ad = ad * static_cast<double>(gain);
                bd = bd * static_cast<double>(gain);
            } else {
                const double gain = static_cast<double>(gainBase);
                ad = ad * gain;
                bd = bd * gain;
            }
            labOut[i * 3 + 0] = std::clamp(L, 0.0f, 100.0f);
            labOut[i * 3 + 1] = std::clamp(static_cast<float>(ad), -128.0f, 127.0f);
            labOut[i * 3 + 2] = std::clamp(static_cast<float>(bd), -128.0f, 127.0f);
        } else {
            float gain = gainBase;
            if (params.vibrance != 0.0f) {
                gain = gain + params.vibrance * std::clamp(1.0f - C / 128.0f, 0.0f, 1.0f);
            }
            if (params.skinProtect > 0.0f) {
                gain = 1.0f + (gain - 1.0f) * (1.0f - params.skinProtect * skinMaskValue);
            }
            a = a * gain;
            b = b * gain;
            labOut[i * 3 + 0] = std::clamp(L, 0.0f, 100.0f);
            labOut[i * 3 + 1] = std::clamp(a, -128.0f, 127.0f);
            labOut[i * 3 + 2] = std::clamp(b, -128.0f, 127.0f);
        }
    }
    return 0;
}

int ApplyGamutSoft(const float* rgb, float* out, int width, int height, float strength)
{
    if (rgb == nullptr || out == nullptr || width <= 0 || height <= 0) {
        return -1;
    }
    const int pixelCount = width * height;
    for (int i = 0; i < pixelCount; ++i) {
        const float r = rgb[i * 3 + 0];
        const float g = rgb[i * 3 + 1];
        const float b = rgb[i * 3 + 2];
        if (strength > 0.0f) {
            const float over = std::max(r - 1.0f, 0.0f) + std::max(g - 1.0f, 0.0f)
                             + std::max(b - 1.0f, 0.0f);
            const float scale = 1.0f / (1.0f + strength * over);
            out[i * 3 + 0] = std::clamp(r * scale, 0.0f, 1.0f);
            out[i * 3 + 1] = std::clamp(g * scale, 0.0f, 1.0f);
            out[i * 3 + 2] = std::clamp(b * scale, 0.0f, 1.0f);
        } else {
            out[i * 3 + 0] = std::clamp(r, 0.0f, 1.0f);
            out[i * 3 + 1] = std::clamp(g, 0.0f, 1.0f);
            out[i * 3 + 2] = std::clamp(b, 0.0f, 1.0f);
        }
    }
    return 0;
}

// ---- C ABI 导出 ----

PIXO_RENDER_NATIVE_API int PixoRenderColorCalApplyLab(
    const float* lab, std::uint8_t* labOut, int width, int height,
    const struct PixoRenderColorCalParams* params)
{
    try {
        if (params == nullptr) {
            return PixoRenderInvalidArgs;
        }
        ColorCalParams p;
        p.saturation = params->saturation;
        p.vibrance = params->vibrance;
        p.hueDeg = params->hueDeg;
        p.neutralA = params->neutralA;
        p.neutralB = params->neutralB;
        p.neutralSigma = params->neutralSigma;
        p.skinProtect = params->skinProtect;
        p.skinTrimA = params->skinTrimA;
        p.skinTrimB = params->skinTrimB;
        p.curveA = params->curveA;
        p.curveB = params->curveB;
        const int status = ApplyColorCalLab(lab, labOut, width, height, p);
        return status < 0 ? PixoRenderInvalidArgs : PixoRenderOk;
    } catch (...) {
        return PixoRenderInternalError;
    }
}

PIXO_RENDER_NATIVE_API int PixoRenderColorCalApplyLabF32(
    const float* lab, float* labOut, int width, int height,
    const struct PixoRenderColorCalParams* params)
{
    try {
        if (params == nullptr) {
            return PixoRenderInvalidArgs;
        }
        ColorCalParams p;
        p.saturation = params->saturation;
        p.vibrance = params->vibrance;
        p.hueDeg = params->hueDeg;
        p.neutralA = params->neutralA;
        p.neutralB = params->neutralB;
        p.neutralSigma = params->neutralSigma;
        p.skinProtect = params->skinProtect;
        p.skinTrimA = params->skinTrimA;
        p.skinTrimB = params->skinTrimB;
        p.curveA = params->curveA;
        p.curveB = params->curveB;
        const int status = ApplyColorCalLabF32(lab, labOut, width, height, p);
        return status < 0 ? PixoRenderInvalidArgs : PixoRenderOk;
    } catch (...) {
        return PixoRenderInternalError;
    }
}

PIXO_RENDER_NATIVE_API int PixoRenderGamutSoft(
    const float* rgb, float* out, int width, int height, float strength)
{
    try {
        const int status = ApplyGamutSoft(rgb, out, width, height, strength);
        return status < 0 ? PixoRenderInvalidArgs : PixoRenderOk;
    } catch (...) {
        return PixoRenderInternalError;
    }
}

} // namespace pixo_render_native
