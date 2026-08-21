cmake_minimum_required(VERSION 3.16)
project(pixo_render_native CXX)

# pixo.render 原生热点内核 (C++20, 遵循 guanlan/AGENTS.md 编码规范)。
# 构建产物为共享库 pixo_render_native.dll/.so, 自动拷贝到 Python 包 render/_native/。
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(PIXO_RENDER_NATIVE_BUILD_TESTS "Build native C++ unit tests" OFF)
option(PIXO_RENDER_NATIVE_OPENMP "Enable OpenMP in native kernels (ON by default to meet performance gates)" ON)
option(PIXO_RENDER_NATIVE_COPY_TO_PY "Copy built DLL to render/_native/ (off for isolated test builds)" ON)

if(MSVC)
    # 与 guanlan dng_engine 一致: 静态运行时 + UTF-8 中文注释
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
    add_compile_options(/utf-8 /W4)
else()
    add_compile_options(-Wall -Wextra)
endif()

add_library(pixo_render_native SHARED
    src/abi.cpp
    src/decode.cpp
    src/hsv.cpp
    src/warm_sat.cpp
    src/colorcal.cpp
    src/refine.cpp
    src/stage_kernels.cpp
)

# MinGW 默认加 lib 前缀, 这里去掉, 统一输出 pixo_render_native.dll
set_target_properties(pixo_render_native PROPERTIES PREFIX "")

# MinGW 下静态链接 libgcc/libstdc++, 避免 DLL 依赖 libgcc_s_seh-1.dll / libstdc++-6.dll,
# 否则 Python ctypes 在未把 MinGW bin 加入 PATH 时无法加载。
if(NOT MSVC)
    target_link_options(pixo_render_native PRIVATE
        -static-libgcc
        -static-libstdc++
    )
endif()

if(PIXO_RENDER_NATIVE_OPENMP)
    find_package(OpenMP)
    if(OpenMP_CXX_FOUND)
        target_link_libraries(pixo_render_native PRIVATE OpenMP::OpenMP_CXX)
    endif()
endif()

target_include_directories(pixo_render_native PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
)

# 拷贝产物到 Python ctypes 加载目录, 保持源码/构建目录干净
if(PIXO_RENDER_NATIVE_COPY_TO_PY)
    set(PIXO_RENDER_NATIVE_PY_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../_native")
    file(MAKE_DIRECTORY "${PIXO_RENDER_NATIVE_PY_DIR}")
    add_custom_command(TARGET pixo_render_native POST_BUILD
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different "$<TARGET_FILE:pixo_render_native>" "${PIXO_RENDER_NATIVE_PY_DIR}/"
        COMMENT "Copy pixo_render_native to render/_native/"
    )
endif()

if(PIXO_RENDER_NATIVE_BUILD_TESTS)
    add_subdirectory(tests)
endif()
