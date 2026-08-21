#pragma once

#include <cstdint>

namespace pixo_render_native {

// M3 refine 融合内核: 饱和度保护、灰空间锐化、色度降噪、高光去色。
// 与 pixo.render/modules/refine.py 的 float32 路径对齐。

struct RefineSatProtectionParams {
    float lo;
    float hi;
};

struct RefineSharpenParams {
    float sharpen;
    const float* gray;
    const float* satProtect;
    const float* grayBlur;
};

struct RefineChromaParams {
    float chromaDenoise;
    const float* gray;
    const float* satProtect;
    const float* blurUp;
    const float* grayBlurUp;
};

struct RefineHighlightParams {
    float highlightDesat;
    const float* gray;
    const float* satProtect;
};

struct RefineApplyParams {
    float sharpen;
    float chromaDenoise;
    float highlightDesat;
    const float* gray;
    const float* satProtect;
    const float* grayBlur;
    const float* blurUp;
    const float* grayBlurUp;
};

// 计算 HSV 饱和保护权重 (与 cv2 uint8 RGB2HSV 的 S 平面一致)。
void RefineSatProtection(const float* rgb, float* satProtect, int width, int height,
                         const RefineSatProtectionParams& params);

// 灰空间 unsharp 锐化。
void RefineSharpen(const float* rgb, float* out, int width, int height,
                   const RefineSharpenParams& params);

// 1/4 降采样色度替换 (blurUp/grayBlurUp 由 Python cv2 预先算好)。
void RefineChroma(const float* rgb, float* out, int width, int height,
                  const RefineChromaParams& params);

// 高光去色。
void RefineHighlight(const float* rgb, float* out, int width, int height,
                     const RefineHighlightParams& params);

// 规格中的一次融合内核 (sharpen -> chroma -> highlight)。
void RefineApply(const float* rgb, float* out, int width, int height,
                 const RefineApplyParams& params);

// gamma 域暖色饱和/色相补强 (in-place, uint8 HSV)。
void WarmSatGammaU8(std::uint8_t* hsv, int width, int height,
                    float gain, float hueShiftDeg);

} // namespace pixo_render_native

#ifdef __cplusplus
extern "C" {
#endif

struct PixoRenderRefineSatProtectionParams {
    float lo;
    float hi;
};

struct PixoRenderRefineSharpenParams {
    float sharpen;
    const float* gray;
    const float* satProtect;
    const float* grayBlur;
};

struct PixoRenderRefineChromaParams {
    float chromaDenoise;
    const float* gray;
    const float* satProtect;
    const float* blurUp;
    const float* grayBlurUp;
};

struct PixoRenderRefineHighlightParams {
    float highlightDesat;
    const float* gray;
    const float* satProtect;
};

struct PixoRenderRefineApplyParams {
    float sharpen;
    float chromaDenoise;
    float highlightDesat;
    const float* gray;
    const float* satProtect;
    const float* grayBlur;
    const float* blurUp;
    const float* grayBlurUp;
};

struct PixoRenderWarmGammaParams {
    float gain;
    float hueShiftDeg;
};

int PixoRenderRefineSatProtection(const float* rgb, float* satProtect, int width, int height,
                              const struct PixoRenderRefineSatProtectionParams* params);
int PixoRenderRefineSharpen(const float* rgb, float* out, int width, int height,
                        const struct PixoRenderRefineSharpenParams* params);
int PixoRenderRefineChroma(const float* rgb, float* out, int width, int height,
                       const struct PixoRenderRefineChromaParams* params);
int PixoRenderRefineHighlight(const float* rgb, float* out, int width, int height,
                          const struct PixoRenderRefineHighlightParams* params);
int PixoRenderRefineApply(const float* rgb, float* out, int width, int height,
                      const struct PixoRenderRefineApplyParams* params);
int PixoRenderWarmSatGammaU8(std::uint8_t* hsv, int width, int height,
                         const struct PixoRenderWarmGammaParams* params);

#ifdef __cplusplus
}
#endif
