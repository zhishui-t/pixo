// spike (r10) v3: ucrt cbrt 是否为 FreeBSD msun s_cbrt.c 的忠实实现?
// 若是, 逐句复刻 (确定性 IEEE double 操作序列) 即可逐位一致地换掉 60ns 的
// CRT 调用 (掩码 56% 成本)。算法: Bruce D. Evans 优化的 msun cbrt
// (rough 5-bit 位黑客 + 23-bit 多项式 + 23-bit 舍入 + 1 步 Halley, <0.667ulp)。
// 常数/操作序逐行照抄, 勿改 (改任一中间舍入即破坏逐位一致)。
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

namespace {

constexpr std::uint32_t B1 = 715094163;
constexpr std::uint32_t B2 = 696219795;
constexpr double P0 = 1.87595182427177009643;
constexpr double P1 = -1.88497979543377169875;
constexpr double P2 = 1.621429720105354466140;
constexpr double P3 = -0.758397934778766047437;
constexpr double P4 = 0.145996192886612446982;

inline double cbrt_msun(double x)
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
    hx = static_cast<std::int32_t>(u.bits >> 32);      // EXTRACT_WORDS (LE)
    low = static_cast<std::uint32_t>(u.bits & 0xFFFFFFFFu);
    sign = static_cast<std::uint32_t>(hx & 0x80000000u);
    hx ^= static_cast<std::int32_t>(sign);
    if (static_cast<std::uint32_t>(hx) >= 0x7ff00000u) {
        return x + x;                                   // cbrt(NaN,INF) is itself
    }
    if (static_cast<std::uint32_t>(hx) < 0x00100000u) { // zero or subnormal
        if ((static_cast<std::uint32_t>(hx) | low) == 0) {
            return x;                                   // cbrt(0) is itself
        }
        u.bits = 0x4350000000000000ULL;                 // t = 2**54
        t = u.value * x;
        high = static_cast<std::uint32_t>(u.bits >> 32);
        u.bits = (static_cast<std::uint64_t>(sign | ((high & 0x7fffffffu) / 3 + B2)) << 32);
        t = u.value;
    } else {
        u.bits = (static_cast<std::uint64_t>(sign | (static_cast<std::uint32_t>(hx) / 3 + B1)) << 32);
        t = u.value;
    }

    r = (t * t) * (t / x);
    t = t * ((P0 + r * (P1 + r * P2)) + ((r * r) * r) * (P3 + r * P4));

    u.value = t;
    u.bits = (u.bits + 0x80000000ULL) & 0xffffffffc0000000ULL;
    t = u.value;

    s = t * t;          // t*t is exact
    r = x / s;          // error <= 0.5 ulps; |r| < |t|
    w = t + t;          // t+t is exact
    r = (r - t) / (w + r);   // r-t is exact; w+r ~= 3*t
    t = t + t * r;      // error <= (0.5 + 0.5/3) * ulp
    return t;
}

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

} // namespace

int main()
{
    const size_t n = 4'000'000;
    std::vector<double> lms(n);
    uint64_t s = 20260907;
    for (size_t i = 0; i < n; ++i) {
        const double r = srgb_decode(next_rand(s));
        const double g = srgb_decode(next_rand(s));
        const double b = srgb_decode(next_rand(s));
        lms[i] = M1[i % 3][0] * r + M1[i % 3][1] * g + M1[i % 3][2] * b;
    }
    size_t mismatch = 0;
    for (size_t i = 0; i < n; ++i) {
        const double a = std::cbrt(lms[i]);
        const double b2 = cbrt_msun(lms[i]);
        if (std::memcmp(&a, &b2, 8) != 0) {
            if (mismatch < 5) {
                std::printf("  x=%.17g ucrt=%.17g msun=%.17g\n", lms[i], a, b2);
            }
            ++mismatch;
        }
    }
    std::printf("LMS domain: mismatch %zu / %zu  -> %s\n", mismatch, n,
                mismatch == 0 ? "ucrt cbrt == msun cbrt (逐位)" : "不同实现");

    // 全域随机再验 (含负值/大小跨 27 个数量级)
    size_t mm2 = 0;
    for (size_t i = 0; i < n; ++i) {
        double v = next_rand(s);
        v = (v - 0.5) * 2.0 * std::pow(10.0, (double)(i % 27) - 6.0);
        const double a = std::cbrt(v);
        const double b2 = cbrt_msun(v);
        if (std::memcmp(&a, &b2, 8) != 0) {
            if (mm2 < 5) std::printf("  wide x=%.17g ucrt=%.17g msun=%.17g\n", v, a, b2);
            ++mm2;
        }
    }
    std::printf("wide domain: mismatch %zu / %zu\n", mm2, n);

    volatile double acc = 0;
    auto t0 = std::chrono::steady_clock::now();
    for (size_t i = 0; i < n; ++i) acc += std::cbrt(lms[i]);
    double d1 = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    t0 = std::chrono::steady_clock::now();
    for (size_t i = 0; i < n; ++i) acc += cbrt_msun(lms[i]);
    double d2 = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    std::printf("ucrt %.2f ns/call | msun-replica %.2f ns/call (acc %f)\n",
                d1 * 1e9 / n, d2 * 1e9 / n, acc);
    return 0;
}
