// pixo.render native 零依赖单元测试入口。
// 构建: cmake -DPIXO_RENDER_NATIVE_BUILD_TESTS=ON && cmake --build .
// 运行: pixo_render_native_tests.exe; 返回值 = 失败用例数。

#include <cmath>
#include <cstdint>
#include <cstdio>

#include "abi.h"
#include "decode.h"
#include "oklab.h"
#include "warm_sat.h"

// C ABI 导出的 HSV 函数（hsv.cpp 中定义）。
extern "C" {
void PixoRenderRgbToHsv(const double* rgb, double* h, double* s, double* v,
                    std::int64_t pixelCount);
void PixoRenderHsvToRgb(const double* h, const double* s, const double* v,
                    double* rgb, std::int64_t pixelCount);
}

namespace {

int failures = 0;

#define CHECK(expr)                                                       \
    do {                                                                  \
        if (!(expr)) {                                                    \
            std::fprintf(stderr, "CHECK failed at %s:%d: %s\n",           \
                         __FILE__, __LINE__, #expr);                      \
            ++failures;                                                   \
        }                                                                 \
    } while (0)

void TestVersion()
{
    struct PixoRenderVersion version{};
    CHECK(PixoRenderVersion(&version) == PixoRenderOk);
    CHECK(version.major == 1);
    CHECK(PixoRenderVersion(nullptr) == PixoRenderInvalidArgs);
}

void TestHsvRoundTrip()
{
    const double rgb[3] = {0.2, 0.5, 0.9};
    double h[1] = {0.0};
    double s[1] = {0.0};
    double v[1] = {0.0};
    double out[3] = {0.0, 0.0, 0.0};

    PixoRenderRgbToHsv(rgb, h, s, v, 1);
    PixoRenderHsvToRgb(h, s, v, out, 1);

    CHECK(std::fabs(out[0] - rgb[0]) < 1e-12);
    CHECK(std::fabs(out[1] - rgb[1]) < 1e-12);
    CHECK(std::fabs(out[2] - rgb[2]) < 1e-12);
}

void TestDecodeCfaHalf()
{
    // 4x4 RGGB: 0=R, 1=G0, 2=B, 3=G1
    const std::uint16_t cfa[16] = {
        1000, 2000, 3000, 4000,
        5000, 6000, 7000, 8000,
        9000, 10000, 11000, 12000,
        13000, 14000, 15000, 16000,
    };
    PixoRenderCfaDecodeParams params{};
    params.patternR = 0;
    params.patternG0 = 1;
    params.patternG1 = 3;
    params.patternB = 2;
    params.black[0] = params.black[1] = params.black[2] = params.black[3] = 0.0f;
    params.whiteLevel = 16384.0f;
    params.outputScale = 1.0f;

    float out[2 * 2 * 3] = {0.0f};
    CHECK(PixoRenderDecodeCfaHalf(cfa, out, 4, 4, &params) == PixoRenderOk);
    const float inv = 1.0f / 16384.0f;
    CHECK(std::fabs(out[0] - 1000.0f * inv) < 1e-6f);
    CHECK(std::fabs(out[1] - 4000.0f * inv) < 1e-6f);
    CHECK(std::fabs(out[2] - 5000.0f * inv) < 1e-6f);
    CHECK(std::fabs(out[3] - 3000.0f * inv) < 1e-6f);
    CHECK(std::fabs(out[4] - 6000.0f * inv) < 1e-6f);
    CHECK(std::fabs(out[5] - 7000.0f * inv) < 1e-6f);
    CHECK(PixoRenderDecodeCfaHalf(nullptr, out, 4, 4, &params) == PixoRenderInvalidArgs);
}

void TestWarmSatExceptionCaught()
{
    PixoRenderWarmSatParams params{};
    params.satScale = 2.0f;
    params.spotSatScale = 2.0f;
    params.hueCenter = 22.5f;
    params.hueHalfwidth = 17.5f;
    params.satMin = 0.05f;
    params.valMin = 0.6f;
    params.coverageMax = 0.0015f;
    params.contrastSigmaFrac = 0.006f;
    params.contrastThr = 0.03f;
    params.contrastSoft = 0.08f;
    float dummy = 0.0f;
    // 超大尺寸使内部 vector 分配抛出 std::bad_alloc，C ABI try/catch 应转为 -3。
    const int status = PixoRenderApplyLocalWarmSat(
        &dummy, &dummy, 1000000000, 1000000000, &params);
    CHECK(status == PixoRenderInternalError);
}

void TestOklabRoundTrip()
{
    // 黑/白/灰端点 + 中间色: 正向 -> 逆向往返, f32 输出容差 1e-6。
    const float rgbIn[4 * 3] = {
        0.0f, 0.0f, 0.0f,
        1.0f, 1.0f, 1.0f,
        0.5f, 0.5f, 0.5f,
        0.8f, 0.2f, 0.1f,
    };
    double l[4] = {0.0};
    double a[4] = {0.0};
    double b[4] = {0.0};

    struct PixoRenderSrgbToOklabParams fwd{};
    fwd.rgb = rgbIn;
    fwd.width = 4;
    fwd.height = 1;
    fwd.stride = 12;
    fwd.l = l;
    fwd.a = a;
    fwd.b = b;
    fwd.planeStride = 4;
    CHECK(PixoRenderSrgbToOklabF32(&fwd) == PixoRenderOk);

    // 黑端点精确为 0 (全零链路); 白端点 L≈1; 灰轴 a/b≈0 (Ottosson 白点闭合)。
    CHECK(l[0] == 0.0 && a[0] == 0.0 && b[0] == 0.0);
    CHECK(std::fabs(l[1] - 1.0) < 1e-6);
    CHECK(std::fabs(a[2]) < 1e-6 && std::fabs(b[2]) < 1e-6);
    CHECK(l[3] > 0.0 && l[3] < 1.0);

    float rgbOut[4 * 3] = {0.0f};
    struct PixoRenderOklabToSrgbParams inv{};
    inv.l = l;
    inv.a = a;
    inv.b = b;
    inv.planeStride = 4;
    inv.rgb = rgbOut;
    inv.width = 4;
    inv.height = 1;
    inv.stride = 12;
    CHECK(PixoRenderOklabToSrgbF32(&inv) == PixoRenderOk);
    for (int i = 0; i < 12; ++i) {
        CHECK(std::fabs(rgbOut[i] - rgbIn[i]) < 1e-6f);
        CHECK(rgbOut[i] >= 0.0f && rgbOut[i] <= 1.0f);
    }

    // 越域 lab (a/b 放大 4 倍) 不产生 NaN, clip 后仍在 [0,1]。
    double lBig[4];
    double aBig[4];
    double bBig[4];
    for (int i = 0; i < 4; ++i) {
        lBig[i] = l[i];
        aBig[i] = a[i] * 4.0;
        bBig[i] = b[i] * 4.0;
    }
    float rgbWide[4 * 3];
    inv.l = lBig;
    inv.a = aBig;
    inv.b = bBig;
    inv.rgb = rgbWide;
    CHECK(PixoRenderOklabToSrgbF32(&inv) == PixoRenderOk);
    for (int i = 0; i < 12; ++i) {
        CHECK(!std::isnan(rgbWide[i]));
        CHECK(rgbWide[i] >= 0.0f && rgbWide[i] <= 1.0f);
    }

    // 参数校验: 空 params / 空指针 / stride 不足。
    CHECK(PixoRenderSrgbToOklabF32(nullptr) == PixoRenderInvalidArgs);
    CHECK(PixoRenderOklabToSrgbF32(nullptr) == PixoRenderInvalidArgs);
    struct PixoRenderSrgbToOklabParams badFwd = fwd;
    badFwd.rgb = nullptr;
    CHECK(PixoRenderSrgbToOklabF32(&badFwd) == PixoRenderInvalidArgs);
    badFwd = fwd;
    badFwd.stride = 11;
    CHECK(PixoRenderSrgbToOklabF32(&badFwd) == PixoRenderInvalidArgs);
    badFwd = fwd;
    badFwd.planeStride = 3;
    CHECK(PixoRenderSrgbToOklabF32(&badFwd) == PixoRenderInvalidArgs);
    struct PixoRenderOklabToSrgbParams badInv = inv;
    badInv.l = nullptr;
    CHECK(PixoRenderOklabToSrgbF32(&badInv) == PixoRenderInvalidArgs);
    badInv = inv;
    badInv.stride = 11;
    CHECK(PixoRenderOklabToSrgbF32(&badInv) == PixoRenderInvalidArgs);
}

void TestOklabStride()
{
    // 带行距的布局 (rgb stride 带尾垫, L/a/b planeStride 带行垫) 与紧凑
    // 布局结果逐位一致 —— 平面 stride 语义自检。
    const int width = 3;
    const int height = 2;
    const int rowFloats = 8 * 3;
    float rgbIn[height * rowFloats];
    for (int i = 0; i < height * rowFloats; ++i) {
        rgbIn[i] = 0.0f;
    }
    // 仅填每行前 width*3 个有效像素, 尾垫保持 0, 验证行距被正确跳过。
    for (int y = 0; y < height; ++y) {
        for (int i = 0; i < width * 3; ++i) {
            rgbIn[y * rowFloats + i] = 0.05f + 0.9f * ((y * width * 3 + i) % 11) / 11.0f;
        }
    }
    // 紧凑输入缓冲: 同一组像素值, 无行垫 —— 与 pad 布局喂同一内核。
    float rgbTight[height * width * 3];
    for (int y = 0; y < height; ++y) {
        for (int i = 0; i < width * 3; ++i) {
            rgbTight[y * width * 3 + i] = rgbIn[y * rowFloats + i];
        }
    }
    double lPad[height * 5];
    double aPad[height * 5];
    double bPad[height * 5];
    struct PixoRenderSrgbToOklabParams fwd{};
    fwd.rgb = rgbIn;
    fwd.width = width;
    fwd.height = height;
    fwd.stride = 8 * 3;
    fwd.l = lPad;
    fwd.a = aPad;
    fwd.b = bPad;
    fwd.planeStride = 5;
    CHECK(PixoRenderSrgbToOklabF32(&fwd) == PixoRenderOk);

    double lTight[height * width];
    double aTight[height * width];
    double bTight[height * width];
    struct PixoRenderSrgbToOklabParams tight = fwd;
    tight.rgb = rgbTight;
    tight.stride = width * 3;
    tight.l = lTight;
    tight.a = aTight;
    tight.b = bTight;
    tight.planeStride = width;
    CHECK(PixoRenderSrgbToOklabF32(&tight) == PixoRenderOk);
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            const std::int64_t p = static_cast<std::int64_t>(y) * 5 + x;
            const std::int64_t t = static_cast<std::int64_t>(y) * width + x;
            CHECK(lPad[p] == lTight[t]);
            CHECK(aPad[p] == aTight[t]);
            CHECK(bPad[p] == bTight[t]);
        }
    }

    // 逆向往返: 带 pad 布局输出的 sRGB 与输入一致 (f32 容差 1e-6)。
    float rgbOut[height * rowFloats] = {0.0f};
    struct PixoRenderOklabToSrgbParams inv{};
    inv.l = lPad;
    inv.a = aPad;
    inv.b = bPad;
    inv.planeStride = 5;
    inv.rgb = rgbOut;
    inv.width = width;
    inv.height = height;
    inv.stride = rowFloats;
    CHECK(PixoRenderOklabToSrgbF32(&inv) == PixoRenderOk);
    for (int i = 0; i < height * rowFloats; ++i) {
        CHECK(std::fabs(rgbOut[i] - rgbIn[i]) < 1e-6f);
    }
}

} // namespace

int main()
{
    TestVersion();
    TestHsvRoundTrip();
    TestDecodeCfaHalf();
    TestWarmSatExceptionCaught();
    TestOklabRoundTrip();
    TestOklabStride();

    if (failures == 0) {
        std::printf("pixo_render_native_tests: all passed\n");
    } else {
        std::printf("pixo_render_native_tests: %d failed\n", failures);
    }
    return failures;
}
