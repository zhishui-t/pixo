// spike (r10): OKLab 掩码 perf 分解 —— pow / cbrt 成本占比 + OpenMP 扩展性。
// 三个变体 (同一操作序, 逐项替换为恒等以隔离成本):
//   full  = 完整掩码链
//   nopow = sRGB decode 的 pow(x,2.4) 换成 x (其余不变)
//   nocbrt = cbrt 换成恒等 (其余不变)
// 用法: spike_oklch_bench.exe <n_pixels> [repeats]
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <vector>
#include <chrono>

#ifdef _OPENMP
#include <omp.h>
#endif

namespace {

constexpr double M1[3][3] = {
    {0.4122214708, 0.5363325363, 0.0514459929},
    {0.2119034982, 0.6806995451, 0.1073969566},
    {0.0883024619, 0.2817188376, 0.6299787005},
};
constexpr double M2[3][3] = {
    {0.2104542553, 0.7936177850, -0.0040720468},
    {1.9779984951, -2.4285922050, 0.4505937099},
    {0.0259040371, 0.7827717662, -0.8086757660},
};
constexpr double A = 0x1.f0c34cp-7;
constexpr double B = 0x1.f5c29p-5;
constexpr double COSA = 0x1.f6ad676b26324p-1;
constexpr double SINA = 0x1.850a0e13d3047p-3;
constexpr double MAJ = 0x1.764f11b60ae97p-5;
constexpr double MIN = 0x1.72367e414e7efp-5;

inline double dec(double c, int mode)
{
    if (c < 0.0) c = 0.0;
    if (c <= 0.04045) return c / 12.92;
    if (mode == 1) return (c + 0.055) / 1.055;          // nopow
    return std::pow((c + 0.055) / 1.055, 2.4);
}

inline double cb(double x, int mode)
{
    if (mode == 2) return x;                             // nocbrt
    return std::cbrt(x);
}

float mask_px(float r32, float g32, float b32, int mode)
{
    const double r = std::min(std::max((double)r32, 0.0), 1.0);
    const double g = std::min(std::max((double)g32, 0.0), 1.0);
    const double b = std::min(std::max((double)b32, 0.0), 1.0);
    const double lr = dec(r, mode), lg = dec(g, mode), lb = dec(b, mode);
    const double l = M1[0][0] * lr + M1[0][1] * lg + M1[0][2] * lb;
    const double m = M1[1][0] * lr + M1[1][1] * lg + M1[1][2] * lb;
    const double s = M1[2][0] * lr + M1[2][1] * lg + M1[2][2] * lb;
    const double l_ = cb(l, mode), m_ = cb(m, mode), s_ = cb(s, mode);
    const double la = M2[1][0] * l_ + M2[1][1] * m_ + M2[1][2] * s_;
    const double lb2 = M2[2][0] * l_ + M2[2][1] * m_ + M2[2][2] * s_;
    const double da = la - A, db = lb2 - B;
    const double u = da * COSA + db * SINA;
    const double v = -da * SINA + db * COSA;
    const double d2 = (u / MAJ) * (u / MAJ) + (v / MIN) * (v / MIN);
    const float d = (float)std::sqrt(d2 > 0.0 ? d2 : 0.0);
    float t = (d - 1.0f) / 0.25f;
    t = std::clamp(t, 0.0f, 1.0f);
    return 1.0f - t * t * (3.0f - 2.0f * t);
}

} // namespace

int main(int argc, char** argv)
{
    if (argc < 2) { std::fprintf(stderr, "usage: %s <n> [repeats]\n", argv[0]); return 2; }
    const long long n = std::atoll(argv[1]);
    const int reps = argc > 2 ? std::atoi(argv[2]) : 5;
    std::vector<float> rgb((size_t)n * 3), mask((size_t)n);
    uint64_t seed = 20260907;
    for (size_t i = 0; i < rgb.size(); ++i) {   // xorshift 快速伪随机 [0,1)
        seed ^= seed << 13; seed ^= seed >> 7; seed ^= seed << 17;
        rgb[i] = (float)((seed >> 40) / (double)(1ULL << 24));
    }
#ifdef _OPENMP
    std::printf("threads=%d\n", omp_get_max_threads());
#else
    std::printf("threads=1 (no OpenMP)\n");
#endif
    const char* names[3] = {"full", "nopow", "nocbrt"};
    for (int mode = 0; mode < 3; ++mode) {
        double best = 1e30;
        for (int rep = 0; rep <= reps; ++rep) {
            const auto t0 = std::chrono::steady_clock::now();
#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
            for (long long i = 0; i < n; ++i)
                mask[i] = mask_px(rgb[i*3], rgb[i*3+1], rgb[i*3+2], mode);
            const double dt = std::chrono::duration<double>(
                std::chrono::steady_clock::now() - t0).count();
            if (rep > 0 && dt < best) best = dt;
        }
        std::printf("%-7s %8.2f ms  (%.1f ns/px)\n", names[mode], best * 1e3,
                    best * 1e9 / n);
    }
    // 防 DCE
    double acc = 0; for (auto v : mask) acc += v;
    std::printf("(acc %f)\n", acc);
    return 0;
}
