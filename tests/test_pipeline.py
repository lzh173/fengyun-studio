"""管线级测试：定标、经纬度清理、区域裁剪、抽稀。

这些测试锁定的是**踩过的坑**，每条都对应一次真实错误：
1. 亮温被当成辐亮度直接显示（0.01~1.5 的荒唐值）
2. 经纬度填充值 -9999.9 没清掉，导致画布范围畸变
3. 400 万像素直接 pcolormesh 慢到不可用
"""
from __future__ import annotations

import glob

import numpy as np
import pytest

from fysat import pipeline
from fysat.model import Geolocation, SatDataset, Variable


# ---------------- 经纬度清理 ----------------

def test_clean_latlon_removes_fill_values():
    lat = np.array([[10.0, -9999.9], [20.0, 30.0]])
    lon = np.array([[100.0, 120.0], [999.0, 130.0]])
    la, lo = pipeline.clean_latlon(lat, lon)

    assert np.isnan(la[0, 1]), "填充值应被清成 NaN"
    assert np.isnan(lo[1, 0])
    assert la[0, 0] == 10.0
    assert lo[1, 1] == 130.0


def test_clean_latlon_rejects_out_of_range():
    lat = np.array([[95.0, -91.0]])
    lon = np.array([[181.0, -181.0]])
    la, lo = pipeline.clean_latlon(lat, lon)
    assert np.isnan(la).all()
    assert np.isnan(lo).all()


def test_clean_latlon_passthrough_when_none():
    la, lo = pipeline.clean_latlon(None, None)
    assert la is None and lo is None


# ---------------- 区域裁剪 ----------------

def test_subset_by_pixels():
    lat = np.arange(100, dtype=float).reshape(10, 10)
    lon = lat.copy()
    data = np.ones((10, 10))

    la, lo, d = pipeline.subset(lat, lon, data, (2, 5, 3, 7))
    assert d.shape == (3, 4)
    assert la[0, 0] == lat[2, 3]


def test_subset_by_extent():
    lon, lat = np.meshgrid(np.arange(100, 120), np.arange(20, 30))
    data = np.arange(200, dtype=float).reshape(10, 20)

    la, lo, d = pipeline.subset_by_extent(lat, lon, data, (104, 109, 22, 27))
    assert d.shape[0] < 10 and d.shape[1] < 20
    assert np.nanmin(lo) >= 104 and np.nanmax(lo) <= 109
    assert np.nanmin(la) >= 22 and np.nanmax(la) <= 27


def test_subset_no_region_returns_input():
    lat = np.zeros((4, 5))
    data = np.ones((4, 5))
    la, lo, d = pipeline.subset(lat, lat, data, None)
    assert d.shape == (4, 5)


# ---------------- 抽稀 ----------------

def test_downsample_reduces_size():
    data = np.zeros((2000, 2000), np.float32)
    lat = np.zeros((2000, 2000), np.float32)
    lon = np.zeros((2000, 2000), np.float32)

    la, lo, d = pipeline.downsample(lat, lon, data, max_cells=100_000)
    assert d.shape[0] * d.shape[1] <= 120_000, f"抽稀后仍太大: {d.shape}"
    assert la.shape == d.shape


def test_downsample_skips_small_arrays():
    data = np.zeros((100, 100), np.float32)
    la, lo, d = pipeline.downsample(None, None, data, max_cells=100_000)
    assert d.shape == (100, 100)


# ---------------- 校准系数解析 ----------------

def test_emissive_band_names_parsing():
    v = Variable(name="x", data=np.zeros((4, 2, 2), np.uint16),
                 source_shape=(4, 2, 2), attrs={"band_name": b"20,21,22,23"})
    assert pipeline._emissive_band_names(v) == [20, 21, 22, 23]

    v2 = Variable(name="y", data=np.zeros((2, 2, 2), np.uint16),
                  source_shape=(2, 2, 2), attrs={"band_name": b"24,25"})
    assert pipeline._emissive_band_names(v2) == [24, 25]


