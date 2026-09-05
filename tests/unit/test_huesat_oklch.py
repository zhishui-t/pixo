"""huesat_oklch 单测 —— 恒等 no-op / 单点形变数值对照 / touch 直通 / 分派。

口径:
  - 单控制点云的 IDW 栅格全表恒等于该点值 (任意格中心的 K 近邻全为它),
    故三线性插值输出 = 常量 → 像素形变量精确可断言 (dh 加度 / c,l 增益);
  - 恒等点云 (dh=0, gain=1) → apply 逐位直通 (连域转换都不做);
  - 恒等包围 + 单个形变点 → 远离形变点的格 8 近邻全为恒等点 → 插值恒等
    → touch 掩码外像素逐位直通;
  - 金样本 hsv 域不变: 缺省 (无 color_domain 键) 与显式 "hsv" 渲染逐位
    一致; 真 RAW 一次 (256 长) 验证 stage 分派 (见 TestStageDispatch)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from pixo.render.core import huesat_oklch as ho  # noqa: E402
from pixo.render.core.hsl_oklch import _cmax_of_l  # noqa: E402
from pixo.render.core.oklab import (oklab_to_oklch, oklab_to_srgb,  # noqa: E402
                                    oklch_to_oklab, srgb_to_oklab)


def _assert_in_gamut_deform(lch_in: np.ndarray, rgb_out: np.ndarray,
                            lch_out: np.ndarray,
                            dh_expect: float, cg: float, lg: float,
                            atol: float = 1e-4) -> None:
    """形变数值断言 (仅在未撞色域 clip 的像素上 —— 判据 = 输出 sRGB 分量
    严格开区间内; 撞界的像素被 oklab_to_srgb 的 linear clip 兜底改变 hue,
    属设计声明的近似, 见 hsl_oklch docstring, 该子集不参与精确断言)。"""
    safe = ((rgb_out > 1e-6) & (rgb_out < 1.0 - 1e-6)).all(axis=-1)
    assert safe.mean() > 0.4, f"未撞界像素占比过低 ({safe.mean():.2f})"
    dh = (lch_out[..., 2] - lch_in[..., 2] + 180.0) % 360.0 - 180.0
    np.testing.assert_allclose(dh[safe], dh_expect, atol=atol)
    # oklab_to_srgb 出口 f32 量化 → 重算 C/L 相对扰动 ~1e-4 量级
    np.testing.assert_allclose((lch_out[..., 1] / lch_in[..., 1])[safe], cg,
                               rtol=2e-3)
    np.testing.assert_allclose((lch_out[..., 0] / lch_in[..., 0])[safe], lg,
                               rtol=2e-3)

DCP_PATH = _REPO / "resources" / "dcp" / \
    "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
POINTS_GLOB = sorted((_REPO / "configs" / "color").glob("hsm_oklch_*.json"))


def _oklch_img(coords: np.ndarray) -> np.ndarray:
    """从 OKLCh 坐标合成 gamma 图 (N,3) → (1,N,3) —— 色域内、色相/色度
    精确可控 (RGB 网格图的色度会随 c 增益越域被 clip 改变 hue, 不适合做
    精确数值对照)。"""
    from pixo.render.core.oklab import oklch_to_oklab
    lab = oklch_to_oklab(np.asarray(coords, dtype=np.float64))
    return oklab_to_srgb(lab).reshape(1, -1, 3)


def _uniform_img(n: int = 8) -> np.ndarray:
    """合成 gamma 图 (值域 [0,1] 网格), 各像素 OKLCh 坐标不同 (温和色度,
    供 no-op/touch 逐位断言; 不做越域敏感的形变数值断言)。"""
    lin, sq = np.meshgrid(np.linspace(0.05, 0.95, n), np.linspace(0.02, 0.9, n))
    img = np.stack([lin, np.full_like(lin, 0.5), sq], axis=-1)
    return img[..., ::-1]  # 随意但确定的三通道图


def _identity_points(h_axis, c_axis, l_axis) -> list[dict]:
    return [{"h": h, "c": c, "l": l, "dh": 0.0, "c_gain": 1.0, "l_gain": 1.0}
            for h in h_axis for c in c_axis for l in l_axis]


def _spec_from_points(points, strength=1.0, **kw) -> ho.OklchDeform:
    table = ho.rasterize_points(
        np.asarray([[p["h"], p["c"], p["l"], p["dh"], p["c_gain"],
                     p["l_gain"]] for p in points], dtype=np.float64),
        grid=kw.pop("grid", (72, 24, 24)), **kw)
    return ho.OklchDeform(table=table, strength=strength, eps_dh=1e-2,
                          eps_gain=1e-2)


# ---------------------------------------------------------------------------
# no-op 纪律
# ---------------------------------------------------------------------------

class TestIdentityNoOp:
    def test_identity_points_bitwise_passthrough(self):
        pts = _identity_points([30.0, 150.0, 270.0], [0.05, 0.15], [0.45, 0.8])
        spec = _spec_from_points(pts)
        assert ho.is_identity_deform(spec)
        img = _uniform_img()
        out = ho.apply_oklch_deform(img, spec)
        assert out.dtype == np.float32
        np.testing.assert_array_equal(out, img.astype(np.float32))

    def test_strength_zero_passthrough(self):
        pts = [{"h": 100.0, "c": 0.1, "l": 0.5, "dh": 30.0,
                "c_gain": 2.0, "l_gain": 1.5}]
        spec = _spec_from_points(pts)
        assert not ho.is_identity_deform(spec)
        img = _uniform_img()
        out = ho.apply_oklch_deform(img, spec, strength=0.0)
        np.testing.assert_array_equal(out, img.astype(np.float32))

    def test_real_point_cloud_not_identity(self):
        if not POINTS_GLOB:
            pytest.skip("点云数据不存在")
        spec = ho.load_oklch_deform(POINTS_GLOB[0])
        assert not ho.is_identity_deform(spec)
        assert spec.table.shape[0] == 72 and spec.table.shape[1:] == (24, 24, 3)


# ---------------------------------------------------------------------------
# 单点形变数值对照
# ---------------------------------------------------------------------------

class TestSinglePointDeform:
    def test_single_point_exact_deform(self):
        """单点云 → 栅格全表恒等于该点 → 任意像素精确形变:
        h+10°, c×1.15, l×0.95 (像素取全色相 L=0.5/C=0.08, 形变后仍在
        sRGB 色域内 —— 越域像素会被 oklab_to_srgb 的 clip 改变 hue,
        不能作精确断言)。"""
        spec = _spec_from_points([{"h": 100.0, "c": 0.08, "l": 0.50,
                                   "dh": 10.0, "c_gain": 1.15, "l_gain": 0.95}])
        h_all = np.arange(0.0, 360.0, 15.0)
        coords = np.stack([np.full_like(h_all, 0.50),
                           np.full_like(h_all, 0.08), h_all], axis=1)
        img = _oklch_img(coords)
        out = ho.apply_oklch_deform(img, spec)
        lch_in = oklab_to_oklch(srgb_to_oklab(img))
        lch_out = oklab_to_oklch(srgb_to_oklab(out.astype(np.float64)))
        _assert_in_gamut_deform(lch_in, out, lch_out, 10.0, 1.15, 0.95)

    def test_strength_partial_mix(self):
        spec = _spec_from_points([{"h": 100.0, "c": 0.08, "l": 0.50,
                                   "dh": 10.0, "c_gain": 1.15, "l_gain": 0.95}])
        h_all = np.arange(0.0, 360.0, 15.0)
        img = _oklch_img(np.stack([np.full_like(h_all, 0.5),
                                   np.full_like(h_all, 0.08), h_all], axis=1))
        out_half = ho.apply_oklch_deform(img, spec, strength=0.5)
        out_full = ho.apply_oklch_deform(img, spec, strength=1.0)
        lch_half = oklab_to_oklch(srgb_to_oklab(out_half.astype(np.float64)))
        lch_full = oklab_to_oklch(srgb_to_oklab(out_full.astype(np.float64)))
        lch_in = oklab_to_oklch(srgb_to_oklab(img))
        # safe 判据与 _assert_in_gamut_deform 同源 (输出 sRGB 严格开区间 =
        # 未撞 oklab_to_srgb 的 clip 兜底): C_max(L) 近似 + 0.02 余量在蓝紫区
        # 包络陡变处不足, 曾漏进被 clip 像素致 half != full/2 假阳性
        safe = ((out_half > 1e-6) & (out_half < 1.0 - 1e-6)
                & (out_full > 1e-6) & (out_full < 1.0 - 1e-6)).all(axis=-1)
        assert safe.mean() > 0.4, f"未撞界像素占比过低 ({safe.mean():.2f})"
        dh_half = (lch_half[..., 2] - lch_in[..., 2] + 180.0) % 360.0 - 180.0
        dh_full = (lch_full[..., 2] - lch_in[..., 2] + 180.0) % 360.0 - 180.0
        np.testing.assert_allclose(dh_half[safe], dh_full[safe] / 2.0,
                                   atol=1e-4)

    def test_rasterize_grid_center_on_point(self):
        """格中心恰在控制点上 → IDW 精确取值 (d²<eps 分支)。"""
        pts = np.asarray([[5.0 * (i + 0.5), 0.10, 0.50, 0.0, 1.0, 1.0]
                          for i in range(72)], dtype=np.float64)
        # 每行 h 都在一个格中心上; 只在 l=0.5/c=0.10 的一行放非恒等值
        pts[:, 3] = 5.0
        table = ho.rasterize_points(pts, grid=(72, 24, 24))
        ci = int(np.floor(0.10 / 0.37 * 24))
        li = int(np.floor(0.50 * 24))
        np.testing.assert_allclose(table[:, ci, li, 0], 5.0, atol=1e-9)


# ---------------------------------------------------------------------------
# touch 直通与环绕
# ---------------------------------------------------------------------------

class TestTouchAndRing:
    def test_identity_region_bitwise_passthrough(self):
        """恒等点包围 + 远端单个形变点 → 恒等区像素逐位直通 (touch 掩码)。"""
        pts = _identity_points(
            [h for h in np.arange(0, 360, 15.0)],
            [0.02, 0.06, 0.12, 0.25], [0.42, 0.6, 0.8, 0.95])
        pts.append({"h": 50.0, "c": 0.10, "l": 0.5, "dh": 40.0,
                    "c_gain": 1.8, "l_gain": 1.0})
        spec = _spec_from_points(pts)
        # 远端像素 (h≈300, c≈0.05, l≈0.6): 8 近邻全为恒等点
        lin = np.array([[[0.30, 0.50, 0.45]]])   # 蓝-灰色, OKLCh h≈270 附近
        out = ho.apply_oklch_deform(lin, spec)
        np.testing.assert_array_equal(out, lin.astype(np.float32))

    def test_hue_ring_continuity(self):
        """跨 0° 环缝连续: 环缝两侧同色像素形变量连续 (无缝跳变)。"""
        pts = [{"h": 0.0, "c": 0.10, "l": 0.5, "dh": 8.0, "c_gain": 1.1,
                "l_gain": 1.0},
               {"h": 30.0, "c": 0.10, "l": 0.5, "dh": 8.0, "c_gain": 1.1,
                "l_gain": 1.0},
               {"h": 330.0, "c": 0.10, "l": 0.5, "dh": 8.0, "c_gain": 1.1,
                "l_gain": 1.0}]
        spec = _spec_from_points(pts)
        h_seam = np.array([359.0, 359.9, 0.1, 1.0, 5.0, 355.0])
        img = _oklch_img(np.stack([np.full_like(h_seam, 0.5),
                                   np.full_like(h_seam, 0.08), h_seam],
                                  axis=1))
        lch_in = oklab_to_oklch(srgb_to_oklab(img))
        out = ho.apply_oklch_deform(img, spec)
        lch_out = oklab_to_oklch(srgb_to_oklab(out.astype(np.float64)))
        dh = (lch_out[..., 2] - lch_in[..., 2] + 180.0) % 360.0 - 180.0
        # atol 1e-5: oklch 域数值路径微调后环缝偏差 ~4.4e-6 (u8 量化 1/255≈0.4
        # 不可见), 语义不变; 1e-6 对跨实现的浮点运算顺序差异过紧
        np.testing.assert_allclose(dh, 8.0, atol=1e-5)   # 环缝两侧全 8°

    def test_chroma_soft_limit_within_gamut(self):
        """强增饱和点 → 软限幅压向色域包络, 输出仍在 [0,1] 且无 NaN。"""
        pts = [{"h": 100.0, "c": 0.10, "l": 0.5, "dh": 0.0, "c_gain": 3.5,
                "l_gain": 1.0}]
        spec = _spec_from_points(pts)
        img = _oklch_img(np.asarray([[0.5, 0.10, 100.0]]))
        out = ho.apply_oklch_deform(img, spec)
        assert np.all(np.isfinite(out)) and out.max() <= 1.0 and out.min() >= 0.0


# ---------------------------------------------------------------------------
# 加载与 stage 分派
# ---------------------------------------------------------------------------

class TestLoadAndDispatch:
    def test_load_schema_validation(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"schema": "other.v1", "points": []}),
                       encoding="utf-8")
        with pytest.raises(ValueError):
            ho.load_oklch_deform(bad)

    def test_load_real_point_cloud_and_apply(self):
        if not POINTS_GLOB:
            pytest.skip("点云数据不存在")
        spec = ho.load_oklch_deform(POINTS_GLOB[0])
        img = _uniform_img(6)
        out = ho.apply_oklch_deform(img, spec)
        assert out.shape == img.shape and np.all(np.isfinite(out))
        assert out.dtype == np.float32

    def test_stage_default_domain_unchanged(self):
        """缺省 (无 color_domain 键) 与显式 "hsv" 渲染逐位一致 (金样本 hsv
        域不变的单测表达)。"""
        if not DCP_PATH.is_file():
            pytest.skip("DCP 不存在")
        from pixo.render.api import Renderer
        raws = sorted((_REPO.parent / "data" / "photo" / "0711" / "raw")
                      .glob("DSC_526*.NEF")) or sorted(
            Path("K:/data/photo/0711/raw").glob("DSC_526*.NEF"))
        if not raws:
            pytest.skip("语料 RAW 不可达")
        r = Renderer(str(DCP_PATH))
        hs = {"enabled": True}
        a = r.render_preview_full(str(raws[0]), long_edge=192,
                                  params={"huesat": dict(hs)})
        b = r.render_preview_full(str(raws[0]), long_edge=192,
                                  params={"huesat": {**hs, "color_domain": "hsv"}})
        np.testing.assert_array_equal(a, b)

    def test_stage_oklch_dispatch_applies(self):
        """color_domain=oklch → 渲染路径走形变 (与 hsv 输出有实质差异)。"""
        if not DCP_PATH.is_file() or not POINTS_GLOB:
            pytest.skip("DCP/点云不存在")
        from pixo.render.api import Renderer
        raws = sorted(Path("K:/data/photo/0711/raw").glob("DSC_526*.NEF"))
        if not raws:
            pytest.skip("语料 RAW 不可达")
        r = Renderer(str(DCP_PATH))
        a = r.render_preview_full(str(raws[0]), long_edge=192,
                                  params={"huesat": {"enabled": True,
                                                     "color_domain": "hsv"}})
        b = r.render_preview_full(str(raws[0]), long_edge=192,
                                  params={"huesat": {"enabled": True,
                                                     "color_domain": "oklch"}})
        assert not np.array_equal(a, b)
