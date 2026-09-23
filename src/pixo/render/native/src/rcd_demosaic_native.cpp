/*
 *  This file is part of RawTherapee.
 *
 *  Copyright (c) 2017-2020 Luis Sanz Rodriguez (luis.sanz.rodriguez(at)gmail(dot)com) and Ingo Weyrich (heckflosse67@gmx.de)
 *
 *  RawTherapee is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  RawTherapee is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with RawTherapee.  If not, see <https://www.gnu.org/licenses/>.
 */
// =============================================================================
// pixo.render R32-T1 移植 (2026-09-23, pixo 为 GPL-3.0-or-later)。
//
// 来源 (Source):
//   - 算法核心: RawTherapee rtengine/rcd_demosaic.cc @ 6c4cb59 (dev 分支, GPLv3)
//     "RATIO CORRECTED DEMOSAICING" release 2.3,
//     上游原始实现 https://github.com/LuisSR/RCD-Demosaicing (GPLv3)。
//   - border_interpolate: RawTherapee rtengine/demosaic_algos.cc @ 6c4cb59
//     (Copyright (c) 2004-2010 Gabor Horvath, GPLv3)。
//   - rt_math 垫片: RawTherapee rtengine/rt_math.h @ 6c4cb59 (SQR/LIM01/intp)。
//
// 适配说明 (仅依赖面替换, 算法步骤/循环结构/常量与 RT 原文逐字一致):
//   1. rt_math.h 的 SQR/LIM01/intp 以等价内联垫片替代 (intp 原文 a*(b-c)+c);
//      ALIGNED16 (opthelper.h GCC 路径) 以 alignas(16) 替代;
//      array2D<T> 以指针+行距薄模板 Array2DView 替代 (仅 [row][col] 下标语义,
//      行距=width, 与 RT 行主序布局等价, 不改数值)。
//   2. FC()/filters 位编码以入口参数 pattern[4] (布局码 0=R,1=G,2=B) 替代;
//      非 RGB Bayer 原文 fallback igv_interpolate → 返回 PixoRenderFallback-
//      Requested (=1, abi.h 既有), 调用方 (io.py) 回落 AHD, 对齐 RT 原文
//      "不支持即回落" 行为。
//   3. 归一化 (设计 v2 M3): RT 原文 rawData ∈ [0,65535] 已减黑, 装载时
//      LIM01(rawData/65536); 本移植输入契约 = Python 侧已按
//      (v-black)/(white-black) 归一化到 [0,1] 的 mosaic → 装载处去 /scale,
//      输出写出去 ×scale(65536), 算法全程与 RT 同在 [0,1] 域, LIM01 保留。
//   4. GUI 件剥离: StopWatch/plistener/progress/M() 移除; chunkSize 参数固定
//      为 RT options.chunkSizeRCD 缺省值 2 (rtgui/options.cc:526)。
//   5. OpenMP 结构原样保留: parallel 区域 + for collapse(2) schedule(dynamic)
//      nowait, 每线程自持 tile 缓冲 (无共享写, RT 原文无数据竞争);
//      交错输出 (interleave) 为 pixo 侧新增独立段。
// =============================================================================

#include "rcd.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <vector>

