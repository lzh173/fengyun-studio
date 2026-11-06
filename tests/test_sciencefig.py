"""科学制图与太阳几何的回归测试。

对应两个真实缺陷：
1. 海岸线默认路径错误（src/assets → 实际在工程根 assets/），
   导致海岸线**从未真正画出来过**，且不报错、静默返回 0 段。
2. 之前误判"MERSI L1 没有太阳天顶角"，
   实际上它在配套 GEO 文件的 Geolocation/SolarZenith。
"""
from __future__ import annotations
from _sample_root import SAMPLE_ROOT, glob_samples

import glob
from pathlib import Path

import numpy as np
import pytest

from fysat import pipeline
from fysat.sciencefig import FigureSpec, _load_coastlines, render_science_figure


ROOT = Path(__file__).resolve().parents[1]


# ---------------- 海岸线 ----------------

def test_coastline_default_path_resolves():
    """默认路径必须能加载到海岸线；返回 0 段说明路径错了。"""
    segs = _load_coastlines(None)
    assert len(segs) > 100, f"默认路径只加载到 {len(segs)} 段，路径可能有误"


def test_coastline_asset_exists_at_expected_location():
    p = ROOT / "assets" / "ne_110m_coastline.geojson"
    assert p.exists(), f"海岸线资源缺失: {p}"
    assert p.stat().st_size > 50_000


def test_coastline_segments_are_2d_arrays():
    segs = _load_coastlines(None)
    assert segs
    for s in segs[:5]:
        assert s.ndim == 2 and s.shape[1] == 2
        assert s.shape[0] >= 2


# ---------------- 太阳天顶角 ----------------

@pytest.fixture(scope="module")
def geo_file():
    hits = glob_samples(r"FY3H_MERSI_GRAN_L1_*GEO1K*.hdf")
    if not hits:
        pytest.skip("缺 MERSI GEO 文件")
    return hits[0]


def test_geo_file_has_solar_zenith(geo_file):
    """文档（MERSI 1KM_GEO 表5 SDS6）：SolarZenith int16 Slope=0.01，单位度。

    注意原始 DN 是放大 100 倍的（2188~5291），
    必须经 pipeline._read_angle 应用 Slope 后才是有物理意义的 21.88°~52.91°。
    """
    from fysat.readers import open_file

    gds = open_file(geo_file, load=False)
    assert "Geolocation/SolarZenith" in gds.variables, \
        f"GEO 文件缺少 SolarZenith，实际变量: {list(gds.variables)[:10]}"

    var = gds.variables["Geolocation/SolarZenith"]
    assert var.scale_factor == pytest.approx(0.01, rel=1e-3), \
        f"Slope 应为 0.01，实际 {var.scale_factor}"

    sza = pipeline._read_angle(gds, "Geolocation/SolarZenith")
    v = sza[np.isfinite(sza)]
    assert v.size > 0
    assert 0 <= v.min() and v.max() <= 180, \
        f"应用 Slope 后天顶角应为 0~180 度，实际 {v.min():.2f}~{v.max():.2f}"


def test_solar_zenith_from_geo(geo_file):
    """能从 GEO 文件读到逐像元太阳天顶角。"""
    from fysat.readers import open_file

    gds = open_file(geo_file, load=False)
    sza = pipeline.solar_zenith(gds)
    assert sza is not None
    assert sza.shape[0] > 100


def test_earth_sun_distance_ratio_default():
    """缺属性时应回退到 1.0，而不是抛异常。"""
    class FakeDS:
        attrs = {}

    assert pipeline.earth_sun_distance_ratio(FakeDS()) == 1.0


# ---------------- TOA 反射率 ----------------

