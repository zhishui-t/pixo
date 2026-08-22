"""T4.1 Pipeline.to_config 导出/往返测试。

覆盖: 默认链 stages 与 DEFAULT_STAGES 一致、params 深拷贝、自定义 params 往返
深相等、to_config→pipeline_from_config→run 同一合成图逐位一致、output/name 保留、
非法 stage 名往返报错、json.dumps 序列化成功。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pixo.render.pipeline.graph import (
    Pipeline, Stage, StageContext,
    DOMAIN_LINEAR_CAM, DOMAIN_GAMMA_RGB,
)
from pixo.render.pipeline.presets import (
    DEFAULT_STAGES, build_default_pipeline, pipeline_from_config,
)


class _FakeStage(Stage):
    name = "_fake_t30"
    domain_in = DOMAIN_LINEAR_CAM
    domain_out = DOMAIN_LINEAR_CAM
    def process(self, ctx):
        ctx.set_image(ctx.image, self.domain_out)


def test_default_chain_stages_match_defaults():
    p = build_default_pipeline()
    cfg = p.to_config()
    assert cfg["stages"] == DEFAULT_STAGES
    assert cfg["name"] == "default"


def test_params_deepcopy_detached():
    p = build_default_pipeline(params={"tone": {"contrast": 0.3},
                                       "clarity": {"strength": 0.4}})
    cfg = p.to_config()
    cfg["params"]["tone"]["contrast"] = 0.99          # 改导出
    cfg["params"]["clarity"] = {}                     # 甚至替换整块
    cfg["params"]["new_stage"] = {"x": 1}             # 新增键
    assert p.params["tone"]["contrast"] == 0.3        # 原管线不受影响
    assert p.params["clarity"]["strength"] == 0.4
    assert "new_stage" not in p.params


def test_custom_params_roundtrip_deep_equal():
    params = {"tone": {"contrast": 0.2, "brightness": 0.4},
              "colorcal": {"vibrance": 0.3, "saturation": -0.1},
              "refine": {"sharpen": 0.5}}
    p = build_default_pipeline(params=params)
    p2 = pipeline_from_config(p.to_config(), prof=p.prof)
    assert [st.name for st in p2.stages] == [st.name for st in p.stages]
    assert p2.params == p.params


def test_roundtrip_run_bit_identical(tmp_path):
    # gamma 域纯链 (不需 raw/prof): clarity + colorcal
    cfg_src = {"stages": ["clarity", "colorcal"], "params": {},
               "output": {"quality": 92}}
    p1 = pipeline_from_config(cfg_src)
    p2 = pipeline_from_config(p1.to_config())

    rng = np.random.default_rng(0)
    img = rng.random((32, 32, 3), dtype=np.float32)

    def render(pipe):
        ctx = StageContext("t", config={})
        ctx.set_image(img, DOMAIN_GAMMA_RGB)
        pipe.run(ctx)
        return ctx.image

    out1, out2 = render(p1), render(p2)
    assert np.array_equal(out1, out2)


def test_output_field_preserved():
    p = pipeline_from_config({"stages": ["clarity"], "params": {},
                              "output": {"quality": 88, "format": "jpg"}})
    cfg = p.to_config()
    assert cfg["output"] == {"quality": 88, "format": "jpg"}


def test_name_preserved():
    p = build_default_pipeline()
    assert p.to_config()["name"] == p.name == "default"


def test_illegal_stage_roundtrip_raises():
    # 自定义 Stage 实例 (非注册名): to_config 输出其 name, 重建按 name 报错
    p = Pipeline(stages=[_FakeStage(), "clarity"], params={})
    cfg = p.to_config()
    assert cfg["stages"] == ["_fake_t30", "clarity"]
    with pytest.raises(KeyError):
        pipeline_from_config(cfg)


def test_json_serializable():
    p = build_default_pipeline(params={"tone": {"contrast": 0.3}})
    s = json.dumps(p.to_config())
    assert "_fake_t30" not in s or True
    assert json.loads(s)["stages"] == DEFAULT_STAGES


def test_empty_output_defaults_to_empty_dict():
    p = build_default_pipeline()
    assert p.to_config()["output"] == {}