namespace {

// --- rt_math.h 垫片 (RawTherapee rtengine/rt_math.h @ 6c4cb59, GPLv3) ---

template <typename T>
constexpr T SQR(T x)
{
    return x * x;
}

template <typename T>
constexpr T LIM01(const T& a)
{
    return std::max(T(0), std::min(a, T(1)));
}

// rt_math.h 原文实现: a * (b - c) + c
template <typename T>
constexpr T intp(T a, T b, T c)
{
    return a * (b - c) + c;
}

// --- array2D<T> 薄垫片: 仅 RT [row][col] 下标语义 (行主序, 行距 = width) ---

template <typename T>
struct Array2DView {
    T* data;
    int width;
    T* operator[](int row) const
    {
        return data + static_cast<size_t>(row) * static_cast<size_t>(width);
    }
};

unsigned fc(const unsigned int cfa[2][2], int r, int c)
{
    return cfa[r & 1][c & 1];
}

// --- border_interpolate ---
// RawTherapee rtengine/demosaic_algos.cc @ 6c4cb59 (Gabor Horvath, GPLv3) 整搬:
// 仅 FC()→fc(cfarray,…) 与 array2D→Array2DView 替换。输入 mosaic 已归一化 [0,1]
// (等价 RT rawData/65536), 输出域随之 [0,1] —— 与核心算法同域, 无需改写。
void border_interpolate(int winw, int winh, int lborders,
                        const Array2DView<const float>& rawData,
                        const Array2DView<float>& red,
                        const Array2DView<float>& green,
                        const Array2DView<float>& blue,
                        const unsigned int cfarray[2][2])
{
    int bord = lborders;
    int width = winw;
    int height = winh;

    for (int i = 0; i < height; i++) {

        float sum[6];

        for (int j = 0; j < bord; j++) { // first few columns
            for (int c = 0; c < 6; c++) {
                sum[c] = 0;
            }

            for (int i1 = i - 1; i1 < i + 2; i1++)
                for (int j1 = j - 1; j1 < j + 2; j1++) {
                    if ((i1 > -1) && (i1 < height) && (j1 > -1)) {
                        int c = fc(cfarray, i1, j1);
                        sum[c] += rawData[i1][j1];
                        sum[c + 3]++;
                    }
                }

            int c = fc(cfarray, i, j);

            if (c == 1) {
                red[i][j] = sum[0] / sum[3];
                green[i][j] = rawData[i][j];
                blue[i][j] = sum[2] / sum[5];
            } else {
                green[i][j] = sum[1] / sum[4];

                if (c == 0) {
                    red[i][j] = rawData[i][j];
                    blue[i][j] = sum[2] / sum[5];
                } else {
                    red[i][j] = sum[0] / sum[3];
                    blue[i][j] = rawData[i][j];
                }
            }
        } // j

        for (int j = width - bord; j < width; j++) { // last few columns
            for (int c = 0; c < 6; c++) {
                sum[c] = 0;
            }

            for (int i1 = i - 1; i1 < i + 2; i1++)
                for (int j1 = j - 1; j1 < j + 2; j1++) {
                    if ((i1 > -1) && (i1 < height) && (j1 < width)) {
                        int c = fc(cfarray, i1, j1);
                        sum[c] += rawData[i1][j1];
                        sum[c + 3]++;
                    }
                }

            int c = fc(cfarray, i, j);

            if (c == 1) {
                red[i][j] = sum[0] / sum[3];
                green[i][j] = rawData[i][j];
                blue[i][j] = sum[2] / sum[5];
            } else {
                green[i][j] = sum[1] / sum[4];

                if (c == 0) {
                    red[i][j] = rawData[i][j];
                    blue[i][j] = sum[2] / sum[5];
                } else {
                    red[i][j] = sum[0] / sum[3];
                    blue[i][j] = rawData[i][j];
                }
            }
        } // j
    } // i

    for (int i = 0; i < bord; i++) { // first few rows

        float sum[6];

        for (int j = bord; j < width - bord; j++) {
            for (int c = 0; c < 6; c++) {
                sum[c] = 0;
            }

            for (int i1 = i - 1; i1 < i + 2; i1++)
                for (int j1 = j - 1; j1 < j + 2; j1++) {
                    if ((i1 > -1) && (i1 < height) && (j1 > -1)) {
                        int c = fc(cfarray, i1, j1);
                        sum[c] += rawData[i1][j1];
                        sum[c + 3]++;
                    }
                }

            int c = fc(cfarray, i, j);

            if (c == 1) {
                red[i][j] = sum[0] / sum[3];
                green[i][j] = rawData[i][j];
                blue[i][j] = sum[2] / sum[5];
            } else {
                green[i][j] = sum[1] / sum[4];

                if (c == 0) {
                    red[i][j] = rawData[i][j];
                    blue[i][j] = sum[2] / sum[5];
                } else {
                    red[i][j] = sum[0] / sum[3];
                    blue[i][j] = rawData[i][j];
                }
            }
        } // j
    } // i

    for (int i = height - bord; i < height; i++) { // last few rows

        float sum[6];

        for (int j = bord; j < width - bord; j++) {
            for (int c = 0; c < 6; c++) {
                sum[c] = 0;
            }

            for (int i1 = i - 1; i1 < i + 2; i1++)
                for (int j1 = j - 1; j1 < j + 2; j1++) {
                    if ((i1 > -1) && (i1 < height) && (j1 < width)) {
                        int c = fc(cfarray, i1, j1);
                        sum[c] += rawData[i1][j1];
                        sum[c + 3]++;
                    }
                }

            int c = fc(cfarray, i, j);

            if (c == 1) {
                red[i][j] = sum[0] / sum[3];
                green[i][j] = rawData[i][j];
                blue[i][j] = sum[2] / sum[5];
            } else {
                green[i][j] = sum[1] / sum[4];

                if (c == 0) {
                    red[i][j] = rawData[i][j];
                    blue[i][j] = sum[2] / sum[5];
                } else {
                    red[i][j] = sum[0] / sum[3];
                    blue[i][j] = rawData[i][j];
                }
            }
        } // j
    } // i
}

} // namespace

