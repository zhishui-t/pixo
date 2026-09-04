// pixo.render 原生热点内核: gamma sRGB <-> Oklab。
//
// 逐位一致契约见 oklab.h 头注; Python 参考实现 pixo.render/core/oklab.py。
// 验收: tests/unit/test_native_oklab.py 随机 100 万像素 + 网格 bit-exact
// (设计 §2.4 验收硬门)。
//
// 编码规范遵循 guanlan/AGENTS.md:
//   - 变量/函数小驼峰, 类大驼峰, 常量 constexpr 且不加 k 前缀
//   - K&R 括号: 函数体左括号换行, 控制语句左括号同行
//   - 行宽 <= 120, 中文注释
//   - namespace 全小写
#include "oklab.h"

#include "abi.h"

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace pixo_render_native {

namespace {

// 行向量语义: out_i = sum_j M[i][j] * in_j (与 core/oklab.py 矩阵布局一致)。

// M1: linear sRGB -> LMS (Ottosson 2020 原文常数, 抄 core/oklab.py)
constexpr double M1LsrgbToLms[3][3] = {
    {0.4122214708, 0.5363325363, 0.0514459929},
    {0.2119034982, 0.6806995451, 0.1073969566},
    {0.0883024619, 0.2817188376, 0.6299787005},
};

// M1⁻¹: LMS -> linear sRGB = inv(M1) 冻结 12 位字面常数 (照抄 core/oklab.py,
// 勿现算 np.linalg.inv/勿抄原文公布逆, 出处见 core/oklab.py 模块 docstring)
constexpr double M1InvLmsToLsrgb[3][3] = {
    {4.07674166135, -3.30771159041, 0.230969928729},
    {-1.26843800409, 2.60975740066, -0.34131939631},
    {-0.00419608654184, -0.703418614459, 1.70761470093},
};

// M2: LMS' -> Oklab (Ottosson 2020 原文常数, 抄 core/oklab.py)
constexpr double M2LmspToLab[3][3] = {
    {0.2104542553, 0.7936177850, -0.0040720468},
    {1.9779984951, -2.4285922050, 0.4505937099},
    {0.0259040371, 0.7827717662, -0.8086757660},
};

// M2⁻¹: Oklab -> LMS' = inv(M2) 冻结 12 位字面常数 (照抄 core/oklab.py)
constexpr double M2InvLabToLmsp[3][3] = {
    {0.999999998451, 0.396337792174, 0.215803758061},
    {1.00000000888, -0.105561342324, -0.0638541747717},
    {1.00000005467, -0.089484182095, -1.29148553786},
};

// gamma sRGB -> linear (IEC 61966-2-1 分段幂律), 负输入按 0; 分支阈值与
// 表达式顺序逐项对齐 core/oklab._srgb_to_linear。
double SrgbDecodeToLinear(double c)
{
    if (c < 0.0) {
        c = 0.0;
    }
    if (c <= 0.04045) {
        return c / 12.92;
    }
    return std::pow((c + 0.055) / 1.055, 2.4);
}

// linear -> gamma sRGB; 入参须已裁剪为非负 (裁剪责任在调用方, 同 core/oklab)。
double LinearEncodeToSrgb(double lin)
{
    if (lin <= 0.0031308) {
        return 12.92 * lin;
    }
    return 1.055 * std::pow(lin, 1.0 / 2.4) - 0.055;
}

} // namespace

int SrgbToOklabF32(const SrgbToOklabParams& params)
{
    if (params.rgb == nullptr || params.l == nullptr || params.a == nullptr ||
        params.b == nullptr || params.width <= 0 || params.height <= 0 ||
        params.stride < params.width * 3 || params.planeStride < params.width) {
        return -1;
    }
    const int width = params.width;
    const int height = params.height;
#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (int y = 0; y < height; ++y) {
        const float* row = params.rgb + static_cast<std::int64_t>(y) * params.stride;
        double* lRow = params.l + static_cast<std::int64_t>(y) * params.planeStride;
        double* aRow = params.a + static_cast<std::int64_t>(y) * params.planeStride;
        double* bRow = params.b + static_cast<std::int64_t>(y) * params.planeStride;
        for (int x = 0; x < width; ++x) {
            const double r = SrgbDecodeToLinear(static_cast<double>(row[x * 3 + 0]));
            const double g = SrgbDecodeToLinear(static_cast<double>(row[x * 3 + 1]));
            const double b = SrgbDecodeToLinear(static_cast<double>(row[x * 3 + 2]));
            // 逐分量加权和, 与 core/oklab.srgb_to_oklab 同操作数顺序同结合, 勿重排
            const double l = M1LsrgbToLms[0][0] * r + M1LsrgbToLms[0][1] * g + M1LsrgbToLms[0][2] * b;
            const double m = M1LsrgbToLms[1][0] * r + M1LsrgbToLms[1][1] * g + M1LsrgbToLms[1][2] * b;
            const double s = M1LsrgbToLms[2][0] * r + M1LsrgbToLms[2][1] * g + M1LsrgbToLms[2][2] * b;
            // cbrt: 实数立方根 (负值有定义), 与 np.cbrt 同 CRT 实现
            const double l_ = std::cbrt(l);
            const double m_ = std::cbrt(m);
            const double s_ = std::cbrt(s);
            lRow[x] = M2LmspToLab[0][0] * l_ + M2LmspToLab[0][1] * m_ + M2LmspToLab[0][2] * s_;
            aRow[x] = M2LmspToLab[1][0] * l_ + M2LmspToLab[1][1] * m_ + M2LmspToLab[1][2] * s_;
            bRow[x] = M2LmspToLab[2][0] * l_ + M2LmspToLab[2][1] * m_ + M2LmspToLab[2][2] * s_;
        }
    }
    return 0;
}

