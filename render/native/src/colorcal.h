#pragma once

#include <cstdint>

namespace pixo_render_native {

// M2 colorcal 全量 Lab 内核参数。
// curveA/curveB 为可空 7 点曲线，对应 _NEUTRAL_CENTERS 顺序。
struct ColorCalParams {
    float saturation;
    float vibrance;
    float hueDeg;
    float neutralA;
    float neutralB;
    float neutralSigma;
    float skinProtect;
    float skinTrimA;
    float skinTrimB;
    const float* curveA;
    const float* curveB;
};

// 全量 Lab 路径：lab (float32 HxWx3) -> labOut (uint8 HxWx3)。
// 内部只计算一次 skinMask，供 skin_trim 与饱和度肤色保护共用。
int ApplyColorCalLab(const float* lab, std::uint8_t* labOut, int width, int height,
                     const ColorCalParams& params);

// Lab->RGB 之后的色域软压缩，与 color_cal.py 第 304~310 行一致。
int ApplyGamutSoft(const float* rgb, float* out, int width, int height, float strength);

} // namespace pixo_render_native

#ifdef __cplusplus
extern "C" {
#endif

// ctypes 可见的 C 结构（与 ColorCalParams 布局一致）。
struct PixoRenderColorCalParams {
    float saturation;
    float vibrance;
    float hueDeg;
    float neutralA;
    float neutralB;
    float neutralSigma;
    float skinProtect;
    float skinTrimA;
    float skinTrimB;
    const float* curveA;   // nullable, 7 点
    const float* curveB;   // nullable, 7 点
};

int PixoRenderColorCalApplyLab(const float* lab, std::uint8_t* labOut, int width, int height,
                           const struct PixoRenderColorCalParams* params);

int PixoRenderGamutSoft(const float* rgb, float* out, int width, int height, float strength);

#ifdef __cplusplus
}
#endif
