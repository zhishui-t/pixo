#pragma once

#include <cstdint>

namespace pixo_render_native {

// Oklab 转换内核 (设计 OWN_PIPELINE_STAGE1_DESIGN.md §2.4, M-O1)。
// Python 参考实现为 pixo.render/core/oklab.py, 两者逐位一致 (bit-exact):
//   - 矩阵常数照抄 core/oklab.py 的冻结字面值 (正向抄 Ottosson 2020 原文,
//     逆向为正向常数的数值逆冻结 12 位, 勿现算/勿抄原文公布逆);
//   - 全程 float64 计算, 逐分量加权和 (与 numpy 表达式同操作数顺序、同结合);
//   - pow/cbrt 走 CRT (api-ms-win-crt-math -> ucrtbase), 与 numpy 同一实现,
//     立方必须写 pow(x, 3.0), 三次连乘 x*x*x 与 numpy x**3 有 1/4 输入不同。
// dtype 契约 (设计 §1.3): "F32 平面版"指 sRGB 域数据为 float32; L/a/b 平面
// 恒为 float64 (内部工作域) —— lab 若以 f32 交接, 量化噪声经近黑区 gamma
// 斜率 12.92 放大, 往返 ~7e-7, 超 1e-7 验收线。

// gamma sRGB float32 (H,W,3 交错) -> Oklab float64 平面 L/a/b (各 HxW)。
// 与 core/oklab.srgb_to_oklab 逐位一致; 负输入按 0 解码 (同 core 侧 clip)。
struct SrgbToOklabParams {
    const float* rgb;      // gamma sRGB [0,1], 行主序, 每像素 3 float 交错
    int width;
    int height;
    int stride;            // rgb 行距 (float 元素数, >= width * 3)
    double* l;             // 输出 L 平面 (H, planeStride)
    double* a;             // 输出 a 平面
    double* b;             // 输出 b 平面
    int planeStride;       // L/a/b 行距 (double 元素数, >= width)
};

// Oklab float64 平面 L/a/b -> gamma sRGB float32 (H,W,3 交错)。
// 与 core/oklab.oklab_to_srgb 逐位一致: linear 域 clip 到 [0,1] 后编码,
// 末端一次性舍入 float32 (同 numpy astype)。
struct OklabToSrgbParams {
    const double* l;       // L 平面 (H, planeStride)
    const double* a;       // a 平面
    const double* b;       // b 平面
    int planeStride;       // L/a/b 行距 (double 元素数, >= width)
    float* rgb;            // 输出 gamma sRGB, 行主序, 3 float 交错
    int width;
    int height;
    int stride;            // rgb 行距 (float 元素数, >= width * 3)
};

// 返回 0 成功, -1 参数非法 (空指针/非正宽高/stride 不足)。
int SrgbToOklabF32(const SrgbToOklabParams& params);
int OklabToSrgbF32(const OklabToSrgbParams& params);

} // namespace pixo_render_native

#ifdef __cplusplus
extern "C" {
#endif

// C ABI (ctypes 加载): 字段与上方同名 namespace 结构一致, 风格对齐
// PixoRenderMatrixApply3Params (指针 + 宽高 + stride)。
struct PixoRenderSrgbToOklabParams {
    const float* rgb;
    int width;
    int height;
    int stride;
    double* l;
    double* a;
    double* b;
    int planeStride;
};

struct PixoRenderOklabToSrgbParams {
    const double* l;
    const double* a;
    const double* b;
    int planeStride;
    float* rgb;
    int width;
    int height;
    int stride;
};

// 导出宏 PIXO_RENDER_NATIVE_API 在 abi.h 定义, 只用于 .cpp 侧定义;
// 头文件声明与 stage_kernels.h 同风格, 不带宏。
int PixoRenderSrgbToOklabF32(const struct PixoRenderSrgbToOklabParams* params);

int PixoRenderOklabToSrgbF32(const struct PixoRenderOklabToSrgbParams* params);

#ifdef __cplusplus
}
#endif
