"""评分器 sRGB 输入边界守卫 —— oklch/hsv 编辑域不得改变 scorer 输入路径。

外部评审假设: "loop 内评分始终接 sRGB 预览图, Oklab 仅编辑中间态"。
本文件把该假设固化为回归守卫。断言依据 (行号为当前源码; 若下列任一处
漂移, 本文件应同步评审):

  被评分图的生产链 (src/pixo/pipeline/loop.py):
    :972       preview_img = backend.render_preview(params, ...) —— 唯一产地;
    :1016      aesthetic = self._score_aesthetic(preview_img, masks) —— 原变量直传;
    :710/:715  raw = self.aesthetic_scorer(image, masks[/image]) —— 零变换透传;
    :326-327   SyntheticRenderBackend._render 单一出口
               ``(clip(out,0,1)*255+0.5).astype(np.uint8)``
               ("最终应为 gamma 域 0..1；转 8-bit RGB 供 Vision 使用") ——
               出口语句不含 params ⇒ 编码路径结构性域无关。

  域选择的真实落点 (render 侧, 不在 loop):
    modules/hsl.py:30/51-53  color_domain ("hsv"|"oklch") 决定 band 归属与内核;
    modules/hsl.py:36-38     wants 仅 enabled=True 进入 process;
    modules/hsl.py:58-64     hsv 内核 hsl_adjust_rgb / oklch 内核 oklch_adjust_rgb
                             (域只改像素内容, 改不到 loop 的评分输入)。

  评分器输入约定 (src/pixo/vision/aesthetic.py):
    :220-224  score() u8 原样接受; float 才 clip[0,1]→u8 —— 契约输入是
              sRGB u8 (或 f01 gamma); linear/Oklab 中间态不在契约内。

守卫三组:
  1. 域真实生效   —— oklch/hsv 两域渲染输出彼此不同且均异于 hsl 关闭基线
                     (证明两条内核都被走到, 守卫不是空转; bands 需显式非零,
                     hsl.py:37 注记缺省/全 0 bands 恒等 no-op);
  2. 编码域无关   —— 两域 render_preview 输出 dtype/形状/值域完全一致
                     (sRGB u8, loop.py:327 出口);
  3. loop 接线    —— 记录型后端 + 记录型 scorer 跑 SinglePhotoLoop
                     (color_domain=hsv / oklch 各一遍): scorer 收到的对象与
                     后端产出对象恒等 (``is``, :972→:1016 直传), dtype/值域/
                     通道数跨域一致。

结论纪律: 若守卫转红, 优先怀疑 loop 在 :972 与 :1016 之间插入了域相关
变换 (缺陷), 如实报缺陷; 本文件只守卫不修码。
"""
from __future__ import annotations

import json

import numpy as np

from pixo.pipeline.loop import SinglePhotoLoop, SyntheticRenderBackend
from pixo.vision import MockSegmenter


# ---------------------------------------------------------------------------
# 公共装置
# ---------------------------------------------------------------------------

def _color_image() -> np.ndarray:
    """含大块高饱和红色区 + 中性灰底的合成图 (linear f01, 后端输入契约)。

    红区保证 hsl 两域内核都有可调像素 (中性灰 S≈0 是两域共同保护区)。
    """
    img = np.full((64, 64, 3), 0.25, dtype=np.float32)
    img[8:56, 8:32] = (0.80, 0.10, 0.10)   # 红
    img[8:56, 40:60] = (0.15, 0.45, 0.75)  # 蓝绿
    return img


def _hsl_params(domain: str) -> dict:
    """显式非零 band 的 hsl 参数 (缺省 bands 全 0 恒等, hsl.py:37)。

    Pipeline 参数面 bands 契约为 **JSON 字符串** (hsl.py:27 schema 注记,
    _resolve_bands 内 json.loads; 裸 list[dict] 过不了 float_or_str 校验)。
    """
    band = {"name": "red", "hue_center": 10.0, "width": 120.0,
            "hue_shift": 45.0, "saturation": 60.0, "luminance": 30.0,
            "domain": domain}
    return {"hsl": {"enabled": True, "color_domain": domain,
                    "bands": json.dumps([band])}}


def _render_backend() -> SyntheticRenderBackend:
    """compose(线性域)→tone(线性→gamma, tone_map.py:282-283)→hsl(gamma,
    hsl.py:19-20) 的最小真实管线; 阶段序按注册 order 升序。"""
    return SyntheticRenderBackend(_color_image(),
                                  stages=("compose", "tone", "hsl"))


