#pragma once

#include <cstdint>

namespace pixo_render_native {

// M2 colorcal 全量 Lab 内核参数。
// curveA/curveB 为可空 7 点曲线，对应 _NEUTRAL_CENTERS 顺序。
// 曲线值为 a/b 偏移量 (Lab 单位) —— a/b 轴在 uint8 Lab 域 (中心 128) 与
// float Lab 域 (中心 0) 只差常数偏移, 单位长度相同, 两套内核共用同一参数
// 结构与曲线值; 仅亮度节点域不同 (见 ApplyColorCalLabF32 注释)。
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

// 全量 Lab 路径（旧, uint8 Lab 域）：lab (float32 HxWx3, L∈[0,255], a/b 中心
// 128, 即 cv2 uint8 Lab 坐标的 float 视图) -> labOut (uint8 HxWx3, 截断 cast)。
// 16bit 精度改造后生产 stage 不再调用 (三段 u8 量化合计 0.81 ΔE76,
// 见 docs/metrics/u8_midpoint_precision.md); 仅为 ABI 向后兼容与
// scripts/measure_u8_precision.py 保真自检保留导出。
// 内部只计算一次 skinMask，供 skin_trim 与饱和度肤色保护共用。
int ApplyColorCalLab(const float* lab, std::uint8_t* labOut, int width, int height,
                     const ColorCalParams& params);

// 全量 Lab 路径（新, float Lab 域）：lab (float32 HxWx3) -> labOut (float32
// HxWx3), 即 cv2 float Lab 坐标: L∈[0,100], a/b 中心 0 (无 u8 中转)。
// 与 uint8 Lab 域的换算: L_f = L_u8 * 100/255; a_f = a_u8 - 128; b_f = b_u8 - 128。
// 算法与 ApplyColorCalLab 逐式对应, 子步骤常量已换域:
//   - 肤色椭圆中心 (140,150)_u8 -> (12,22)_f (偏移 -128); 半径 22/14、倾角
//     0.65、软边 0.25 不变 (a/b 轴两域单位相同);
//   - 色度 C 两域同单位同值 (|a-128,b-128|_u8 == |a,b|_f), 中性权重平台
//     plateau=12 / sigma、vibrance 参考色度 128、全部 a/b 偏移量不变;
//   - 曲线插值亮度节点 = uint8 域 _NEUTRAL_CENTERS [8..248] * 100/255;
//   - 色相旋转绕中心 0 (uint8 域绕 128);
//   - 输出限幅 [0,100]/[-128,127] 等价 uint8 域的 [0,255] 限幅 (float 出,
//     无截断)。
int ApplyColorCalLabF32(const float* lab, float* labOut, int width, int height,
                        const ColorCalParams& params);

// OKLab 肤色椭圆常数 (v1.6.0 参数化, tech_debt #18 清偿)。
// **单源在 Python 侧 core/skin.py SKIN_OKLAB_***, 本结构仅承接运行时传入,
// 内核不再持有编译期副本。数值纪律 (对齐语义随字段携带):
//   - centerA/centerB: np.float32(...) 舍入后展宽的 f64 (Python 侧完成舍入,
//     native 按 f64 直收 —— 椭圆距离的 da/db 减法用该值);
//   - cosAngle/sinAngle: Python 侧 np.cos/np.sin 的 f64 结果直传 (内核不调
//     libm cos/sin, 消除跨实现 1 ULP);
//   - major/minor: Python float (f64) 直传;
//   - softBand: **float** (f32) —— smoothstep 的 (d-1)/band 除法按 f32 语义
//     (与 numpy NEP50 的 f32 数组/弱标量除一致)。
struct SkinOklabEllipse {
    double centerA;
    double centerB;
    double cosAngle;
    double sinAngle;
    double major;
    double minor;
    float softBand;
};

// oklch 域全量内核 (v1.5.0; v1.6.0 椭圆参数化): 与 ApplyColorCalLabF32
// 逐式对应, 唯一差异 = 肤色掩码源。掩码 = OKLab 椭圆 SkinMaskOklab
// (ellipse, 原始 gamma sRGB 像素), 与 core/skin.py::skin_mask_oklab 逐位
// 对齐 (cbrt 用 msun 复刻, 与 ucrt/np.cbrt 差 <=1 ULP f64, 经 f64->f32
// 舍入后实际逐位一致 —— 见 colorcal.cpp CbrtFast 注释与
// test_native_colorcal_oklch.py)。
// rgb = 校正前 gamma sRGB float32 (H,W,3) (掩码取原始像素口径); lab/labOut
// 仍为 cv2 float Lab 坐标 (校准域不换, 同 Python oklch 分支结构)。
int ApplyColorCalLabF32Oklch(const float* lab, const float* rgb, float* labOut,
                             int width, int height, const ColorCalParams& params,
                             const SkinOklabEllipse& ellipse);

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

// float Lab 域内核 (float32 Lab 入/出)。params 结构与上面同一布局; 曲线
// 亮度节点在 float L∈[0,100] 域解释 (见 ApplyColorCalLabF32)。
int PixoRenderColorCalApplyLabF32(const float* lab, float* labOut, int width, int height,
                              const struct PixoRenderColorCalParams* params);

// ctypes 可见的 OKLab 椭圆常数 (与 SkinOklabEllipse 同布局; 字段语义/精度
// 纪律见上方 SkinOklabEllipse 注释 —— 单源 core/skin.py, Python 侧变换后传入)。
struct PixoRenderSkinOklabEllipse {
    double centerA;
    double centerB;
    double cosAngle;
    double sinAngle;
    double major;
    double minor;
    float softBand;
};

// oklch 域内核 (v1.5.0 引入; **v1.6.0 签名变化**: 增第 7 参 ellipse,
// 签名与 1.5.0 不兼容 —— ctypes 侧以 version >= 1.6.0 为调用门)。
// rgb = 校正前 gamma sRGB f32 (H,W,3) 供 OKLab 椭圆掩码; ellipse 常数
// 从 Python 单源传入; 其余契约同 PixoRenderColorCalApplyLabF32。
int PixoRenderColorCalApplyLabF32Oklch(const float* lab, const float* rgb,
                                   float* labOut, int width, int height,
                                   const struct PixoRenderColorCalParams* params,
                                   const struct PixoRenderSkinOklabEllipse* ellipse);

int PixoRenderGamutSoft(const float* rgb, float* out, int width, int height, float strength);

#ifdef __cplusplus
}
#endif