// RCD 核心: RawTherapee rtengine/rcd_demosaic.cc @ 6c4cb59
// RawImageSource::rcd_demosaic() 逐字移植 (适配见文件头注 1-5)。
PIXO_RENDER_NATIVE_API int PixoRenderDemosaicRCD(const float* mosaic, float* out,
                                                 int width, int height,
                                                 const int* pattern)
{
    if (mosaic == nullptr || out == nullptr || pattern == nullptr) {
        return PixoRenderInvalidArgs;
    }
    if (width <= 0 || height <= 0) {
        return PixoRenderInvalidArgs;
    }

    // 2x2 布局门 (RT 原文: FC(i,j)==3 → fallback igv_interpolate 的等价门):
    // 必须恰 1R + 2G + 1B, 码值 0/1/2。
    int count[3] = {0, 0, 0};
    for (int p = 0; p < 4; ++p) {
        if (pattern[p] < 0 || pattern[p] > 2) {
            return PixoRenderFallbackRequested;
        }
        count[pattern[p]]++;
    }
    if (count[0] != 1 || count[1] != 2 || count[2] != 1) {
        return PixoRenderFallbackRequested;
    }

    // RCD 最小可运行尺寸: 2*rcdBorder+1 (内部算法区留 9px 边界)。
    if (std::min(width, height) < 2 * 9 + 1) {
        return PixoRenderFallbackRequested;
    }

    const unsigned int cfarray[2][2] = {
        {static_cast<unsigned>(pattern[0]), static_cast<unsigned>(pattern[1])},
        {static_cast<unsigned>(pattern[2]), static_cast<unsigned>(pattern[3])}};

    // 输出平面 (RT 为 RawImageSource 成员 red/green/blue; 此处函数内分配,
    // 末尾交错写 out)。
    const size_t planeLen = static_cast<size_t>(width) * static_cast<size_t>(height);
    std::vector<float> redPlane(planeLen);
    std::vector<float> greenPlane(planeLen);
    std::vector<float> bluePlane(planeLen);
    const Array2DView<const float> rawData{mosaic, width};
    const Array2DView<float> red{redPlane.data(), width};
    const Array2DView<float> green{greenPlane.data(), width};
    const Array2DView<float> blue{bluePlane.data(), width};

    constexpr int tileBorder = 9; // avoid tile-overlap errors
    constexpr int rcdBorder = 9;
    constexpr int tileSize = 194;
    constexpr int tileSizeN = tileSize - 2 * tileBorder;
    const int numTh = height / (tileSizeN) + ((height % (tileSizeN)) ? 1 : 0);
    const int numTw = width / (tileSizeN) + ((width % (tileSizeN)) ? 1 : 0);
    constexpr int w1 = tileSize, w2 = 2 * tileSize, w3 = 3 * tileSize,
                  w4 = 4 * tileSize;
    // Tolerance to avoid dividing by zero
    constexpr float eps = 1e-5f;
    constexpr float epssq = 1e-10f;

// RT 原文 scale = 65536.f: 装载处 /scale 与输出处 ×scale 已按文件头注 3 移除
// (输入契约 = Python 侧已归一化 [0,1]), 算法域与 RT 一致。

#ifdef _OPENMP
#pragma omp parallel
#endif
    {
        float* const cfa = (float*)calloc(tileSize * tileSize, sizeof *cfa);
        float (*const rgb)[tileSize * tileSize] =
            (float (*)[tileSize * tileSize])malloc(3 * sizeof *rgb);
        float* const VH_Dir = (float*)calloc(tileSize * tileSize, sizeof *VH_Dir);
        float* const PQ_Dir =
            (float*)calloc(tileSize * tileSize / 2, sizeof *PQ_Dir);
        float* const lpf = PQ_Dir; // reuse buffer, they don't overlap in usage
        float* const P_CDiff_Hpf =
            (float*)calloc(tileSize * tileSize / 2, sizeof *P_CDiff_Hpf);
        float* const Q_CDiff_Hpf =
            (float*)calloc(tileSize * tileSize / 2, sizeof *Q_CDiff_Hpf);

#ifdef _OPENMP
// chunkSize = RT options.chunkSizeRCD 缺省值 2 (rtgui/options.cc:526)
#pragma omp for schedule(dynamic, 2) collapse(2) nowait
#endif
        for (int tr = 0; tr < numTh; ++tr) {
            for (int tc = 0; tc < numTw; ++tc) {
                const int rowStart = tr * tileSizeN;
                const int rowEnd = std::min(rowStart + tileSize, height);
                if (rowStart + tileBorder == rowEnd - tileBorder) {
                    continue;
                }
                const int colStart = tc * tileSizeN;
                const int colEnd = std::min(colStart + tileSize, width);
                if (colStart + tileBorder == colEnd - tileBorder) {
                    continue;
                }

                const int tileRows = std::min(rowEnd - rowStart, tileSize);
                const int tilecols = std::min(colEnd - colStart, tileSize);

                for (int row = rowStart; row < rowEnd; row++) {
                    const int c0 = fc(cfarray, row, colStart);
                    const int c1 = fc(cfarray, row, colStart + 1);
                    for (int col = colStart, indx = (row - rowStart) * tileSize;
                         col < colEnd; ++col, ++indx) {
                        cfa[indx] = rgb[c0][indx] = rgb[c1][indx] =
                            LIM01(rawData[row][col]); // 注 3: RT /scale 移除
                    }
                }

                // Step 1: Find cardinal and diagonal interpolation directions
                float bufferV[3][tileSize - 8];

                // Step 1.1: Calculate the square of the vertical and horizontal
                // color difference high pass filter
                for (int row = 3; row < std::min(tileRows - 3, 5); ++row) {
                    for (int col = 4, indx = row * tileSize + col;
                         col < tilecols - 4; ++col, ++indx) {
                        bufferV[row - 3][col - 4] =
                            SQR((cfa[indx - w3] - cfa[indx - w1] - cfa[indx + w1] +
                                 cfa[indx + w3]) -
                                3.f * (cfa[indx - w2] + cfa[indx + w2]) +
                                6.f * cfa[indx]);
                    }
                }

                // Step 1.2: Obtain the vertical and horizontal directional
                // discrimination strength
                float bufferH[tileSize - 6] alignas(16); // RT: ALIGNED16
                float* V0 = bufferV[0];
                float* V1 = bufferV[1];
                float* V2 = bufferV[2];
                for (int row = 4; row < tileRows - 4; ++row) {
                    for (int col = 3, indx = row * tileSize + col;
                         col < tilecols - 3; ++col, ++indx) {
                        bufferH[col - 3] =
                            SQR((cfa[indx - 3] - cfa[indx - 1] - cfa[indx + 1] +
                                 cfa[indx + 3]) -
                                3.f * (cfa[indx - 2] + cfa[indx + 2]) +
                                6.f * cfa[indx]);
                    }
                    for (int col = 4, indx = (row + 1) * tileSize + col;
                         col < tilecols - 4; ++col, ++indx) {
                        V2[col - 4] =
                            SQR((cfa[indx - w3] - cfa[indx - w1] - cfa[indx + w1] +
                                 cfa[indx + w3]) -
                                3.f * (cfa[indx - w2] + cfa[indx + w2]) +
                                6.f * cfa[indx]);
                    }
                    for (int col = 4, indx = row * tileSize + col;
                         col < tilecols - 4; ++col, ++indx) {

                        float V_Stat =
                            std::max(epssq, V0[col - 4] + V1[col - 4] + V2[col - 4]);
                        float H_Stat = std::max(
                            epssq, bufferH[col - 4] + bufferH[col - 3] + bufferH[col - 2]);

                        VH_Dir[indx] = V_Stat / (V_Stat + H_Stat);
                    }
                    // rotate pointers from row0, row1, row2 to row1, row2, row0
                    std::swap(V0, V2);
                    std::swap(V0, V1);
                }

                // Step 2: Low pass filter incorporating green, red and blue local
                // samples from the raw data
                for (int row = 2; row < tileRows - 2; ++row) {
                    for (int col = 2 + (fc(cfarray, row, 0) & 1),
                             indx = row * tileSize + col, lpindx = indx / 2;
                         col < tilecols - 2; col += 2, indx += 2, ++lpindx) {
                        lpf[lpindx] =
                            cfa[indx] +
                            0.5f * (cfa[indx - w1] + cfa[indx + w1] + cfa[indx - 1] +
                                    cfa[indx + 1]) +
                            0.25f * (cfa[indx - w1 - 1] + cfa[indx - w1 + 1] +
                                     cfa[indx + w1 - 1] + cfa[indx + w1 + 1]);
                    }
                }

                // Step 3: Populate the green channel at blue and red CFA positions
                for (int row = 4; row < tileRows - 4; ++row) {
                    for (int col = 4 + (fc(cfarray, row, 0) & 1),
                             indx = row * tileSize + col, lpindx = indx / 2;
                         col < tilecols - 4; col += 2, indx += 2, ++lpindx) {
                        // Cardinal gradients
                        const float cfai = cfa[indx];
                        const float N_Grad =
                            eps + (std::fabs(cfa[indx - w1] - cfa[indx + w1]) +
                                   std::fabs(cfai - cfa[indx - w2])) +
                            (std::fabs(cfa[indx - w1] - cfa[indx - w3]) +
                             std::fabs(cfa[indx - w2] - cfa[indx - w4]));
                        const float S_Grad =
                            eps + (std::fabs(cfa[indx - w1] - cfa[indx + w1]) +
                                   std::fabs(cfai - cfa[indx + w2])) +
                            (std::fabs(cfa[indx + w1] - cfa[indx + w3]) +
                             std::fabs(cfa[indx + w2] - cfa[indx + w4]));
                        const float W_Grad =
                            eps + (std::fabs(cfa[indx - 1] - cfa[indx + 1]) +
                                   std::fabs(cfai - cfa[indx - 2])) +
                            (std::fabs(cfa[indx - 1] - cfa[indx - 3]) +
                             std::fabs(cfa[indx - 2] - cfa[indx - 4]));
                        const float E_Grad =
                            eps + (std::fabs(cfa[indx - 1] - cfa[indx + 1]) +
                                   std::fabs(cfai - cfa[indx + 2])) +
                            (std::fabs(cfa[indx + 1] - cfa[indx + 3]) +
                             std::fabs(cfa[indx + 2] - cfa[indx + 4]));

                        // Cardinal pixel estimations
                        const float lpfi = lpf[lpindx];
                        const float N_Est = cfa[indx - w1] * (lpfi + lpfi) /
                                            (eps + lpfi + lpf[lpindx - w1]);
                        const float S_Est = cfa[indx + w1] * (lpfi + lpfi) /
                                            (eps + lpfi + lpf[lpindx + w1]);
                        const float W_Est =
                            cfa[indx - 1] * (lpfi + lpfi) / (eps + lpfi + lpf[lpindx - 1]);
                        const float E_Est =
                            cfa[indx + 1] * (lpfi + lpfi) / (eps + lpfi + lpf[lpindx + 1]);

                        // Vertical and horizontal estimations
                        const float V_Est =
                            (S_Grad * N_Est + N_Grad * S_Est) / (N_Grad + S_Grad);
                        const float H_Est =
                            (W_Grad * E_Est + E_Grad * W_Est) / (E_Grad + W_Grad);

                        // G@B and G@R interpolation
                        // Refined vertical and horizontal local discrimination
                        const float VH_Central_Value = VH_Dir[indx];
                        const float VH_Neighbourhood_Value =
                            0.25f * ((VH_Dir[indx - w1 - 1] + VH_Dir[indx - w1 + 1]) +
                                     (VH_Dir[indx + w1 - 1] + VH_Dir[indx + w1 + 1]));

                        const float VH_Disc =
                            std::fabs(0.5f - VH_Central_Value) <
                                    std::fabs(0.5f - VH_Neighbourhood_Value)
                                ? VH_Neighbourhood_Value
                                : VH_Central_Value;
                        rgb[1][indx] = intp(VH_Disc, H_Est, V_Est);
                    }
                }

                /**
                * STEP 4: Populate the red and blue channels
                */

                // Step 4.0: Calculate the square of the P/Q diagonals color
                // difference high pass filter
                for (int row = 3; row < tileRows - 3; ++row) {
                    for (int col = 3, indx = row * tileSize + col, indx2 = indx / 2;
                         col < tilecols - 3; col += 2, indx += 2, indx2++) {
                        P_CDiff_Hpf[indx2] =
                            SQR((cfa[indx - w3 - 3] - cfa[indx - w1 - 1] -
                                 cfa[indx + w1 + 1] + cfa[indx + w3 + 3]) -
                                3.f * (cfa[indx - w2 - 2] + cfa[indx + w2 + 2]) +
                                6.f * cfa[indx]);
                        Q_CDiff_Hpf[indx2] =
                            SQR((cfa[indx - w3 + 3] - cfa[indx - w1 + 1] -
                                 cfa[indx + w1 - 1] + cfa[indx + w3 - 3]) -
                                3.f * (cfa[indx - w2 + 2] + cfa[indx + w2 - 2]) +
                                6.f * cfa[indx]);
                    }
                }

                // Step 4.1: Obtain the P/Q diagonals directional discrimination
                // strength
                for (int row = 4; row < tileRows - 4; ++row) {
                    for (int col = 4 + (fc(cfarray, row, 0) & 1),
                             indx = row * tileSize + col, indx2 = indx / 2,
                             indx3 = (indx - w1 - 1) / 2, indx4 = (indx + w1 - 1) / 2;
                         col < tilecols - 4;
                         col += 2, indx += 2, indx2++, indx3++, indx4++) {
                        float P_Stat = std::max(
                            epssq,
                            P_CDiff_Hpf[indx3] + P_CDiff_Hpf[indx2] + P_CDiff_Hpf[indx4 + 1]);
                        float Q_Stat = std::max(
                            epssq,
                            Q_CDiff_Hpf[indx3 + 1] + Q_CDiff_Hpf[indx2] + Q_CDiff_Hpf[indx4]);
                        PQ_Dir[indx2] = P_Stat / (P_Stat + Q_Stat);
                    }
                }

                // Step 4.2: Populate the red and blue channels at blue and red CFA
                // positions
                for (int row = 4; row < tileRows - 4; ++row) {
                    for (int col = 4 + (fc(cfarray, row, 0) & 1),
                             indx = row * tileSize + col,
                             c = 2 - static_cast<int>(fc(cfarray, row, col)),
                             pqindx = indx / 2, pqindx2 = (indx - w1 - 1) / 2,
                             pqindx3 = (indx + w1 - 1) / 2;
                         col < tilecols - 4;
                         col += 2, indx += 2, ++pqindx, ++pqindx2, ++pqindx3) {

                        // Refined P/Q diagonal local discrimination
                        float PQ_Central_Value = PQ_Dir[pqindx];
                        float PQ_Neighbourhood_Value =
                            0.25f * (PQ_Dir[pqindx2] + PQ_Dir[pqindx2 + 1] +
                                     PQ_Dir[pqindx3] + PQ_Dir[pqindx3 + 1]);

                        float PQ_Disc =
                            (std::fabs(0.5f - PQ_Central_Value) <
                             std::fabs(0.5f - PQ_Neighbourhood_Value))
                                ? PQ_Neighbourhood_Value
                                : PQ_Central_Value;

                        // Diagonal gradients
                        float NW_Grad =
                            eps +
                            std::fabs(rgb[c][indx - w1 - 1] - rgb[c][indx + w1 + 1]) +
                            std::fabs(rgb[c][indx - w1 - 1] - rgb[c][indx - w3 - 3]) +
                            std::fabs(rgb[1][indx] - rgb[1][indx - w2 - 2]);
                        float NE_Grad =
                            eps +
                            std::fabs(rgb[c][indx - w1 + 1] - rgb[c][indx + w1 - 1]) +
                            std::fabs(rgb[c][indx - w1 + 1] - rgb[c][indx - w3 + 3]) +
                            std::fabs(rgb[1][indx] - rgb[1][indx - w2 + 2]);
                        float SW_Grad =
                            eps +
                            std::fabs(rgb[c][indx - w1 + 1] - rgb[c][indx + w1 - 1]) +
                            std::fabs(rgb[c][indx + w1 - 1] - rgb[c][indx + w3 - 3]) +
                            std::fabs(rgb[1][indx] - rgb[1][indx + w2 - 2]);
                        float SE_Grad =
                            eps +
                            std::fabs(rgb[c][indx - w1 - 1] - rgb[c][indx + w1 + 1]) +
                            std::fabs(rgb[c][indx + w1 + 1] - rgb[c][indx + w3 + 3]) +
                            std::fabs(rgb[1][indx] - rgb[1][indx + w2 + 2]);

                        // Diagonal colour differences
                        float NW_Est = rgb[c][indx - w1 - 1] - rgb[1][indx - w1 - 1];
                        float NE_Est = rgb[c][indx - w1 + 1] - rgb[1][indx - w1 + 1];
                        float SW_Est = rgb[c][indx + w1 - 1] - rgb[1][indx + w1 - 1];
                        float SE_Est = rgb[c][indx + w1 + 1] - rgb[1][indx + w1 + 1];

                        // P/Q estimations
                        float P_Est =
                            (NW_Grad * SE_Est + SE_Grad * NW_Est) / (NW_Grad + SE_Grad);
                        float Q_Est =
                            (NE_Grad * SW_Est + SW_Grad * NE_Est) / (NE_Grad + SW_Grad);

                        // R@B and B@R interpolation
                        rgb[c][indx] = rgb[1][indx] + intp(PQ_Disc, Q_Est, P_Est);
                    }
                }

                // Step 4.3: Populate the red and blue channels at green CFA
                // positions
                for (int row = 4; row < tileRows - 4; ++row) {
                    for (int col = 4 + (fc(cfarray, row, 1) & 1),
                             indx = row * tileSize + col;
                         col < tilecols - 4; col += 2, indx += 2) {

                        // Refined vertical and horizontal local discrimination
                        float VH_Central_Value = VH_Dir[indx];
                        float VH_Neighbourhood_Value =
                            0.25f * ((VH_Dir[indx - w1 - 1] + VH_Dir[indx - w1 + 1]) +
                                     (VH_Dir[indx + w1 - 1] + VH_Dir[indx + w1 + 1]));

                        float VH_Disc =
                            (std::fabs(0.5f - VH_Central_Value) <
                             std::fabs(0.5f - VH_Neighbourhood_Value))
                                ? VH_Neighbourhood_Value
                                : VH_Central_Value;
                        float rgb1 = rgb[1][indx];
                        float N1 = eps + std::fabs(rgb1 - rgb[1][indx - w2]);
                        float S1 = eps + std::fabs(rgb1 - rgb[1][indx + w2]);
                        float W1 = eps + std::fabs(rgb1 - rgb[1][indx - 2]);
                        float E1 = eps + std::fabs(rgb1 - rgb[1][indx + 2]);

                        float rgb1mw1 = rgb[1][indx - w1];
                        float rgb1pw1 = rgb[1][indx + w1];
                        float rgb1m1 = rgb[1][indx - 1];
                        float rgb1p1 = rgb[1][indx + 1];
                        for (int c = 0; c <= 2; c += 2) {
                            // Cardinal gradients
                            float SNabs =
                                std::fabs(rgb[c][indx - w1] - rgb[c][indx + w1]);
                            float EWabs =
                                std::fabs(rgb[c][indx - 1] - rgb[c][indx + 1]);
                            float N_Grad =
                                N1 + SNabs +
                                std::fabs(rgb[c][indx - w1] - rgb[c][indx - w3]);
                            float S_Grad =
                                S1 + SNabs +
                                std::fabs(rgb[c][indx + w1] - rgb[c][indx + w3]);
                            float W_Grad =
                                W1 + EWabs +
                                std::fabs(rgb[c][indx - 1] - rgb[c][indx - 3]);
                            float E_Grad =
                                E1 + EWabs +
                                std::fabs(rgb[c][indx + 1] - rgb[c][indx + 3]);

                            // Cardinal colour differences
                            float N_Est = rgb[c][indx - w1] - rgb1mw1;
                            float S_Est = rgb[c][indx + w1] - rgb1pw1;
                            float W_Est = rgb[c][indx - 1] - rgb1m1;
                            float E_Est = rgb[c][indx + 1] - rgb1p1;

                            // Vertical and horizontal estimations
                            float V_Est =
                                (N_Grad * S_Est + S_Grad * N_Est) / (N_Grad + S_Grad);
                            float H_Est =
                                (E_Grad * W_Est + W_Grad * E_Est) / (E_Grad + W_Grad);

                            // R@G and B@G interpolation
                            rgb[c][indx] = rgb1 + intp(VH_Disc, H_Est, V_Est);
                        }
                    }
                }

                // For the outermost tiles in all directions we can use a smaller
                // border margin
                const int firstVertical =
                    rowStart + ((tr == 0) ? rcdBorder : tileBorder);
                const int lastVertical =
                    rowEnd - ((tr == numTh - 1) ? rcdBorder : tileBorder);
                const int firstHorizontal =
                    colStart + ((tc == 0) ? rcdBorder : tileBorder);
                const int lastHorizontal =
                    colEnd - ((tc == numTw - 1) ? rcdBorder : tileBorder);
                for (int row = firstVertical; row < lastVertical; ++row) {
                    for (int col = firstHorizontal; col < lastHorizontal; ++col) {
                        int idx = (row - rowStart) * tileSize + col - colStart;
                        // 注 3: RT ×scale(65536) 移除, 输出域 [0,1]
                        red[row][col] = std::max(0.f, rgb[0][idx]);
                        green[row][col] = std::max(0.f, rgb[1][idx]);
                        blue[row][col] = std::max(0.f, rgb[2][idx]);
                    }
                }
            }
        }

        free(cfa);
        free(rgb);
        free(VH_Dir);
        free(PQ_Dir);
        free(P_CDiff_Hpf);
        free(Q_CDiff_Hpf);
    }

    border_interpolate(width, height, rcdBorder, rawData, red, green, blue,
                       cfarray);

    // pixo 侧新增: 平面 → (H,W,3) HWC 交错 (RT 原文输出为成员平面, 无此段)
    const size_t rowLen = static_cast<size_t>(width) * 3;
#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (int row = 0; row < height; ++row) {
        const float* rp = &redPlane[static_cast<size_t>(row) * width];
        const float* gp = &greenPlane[static_cast<size_t>(row) * width];
        const float* bp = &bluePlane[static_cast<size_t>(row) * width];
        float* op = out + static_cast<size_t>(row) * rowLen;
        for (int col = 0; col < width; ++col) {
            op[col * 3 + 0] = rp[col];
            op[col * 3 + 1] = gp[col];
            op[col * 3 + 2] = bp[col];
        }
    }

    return PixoRenderOk;
}
