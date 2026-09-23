// spike (r10) v2 bench: 掩码成本对比 ucrt cbrt vs msun 复刻 cbrt (threaded)。
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#ifdef _OPENMP
#include <omp.h>
#endif
namespace {
constexpr double M1[3][3] = {
    {0.4122214708, 0.5363325363, 0.0514459929},
    {0.2119034982, 0.6806995451, 0.1073969566},
    {0.0883024619, 0.2817188376, 0.6299787005}};
constexpr double M2[3][3] = {
    {0.2104542553, 0.7936177850, -0.0040720468},
    {1.9779984951, -2.4285922050, 0.4505937099},
    {0.0259040371, 0.7827717662, -0.8086757660}};
constexpr double A = 0x1.f0c34cp-7, B = 0x1.f5c29p-5;
constexpr double COSA = 0x1.f6ad676b26324p-1, SINA = 0x1.850a0e13d3047p-3;
constexpr double MAJ = 0x1.764f11b60ae97p-5, MIN = 0x1.72367e414e7efp-5;
// msun s_cbrt.c 复刻 (Bruce D. Evans), 与 ucrt cbrt 差 <=1ULP f64
constexpr uint32_t CB1 = 715094163, CB2 = 696219795;
constexpr double P0 = 1.87595182427177009643, P1 = -1.88497979543377169875;
constexpr double P2 = 1.621429720105354466140, P3 = -0.758397934778766047437;
constexpr double P4 = 0.145996192886612446982;
inline double cbrt_fast(double x) {
    int32_t hx; union { double v; uint64_t b; } u; double r, s, t = 0.0, w;
    uint32_t sign, high, low;
    u.v = x; hx = (int32_t)(u.b >> 32); low = (uint32_t)u.b;
    sign = (uint32_t)hx & 0x80000000u; hx ^= (int32_t)sign;
    if ((uint32_t)hx >= 0x7ff00000u) return x + x;
    if ((uint32_t)hx < 0x00100000u) {
        if (((uint32_t)hx | low) == 0) return x;
        u.b = 0x4350000000000000ULL; t = u.v * x;
        high = (uint32_t)(u.b >> 32);
        u.b = (uint64_t)(sign | ((high & 0x7fffffffu) / 3 + CB2)) << 32; t = u.v;
    } else {
        u.b = (uint64_t)(sign | ((uint32_t)hx / 3 + CB1)) << 32; t = u.v;
    }
    r = (t * t) * (t / x);
    t = t * ((P0 + r * (P1 + r * P2)) + ((r * r) * r) * (P3 + r * P4));
    u.v = t; u.b = (u.b + 0x80000000ULL) & 0xffffffffc0000000ULL; t = u.v;
    s = t * t; r = x / s; w = t + t; r = (r - t) / (w + r);
    return t + t * r;
}
inline double dec(double c) {
    if (c < 0.0) c = 0.0;
    if (c <= 0.04045) return c / 12.92;
    return std::pow((c + 0.055) / 1.055, 2.4);
}
template <int CBRT_FAST>
float mask_px(float r32, float g32, float b32) {
    const double r = std::min(std::max((double)r32, 0.0), 1.0);
    const double g = std::min(std::max((double)g32, 0.0), 1.0);
    const double b = std::min(std::max((double)b32, 0.0), 1.0);
    const double lr = dec(r), lg = dec(g), lb = dec(b);
    const double l = M1[0][0] * lr + M1[0][1] * lg + M1[0][2] * lb;
    const double m = M1[1][0] * lr + M1[1][1] * lg + M1[1][2] * lb;
    const double s = M1[2][0] * lr + M1[2][1] * lg + M1[2][2] * lb;
    const double l_ = CBRT_FAST ? cbrt_fast(l) : std::cbrt(l);
    const double m_ = CBRT_FAST ? cbrt_fast(m) : std::cbrt(m);
    const double s_ = CBRT_FAST ? cbrt_fast(s) : std::cbrt(s);
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
int main(int argc, char** argv) {
    const long long n = argc > 1 ? std::atoll(argv[1]) : 262144;
    const int reps = argc > 2 ? std::atoi(argv[2]) : 5;
    std::vector<float> rgb((size_t)n * 3), m1((size_t)n), m2((size_t)n);
    uint64_t seed = 20260907;
    for (size_t i = 0; i < rgb.size(); ++i) {
        seed ^= seed << 13; seed ^= seed >> 7; seed ^= seed << 17;
        rgb[i] = (float)((seed >> 40) / (double)(1ULL << 24));
    }
#ifdef _OPENMP
    std::printf("threads=%d\n", omp_get_max_threads());
#endif
    auto bench = [&](const char* name, auto fn, std::vector<float>& out) {
        double best = 1e30;
        for (int rep = 0; rep <= reps; ++rep) {
            auto t0 = std::chrono::steady_clock::now();
#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
            for (long long i = 0; i < n; ++i)
                out[i] = fn(rgb[i*3], rgb[i*3+1], rgb[i*3+2]);
            double dt = std::chrono::duration<double>(
                std::chrono::steady_clock::now() - t0).count();
            if (rep > 0 && dt < best) best = dt;
        }
        std::printf("%-22s %8.2f ms (%.1f ns/px)\n", name, best * 1e3, best * 1e9 / n);
    };
    bench("mask/ucrt-cbrt", mask_px<0>, m1);
    bench("mask/msun-cbrt", mask_px<1>, m2);
    size_t diff = 0;
    for (size_t i = 0; i < (size_t)n; ++i)
        if (std::memcmp(&m1[i], &m2[i], 4) != 0) ++diff;
    double md = 0; for (size_t i = 0; i < (size_t)n; ++i) md = std::max(md, (double)std::fabs(m1[i]-m2[i]));
    std::printf("mask diff: %zu / %lld px, max |delta| = %.3e\n", diff, n, md);
    return 0;
}
