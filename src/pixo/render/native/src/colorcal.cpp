// M2: colorcal 全量 Lab 路径 C++ 内核。
// 与 pixo.render/modules/color_cal.py 的 Lab 分支逐像素对齐；
// 一次计算 skinMask，供 skin_trim 与饱和度肤色保护共用（修复 Python 重复计算）。
// v1.5.0: 新增 ApplyColorCalLabF32Oklch (oklch 域, OKLab 椭圆掩码版, F11
// 15x 性能鸿沟的 native 回收), 见该函数头注释。
#include "colorcal.h"

#include "abi.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>

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

// ---- OKLab 椭圆掩码 (v1.5.0, oklch 域) ----
// Python 参考链: core/skin.py::skin_mask_oklab (f32 gamma sRGB -> f64 clip
// [0,1] -> core/oklab.srgb_to_oklab -> OKLab a-b 椭圆马氏距离 -> f32
// smoothstep)。掩码常数 hex 字面量与 Python 运行时逐位相同:
//   - 中心 np.float32(...) 舍入后展宽的 f64 (十进制 0.061263 的 f32 不是
//     精确值, 直接写 double 常数会差 1 ULP);
//   - 倾角 np.cos/np.sin(angle) 的 f64 结果 (消除 libm cos/sin 跨实现
//     1 ULP 风险);
//   - 半轴为 Python float 的 round-trip 十进制 (精确); 软带为 f32 (NEP50
//     语义: f32 数组除以该标量按 f32 除)。
// **双源警告 (tech_debt #18)**: 单源在 core/skin.py SKIN_OKLAB_*, 本处为
// 硬编码副本 —— 椭圆再变更时必须同步此处并跑 test_native_colorcal_oklch
// (常数失同步会被掩码 bitwise 测试抓红); 清偿=内核签名参数化。
// 常数为 **r10 低彩度端重拟合版** (2026-09-07, 覆盖分位 0.96→0.98 + 软带
// 0.25→0.31 重定标, 出处 core/skin.py r10 注释 / configs/color/skin_oklab.json)。
constexpr double SkinOklabA = 0x1.efae7ap-7;             // float32(0.015127) 展宽
constexpr double SkinOklabB = 0x1.f5ddd2p-5;             // float32(0.061263) 展宽
constexpr double SkinOklabCos = 0x1.f62a2ab9fefa4p-1;   // np.cos(0.196323)
constexpr double SkinOklabSin = 0x1.8f7dddf635799p-3;   // np.sin(0.196323)
constexpr double SkinOklabMajor = 0.049594;             // SKIN_OKLAB_MAJOR
constexpr double SkinOklabMinor = 0.047463;             // SKIN_OKLAB_MINOR
constexpr float SkinOklabSoftBand = 0.31f;              // SKIN_OKLAB_SOFT_BAND

// M1/M2 矩阵照抄 core/oklab.py (同 oklab.cpp, 勿改字面值/勿重排求和序)。
constexpr double M1LsrgbToLms[3][3] = {
    {0.4122214708, 0.5363325363, 0.0514459929},
    {0.2119034982, 0.6806995451, 0.1073969566},
    {0.0883024619, 0.2817188376, 0.6299787005},
};
constexpr double M2LmspToLab[3][3] = {
    {0.2104542553, 0.7936177850, -0.0040720468},
    {1.9779984951, -2.4285922050, 0.4505937099},
    {0.0259040371, 0.7827717662, -0.8086757660},
};

