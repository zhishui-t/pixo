// 3D LUT 四面体插值 float 内核 (Kasson 1993), v1.3.0。
//
// 与 render/core/lut3d.py 的 lookup() 路径逐位对齐 (同一算式, 同一运算序),
// 差异实测 0 (见 tests/unit/test_lut_native.py 等价实测)。无状态设计:
// LUT 表/shaper 每次由调用方传指针, 缓存归 Python 侧管理。
//
// ---- 精度模型 (对齐 numpy 参考的真实语义) ----
//
// numpy 版 `f = pos - i0` (float32 数组 - int32 数组) 按 NEP 50 数组-数组
// 提升规则升为 **float64**, 因此权重 w 与最终 4 顶点 MAC 全程 float64,
// 仅在最后 .astype(np.float32) 舍入一次。本内核同样:
//   f/w/MAC 以 double 计算 (顶点值从 float32 精确升 double),
//   MAC 求值序 ((c000*w0 + v1*w1) + v2*w2) + c111*w3 与 numpy 表达式一致,
//   结果舍入 float32 一次, 再做 strength 混合 (float32 域)。
// 1D shaper 同理: `frac = pos - i0` 也是 f64, 线性插值 MAC 在 f64 域。
//
// ---- Python 算式 → C++ 的映射说明 ----
//
// Python lut3d.tetrahedral_interp 用 np.sort 得 (fmin,fmid,fmax) 权重、
// np.argmax/np.argmin 选四面体棱方向; 本内核不用排序, 直接比较展开:
//
//   max_axis = np.argmax(f)  # 首个最大值所在轴 (0=r,1=g,2=b)
//     → (fr >= fg) ? ((fr >= fb) ? 0 : 2) : ((fg >= fb) ? 1 : 2)
//   min_axis = np.argmin(f)  # 首个最小值所在轴
//     → (fr <= fg) ? ((fr <= fb) ? 0 : 2) : ((fg <= fb) ? 1 : 2)
//   (>= / <= 比较保证与 argmax/argmin "并列取先" 的平局语义一致)
//
// 由此 (max_axis, min_axis) 恰好枚举 fr/fg/fb 的 6 种排序 (Kasson 四面体
// 分解), 顶点取值与 numpy 版一致 (v1/v2 的 0/1 指示乘法与直接选取在 IEEE
// 下逐位等价 —— 乘 1 恒等, 乘 0 得 0):
//
//   排序            max,min   四顶点 (c000 → v1 → v2 → c111)
//   r>=g>=b         r, b      c000, c100(+r),     c110(+r+g), c111
//   r>=b>=g         r, g      c000, c100(+r),     c101(+r+b), c111
//   g>=r>=b         g, b      c000, c010(+g),     c110(+r+g), c111
//   g>=b>=r         g, r      c000, c010(+g),     c011(+g+b), c111
//   b>=r>=g         b, g      c000, c001(+b),     c101(+r+b), c111
//   b>=g>=r         b, r      c000, c001(+b),     c011(+g+b), c111
//
//   v1 = c000 在最大分量轴进 i1 = min(i0+1, size-1) 一步;
//   v2 = c111 在最小分量轴退回 i0 一步 (等价 c111 减该轴 i1-i0 步 ——
//        上边界 i0 = size-1 时 i1 = i0, 直接 ±1 步会越界/错格点)。
//   权重 (与排序轴无关, 只依赖 f 的升序值):
//     w0 = 1-fmax, w1 = fmax-fmid, w2 = fmid-fmin, w3 = fmin
//
// 域缩放/shaper 与 Python _prepare_input/_interp1d 相同:
//   t = clip((v - dmin) / dspan, 0, 1)  [float32: 标量弱类型不提升];
//   t = shaper 线性插值 (可选, f64 MAC 后舍入 f32);
//   pos = t * (size-1); clamp [0, size-1]; i0 = floor(pos), f = pos - i0
//   [f64], i1 = min(i0+1, size-1)。
#include "lut3d.h"

#include "abi.h"

#include <algorithm>
#include <cmath>
#include <cstddef>

