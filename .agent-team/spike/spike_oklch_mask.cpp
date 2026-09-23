// spike (r10 疑难): OKLab 椭圆肤色掩码 C++ 原型 —— 与
// pixo.render/core/skin.py::skin_mask_oklab 逐位对齐的最小验证。
//
// 回答的问题: native 内核内嵌 OKLab 掩码 (sRGB→OKLab→椭圆→smoothstep)
// 能否与 Python float64 numpy 链路逐位一致?
//
// 数值契约 (逐式对应 skin_mask_oklab, dtype 语义按 numpy 2.x NEP50):
//   1. 入参清洗: f32 rgb → 展宽 f64 → clip [0,1]   (skin_mask_oklab 入口)
//   2. sRGB→linear: c<=0.04045 ? c/12.92 : pow((c+0.055)/1.055, 2.4)  (f64)
//   3. M1 矩阵逐分量加权和 (同操作数顺序同结合, core/oklab.py 契约)
//   4. cbrt → M2 → OKLab a/b (f64)
//   5. 椭圆: da = a - np.float32(0.01516)  ← 常数先舍入 f32 再展宽 f64
//            (十进制 0.06125 的 f32 不是精确值, 直接写 double 会差 1ULP)
//   6. d = sqrt(max(d2,0)) → 舍入 f32; smoothstep 全 f32
// cos/sin/中心/半轴常数以 hex 字面量嵌入 (与 Python 运行时逐位相同,
// 消除 libm cos/sin 的跨实现 1ULP 风险; 出处 np.cos(0.191122) 等,
// 提取脚本见 spike_oklch_mask.py)。
//
// 用法: spike_oklch_mask.exe <rgb.bin> <n_pixels> <mask_out.bin> [repeats]
//   rgb.bin: n*3 个 little-endian float32; mask_out.bin: n 个 float32。
//   repeats>1 时循环计时 (perf 信号), 输出耗时至 stdout。
// 产物属 spike, 不入主代码; 结论回收后可删。
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

