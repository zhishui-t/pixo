#pragma once

// pixo.render Native C ABI 统一头文件。
// 导出宏、版本结构、状态码只在 abi.h 定义，所有导出函数统一从这里取宏。

#include <cstdint>

#ifdef _WIN32
#define PIXO_RENDER_NATIVE_API extern "C" __declspec(dllexport)
#else
#define PIXO_RENDER_NATIVE_API extern "C" __attribute__((visibility("default")))
#endif

// 状态码：0 成功，1 请求 Python 回退，负数为错误。
enum PixoRenderStatus {
    PixoRenderOk = 0,
    PixoRenderFallbackRequested = 1,
    PixoRenderInvalidArgs = -1,
    PixoRenderUnsupported = -2,
    PixoRenderInternalError = -3,
};

// ABI 版本结构，ctypes 侧对应 (major, minor, patch) 三个 c_int。
struct PixoRenderVersion {
    int major;
    int minor;
    int patch;
};

// 返回当前 DLL 的 ABI 版本；version 为空返回 PixoRenderInvalidArgs。
PIXO_RENDER_NATIVE_API int PixoRenderVersion(struct PixoRenderVersion* version);