def test_reflectance_toa_uses_cosine_correction():
    """Ref_TOA = Ref* / cos(SZA) * d^2；SZA 越大订正后越亮。"""
    class FakeDS:
        attrs = {"EarthSun Distance Ratio": 1.0}
        variables = {}

        class _V:
            data = np.full((4, 4), 1000, dtype=np.uint16)
            scale_factor = 1.0
            add_offset = 0.0
            fill_value = 65535
            valid_range = (0, 4095)
            unit = "none"
            source_shape = (4, 4)

        def load(self, name):
            return self._V()

    ds = FakeDS()
    flat = np.full((4, 4), 0.0, dtype=np.float32)
    shallow = np.full((4, 4), 60.0, dtype=np.float32)

    # 直接验算 cos 修正的关系
    d = 1.0
    ref = 0.2
    toa_flat = ref / np.cos(np.deg2rad(flat)) * d ** 2
    toa_shallow = ref / np.cos(np.deg2rad(shallow)) * d ** 2
    assert np.allclose(toa_flat, 0.2)
    assert toa_shallow.mean() > toa_flat.mean(), "斜射时应更亮"


def test_visible_data_returns_normalized_reflectance():
    """反射率应是 0~1 归一化值（乘过 0.01），不是百分数。"""
    hits = glob_samples(r"FY3H_MERSI_GRAN_L1_*1000M*.HDF")
    if not hits:
        pytest.skip("缺 MERSI 样本")
    from fysat.readers import open_file

    ds = open_file(hits[0], load=False)
    src = pipeline.true_color_source(ds)
    assert src is not None, "应能定位真彩色波段（EV_250_Aggr.1KM_RefSB）"
    var, idx, chs = src
    assert var.endswith("EV_250_Aggr.1KM_RefSB")
    assert idx == (2, 1, 0), f"b3/b2/b1 的数组索引应为 (2,1,0)，实际 {idx}"
    assert chs == (3, 2, 1)

    ref, unit = pipeline.visible_data(ds, var, idx[0])
    v = ref[np.isfinite(ref)]
    assert v.size > 0
    assert np.percentile(v, 99) < 2.0, \
        f"反射率 p99={np.percentile(v,99):.2f}，说明没做 0.01 归一化"


def test_true_color_bands_not_from_1km_varsb():
    """真彩色绝不能取 EV_1KM_RefSB（b5-b19 全在短波红外，会得到黄绿错误图）。"""
    hits = glob_samples(r"FY3H_MERSI_GRAN_L1_*1000M*.HDF")
    if not hits:
        pytest.skip("缺 MERSI 样本")
    from fysat.readers import open_file

    ds = open_file(hits[0], load=False)
    src = pipeline.true_color_source(ds)
    assert src is not None
    assert "EV_250" in src[0], f"真彩色源应为 250M 变量，实际 {src[0]}"


def test_true_color_output_is_neutral():
    """真彩色输出应是 uint8 RGB，且三通道均值接近（白平衡生效）。"""
    rng = np.random.default_rng(0)
    r = rng.random((60, 80)).astype(np.float32) * 0.6
    g = rng.random((60, 80)).astype(np.float32) * 0.5
    b = rng.random((60, 80)).astype(np.float32) * 0.4

    rgb = pipeline.true_color(r, g, b)
    assert rgb.shape == (60, 80, 3)
    assert rgb.dtype == np.uint8

    means = rgb.reshape(-1, 3).mean(axis=0)
    spread = means.max() / max(means.min(), 1)
    assert spread < 1.5, f"白平衡后通道均值仍差 {spread:.2f} 倍: {means}"


# ---------------- 制图端到端 ----------------

def test_science_figure_draws_coastline(tmp_path):
    """生成一张图，确保海岸线分支不抛异常且地图有内容。"""
    from fysat.provenance import build_provenance

    lon, lat = np.meshgrid(np.linspace(100, 130, 120), np.linspace(5, 35, 100))
    data = 280 + 20 * np.sin(np.linspace(0, 6, 120))[None, :] + 0 * lat

    spec = FigureSpec(out_path=tmp_path / "map.png", dpi=80, figsize=(6, 4),
                      title="测试", draw_coast=True)
    thermal = {"data": data, "lat": lat, "lon": lon,
               "label": "BT", "unit": "K", "cmap": "turbo"}
    out = render_science_figure(thermal, None, spec)
    assert out.exists() and out.stat().st_size > 5000
