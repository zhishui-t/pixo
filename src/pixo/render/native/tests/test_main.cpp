// pixo.render native 零依赖单元测试入口。
// 构建: cmake -DPIXO_RENDER_NATIVE_BUILD_TESTS=ON && cmake --build .
// 运行: pixo_render_native_tests.exe; 返回值 = 失败用例数。

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#include "abi.h"
#include "decode.h"
#include "oklab.h"
#include "rcd.h"
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

// ---------------------------------------------------------------------------
// RCD 去马赛克 (R32-T1): 合成 Bayer 四相位 + 伪彩 vs 双线性基线 + 确定性金样本
// + 错误路径。

// 简单双线性去马赛克基线 (伪彩对照用, 非 RT 代码): G@R/B = 十字均值,
// R/B@G = 同向均值, R/B@对角位 = 对角均值; 越界邻居跳过。
void bilinear_ref(const float* cfa, float* out, int w, int h, const int pat[4])
{
    auto code = [&](int r, int c) { return pat[((r & 1) << 1) | (c & 1)]; };
    for (int r = 0; r < h; ++r) {
        for (int c = 0; c < w; ++c) {
            const float v = cfa[r * w + c];
            float acc[3] = {0.f, 0.f, 0.f};
            int cnt[3] = {0, 0, 0};
            static const int dr[4] = {0, 0, -1, 1};
            static const int dc[4] = {-1, 1, 0, 0};
            for (int k = 0; k < 4; ++k) {
                const int rr = r + dr[k];
                const int cc = c + dc[k];
                if (rr >= 0 && rr < h && cc >= 0 && cc < w) {
                    acc[code(rr, cc)] += cfa[rr * w + cc];
                    cnt[code(rr, cc)]++;
                }
            }
            float racc[3] = {0.f, 0.f, 0.f};
            int rcnt[3] = {0, 0, 0};
            static const int ddr[4] = {-1, -1, 1, 1};
            static const int ddc[4] = {-1, 1, -1, 1};
            for (int k = 0; k < 4; ++k) {
                const int rr = r + ddr[k];
                const int cc = c + ddc[k];
                if (rr >= 0 && rr < h && cc >= 0 && cc < w) {
                    racc[code(rr, cc)] += cfa[rr * w + cc];
                    rcnt[code(rr, cc)]++;
                }
            }
            const int cd = code(r, c);
            for (int ch = 0; ch < 3; ++ch) {
                float val = v;
                if (ch != cd) {
                    // 优先十字 (G 邻居在十字位), 对角补 (R/B 邻居在对角位)
                    if (cnt[ch] > 0) {
                        val = acc[ch] / static_cast<float>(cnt[ch]);
                    } else if (rcnt[ch] > 0) {
                        val = racc[ch] / static_cast<float>(rcnt[ch]);
                    } else {
                        val = v;
                    }
                }
                out[(r * w + c) * 3 + ch] = val;
            }
        }
    }
}

// 色度高频能量 (伪彩指标): chroma=|R-G|, 高频=|chroma - 4邻均值|,
// 返回指定矩形区 (行 [r0,r1), 列 [c0,c1)) 内均值。
float chroma_hf_energy(const float* rgb, int w, int r0, int r1, int c0, int c1)
{
    double sum = 0.0;
    int n = 0;
    for (int r = r0; r < r1; ++r) {
        for (int c = c0; c < c1; ++c) {
            const float* p = rgb + (r * w + c) * 3;
            const float chroma = std::fabs(p[0] - p[1]);
            float avg = 0.f;
            int cnt = 0;
            static const int dr[4] = {0, 0, -1, 1};
            static const int dc[4] = {-1, 1, 0, 0};
            for (int k = 0; k < 4; ++k) {
                const int rr = r + dr[k];
                const int cc = c + dc[k];
                if (rr >= r0 && rr < r1 && cc >= c0 && cc < c1) {
                    const float* q = rgb + (rr * w + cc) * 3;
                    avg += std::fabs(q[0] - q[1]);
                    ++cnt;
                }
            }
            if (cnt > 0) {
                sum += std::fabs(chroma - avg / static_cast<float>(cnt));
                ++n;
            }
        }
    }
    return n > 0 ? static_cast<float>(sum / n) : 0.f;
}