namespace pixo_render_native {

namespace {

// 三值排序 (等价 np.sort 的值, 与并列元的先后无关 —— 权重只依赖值)。
inline void sort3(double a, double b, double c, double& lo, double& mid,
                  double& hi)
{
    if (a <= b) {
        if (b <= c) { lo = a; mid = b; hi = c; }
        else if (a <= c) { lo = a; mid = c; hi = b; }
        else { lo = c; mid = a; hi = b; }
    } else {
        if (a <= c) { lo = b; mid = a; hi = c; }
        else if (b <= c) { lo = b; mid = c; hi = a; }
        else { lo = c; mid = b; hi = a; }
    }
}

// 单通道 0..1 域缩放 + 可选 1D shaper (对齐 _prepare_input + _interp1d)。
// 域缩放在 float32 (Python 标量弱类型不提升 dtype); shaper 的 frac 与
// 线性插值 MAC 在 double (pos - i0 的 int32 数组提升), 结果舍入 float32。
inline float shape_channel(float v, float dmin, float dspan,
                           const float* shaper, int shaperSize)
{
    float t = (v - dmin) / dspan;
    t = std::clamp(t, 0.0f, 1.0f);
    if (shaper == nullptr) {
        return t;
    }
    // pos = t * m 在 float32 (弱 int 标量不提升), frac 与插值 MAC 在 double
    // (pos - i0 的 int32 数组提升), 与 _interp1d 逐位一致。posf ∈ [0, m]
    // 非负, 截断取整 == floor (位等价, 省 floorps)。
    const float posf = t * static_cast<float>(shaperSize - 1);
    const double pos = static_cast<double>(posf);
    int i0 = std::clamp(static_cast<int>(posf), 0, shaperSize - 1);
    int i1 = std::min(i0 + 1, shaperSize - 1);
    const double frac = pos - static_cast<double>(i0);
    const double sv = static_cast<double>(shaper[i0]) * (1.0 - frac)
                    + static_cast<double>(shaper[i1]) * frac;
    return static_cast<float>(sv);}

} // namespace

int ApplyLut3DF32(const float* rgb, float* out, int width, int height,
                  const Lut3DParams& params)
{
    if (rgb == nullptr || out == nullptr || width <= 0 || height <= 0 ||
        params.lut == nullptr || params.size < 2 ||
        params.domainSpan <= 0.0f || !std::isfinite(params.domainSpan) ||
        (params.shaper != nullptr && params.shaperSize < 2)) {
        return -1;
    }
    const int n = params.size;
    const int s = n - 1;
    const float sf = static_cast<float>(s);
    const float* lut = params.lut;
    const float* shaper = params.shaper;
    const int shaperSize = params.shaperSize;
    const float dmin = params.domainMin;
    const float dspan = params.domainSpan;
    // 混合权重 (double 计算再舍入, 对齐 Python 1.0-strength 的 f64 标量语义)。
    const float oneMinusS = static_cast<float>(1.0 - params.strength);
    const float sMul = static_cast<float>(params.strength);
    // strength==1 时混合退化为直通 (in*0 + res*1 == res 位等价), 免 2 次乘加。
    const bool passthrough = (oneMinusS == 0.0f && sMul == 1.0f);

    // 轴步长 (格点索引 → lut 线性下标): r 最慢, b 最快。
    const std::ptrdiff_t stepR = static_cast<std::ptrdiff_t>(n) * n * 3;
    const std::ptrdiff_t stepG = static_cast<std::ptrdiff_t>(n) * 3;
    const std::ptrdiff_t stepB = 3;

    const long long pixelCount = static_cast<long long>(width) * height;
#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (long long i = 0; i < pixelCount; ++i) {
        const float* in = rgb + i * 3;
        float* o = out + i * 3;

        float tr = shape_channel(in[0], dmin, dspan, shaper, shaperSize);
        float tg = shape_channel(in[1], dmin, dspan, shaper, shaperSize);
        float tb = shape_channel(in[2], dmin, dspan, shaper, shaperSize);

        const float pr = std::clamp(tr * sf, 0.0f, sf);
        const float pg = std::clamp(tg * sf, 0.0f, sf);
        const float pb = std::clamp(tb * sf, 0.0f, sf);

        // pr/pg/pb ∈ [0, s] 非负, 截断取整 == floor (位等价)。
        int ir0 = std::clamp(static_cast<int>(pr), 0, s);
        int ig0 = std::clamp(static_cast<int>(pg), 0, s);
        int ib0 = std::clamp(static_cast<int>(pb), 0, s);
        int ir1 = std::min(ir0 + 1, s);
        int ig1 = std::min(ig0 + 1, s);
        int ib1 = std::min(ib0 + 1, s);

        // f = pos - i0: numpy 中 f32 数组 - int32 数组提升 f64, 此处同步。
        const double fr = static_cast<double>(pr) - static_cast<double>(ir0);
        const double fg = static_cast<double>(pg) - static_cast<double>(ig0);
        const double fb = static_cast<double>(pb) - static_cast<double>(ib0);

        // 首个最大/最小分量轴 (对齐 np.argmax/np.argmin 并列取先)。
        const int maxAxis = (fr >= fg) ? ((fr >= fb) ? 0 : 2)
                                       : ((fg >= fb) ? 1 : 2);
        const int minAxis = (fr <= fg) ? ((fr <= fb) ? 0 : 2)
                                       : ((fg <= fb) ? 1 : 2);

        double fmin, fmid, fmax;
        sort3(fr, fg, fb, fmin, fmid, fmax);
        const double w0 = 1.0 - fmax;
        const double w1 = fmax - fmid;
        const double w2 = fmid - fmin;
        const double w3 = fmin;

        const float* c000 = lut + (static_cast<std::ptrdiff_t>(ir0) * n * n
                                   + static_cast<std::ptrdiff_t>(ig0) * n
                                   + ib0) * 3;
        const float* c111 = lut + (static_cast<std::ptrdiff_t>(ir1) * n * n
                                   + static_cast<std::ptrdiff_t>(ig1) * n
                                   + ib1) * 3;
        const std::ptrdiff_t dR = static_cast<std::ptrdiff_t>(ir1 - ir0);
        const std::ptrdiff_t dG = static_cast<std::ptrdiff_t>(ig1 - ig0);
        const std::ptrdiff_t dB = static_cast<std::ptrdiff_t>(ib1 - ib0);
        const std::ptrdiff_t maxStep = maxAxis == 0 ? dR * stepR
                                       : maxAxis == 1 ? dG * stepG : dB * stepB;
        const std::ptrdiff_t minStep = minAxis == 0 ? dR * stepR
                                       : minAxis == 1 ? dG * stepG : dB * stepB;
        const float* v1 = c000 + maxStep;
        const float* v2 = c111 - minStep;

        // MAC 在 double 域 (对齐 numpy f64 提升), 求值序左结合, 末尾舍入一次。
        const float r0 = static_cast<float>(
            (static_cast<double>(c000[0]) * w0 + static_cast<double>(v1[0]) * w1)
            + static_cast<double>(v2[0]) * w2 + static_cast<double>(c111[0]) * w3);
        const float r1 = static_cast<float>(
            (static_cast<double>(c000[1]) * w0 + static_cast<double>(v1[1]) * w1)
            + static_cast<double>(v2[1]) * w2 + static_cast<double>(c111[1]) * w3);
        const float r2 = static_cast<float>(
            (static_cast<double>(c000[2]) * w0 + static_cast<double>(v1[2]) * w1)
            + static_cast<double>(v2[2]) * w2 + static_cast<double>(c111[2]) * w3);
        if (passthrough) {
            o[0] = r0;
            o[1] = r1;
            o[2] = r2;
        } else {
            o[0] = in[0] * oneMinusS + r0 * sMul;
            o[1] = in[1] * oneMinusS + r1 * sMul;
            o[2] = in[2] * oneMinusS + r2 * sMul;
        }
    }
    return 0;
}

} // namespace pixo_render_native

// ---- C ABI 导出 ----

PIXO_RENDER_NATIVE_API int PixoRenderLut3DApplyF32(
    const float* rgb, float* out, int width, int height,
    const struct PixoRenderLut3DParams* params)
{
    if (params == nullptr) {
        return -1;
    }
    pixo_render_native::Lut3DParams p;
    p.lut = params->lut;
    p.size = params->size;
    p.domainMin = params->domainMin;
    p.domainSpan = params->domainSpan;
    p.shaper = params->shaper;
    p.shaperSize = params->shaperSize;
    p.strength = params->strength;
    return pixo_render_native::ApplyLut3DF32(rgb, out, width, height, p);
}