namespace {

// M1: linear sRGB -> LMS (Ottosson 2020, 照抄 core/oklab.py)
constexpr double M1LsrgbToLms[3][3] = {
    {0.4122214708, 0.5363325363, 0.0514459929},
    {0.2119034982, 0.6806995451, 0.1073969566},
    {0.0883024619, 0.2817188376, 0.6299787005},
};

// M2: LMS' -> Oklab (Ottosson 2020, 照抄 core/oklab.py)
constexpr double M2LmspToLab[3][3] = {
    {0.2104542553, 0.7936177850, -0.0040720468},
    {1.9779984951, -2.4285922050, 0.4505937099},
    {0.0259040371, 0.7827717662, -0.8086757660},
};

// OKLab 椭圆常数 (core/skin.py SKIN_OKLAB_*), hex 字面量与 Python 逐位相同:
//   中心: np.float32(0.01516/0.06125) 舍入后展宽的 f64 值
//   倾角: np.cos/np.sin(0.191122) 的 f64 结果
//   半轴/软带: Python float 直接 round-trip
constexpr double SkinOklabA = 0x1.f0c34cp-7;      // float32(0.01516) 展宽
constexpr double SkinOklabB = 0x1.f5c29p-5;       // float32(0.06125) 展宽
constexpr double SkinOklabCos = 0x1.f6ad676b26324p-1;   // np.cos(0.191122)
constexpr double SkinOklabSin = 0x1.850a0e13d3047p-3;   // np.sin(0.191122)
constexpr double SkinOklabMajor = 0x1.764f11b60ae97p-5; // 0.045692
constexpr double SkinOklabMinor = 0x1.72367e414e7efp-5; // 0.045192
constexpr float SkinOklabSoftBand = 0.25f;

double SrgbDecodeToLinear(double c)
{
    if (c < 0.0) {
        c = 0.0;    // clip(c, 0, None) (入参已 [0,1], 防御性保留)
    }
    if (c <= 0.04045) {
        return c / 12.92;
    }
    return std::pow((c + 0.055) / 1.055, 2.4);
}

// 单像素掩码: 与 skin_mask_oklab(img) 逐式对应 (返回 f32)
float SkinMaskOklabPixel(float r32, float g32, float b32)
{
    // 1) 入参清洗: f32 → f64 展宽 → clip [0,1]
    const double r = std::min(std::max(static_cast<double>(r32), 0.0), 1.0);
    const double g = std::min(std::max(static_cast<double>(g32), 0.0), 1.0);
    const double b = std::min(std::max(static_cast<double>(b32), 0.0), 1.0);
    // 2-4) sRGB → OKLab (f64, 逐分量加权和同序)
    const double lr = SrgbDecodeToLinear(r);
    const double lg = SrgbDecodeToLinear(g);
    const double lb = SrgbDecodeToLinear(b);
    const double l = M1LsrgbToLms[0][0] * lr + M1LsrgbToLms[0][1] * lg + M1LsrgbToLms[0][2] * lb;
    const double m = M1LsrgbToLms[1][0] * lr + M1LsrgbToLms[1][1] * lg + M1LsrgbToLms[1][2] * lb;
    const double s = M1LsrgbToLms[2][0] * lr + M1LsrgbToLms[2][1] * lg + M1LsrgbToLms[2][2] * lb;
    const double l_ = std::cbrt(l);
    const double m_ = std::cbrt(m);
    const double s_ = std::cbrt(s);
    const double labA = M2LmspToLab[1][0] * l_ + M2LmspToLab[1][1] * m_ + M2LmspToLab[1][2] * s_;
    const double labB = M2LmspToLab[2][0] * l_ + M2LmspToLab[2][1] * m_ + M2LmspToLab[2][2] * s_;
    // 5) 椭圆马氏距离 (f64): da/db 的中心是 np.float32 舍入后展宽值
    const double da = labA - SkinOklabA;
    const double db = labB - SkinOklabB;
    const double u = da * SkinOklabCos + db * SkinOklabSin;
    const double v = -da * SkinOklabSin + db * SkinOklabCos;
    const double d2 = (u / SkinOklabMajor) * (u / SkinOklabMajor)
                    + (v / SkinOklabMinor) * (v / SkinOklabMinor);
    const float d = static_cast<float>(std::sqrt(d2 > 0.0 ? d2 : 0.0));
    // 6) smoothstep 软带 (f32, NEP50: Python 标量不提升 dtype)
    float t = (d - 1.0f) / SkinOklabSoftBand;
    t = std::clamp(t, 0.0f, 1.0f);
    return 1.0f - t * t * (3.0f - 2.0f * t);
}

} // namespace

int main(int argc, char** argv)
{
    if (argc < 4) {
        std::fprintf(stderr, "usage: %s <rgb.bin> <n> <mask.bin> [repeats]\n", argv[0]);
        return 2;
    }
    const char* rgbPath = argv[1];
    const long long n = std::atoll(argv[2]);
    const char* maskPath = argv[3];
    const int repeats = argc > 4 ? std::atoi(argv[4]) : 1;
    if (n <= 0) {
        std::fprintf(stderr, "bad n\n");
        return 2;
    }
    std::FILE* fi = std::fopen(rgbPath, "rb");
    if (fi == nullptr) {
        std::fprintf(stderr, "open rgb.bin failed\n");
        return 2;
    }
    std::vector<float> rgb(static_cast<size_t>(n) * 3);
    if (std::fread(rgb.data(), sizeof(float), rgb.size(), fi) != rgb.size()) {
        std::fprintf(stderr, "read rgb.bin failed\n");
        return 2;
    }
    std::fclose(fi);

    std::vector<float> mask(static_cast<size_t>(n));
    for (int rep = 0; rep < repeats; ++rep) {
        for (long long i = 0; i < n; ++i) {
            mask[i] = SkinMaskOklabPixel(rgb[i * 3 + 0], rgb[i * 3 + 1], rgb[i * 3 + 2]);
        }
    }

    std::FILE* fo = std::fopen(maskPath, "wb");
    if (fo == nullptr) {
        std::fprintf(stderr, "open mask.bin failed\n");
        return 2;
    }
    std::fwrite(mask.data(), sizeof(float), mask.size(), fo);
    std::fclose(fo);
    return 0;
}