// 逐位比较 float (确定性金样本); 失败时打印实际位型供钉样本。
bool float_bits_eq(float actual, float expected)
{
    std::uint32_t a = 0, e = 0;
    std::memcpy(&a, &actual, sizeof a);
    std::memcpy(&e, &expected, sizeof e);
    if (a != e) {
        std::fprintf(stderr,
                     "  golden float mismatch: actual bits=0x%08x (%.9g), "
                     "expected bits=0x%08x (%.9g)\n",
                     a, actual, e, expected);
        return false;
    }
    return true;
}

void TestRcdDemosaic()
{
    // 四相位 (row-major 2x2 布局码 0=R,1=G,2=B)
    const int phases[4][4] = {
        {0, 1, 1, 2}, // RGGB
        {2, 1, 1, 0}, // BGGR
        {1, 0, 2, 1}, // GRBG
        {1, 2, 0, 1}, // GBRG
    };
    const int w = 48;
    const int h = 36;
    std::vector<float> cfa(static_cast<size_t>(w) * h);
    std::vector<float> out(static_cast<size_t>(w) * h * 3);

    for (const auto& pat : phases) {
        // 1) 恒场 0.5 → 全图 ≈0.5, 无 NaN (含 border_interpolate 区)
        std::fill(cfa.begin(), cfa.end(), 0.5f);
        CHECK(PixoRenderDemosaicRCD(cfa.data(), out.data(), w, h, pat) ==
              PixoRenderOk);
        for (size_t i = 0; i < out.size(); ++i) {
            CHECK(!std::isnan(out[i]));
            CHECK(std::fabs(out[i] - 0.5f) < 1e-5f);
        }

        // 2) 垂直渐变 (中性梯, 无色度) → 单调保序 + 内部近似恢复
        for (int r = 0; r < h; ++r) {
            const float v = static_cast<float>(r) / static_cast<float>(h - 1);
            std::fill(cfa.begin() + r * w, cfa.begin() + (r + 1) * w, v);
        }
        CHECK(PixoRenderDemosaicRCD(cfa.data(), out.data(), w, h, pat) ==
              PixoRenderOk);
        for (int r = 1; r < h; ++r) {
            for (int c = 4; c < w - 4; c += 7) {
                const float prev = out[((r - 1) * w + c) * 3];
                const float curr = out[(r * w + c) * 3];
                CHECK(curr >= prev - 1e-5f); // 渐变保序 (浮点容差)
            }
        }
        for (int r = 10; r < h - 10; r += 3) {
            const float v = static_cast<float>(r) / static_cast<float>(h - 1);
            for (int c = 10; c < w - 10; c += 5) {
                CHECK(std::fabs(out[(r * w + c) * 3] - v) < 0.02f);
                CHECK(std::fabs(out[(r * w + c) * 3 + 1] - v) < 0.02f);
                CHECK(std::fabs(out[(r * w + c) * 3 + 2] - v) < 0.02f);
            }
        }
    }

    // 3) 彩色垂直边伪彩: 左红场/右绿场, RCD 色度高频能量须低于双线性基线
    {
        const int* pat = phases[0]; // RGGB
        const int edge = w / 2;
        for (int r = 0; r < h; ++r) {
            for (int c = 0; c < w; ++c) {
                const bool left = c < edge;
                const int site = pat[((r & 1) << 1) | (c & 1)];
                // 场值: 左 = {R:0.6, G:0.1, B:0.1}; 右 = {R:0.1, G:0.6, B:0.1}
                const float field[3] = {left ? 0.6f : 0.1f, left ? 0.1f : 0.6f,
                                        0.1f};
                cfa[r * w + c] = field[site];
            }
        }
        CHECK(PixoRenderDemosaicRCD(cfa.data(), out.data(), w, h, pat) ==
              PixoRenderOk);
        std::vector<float> bil(static_cast<size_t>(w) * h * 3);
        bilinear_ref(cfa.data(), bil.data(), w, h, pat);
        // 边带 (edge±3) 与内部行: RCD 伪彩显著低于双线性
        const float e_rcd = chroma_hf_energy(out.data(), w, 9, h - 9, edge - 3, edge + 3);
        const float e_bil = chroma_hf_energy(bil.data(), w, 9, h - 9, edge - 3, edge + 3);
        CHECK(e_rcd < e_bil);

        // 4) 确定性金样本: 同输入两次运行逐位一致; 关键点位型钉样本
        //    (锁算法不漂移; 再生成方式: 本测试失败输出会打印 actual bits)
        std::vector<float> out2(out.size());
        CHECK(PixoRenderDemosaicRCD(cfa.data(), out2.data(), w, h, pat) ==
              PixoRenderOk);
        CHECK(std::memcmp(out.data(), out2.data(), out.size() * sizeof(float)) == 0);

        // 采样点 (边缘带内部): 金样本位型 (串行构建首轮实测钉入, 源 = RGGB
        // 红绿边场景; 再生成: 本 CHECK 失败输出打印 actual bits)
        struct Golden {
            int r, c, ch;
            std::uint32_t bits;
        };
        const Golden goldens[] = {
            {18, 21, 0, 0x3f1999a4u}, // R@G(左区) ≈0.60000062
            {18, 21, 1, 0x3dcccccdu}, // G 本位(左区) = 0.1
            {18, 24, 0, 0x3dcccccdu}, // R 本位(右区) = 0.1
            {18, 24, 1, 0x3f19996eu}, // G@R(右区, 垂直向判定) ≈0.5999974
            {18, 27, 2, 0x3dcccdf0u}, // B@G ≈0.10000217
        };
        for (const auto& g : goldens) {
            CHECK(float_bits_eq(out[(g.r * w + g.c) * 3 + g.ch],
                                [&g] {
                                    float v = 0.f;
                                    std::memcpy(&v, &g.bits, sizeof v);
                                    return v;
                                }()));
        }
    }

    // 5) 错误路径: 非法布局 / 尺寸过小 / 非正尺寸 / 空指针
    {
        const int good[4] = {0, 1, 1, 2};
        std::vector<float> cfaS(20 * 20, 0.5f);
        std::vector<float> outS(20 * 20 * 3);

        const int bad1[4] = {0, 0, 2, 2};  // 2R 0G 2B
        CHECK(PixoRenderDemosaicRCD(cfaS.data(), outS.data(), 20, 20, bad1) ==
              PixoRenderFallbackRequested);
        const int bad2[4] = {0, 1, 2, 3};  // 码值 3 越界
        CHECK(PixoRenderDemosaicRCD(cfaS.data(), outS.data(), 20, 20, bad2) ==
              PixoRenderFallbackRequested);
        const int bad3[4] = {1, 1, 1, 1};  // 全 G
        CHECK(PixoRenderDemosaicRCD(cfaS.data(), outS.data(), 20, 20, bad3) ==
              PixoRenderFallbackRequested);
        CHECK(PixoRenderDemosaicRCD(cfaS.data(), outS.data(), 10, 20, good) ==
              PixoRenderFallbackRequested); // < 19
        CHECK(PixoRenderDemosaicRCD(cfaS.data(), outS.data(), 0, 20, good) ==
              PixoRenderInvalidArgs);
        CHECK(PixoRenderDemosaicRCD(nullptr, outS.data(), 20, 20, good) ==
              PixoRenderInvalidArgs);
        CHECK(PixoRenderDemosaicRCD(cfaS.data(), nullptr, 20, 20, good) ==
              PixoRenderInvalidArgs);
        CHECK(PixoRenderDemosaicRCD(cfaS.data(), outS.data(), 20, 20, nullptr) ==
              PixoRenderInvalidArgs);
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
    TestRcdDemosaic();

    if (failures == 0) {
        std::printf("pixo_render_native_tests: all passed\n");
    } else {
        std::printf("pixo_render_native_tests: %d failed\n", failures);
    }
    return failures;
}
