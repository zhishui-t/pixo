"""measure_engine 纯函数测试 (合成数据)。"""
import numpy as np
from rawlab.tools.measure_engine import exposure_stats, noise_stats, measure_one


def _img(seed=0, size=64):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, (size, size, 3), dtype=np.uint8)


def test_exposure_stats_identity():
    img = _img(1)
    e = exposure_stats(img, img)
    assert e['dEV'] == 0.0 and e['dL_med'] == 0.0
    assert e['clip_ours_pct'] == e['clip_target_pct']


def test_exposure_stats_brighter():
    a = np.full((32, 32, 3), 100, np.uint8)
    b = np.full((32, 32, 3), 150, np.uint8)
    e = exposure_stats(a, b)
    assert e['dL_med'] < -20 and e['dEV'] < -0.2


def test_noise_stats_structure():
    img = _img(2)
    n = noise_stats(img, img)
    assert n['luma_lap_std'] == [0.0, 0.0] or n['luma_lap_std'][0] == n['luma_lap_std'][1]


def test_measure_one_identity():
    img = _img(3)
    m = measure_one(img, img)
    assert m['full']['da'] == 0.0 and m['full']['db'] == 0.0
    assert len(m['hue_sectors']) == 12