def test_reflective_band_names_parsing():
    v = Variable(name="x", data=np.zeros((15, 2, 2), np.uint16),
                 source_shape=(15, 2, 2), attrs={"band_name": b"5-19"})
    bands = pipeline._reflective_band_names(v)
    assert bands[0] == 5 and bands[-1] == 19 and len(bands) == 15


def test_slope_is_per_channel():
    """EV_1KM_Emissive 的 Slope 是 [0.0002,0.0002,0.01,0.01]，不能统一取 0.01。"""
    v = Variable(name="x", data=np.zeros((4, 2, 2), np.uint16),
                 source_shape=(4, 2, 2),
                 attrs={"Slope": np.array([0.0002, 0.0002, 0.01, 0.01])})
    assert pipeline._slope_of(v, 0) == pytest.approx(0.0002)
    assert pipeline._slope_of(v, 2) == pytest.approx(0.01)
    assert pipeline._slope_of(v, 3) == pytest.approx(0.01)


# ---------------- 真实文件：亮温必须物理合理 ----------------

@pytest.fixture(scope="module")
def fy3h_file():
    hits = glob.glob(r"Y:\download-data\**\FY3H_MERSI_GRAN_L1_*1000M*.hdf", recursive=True)
    if not hits:
        pytest.skip("缺 FY-3H 样本")
    return hits[0]


def test_real_brightness_temperature_is_physical(fy3h_file):
    """核心回归：亮温必须落在 150~350 K，而不是 0.01~1.5 的辐亮度值。"""
    from fysat.readers import open_file

    ds = open_file(fy3h_file, load=False)
    wc = pipeline.window_channel(ds)
    assert wc is not None, "应能找到窗区通道"

    bt, unit = pipeline.thermal_data(ds, wc[0], wc[1])
    assert unit == "K"

    v = bt[np.isfinite(bt)]
    assert v.size > 1000
    assert 150 < np.min(v) and np.max(v) < 350, \
        f"亮温 {np.min(v):.1f}~{np.max(v):.1f} K 超出物理范围"

    # 真实大气：应有冷云顶，也应有暖地表
    assert (bt < 240).mean() > 0.01, "应有云顶（<240K）"
    assert (bt > 290).mean() > 0.01, "应有暖地表（>290K）"


def test_real_window_channel_found(fy3h_file):
    from fysat.readers import open_file

    ds = open_file(fy3h_file, load=False)
    wc = pipeline.window_channel(ds)
    assert wc is not None
    var_name, band = wc
    # 窗区应该是 24（10.7µm）或 25（12µm）
    var = ds.variables[var_name]
    bands = pipeline._emissive_band_names(var)
    assert bands[band] in (24, 25), f"选到了非窗区通道 b{bands[band]}"


def test_real_geo_grid_is_clean(fy3h_file):
    from fysat.readers import open_file

    ds = open_file(fy3h_file, load=False)
    lat, lon = pipeline.geo_grid(ds, (200, 200))
    assert lat is not None
    finite = np.isfinite(lat) & np.isfinite(lon)
    assert finite.mean() > 0.9, f"清理后有效点仅 {finite.mean()*100:.1f}%"

    la = lat[finite]
    lo = lon[finite]
    assert -90 <= np.min(la) and np.max(la) <= 90
    assert -180 <= np.min(lo) and np.max(lo) <= 360


def test_visible_reflectance_is_percent(fy3h_file):
    from fysat.readers import open_file

    ds = open_file(fy3h_file, load=False)
    refl, unit = pipeline.visible_data(ds, "Data/EV_1KM_RefSB", 0)
    assert unit == "%"
    v = refl[np.isfinite(refl)]
    assert v.size > 1000
    assert np.percentile(v, 99) < 120, "反射率超过 120% 说明定标或索引有问题"
    assert np.median(v) > 0
