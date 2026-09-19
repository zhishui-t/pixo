// pixo.render Native C ABI 版本导出。
//
// 首个补全版本定为 1.1.0；Python ctypes 加载后只要求 major == 1。
// 1.2.0: 新增 PixoRenderColorCalApplyLabF32 (colorcal float Lab 域内核,
//        16bit 精度改造); 旧 PixoRenderColorCalApplyLab (uint8 Lab) 保留导出。
// 1.3.0: 新增 PixoRenderLut3DApplyF32 (stylize 3D LUT 四面体插值 float 内核,
//        对齐 lut3d.lookup 的 float32 语义, 取代 u8 256³ 预计算查表路径)。
// 1.4.0: 新增 PixoRenderSrgbToOklabF32 / PixoRenderOklabToSrgbF32 (Oklab
//        F32 平面版转换内核, 与 core/oklab.py 逐位一致, M-O1)。
// 1.5.0: 新增 PixoRenderColorCalApplyLabF32Oklch (colorcal oklch 域内核,
//        OKLab 椭圆掩码版 —— F11 实测 oklch 旁路 native 走纯 Python 路径
//        15x 慢 (8.5ms->131ms @512), 本内核堵回 native 量级)。
// 1.6.0: PixoRenderColorCalApplyLabF32Oklch 签名变化 —— 增第 7 参
//        PixoRenderSkinOklabEllipse* (椭圆常数参数化, tech_debt #18 清偿,
//        单源 core/skin.py SKIN_OKLAB_*, 编译期 constexpr 副本删除)。
//        与 1.5.0 的 6 参签名不兼容, ctypes 侧以 version >= 1.6.0 为调用门。
#include "abi.h"

PIXO_RENDER_NATIVE_API int PixoRenderVersion(struct PixoRenderVersion* version)
{
    if (version == nullptr) {
        return PixoRenderInvalidArgs;
    }
    version->major = 1;
    version->minor = 6;
    version->patch = 0;
    return PixoRenderOk;
}
