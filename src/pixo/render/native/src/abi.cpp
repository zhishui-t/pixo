// pixo.render Native C ABI 版本导出。
//
// 首个补全版本定为 1.1.0；Python ctypes 加载后只要求 major == 1。
// 1.2.0: 新增 PixoRenderColorCalApplyLabF32 (colorcal float Lab 域内核,
//        16bit 精度改造); 旧 PixoRenderColorCalApplyLab (uint8 Lab) 保留导出。
// 1.3.0: 新增 PixoRenderLut3DApplyF32 (stylize 3D LUT 四面体插值 float 内核,
//        对齐 lut3d.lookup 的 float32 语义, 取代 u8 256³ 预计算查表路径)。
#include "abi.h"

PIXO_RENDER_NATIVE_API int PixoRenderVersion(struct PixoRenderVersion* version)
{
    if (version == nullptr) {
        return PixoRenderInvalidArgs;
    }
    version->major = 1;
    version->minor = 3;
    version->patch = 0;
    return PixoRenderOk;
}
