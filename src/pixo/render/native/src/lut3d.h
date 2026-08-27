#pragma once

#include <cstdint>

namespace pixo_render_native {

// 3D LUT 四面体插值 (Kasson 1993) 参数。
// 与 render/core/lut3d.py 的 lookup()/tetrahedral_interp 逐位对齐:
//   lut       size^3 * 3 float, 索引序 [r, g, b] (r 最慢, b 最快, .cube 行序);
//   domainMin/domainSpan 输入窗口 (归一化 0..1 单位), span 由 Python 侧以
//             float64 计算 DOMAIN_MAX-DOMAIN_MIN 后舍入 float32 传入 —— 与
//             numpy 标量语义 ((x-dmin)/(dmax-dmin) 中 span 先 f64 后 f32) 位对齐;
//   shaper    可选 1D LUT (m, ) float, 定义在 [0,1] 均匀采样, 先于 3D 查表;
//   strength  0..1 输出与原图混合 (0=原图), float64 以对齐 Python 端 1.0-s。
struct Lut3DParams {
    const float* lut;
    int size;
    float domainMin;
    float domainSpan;
    const float* shaper;
    int shaperSize;
    double strength;
};

int ApplyLut3DF32(const float* rgb, float* out, int width, int height,
                  const Lut3DParams& params);

} // namespace pixo_render_native

#ifdef __cplusplus
extern "C" {
#endif

struct PixoRenderLut3DParams {
    const float* lut;
    int size;
    float domainMin;
    float domainSpan;
    const float* shaper;
    int shaperSize;
    double strength;
};

int PixoRenderLut3DApplyF32(const float* rgb, float* out, int width, int height,
                            const struct PixoRenderLut3DParams* params);

#ifdef __cplusplus
}
#endif
