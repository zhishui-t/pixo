#pragma once

namespace pixo_render_native {

struct WarmSatParams {
    float satScale;
    float spotSatScale;
    float hueCenter;
    float hueHalfwidth;
    float satMin;
    float valMin;
    float coverageMax;
    float contrastSigmaFrac;
    float contrastThr;
    float contrastSoft;
};

// 应用局部暖色高光饱和度增强（broad + spot 完整路径）。
// 返回 0 表示已处理；负数为参数非法。
int ApplyLocalWarmSatF32(const float* rgb, float* out, int width, int height,
                         const WarmSatParams& params);

// float64 版本，语义与 float32 版本一致，用于高精度等价基准。
int ApplyLocalWarmSatF64(const double* rgb, double* out, int width, int height,
                         const WarmSatParams& params);

} // namespace pixo_render_native

#ifdef __cplusplus
extern "C" {
#endif

// ctypes 可见的 C 结构（与 WarmSatParams 布局一致）
struct PixoRenderWarmSatParams {
    float satScale;
    float spotSatScale;
    float hueCenter;
    float hueHalfwidth;
    float satMin;
    float valMin;
    float coverageMax;
    float contrastSigmaFrac;
    float contrastThr;
    float contrastSoft;
};

// 返回 0 成功；1 需要 Python 回退；负数为参数非法。
int PixoRenderApplyLocalWarmSat(const float* rgb, float* out, int width, int height,
                            const struct PixoRenderWarmSatParams* params);

// float64 版本：输入/输出均为 double。
int PixoRenderApplyLocalWarmSatF64(const double* rgb, double* out, int width,
                               int height,
                               const struct PixoRenderWarmSatParams* params);

#ifdef __cplusplus
}
#endif
