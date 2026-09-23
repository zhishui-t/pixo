// spike (r10): ucrt pow/cbrt 单调用成本 + Newton cbrt 与 std::cbrt 逐位一致性探测。
// 问题: 掩码 56% 成本在 cbrt (58ns/次, 比 pow 还慢) —— 若 ucrt cbrt 可被
// 快速 Newton 版逐位复现, 掩码成本可腰斩, 性能验收 (<=2x hsv native) 落袋。
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

namespace {

inline uint64_t rdtsc_like_seed() { return 20260907ULL; }

inline double next_rand(uint64_t& s)
{
    s ^= s << 13; s ^= s >> 7; s ^= s << 17;
    return (double)(s >> 11) / 9007199254740992.0;   // [0,1) 53bit
}

// ---- Newton cbrt 候选: 位黑客种子 + 4 轮 Newton + 正确舍入修正 ----
// 种子: 指数 /3 + 线性修正; Newton 收敛到 ~1ulp 后, 用一次邻域表决取
// 与精确值最近的双精度 (依赖 (t+eps)^3 与 x 的比较, 全 double 可判)。
inline double cbrt_newton(double x)
{
    if (x == 0.0 || !std::isfinite(x)) return std::cbrt(x);   // 委托边缘
    const int neg = std::signbit(x);
    double ax = std::fabs(x);
    // 位黑客种子: 指数域 /3 (逼近 2^(k/3)), 尾数一阶修正
    std::uint64_t bits;
    std::memcpy(&bits, &ax, 8);
    const std::uint64_t hi = bits / 3 + 2 * 0x0000000000000000ULL
                             + 6819030192609640192ULL / 3;   // ~0x1FF7800000000000/3 近似
    std::uint64_t seedBits = bits / 3 + 6819029265515443200ULL; // 常数见下推导备注
    (void)hi;
    double t;
    std::memcpy(&t, &seedBits, 8);
    // Newton: t = t - (t^3 - ax)/(3 t^2) = (2t + ax/t^2)/3
    for (int i = 0; i < 4; ++i) {
        t = (2.0 * t + ax / (t * t)) / 3.0;
    }
    // 正确舍入表决: 检查 t 与 nextafter 邻域谁的立方更接近 ax
    double lo = t, hiV = t;
    // Newton 已到 ~1ulp; 检查 t 和相邻两个双精度
    double c1 = t;
    double c0 = std::nextafter(t, 0.0);
    double c2 = std::nextafter(t, 2.0);
    double d1 = std::fabs(c1 * c1 * c1 - ax);
    double d0 = std::fabs(c0 * c0 * c0 - ax);
    double d2 = std::fabs(c2 * c2 * c2 - ax);
    double best = c1;
    if (d0 < d1) best = c0;
    if (d2 < d1 && d2 < d0) best = c2;
    (void)lo; (void)hiV;
    return neg ? -best : best;
}

} // namespace

int main()
{
    const size_t n = 4'000'000;
    std::vector<double> xs(n), pows(n), cbs(n), news(n);
    uint64_t s = rdtsc_like_seed();
    // 语料: 掩码真实输入分布 —— LMS 值 (≈ [0, 1.05] 线性 sRGB 的凸组合)
    for (size_t i = 0; i < n; ++i) {
        double c = next_rand(s);
        xs[i] = c * 1.05;
    }

    // 逐位一致性: Newton vs std::cbrt
    size_t mismatch = 0;
    double worstRel = 0;
    for (size_t i = 0; i < n; ++i) {
        cbs[i] = std::cbrt(xs[i]);
        news[i] = cbrt_newton(xs[i]);
        if (std::memcmp(&cbs[i], &news[i], 8) != 0) {
            ++mismatch;
            double rel = std::fabs(news[i] - cbs[i]) / cbs[i];
            if (rel > worstRel) worstRel = rel;
        }
    }
    std::printf("cbrt newton vs std: mismatch %zu / %zu, worst rel %.3e\n",
                mismatch, n, worstRel);

    // 计时
    auto bench = [&](const char* name, auto fn) {
        volatile double acc = 0;
        auto t0 = std::chrono::steady_clock::now();
        for (size_t i = 0; i < n; ++i) acc += fn(xs[i]);
        double dt = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - t0).count();
        std::printf("%-12s %7.2f ns/call (acc %f)\n", name, dt * 1e9 / n, acc);
    };
    bench("std::cbrt", [](double v) { return std::cbrt(v); });
    bench("newton", [](double v) { return cbrt_newton(v); });
    bench("std::pow2.4", [](double v) { return std::pow(v, 2.4); });
    // pow 语料换到 decode 定义域 [0.052,1]
    for (size_t i = 0; i < n; ++i) xs[i] = 0.052 + next_rand(s) * 0.948;
    bench("pow(dom)", [](double v) { return std::pow(v, 2.4); });
    return 0;
}
