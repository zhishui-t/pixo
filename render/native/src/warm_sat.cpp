// M1: apply_local_warm_sat 的完整 C++ 实现（broad + spot 分支，float32/float64）。
// 与 pixo.render/core/huesat.py 语义对齐：
//   线性 sRGB -> 线性 ProPhoto -> HSV -> 平滑权重 -> 覆盖率决策 ->
//   broad 或 spot(GaussianBlur + 反差门) -> 改 S -> HSV -> ProPhoto -> sRGB。
#include "warm_sat.h"

#include "abi.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <type_traits>
#ifdef _OPENMP
#include <omp.h>
#endif
#include <vector>

namespace pixo_render_native {

namespace {

// 3×3 矩阵常量（行主序，与 pixo.render/core/color.py 的 _SRGB_TO_PROPHOTO /
// _PROPHOTO_TO_SRGB 逐项一致；float32 用截断常量，float64 用完整精度）。
template <typename T>
constexpr T SrgbToProphoto[9] = {
    T(0.529345932772873), T(0.33007276911858824), T(0.14058129149952214),
    T(0.09837426739499831), T(0.8734610322807564), T(0.02816463441116391),
    T(0.016883180798186813), T(0.11767249083852699), T(0.8654442998857458),
};

template <typename T>
constexpr T ProphotoToSrgb[9] = {
    T(2.034075761127914), T(-0.727334053528418), T(-0.3067417508323348),
    T(-0.22881312503437068), T(1.2317300675804077), T(-0.0029168629542076674),
    T(-0.008569769855748604), T(-0.15328662143133767), T(1.161856414213668),
};

template <typename T>
T Modulo(T value, T range)
{
    T result = std::fmod(value, range);
    if (result < T(0)) {
        result += range;
    }
    return result;
}

template <typename T>
T SmoothStep(T x)
{
    x = std::clamp(x, T(0), T(1));
    return x * x * (T(3) - T(2) * x);
}

// SmoothStep(x)^6，用乘法代替 pow，显著降低标量循环开销。
template <typename T>
T SmoothStepPow6(T x)
{
    const T t = SmoothStep(x);
    const T t2 = t * t;
    return t2 * t2 * t2;
}

template <typename T>
T SrgbEncodeV(T v)
{
    v = std::max(v, T(0));
    if (v <= T(0.0031308)) {
        return T(12.92) * v;
    }
    return T(1.055) * std::pow(v, T(1) / T(2.4)) - T(0.055);
}

// sRGB encode 4096 点 LUT（输入域 [0,2]），避免逐像素 std::pow。
// 与架构文档 §5.1 的 SrgbEncodeLut 一致；线性插值误差 ≤1e-6。
float SrgbEncodeVFast(float v)
{
    v = std::max(v, 0.0f);
    if (v <= 0.0031308f) {
        return 12.92f * v;
    }
    if (v >= 2.0f) {
        return SrgbEncodeV<float>(v);
    }
    constexpr int LutSize = 4096;
    static const std::array<float, LutSize> table = [] {
        std::array<float, LutSize> t{};
        for (int i = 0; i < LutSize; ++i) {
            const double x = 2.0 * static_cast<double>(i) /
                             static_cast<double>(LutSize - 1);
            t[static_cast<size_t>(i)] = static_cast<float>(SrgbEncodeV<double>(x));
        }
        return t;
    }();
    const float pos = v * static_cast<float>(LutSize - 1) / 2.0f;
    int i = static_cast<int>(pos);
    if (i >= LutSize - 1) {
        return table[LutSize - 1];
    }
    const float frac = pos - static_cast<float>(i);
    return table[static_cast<size_t>(i)] * (1.0f - frac) +
           table[static_cast<size_t>(i + 1)] * frac;
}


template <typename T>
void RgbToHsvPixel(T r, T g, T b, T& h, T& s, T& v)
{
    const T maxValue = std::max(r, std::max(g, b));
    const T minValue = std::min(r, std::min(g, b));
    const T delta = maxValue - minValue;
    h = T(0);
    s = T(0);
    v = maxValue;
    if (delta > T(0)) {
        const T deltaInv = T(1) / delta;
        s = (maxValue > T(0)) ? delta / maxValue : T(0);
        T segment = T(0);
        if (maxValue == r) {
            segment = Modulo((g - b) * deltaInv, T(6));
        } else if (maxValue == g) {
            segment = (b - r) * deltaInv + T(2);
        } else {
            segment = (r - g) * deltaInv + T(4);
        }
        h = Modulo(T(60) * segment, T(360));
    }
}

template <typename T>
void HsvToRgbPixel(T h, T s, T v, T& r, T& g, T& b)
{
    const T hue = Modulo(h, T(360));
    const T sector = hue / T(60);
    const int sectorIndex = static_cast<int>(std::floor(sector)) % 6;
    const T fraction = sector - std::floor(sector);
    const T p = v * (T(1) - s);
    const T q = v * (T(1) - fraction * s);
    const T t = v * (T(1) - (T(1) - fraction) * s);
    switch (sectorIndex) {
        case 0: r = v; g = t; b = p; break;
        case 1: r = q; g = v; b = p; break;
        case 2: r = p; g = v; b = t; break;
        case 3: r = p; g = q; b = v; break;
        case 4: r = t; g = p; b = v; break;
        default: r = v; g = p; b = q; break;
    }
}

// OpenCV BORDER_REFLECT101 的任意整数映射（支持 kernel 大于图像尺寸）。
int Reflect101(int index, int size)
{
    if (size == 1) {
        return 0;
    }
    const int d = index < 0 ? -index : index;
    const int period = 2 * (size - 1);
    const int m = d % period;
    return m < size ? m : period - m;
}

// 可分离 GaussianBlur，语义对齐 cv2.GaussianBlur(src, (0,0), sigma)：
//   ksize = cvRound(sigma * 4) * 2 + 1；border=REFLECT101。
// 内部用 T 累加，float32 路径误差与 cv2 ≤1e-6。
template <typename T>
void GaussianBlurSeparable(const T* src, T* dst, int width, int height,
                           double sigma)
{
    const int ksize = static_cast<int>(std::lround(sigma * 4.0)) * 2 + 1;
    const int radius = ksize / 2;

    std::vector<T> kernel(static_cast<size_t>(ksize));
    double sum = 0.0;
    for (int i = 0; i < ksize; ++i) {
        const double x = static_cast<double>(i - radius) / sigma;
        const double w = std::exp(-0.5 * x * x);
        kernel[static_cast<size_t>(i)] = static_cast<T>(w);
        sum += w;
    }
    const double invSum = 1.0 / sum;
    for (T& k : kernel) {
        k = static_cast<T>(static_cast<double>(k) * invSum);
    }

    std::vector<T> tmp(static_cast<size_t>(width) *
                       static_cast<size_t>(height));

#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (int y = 0; y < height; ++y) {
        const T* row = src + static_cast<size_t>(y) * static_cast<size_t>(width);
        T* trow = tmp.data() + static_cast<size_t>(y) * static_cast<size_t>(width);

        int x = 0;
        for (; x < radius && x < width; ++x) {
            T acc = T(0);
            for (int j = 0; j < ksize; ++j) {
                const int xx = Reflect101(x + j - radius, width);
                acc += kernel[static_cast<size_t>(j)] * row[xx];
            }
            trow[x] = acc;
        }
        for (; x < width - radius; ++x) {
            T acc = kernel[static_cast<size_t>(radius)] * row[x];
            for (int j = 1; j <= radius; ++j) {
                acc += kernel[static_cast<size_t>(radius - j)] *
                       (row[x - j] + row[x + j]);
            }
            trow[x] = acc;
        }
        for (; x < width; ++x) {
            T acc = T(0);
            for (int j = 0; j < ksize; ++j) {
                const int xx = Reflect101(x + j - radius, width);
                acc += kernel[static_cast<size_t>(j)] * row[xx];
            }
            trow[x] = acc;
        }
    }

#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            T acc;
            if (y >= radius && y < height - radius) {
                acc = kernel[static_cast<size_t>(radius)] *
                      tmp[static_cast<size_t>(y) * static_cast<size_t>(width) + x];
                for (int j = 1; j <= radius; ++j) {
                    acc += kernel[static_cast<size_t>(radius - j)] *
                           (tmp[static_cast<size_t>(y - j) * static_cast<size_t>(width) + x] +
                            tmp[static_cast<size_t>(y + j) * static_cast<size_t>(width) + x]);
                }
            } else {
                acc = T(0);
                for (int i = 0; i < ksize; ++i) {
                    const int srcY = Reflect101(y + i - radius, height);
                    acc += kernel[static_cast<size_t>(i)] *
                           tmp[static_cast<size_t>(srcY) * static_cast<size_t>(width) + x];
                }
            }
            dst[static_cast<size_t>(y) * static_cast<size_t>(width) + x] = acc;
        }
    }
}