// 快速 cbrt: FreeBSD msun s_cbrt.c 逐句复刻 (Bruce D. Evans 优化版:
// 5-bit 位黑客种子 + 23-bit 多项式 + 23-bit 舍入 + 1 步 Halley, <0.667 ulp)。
// 为什么不用 std::cbrt (ucrtbase): ucrt 的 cbrt 非 msun 实现 (实测 ~31% 输入
// 与 msun 差 1 ULP f64), 但 60ns/次占掩码成本 ~33%; 本复刻 12ns/次, 与 ucrt
// (即 numpy np.cbrt, 已实测逐位同源) 差 <= 1 ULP f64 —— 经掩码链的 f64->f32
// 舍入 (d 舍入 f32) 后实际逐位一致 (262144 px 随机语料 0 差异, 差异期望
// ~1e-8/px; 即使命中, 掩码差 1 ULP f32 => Lab 输出差 ~2.4e-7 << 1e-6 容差,
// 对齐验收见 tests/unit/test_native_colorcal_oklch.py)。
// 常数/操作序逐行照抄源码, 勿改 (改任一中间舍入即破坏 <=1ULP 等价)。
constexpr std::uint32_t CbrtB1 = 715094163;   // (682-0.03306235651)*2^20
constexpr std::uint32_t CbrtB2 = 696219795;   // (678-0.03306235651)*2^20
constexpr double CbrtP0 = 1.87595182427177009643;
constexpr double CbrtP1 = -1.88497979543377169875;
constexpr double CbrtP2 = 1.621429720105354466140;
constexpr double CbrtP3 = -0.758397934778766047437;
constexpr double CbrtP4 = 0.145996192886612446982;

double CbrtFast(double x)
{
    std::int32_t hx;
    union {
        double value;
        std::uint64_t bits;
    } u;
    double r, s, t = 0.0, w;
    std::uint32_t sign;
    std::uint32_t high, low;

    u.value = x;
    hx = static_cast<std::int32_t>(u.bits >> 32);        // EXTRACT_WORDS (LE)
    low = static_cast<std::uint32_t>(u.bits);
    sign = static_cast<std::uint32_t>(hx) & 0x80000000u;
    hx ^= static_cast<std::int32_t>(sign);
    if (static_cast<std::uint32_t>(hx) >= 0x7ff00000u) {
        return x + x;                                    // cbrt(NaN,INF) is itself
    }
    if (static_cast<std::uint32_t>(hx) < 0x00100000u) {  // zero or subnormal
        if ((static_cast<std::uint32_t>(hx) | low) == 0) {
            return x;                                    // cbrt(0) is itself
        }
        u.bits = 0x4350000000000000ULL;                  // t = 2**54
        t = u.value * x;
        high = static_cast<std::uint32_t>(u.bits >> 32);
        u.bits = static_cast<std::uint64_t>(
                      sign | ((high & 0x7fffffffu) / 3 + CbrtB2)) << 32;
        t = u.value;
    } else {
        u.bits = static_cast<std::uint64_t>(
                      sign | (static_cast<std::uint32_t>(hx) / 3 + CbrtB1)) << 32;
        t = u.value;
    }

    r = (t * t) * (t / x);
    t = t * ((CbrtP0 + r * (CbrtP1 + r * CbrtP2))
           + ((r * r) * r) * (CbrtP3 + r * CbrtP4));

    u.value = t;
    u.bits = (u.bits + 0x80000000ULL) & 0xffffffffc0000000ULL;
    t = u.value;

    s = t * t;                 // t*t is exact
    r = x / s;                 // error <= 0.5 ulps
    w = t + t;                 // t+t is exact
    r = (r - t) / (w + r);     // r-t is exact; w+r ~= 3*t
    return t + t * r;          // error <= (0.5 + 0.5/3) * ulp
}

