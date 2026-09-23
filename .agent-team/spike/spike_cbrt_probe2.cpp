// spike (r10) v2: 除法-free Newton cbrt (正确舍入, long double 投票) vs ucrt cbrt。
// 语料换为生产分布: 随机 gamma sRGB -> decode -> M1 -> LMS 值 (掩码真实输入)。
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

namespace {

inline double next_rand(uint64_t& s)
{
    s ^= s << 13; s ^= s >> 7; s ^= s << 17;
    return (double)(s >> 11) / 9007199254740992.0;
}

inline double srgb_decode(double c)
{
    if (c < 0.0) c = 0.0;
    if (c <= 0.04045) return c / 12.92;
    return std::pow((c + 0.055) / 1.055, 2.4);
}

constexpr double M1[3][3] = {
    {0.4122214708, 0.5363325363, 0.0514459929},
    {0.2119034982, 0.6806995451, 0.1073969566},
    {0.0883024619, 0.2817188376, 0.6299787005},
};

// ---- 除法-free Newton cbrt, 正确舍入 ----
// y = x^(-1/3) 迭代 (仅乘法): y <- y*(4 - x*y*y*y)/3; 出口 t = x*y。
// 种子: 位黑客 bits/3 + C (C 按最小化种子相对误差数值求出, 见 main 校验)。
// 投票: t 的三个相邻 double 在 long double (64bit 尾数) 下比 |t^3 - x|,
// 取最近者 = 该 x 的正确舍入 cbrt (立方比较在 64bit 精度下可判)。
constexpr std::uint64_t kCbrtMagic = 0x2A9F53C851CE7590ULL;   // (2/3)*1023*2^52 + 0.5*(cbrt(2)-1)*2^52 附近, 见验证

inline double cbrt_fast(double x)
{
    if (x == 0.0 || std::isfinite(x) == false) {
        return std::cbrt(x);    // 0/inf/nan 委托 (掩码语料不出现)
    }
    const bool neg = std::signbit(x);
    const double ax = std::fabs(x);
    std::uint64_t bits;
    std::memcpy(&bits, &ax, sizeof(bits));
    std::uint64_t seedBits = bits / 3 + kCbrtMagic;
    double y;
    std::memcpy(&y, &seedBits, sizeof(y));
    // 归一化 y ∈ [~0.6, ~1.26) 量级; 迭代对 y 本身做 (x 已折入种子数量级):
    // 直接按 t = cbrt(ax) 迭代: t <- t - (t^3-ax)/(3t^2) 需除法;
    // 改走 y = t/seed... 这里用 t-型除法-free 形式: 以 y 为 ax^(-1/3) 的
    // 种子需另折 1/ax —— 为避免除法, 直接对 t 迭代但用倒数近似分母:
    // 简洁起见: 3 轮经典 Newton (1 除) —— 除法 4-8ns, 仍远快于 ucrt 60ns。
    double t = y;
    for (int i = 0; i < 3; ++i) {
        t = (2.0 * t + ax / (t * t)) / 3.0;
    }
    // 正确舍入投票 (位增量取相邻 double, 避免 nextafter 调用开销)
    std::uint64_t tb;
    std::memcpy(&tb, &t, sizeof(tb));
    const double tUp = [&]{ std::uint64_t b = tb + 1; double v; std::memcpy(&v, &b, 8); return v; }();
    const double tDn = [&]{ std::uint64_t b = tb - 1; double v; std::memcpy(&v, &b, 8); return v; }();
    const long double axl = (long double)ax;
    auto cubeErr = [&](double c) -> long double {
        const long double cl = (long double)c;
        const long double c3 = cl * cl * cl;
        return c3 > axl ? c3 - axl : axl - c3;
    };
    const long double e0 = cubeErr(tDn);
    const long double e1 = cubeErr(t);
    const long double e2 = cubeErr(tUp);
    double best = t;
    if (e1 <= e0) {
        if (e2 < e1) best = tUp;
    } else {
        best = tDn;
        if (e2 < e0) best = tUp;
    }
    return neg ? -best : best;
}

} // namespace

int main()
{
    // 种子常数自检: 对若干 (E, M) 检查种子相对误差 < 5%
    {
        uint64_t s = 99;
        double worst = 0;
        for (int i = 0; i < 100000; ++i) {
            double v = next_rand(s) * 8.0 + 1e-9;
            uint64_t bits; std::memcpy(&bits, &v, 8);
            uint64_t sb = bits / 3 + kCbrtMagic;
            double seed; std::memcpy(&seed, &sb, 8);
            double rel = std::fabs(seed - std::cbrt(v)) / std::cbrt(v);
            if (rel > worst) worst = rel;
        }
        std::printf("seed worst rel err = %.4f\n", worst);
    }

    const size_t n = 4'000'000;
    std::vector<double> lms(n), ref(n), fast(n);
    uint64_t s = 20260907;
    for (size_t i = 0; i < n; ++i) {
        const double r = srgb_decode(next_rand(s));
        const double g = srgb_decode(next_rand(s));
        const double b = srgb_decode(next_rand(s));
        // 轮转取 l/m/s 三个分量, 覆盖全值域
        double v = M1[i % 3][0] * r + M1[i % 3][1] * g + M1[i % 3][2] * b;
        lms[i] = v;
    }
    size_t mismatch = 0;
    for (size_t i = 0; i < n; ++i) {
        ref[i] = std::cbrt(lms[i]);
        fast[i] = cbrt_fast(lms[i]);
        if (std::memcmp(&ref[i], &fast[i], 8) != 0) {
            if (mismatch < 5) {
                std::printf("  mismatch x=%.17g std=%.17g fast=%.17g\n",
                            lms[i], ref[i], fast[i]);
            }
            ++mismatch;
        }
    }
    std::printf("domain LMS: mismatch %zu / %zu\n", mismatch, n);

    // 计时
    volatile double acc = 0;
    auto t0 = std::chrono::steady_clock::now();
    for (size_t i = 0; i < n; ++i) acc += std::cbrt(lms[i]);
    double d1 = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    t0 = std::chrono::steady_clock::now();
    for (size_t i = 0; i < n; ++i) acc += cbrt_fast(lms[i]);
    double d2 = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    std::printf("ucrt cbrt %.2f ns/call | fast %.2f ns/call (acc %f)\n",
                d1 * 1e9 / n, d2 * 1e9 / n, acc);
    return 0;
}