template <typename T>
int ApplyLocalWarmSatImpl(const T* rgb, T* out, int width, int height,
                          const WarmSatParams& params)
{
    if (rgb == nullptr || out == nullptr || width <= 0 || height <= 0) {
        return -1;
    }
    // 调用方约定：至少一个 scale > 1 才会进入本内核。
    if (params.satScale <= 1.0f && params.spotSatScale <= 1.0f) {
        return -1;
    }

    const size_t pixelCount = static_cast<size_t>(width) *
                              static_cast<size_t>(height);
    std::vector<T> h(pixelCount);
    std::vector<T> s(pixelCount);
    std::vector<T> v(pixelCount);
    std::vector<T> vEnc(pixelCount);

    const T edgeDeg = std::max(static_cast<T>(params.hueHalfwidth) * T(0.25),
                               T(1));
    const T lo = static_cast<T>(params.hueCenter) -
                 static_cast<T>(params.hueHalfwidth);
    const T hi = static_cast<T>(params.hueCenter) +
                 static_cast<T>(params.hueHalfwidth);
    const T satMinT = static_cast<T>(params.satMin);
    const T valMinT = static_cast<T>(params.valMin);

    int hardCount = 0;
    const int pixelCountInt = static_cast<int>(pixelCount);
#ifdef _OPENMP
#pragma omp parallel for reduction(+:hardCount) schedule(static)
#endif
    for (int i = 0; i < pixelCountInt; ++i) {
        const T r0 = rgb[i * 3 + 0];
        const T g0 = rgb[i * 3 + 1];
        const T b0 = rgb[i * 3 + 2];

        // sRGB(D65) -> ProPhoto(D50)
        const T ppR = SrgbToProphoto<T>[0] * r0 + SrgbToProphoto<T>[1] * g0 +
                      SrgbToProphoto<T>[2] * b0;
        const T ppG = SrgbToProphoto<T>[3] * r0 + SrgbToProphoto<T>[4] * g0 +
                      SrgbToProphoto<T>[5] * b0;
        const T ppB = SrgbToProphoto<T>[6] * r0 + SrgbToProphoto<T>[7] * g0 +
                      SrgbToProphoto<T>[8] * b0;
        const T pr = std::max(ppR, T(0));
        const T pg = std::max(ppG, T(0));
        const T pb = std::max(ppB, T(0));

        T hv, sv, vv;
        RgbToHsvPixel(pr, pg, pb, hv, sv, vv);
        T ve;
        if constexpr (std::is_same<T, float>::value) {
            ve = static_cast<T>(SrgbEncodeVFast(static_cast<float>(vv)));
        } else {
            ve = SrgbEncodeV(vv);
        }
        h[i] = hv;
        s[i] = sv;
        v[i] = vv;
        vEnc[i] = ve;

        if (hv >= lo && hv <= hi && sv >= satMinT && ve >= valMinT) {
            ++hardCount;
        }
    }

    const double coverage = static_cast<double>(hardCount) /
                            static_cast<double>(pixelCount);
    const bool useSpot = coverage > static_cast<double>(params.coverageMax);
    const T scale = useSpot ? static_cast<T>(params.spotSatScale)
                            : static_cast<T>(params.satScale);

    std::vector<T> vBlur;
    if (useSpot) {
        const double minDim = static_cast<double>(std::min(width, height));
        const double sigma = std::max(
            3.0, minDim * static_cast<double>(params.contrastSigmaFrac));
        vBlur.resize(pixelCount);
        GaussianBlurSeparable(vEnc.data(), vBlur.data(), width, height, sigma);
    }

    const T contrastThr = static_cast<T>(params.contrastThr);
    const T contrastSoft =
        std::max(static_cast<T>(params.contrastSoft), T(1e-6));

#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (int i = 0; i < pixelCountInt; ++i) {
        const T hueW = SmoothStep((h[i] - lo) / edgeDeg) *
                       SmoothStep((hi - h[i]) / edgeDeg);
        const T satW = SmoothStepPow6(
            s[i] / std::max(satMinT, T(1e-9)));
        const T valW = SmoothStep(
            (vEnc[i] - (valMinT - T(0.05))) / T(0.08));
        T w = hueW * satW * valW;
        if (useSpot) {
            const T detail = vEnc[i] - vBlur[i];
            const T spotW = SmoothStep((detail - contrastThr) / contrastSoft);
            w = w * spotW;
        }

        // w==0 的像素（中性/带外/暗部）直接拷贝输入，与 Python 参考的
        // “严格不变”行为一致，也避免无谓的矩阵往返。
        // 注意：float64 等价基准不短路，必须走完整矩阵往返以对齐 Python 逐位结果。
        if (w == T(0) && std::is_same<T, float>::value) {
            out[i * 3 + 0] = rgb[i * 3 + 0];
            out[i * 3 + 1] = rgb[i * 3 + 1];
            out[i * 3 + 2] = rgb[i * 3 + 2];
            continue;
        }

        const T s2 = std::clamp(s[i] * (T(1) + (scale - T(1)) * w), T(0),
                                T(1));

        T rr, gg, bb;
        HsvToRgbPixel(h[i], s2, v[i], rr, gg, bb);

        // ProPhoto(D50) -> sRGB(D65)
        const T sr = ProphotoToSrgb<T>[0] * rr + ProphotoToSrgb<T>[1] * gg +
                     ProphotoToSrgb<T>[2] * bb;
        const T sg = ProphotoToSrgb<T>[3] * rr + ProphotoToSrgb<T>[4] * gg +
                     ProphotoToSrgb<T>[5] * bb;
        const T sb = ProphotoToSrgb<T>[6] * rr + ProphotoToSrgb<T>[7] * gg +
                     ProphotoToSrgb<T>[8] * bb;

        out[i * 3 + 0] = std::max(sr, T(0));
        out[i * 3 + 1] = std::max(sg, T(0));
        out[i * 3 + 2] = std::max(sb, T(0));
    }
    return 0;
}

} // namespace