class _RecordingBackend:
    """记录 render_preview/render_full 返回对象的透传代理 (其余属性转发)。"""

    def __init__(self, inner: SyntheticRenderBackend) -> None:
        object.__setattr__(self, "_inner", inner)
        self.previews: list[np.ndarray] = []

    def render_preview(self, params, long_edge=512):
        img = self._inner.render_preview(params, long_edge=long_edge)
        self.previews.append(img)
        return img

    def render_full(self, params):
        img = self._inner.render_full(params)
        self.previews.append(img)
        return img

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __setattr__(self, name, value):
        if name in ("_inner", "previews"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._inner, name, value)   # state_extras 等注入转发内层


def _run_loop(domain: str):
    """SinglePhotoLoop 单轮跑指定 color_domain, 返回 (scorer 收到图, 后端产出图, 结果)。"""
    backend = _RecordingBackend(_render_backend())
    seen: list[np.ndarray] = []

    def scorer(image_rgb, masks=None):
        seen.append(image_rgb)
        return 0.5

    loop = SinglePhotoLoop(
        render_backend=backend,
        segmenter=MockSegmenter(),
        max_iterations=1,
        preview_long_edge=64,
        prompts=["face", "sky", "plant"],
        aesthetic_scorer=scorer,
    )
    result = loop.run("scorer_input_domain", image_rgb=_color_image(),
                      params=_hsl_params(domain))
    return seen, backend.previews, result


# ---------------------------------------------------------------------------
# 1. 域真实生效 (守卫非空转的前提)
# ---------------------------------------------------------------------------

def test_domain_kernels_engaged():
    """oklch/hsv 两域渲染输出彼此不同且均异于 hsl 关闭基线。"""
    backend = _render_backend()
    off = backend.render_preview({"hsl": {"enabled": False}}, long_edge=64)
    outs = {d: backend.render_preview(_hsl_params(d), long_edge=64)
            for d in ("hsv", "oklch")}
    for d, img in outs.items():
        assert not np.array_equal(img, off), \
            f"color_domain={d} 输出与 hsl 关闭基线逐位相同 —— 内核未生效, 守卫空转"
    assert not np.array_equal(outs["hsv"], outs["oklch"]), \
        "hsv 与 oklch 两域输出逐位相同 —— 两内核路径未被区分走到"


# ---------------------------------------------------------------------------
# 2. 编码路径域无关 (loop.py:326-327 单一出口的结构性断言)
# ---------------------------------------------------------------------------

def test_preview_encoding_domain_invariant():
    """两域 render_preview 输出 dtype/形状/值域一致 (sRGB u8 gamma 编码)。"""
    backend = _render_backend()
    for domain in ("hsv", "oklch"):
        img = backend.render_preview(_hsl_params(domain), long_edge=64)
        assert img.dtype == np.uint8, \
            f"color_domain={domain}: render_preview 输出 dtype={img.dtype}, " \
            "背离 loop.py:327 的 u8 单一出口"
        assert img.ndim == 3 and img.shape[2] == 3
        assert int(img.min()) >= 0 and int(img.max()) <= 255, \
            f"color_domain={domain}: 值域 [{img.min()}, {img.max()}] 越出 u8 域"


# ---------------------------------------------------------------------------
# 3. loop 接线守卫 (scorer 收到的就是后端产出的 sRGB u8 预览)
# ---------------------------------------------------------------------------

def test_loop_scores_the_preview_image():
    """scorer 收到对象与后端产出恒等, dtype/值域/通道数跨两域一致。"""
    for domain in ("hsv", "oklch"):
        seen, previews, result = _run_loop(domain)
        assert result.state == "ACCEPTED"
        assert seen, f"color_domain={domain}: scorer 未被调用"
        assert len(seen) == len(previews), \
            "scorer 调用数与后端渲染数不配对 (评分读的不是本轮渲染?)"
        for i, (img, src) in enumerate(zip(seen, previews)):
            assert img is src, \
                (f"color_domain={domain} 第 {i} 次: scorer 收到的不是 "
                 "render_preview 返回对象 —— loop 在 :972 与 :1016 之间引入了"
                 "变换/拷贝, 评审假设被破坏, 按缺陷上报")
            assert img.dtype == np.uint8, \
                f"color_domain={domain} 第 {i} 次: scorer 输入 dtype={img.dtype}"
            assert img.ndim == 3 and img.shape[2] in (3, 4)
            assert int(img.min()) >= 0 and int(img.max()) <= 255


def test_scorer_input_encoding_consistent_across_domains():
    """跨域汇总: 所有 scorer 输入的 dtype/值域类别一致 (sRGB u8)。"""
    pools = [_run_loop(d)[:2] for d in ("hsv", "oklch")]
    seen_all = [img for seen, _ in pools for img in seen]
    assert seen_all
    dtypes = {img.dtype for img in seen_all}
    assert dtypes == {np.dtype(np.uint8)}, \
        f"两域 scorer 输入 dtype 不一致: {dtypes}"
    for img in seen_all:
        assert int(img.min()) >= 0 and int(img.max()) <= 255