// OKLab 椭圆肤色软掩码 (单像素): 原始 gamma sRGB f32 -> 掩码 f32,
// 与 core/skin.py::skin_mask_oklab 逐式对应 (数值契约见上方块注释)。
// 掩码取**原始**像素 (校正前, 与 SkinMaskF32(aOrig,bOrig) 同口径)。
float SkinMaskOklab(float r32, float g32, float b32)
{
    // 入参清洗: f32 -> f64 展宽 -> clip [0,1] (skin_mask_oklab 入口)
    const double r = std::min(std::max(static_cast<double>(r32), 0.0), 1.0);
    const double g = std::min(std::max(static_cast<double>(g32), 0.0), 1.0);
    const double b = std::min(std::max(static_cast<double>(b32), 0.0), 1.0);
    // sRGB EOTF 解码 (f64): c<=0.04045 ? c/12.92 : pow((c+0.055)/1.055, 2.4)
    // (pow 走 CRT ucrtbase, 与 numpy np.power 同实现 —— 逐位)
    auto decode = [](double c) -> double {
        if (c < 0.0) {
            c = 0.0;
        }
        if (c <= 0.04045) {
            return c / 12.92;
        }
        return std::pow((c + 0.055) / 1.055, 2.4);
    };
    const double lr = decode(r);
    const double lg = decode(g);
    const double lb = decode(b);
    // M1 -> LMS -> cbrt -> M2 -> OKLab a/b (掩码只需 a/b, L 行不算;
    // 逐分量加权和与 core/oklab.py 同操作数顺序同结合, 勿重排)
    const double l = M1LsrgbToLms[0][0] * lr + M1LsrgbToLms[0][1] * lg
                   + M1LsrgbToLms[0][2] * lb;
    const double m = M1LsrgbToLms[1][0] * lr + M1LsrgbToLms[1][1] * lg
                   + M1LsrgbToLms[1][2] * lb;
    const double s = M1LsrgbToLms[2][0] * lr + M1LsrgbToLms[2][1] * lg
                   + M1LsrgbToLms[2][2] * lb;
    const double l_ = CbrtFast(l);
    const double m_ = CbrtFast(m);
    const double s_ = CbrtFast(s);
    const double labA = M2LmspToLab[1][0] * l_ + M2LmspToLab[1][1] * m_
                      + M2LmspToLab[1][2] * s_;
    const double labB = M2LmspToLab[2][0] * l_ + M2LmspToLab[2][1] * m_
                      + M2LmspToLab[2][2] * s_;
    // OKLab a-b 平面椭圆马氏距离 (f64; 中心为 np.float32 舍入后展宽值)
    const double da = labA - SkinOklabA;
    const double db = labB - SkinOklabB;
    const double u = da * SkinOklabCos + db * SkinOklabSin;
    const double v = -da * SkinOklabSin + db * SkinOklabCos;
    const double d2 = (u / SkinOklabMajor) * (u / SkinOklabMajor)
                    + (v / SkinOklabMinor) * (v / SkinOklabMinor);
    const float d = static_cast<float>(std::sqrt(d2 > 0.0 ? d2 : 0.0));
    // smoothstep 软带 (f32, NEP50: Python 标量不提升 dtype)
    const float t = std::clamp((d - 1.0f) / SkinOklabSoftBand, 0.0f, 1.0f);
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

// oklch 域全量内核 (v1.5.0): 与 ApplyColorCalLabF32 逐式对应, **唯一差异**=
// 肤色掩码源 —— Lab 椭圆 SkinMaskF32(aOrig,bOrig) 换成 OKLab 椭圆
// SkinMaskOklab(rgb 原始像素) (与 modules/color_cal.py oklch 分支的
// _skin_region_mask -> core/skin.py::skin_mask_oklab 同掩码, F11 设计 §3)。
// rgb 额外输入 = 校正前 gamma sRGB f32 (H,W,3) —— 掩码取原始像素口径。
// 其余算步骤 (中性轴/曲线/色相/饱和增益/限幅) 与 float Lab 域 hsv 内核
// 完全相同: oklch 只换掩码域, 不换校准域 (同 Python 侧结构)。
int ApplyColorCalLabF32Oklch(const float* lab, const float* rgb, float* labOut,
                             int width, int height, const ColorCalParams& params)
{
    if (lab == nullptr || rgb == nullptr || labOut == nullptr
            || width <= 0 || height <= 0) {
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
#pragma omp parallel for schedule(dynamic, 2048)
#endif
    for (int i = 0; i < pixelCount; ++i) {
        const float L = lab[i * 3 + 0];
        const float aOrig = lab[i * 3 + 1];
        const float bOrig = lab[i * 3 + 2];
        // C 与 uint8 域同单位同值 (u8 域为 |a-128,b-128|)
        const float C = std::sqrt(aOrig * aOrig + bOrig * bOrig);
        float skinMaskValue = 0.0f;
        if (needSkin) {
            // oklch 域: OKLab 椭圆掩码取原始 gamma RGB 像素
            skinMaskValue = SkinMaskOklab(rgb[i * 3 + 0], rgb[i * 3 + 1], rgb[i * 3 + 2]);
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

PIXO_RENDER_NATIVE_API int PixoRenderColorCalApplyLabF32Oklch(
    const float* lab, const float* rgb, float* labOut, int width, int height,
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
        const int status = ApplyColorCalLabF32Oklch(lab, rgb, labOut, width, height, p);
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
