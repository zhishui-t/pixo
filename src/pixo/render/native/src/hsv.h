#pragma once

#include <cstdint>

namespace pixo_render_native {

// RGB -> HSV (float64), 与 pixo.render/core/huesat.py 的 NumPy 实现语义一致。
// rgb 为连续 (n, 3) 数组; h/s/v 为连续 n 数组。
void RgbToHsv(const double* rgb, double* h, double* s, double* v, std::int64_t pixelCount);

// HSV -> RGB (float64), 与 pixo.render/core/huesat.py 的 NumPy 实现语义一致。
void HsvToRgb(const double* h, const double* s, const double* v, double* rgb, std::int64_t pixelCount);

// RGB -> HSV (float32), 供 apply_local_warm_sat 现有 float32 路径使用。
void RgbToHsvF32(const float* rgb, float* h, float* s, float* v, std::int64_t pixelCount);

// HSV -> RGB (float32), 供 apply_local_warm_sat 现有 float32 路径使用。
void HsvToRgbF32(const float* h, const float* s, const float* v, float* rgb, std::int64_t pixelCount);

} // namespace pixo_render_native
