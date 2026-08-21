// pixo.render native 零依赖单元测试入口。
// 构建: cmake -DPIXO_RENDER_NATIVE_BUILD_TESTS=ON && cmake --build .
// 运行: pixo_render_native_tests.exe; 返回值 = 失败用例数。

#include <cmath>
#include <cstdint>
#include <cstdio>

#include "abi.h"
#include "decode.h"
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

} // namespace

int main()
{
    TestVersion();
    TestHsvRoundTrip();
    TestDecodeCfaHalf();
    TestWarmSatExceptionCaught();

    if (failures == 0) {
        std::printf("pixo_render_native_tests: all passed\n");
    } else {
        std::printf("pixo_render_native_tests: %d failed\n", failures);
    }
    return failures;
}