int OklabToSrgbF32(const OklabToSrgbParams& params)
{
    if (params.l == nullptr || params.a == nullptr || params.b == nullptr ||
        params.rgb == nullptr || params.width <= 0 || params.height <= 0 ||
        params.stride < params.width * 3 || params.planeStride < params.width) {
        return -1;
    }
    const int width = params.width;
    const int height = params.height;
#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (int y = 0; y < height; ++y) {
        const double* lRow = params.l + static_cast<std::int64_t>(y) * params.planeStride;
        const double* aRow = params.a + static_cast<std::int64_t>(y) * params.planeStride;
        const double* bRow = params.b + static_cast<std::int64_t>(y) * params.planeStride;
        float* row = params.rgb + static_cast<std::int64_t>(y) * params.stride;
        for (int x = 0; x < width; ++x) {
            const double labL = lRow[x];
            const double labA = aRow[x];
            const double labB = bRow[x];
            const double l_ = M2InvLabToLmsp[0][0] * labL + M2InvLabToLmsp[0][1] * labA + M2InvLabToLmsp[0][2] * labB;
            const double m_ = M2InvLabToLmsp[1][0] * labL + M2InvLabToLmsp[1][1] * labA + M2InvLabToLmsp[1][2] * labB;
            const double s_ = M2InvLabToLmsp[2][0] * labL + M2InvLabToLmsp[2][1] * labA + M2InvLabToLmsp[2][2] * labB;
            // cbrt 逆: 立方须走 pow(x, 3.0) 与 numpy `x**3` 同 CRT pow;
            // 三次连乘会有 1 ULP 级差异, 禁止改写
            const double l = std::pow(l_, 3.0);
            const double m = std::pow(m_, 3.0);
            const double s = std::pow(s_, 3.0);
            const double r = M1InvLmsToLsrgb[0][0] * l + M1InvLmsToLsrgb[0][1] * m + M1InvLmsToLsrgb[0][2] * s;
            const double g = M1InvLmsToLsrgb[1][0] * l + M1InvLmsToLsrgb[1][1] * m + M1InvLmsToLsrgb[1][2] * s;
            const double b = M1InvLmsToLsrgb[2][0] * l + M1InvLmsToLsrgb[2][1] * m + M1InvLmsToLsrgb[2][2] * s;
            // 越域 linear clip 到 [0,1] 后编码 (同 core/oklab.oklab_to_srgb)
            const double rClip = std::max(0.0, std::min(1.0, r));
            const double gClip = std::max(0.0, std::min(1.0, g));
            const double bClip = std::max(0.0, std::min(1.0, b));
            row[x * 3 + 0] = static_cast<float>(LinearEncodeToSrgb(rClip));
            row[x * 3 + 1] = static_cast<float>(LinearEncodeToSrgb(gClip));
            row[x * 3 + 2] = static_cast<float>(LinearEncodeToSrgb(bClip));
        }
    }
    return 0;
}

} // namespace pixo_render_native

// ---- C ABI 导出 (供 Python ctypes 加载) ----

PIXO_RENDER_NATIVE_API int PixoRenderSrgbToOklabF32(
    const struct PixoRenderSrgbToOklabParams* params)
{
    if (params == nullptr) {
        return PixoRenderInvalidArgs;
    }
    pixo_render_native::SrgbToOklabParams p;
    p.rgb = params->rgb;
    p.width = params->width;
    p.height = params->height;
    p.stride = params->stride;
    p.l = params->l;
    p.a = params->a;
    p.b = params->b;
    p.planeStride = params->planeStride;
    return pixo_render_native::SrgbToOklabF32(p);
}

PIXO_RENDER_NATIVE_API int PixoRenderOklabToSrgbF32(
    const struct PixoRenderOklabToSrgbParams* params)
{
    if (params == nullptr) {
        return PixoRenderInvalidArgs;
    }
    pixo_render_native::OklabToSrgbParams p;
    p.l = params->l;
    p.a = params->a;
    p.b = params->b;
    p.planeStride = params->planeStride;
    p.rgb = params->rgb;
    p.width = params->width;
    p.height = params->height;
    p.stride = params->stride;
    return pixo_render_native::OklabToSrgbF32(p);
}
