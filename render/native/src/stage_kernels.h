#pragma once

#include <cstdint>

namespace pixo_render_native {

// P1 预览 stage 内核参数与函数（与 pixo.render/modules/*.py 的 float32 路径对齐）。

struct ExposureParams {
    float ev;
    float rolloffKnee;
    float vignette;
};

struct MatrixApply3Params {
    const float* matrix;  // 9 floats 行主序；out = rgb @ matrix.T
};

struct ToneApplyLut1DParams {
    const float* lut;     // 0..1 均匀 LUT
    int lutSize;
};

struct ClarityParams {
    float strength;
    const float* gray;       // HxW
    const float* smallBlur;  // HxW
    const float* largeBlur;  // HxW
};

int ApplyExposure(const float* rgb, float* out, int width, int height,
                  const ExposureParams& params);

int ApplyMatrix3(const float* rgb, float* out, int width, int height,
                 const MatrixApply3Params& params);

int ApplyToneLut1D(const float* rgb, float* out, int width, int height,
                   const ToneApplyLut1DParams& params);

int ApplyClarity(const float* rgb, float* out, int width, int height,
                 const ClarityParams& params);

} // namespace pixo_render_native

#ifdef __cplusplus
extern "C" {
#endif

struct PixoRenderExposureParams {
    float ev;
    float rolloffKnee;
    float vignette;
};

struct PixoRenderMatrixApply3Params {
    const float* matrix;
};

struct PixoRenderToneApplyLut1DParams {
    const float* lut;
    int lutSize;
};

struct PixoRenderClarityParams {
    float strength;
    const float* gray;
    const float* smallBlur;
    const float* largeBlur;
};

int PixoRenderExposureApply(const float* rgb, float* out, int width, int height,
                        const struct PixoRenderExposureParams* params);

int PixoRenderMatrixApply3(const float* rgb, float* out, int width, int height,
                       const struct PixoRenderMatrixApply3Params* params);

int PixoRenderToneApplyLut1D(const float* rgb, float* out, int width, int height,
                         const struct PixoRenderToneApplyLut1DParams* params);

int PixoRenderClarityApply(const float* rgb, float* out, int width, int height,
                       const struct PixoRenderClarityParams* params);

#ifdef __cplusplus
}
#endif