int ApplyLocalWarmSatF32(const float* rgb, float* out, int width, int height,
                         const WarmSatParams& params)
{
    return ApplyLocalWarmSatImpl<float>(rgb, out, width, height, params);
}

int ApplyLocalWarmSatF64(const double* rgb, double* out, int width, int height,
                         const WarmSatParams& params)
{
    return ApplyLocalWarmSatImpl<double>(rgb, out, width, height, params);
}

} // namespace pixo_render_native

// ---- C ABI 导出 ----

PIXO_RENDER_NATIVE_API int PixoRenderApplyLocalWarmSat(
    const float* rgb, float* out, int width, int height,
    const struct PixoRenderWarmSatParams* params)
{
    try {
        if (params == nullptr) {
            return PixoRenderInvalidArgs;
        }
        pixo_render_native::WarmSatParams p;
        p.satScale = params->satScale;
        p.spotSatScale = params->spotSatScale;
        p.hueCenter = params->hueCenter;
        p.hueHalfwidth = params->hueHalfwidth;
        p.satMin = params->satMin;
        p.valMin = params->valMin;
        p.coverageMax = params->coverageMax;
        p.contrastSigmaFrac = params->contrastSigmaFrac;
        p.contrastThr = params->contrastThr;
        p.contrastSoft = params->contrastSoft;
        const int status = pixo_render_native::ApplyLocalWarmSatF32(
            rgb, out, width, height, p);
        return status < 0 ? PixoRenderInvalidArgs : PixoRenderOk;
    } catch (...) {
        return PixoRenderInternalError;
    }
}

PIXO_RENDER_NATIVE_API int PixoRenderApplyLocalWarmSatF64(
    const double* rgb, double* out, int width, int height,
    const struct PixoRenderWarmSatParams* params)
{
    try {
        if (params == nullptr) {
            return PixoRenderInvalidArgs;
        }
        pixo_render_native::WarmSatParams p;
        p.satScale = params->satScale;
        p.spotSatScale = params->spotSatScale;
        p.hueCenter = params->hueCenter;
        p.hueHalfwidth = params->hueHalfwidth;
        p.satMin = params->satMin;
        p.valMin = params->valMin;
        p.coverageMax = params->coverageMax;
        p.contrastSigmaFrac = params->contrastSigmaFrac;
        p.contrastThr = params->contrastThr;
        p.contrastSoft = params->contrastSoft;
        const int status = pixo_render_native::ApplyLocalWarmSatF64(
            rgb, out, width, height, p);
        return status < 0 ? PixoRenderInvalidArgs : PixoRenderOk;
    } catch (...) {
        return PixoRenderInternalError;
    }
}
