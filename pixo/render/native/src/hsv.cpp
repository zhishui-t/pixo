// pixo.render 原生热点内核: RGB <-> HSV。
//
// 编码规范遵循 guanlan/AGENTS.md:
//   - 变量/函数小驼峰, 类大驼峰, 常量 constexpr 且不加 k 前缀
//   - K&R 括号: 函数体左括号换行, 控制语句左括号同行
//   - 行宽 <= 120, 中文注释
//   - namespace 全小写
#include "hsv.h"

#include "abi.h"

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace pixo_render_native {

namespace {

constexpr double HueRange = 360.0;
constexpr double SectorCount = 6.0;

// 与 Python `%` 一致的非负取模。
double Modulo(double value, double range)
{
    double result = std::fmod(value, range);
    if (result < 0.0) {
        result += range;
    }
    return result;
}

} // namespace

void RgbToHsv(const double* rgb, double* h, double* s, double* v, std::int64_t pixelCount)
{
    for (std::int64_t i = 0; i < pixelCount; ++i) {
        const double r = rgb[i * 3 + 0];
        const double g = rgb[i * 3 + 1];
        const double b = rgb[i * 3 + 2];
        const double maxValue = std::max(r, std::max(g, b));
        const double minValue = std::min(r, std::min(g, b));
        const double delta = maxValue - minValue;
        double hue = 0.0;
        double saturation = 0.0;
        if (delta > 0.0) {
            const double deltaInv = 1.0 / delta;
            saturation = (maxValue > 0.0) ? delta / maxValue : 0.0;
            double segment = 0.0;
            if (maxValue == r) {
                segment = Modulo((g - b) * deltaInv, SectorCount);
            } else if (maxValue == g) {
                segment = (b - r) * deltaInv + 2.0;
            } else {
                segment = (r - g) * deltaInv + 4.0;
            }
            hue = Modulo(60.0 * segment, HueRange);
        }
        h[i] = hue;
        s[i] = saturation;
        v[i] = maxValue;
    }
}

void HsvToRgb(const double* h, const double* s, const double* v, double* rgb, std::int64_t pixelCount)
{
    for (std::int64_t i = 0; i < pixelCount; ++i) {
        const double hue = Modulo(h[i], HueRange);
        const double saturation = s[i];
        const double value = v[i];
        const double sector = hue / 60.0;
        const std::int64_t sectorIndex = static_cast<std::int64_t>(std::floor(sector)) % 6;
        const double fraction = sector - std::floor(sector);
        const double p = value * (1.0 - saturation);
        const double q = value * (1.0 - fraction * saturation);
        const double t = value * (1.0 - (1.0 - fraction) * saturation);
        double r = 0.0;
        double g = 0.0;
        double b = 0.0;
        switch (sectorIndex) {
            case 0:
                r = value; g = t; b = p;
                break;
            case 1:
                r = q; g = value; b = p;
                break;
            case 2:
                r = p; g = value; b = t;
                break;
            case 3:
                r = p; g = q; b = value;
                break;
            case 4:
                r = t; g = p; b = value;
                break;
            default:
                r = value; g = p; b = q;
                break;
        }
        rgb[i * 3 + 0] = r;
        rgb[i * 3 + 1] = g;
        rgb[i * 3 + 2] = b;
    }
}

void RgbToHsvF32(const float* rgb, float* h, float* s, float* v, std::int64_t pixelCount)
{
    for (std::int64_t i = 0; i < pixelCount; ++i) {
        const float r = rgb[i * 3 + 0];
        const float g = rgb[i * 3 + 1];
        const float b = rgb[i * 3 + 2];
        const float maxValue = std::max(r, std::max(g, b));
        const float minValue = std::min(r, std::min(g, b));
        const float delta = maxValue - minValue;
        float hue = 0.0f;
        float saturation = 0.0f;
        if (delta > 0.0f) {
            const float deltaInv = 1.0f / delta;
            saturation = (maxValue > 0.0f) ? delta / maxValue : 0.0f;
            float segment = 0.0f;
            if (maxValue == r) {
                segment = static_cast<float>(Modulo(static_cast<double>((g - b) * deltaInv), SectorCount));
            } else if (maxValue == g) {
                segment = (b - r) * deltaInv + 2.0f;
            } else {
                segment = (r - g) * deltaInv + 4.0f;
            }
            hue = static_cast<float>(Modulo(static_cast<double>(60.0f * segment), HueRange));
        }
        h[i] = hue;
        s[i] = saturation;
        v[i] = maxValue;
    }
}

void HsvToRgbF32(const float* h, const float* s, const float* v, float* rgb, std::int64_t pixelCount)
{
    for (std::int64_t i = 0; i < pixelCount; ++i) {
        const double hue = Modulo(static_cast<double>(h[i]), HueRange);
        const double saturation = static_cast<double>(s[i]);
        const double value = static_cast<double>(v[i]);
        const double sector = hue / 60.0;
        const std::int64_t sectorIndex = static_cast<std::int64_t>(std::floor(sector)) % 6;
        const double fraction = sector - std::floor(sector);
        const float p = static_cast<float>(value * (1.0 - saturation));
        const float q = static_cast<float>(value * (1.0 - fraction * saturation));
        const float t = static_cast<float>(value * (1.0 - (1.0 - fraction) * saturation));
        float r = 0.0f;
        float g = 0.0f;
        float b = 0.0f;
        switch (sectorIndex) {
            case 0:
                r = static_cast<float>(value); g = t; b = p;
                break;
            case 1:
                r = q; g = static_cast<float>(value); b = p;
                break;
            case 2:
                r = p; g = static_cast<float>(value); b = t;
                break;
            case 3:
                r = p; g = q; b = static_cast<float>(value);
                break;
            case 4:
                r = t; g = p; b = static_cast<float>(value);
                break;
            default:
                r = static_cast<float>(value); g = p; b = q;
                break;
        }
        rgb[i * 3 + 0] = r;
        rgb[i * 3 + 1] = g;
        rgb[i * 3 + 2] = b;
    }
}

} // namespace pixo_render_native

// ---- C ABI 导出 (供 Python ctypes 加载) ----

PIXO_RENDER_NATIVE_API void PixoRenderRgbToHsv(
    const double* rgb, double* h, double* s, double* v, std::int64_t pixelCount)
{
    pixo_render_native::RgbToHsv(rgb, h, s, v, pixelCount);
}

PIXO_RENDER_NATIVE_API void PixoRenderHsvToRgb(
    const double* h, const double* s, const double* v, double* rgb,
    std::int64_t pixelCount)
{
    pixo_render_native::HsvToRgb(h, s, v, rgb, pixelCount);
}

PIXO_RENDER_NATIVE_API void PixoRenderRgbToHsvF32(
    const float* rgb, float* h, float* s, float* v, std::int64_t pixelCount)
{
    pixo_render_native::RgbToHsvF32(rgb, h, s, v, pixelCount);
}

PIXO_RENDER_NATIVE_API void PixoRenderHsvToRgbF32(
    const float* h, const float* s, const float* v, float* rgb,
    std::int64_t pixelCount)
{
    pixo_render_native::HsvToRgbF32(h, s, v, rgb, pixelCount);
}
