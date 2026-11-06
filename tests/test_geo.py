"""定位与重采样验证 —— 全部用官方 L1 真实样本断言。

样本
----
* FY-3H MERSI L1 250M：``/GEO/Latitude|Longitude`` (400, 410)，每 20 像元一点，配 8000×8192 数据
* FY-4B AGRI L1 FDI 1KM：全圆盘 (10992, 10992)，星下点 105°E / 0°N / 35786000 m，标称像元 1000 m
* FY-2G FDI L1：全圆盘 (2288, 2288)，标称像元 5000 m，CALChannelIR1 查表出亮温

标称投影的正确性用「数据自带的圆盘形状」交叉验证：预测得到的地球圆盘掩膜与文件里
``!= 65535`` 的掩膜必须几乎逐像元一致（FY-2G 99.7%，FY-4B 99.9%）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from _sample_root import SAMPLE_ROOT

from fysat import calib, geo
from fysat.readers import open_file

FY3H = SAMPLE_ROOT / r"FY3H_MERSI_GRAN_L1_20261022_1810_0250M_V0.hdf"
FY4B = SAMPLE_ROOT / (
    r"FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_MULT_NOM_"
    r"20261030154500_20261030155959_1000M_V0001.HDF"
)
FY2G = SAMPLE_ROOT / r"C202610181401129865\FY2G_FDI_ALL_NOM_20261018_1300.hdf"

# FY-4B 全局属性
FY4B_SUB_LON, FY4B_SUB_LAT, FY4B_HEIGHT = 105.0, 0.0, 35786000.0
FY4B_PIXEL = 1000.0
FY4B_SHAPE = (10992, 10992)


def _sample(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"缺少真实样本: {path}")
    return path


# ---------------------------------------------------------------- FY-3H 粗网格

@pytest.fixture(scope="module")
def fy3h_geo():
    """FY-3H 的粗经纬网格 + 亮温子样（抽稀 8 倍，留作重采样用）。"""
    import h5py

    path = _sample(FY3H)
    ds = open_file(path, load=False)
    assert ds.geolocation.kind == "latlon_grid"
    with h5py.File(path, "r") as f:
        lat = np.asarray(f["/GEO/Latitude"][()], dtype=np.float32)
        lon = np.asarray(f["/GEO/Longitude"][()], dtype=np.float32)
        dn = np.asarray(f["/Data/EV_250_Emissive_b24"][::8, ::8], dtype=np.uint16)
    bt = calib.bt_from_dn_planck(dn, 0.01, 0.0, 10.7342, fill=calib.FY3_BAD_DN)
    return ds, lat, lon, dn, bt


def test_reader_recognises_geolocation_grid(fy3h_geo):
    """读取器把 /GEO 认成 step=20 的 latlon_grid，范围与 10 月 22 日这颗 granule 一致。"""
    ds, lat, lon, _, _ = fy3h_geo
    g = ds.geolocation
    assert g.kind == "latlon_grid"
    assert g.step == 20, "250m granule 每 20 像元一个定位点"
    assert g.lat.shape == g.lon.shape == (400, 410)
    assert np.array_equal(g.lat, lat)

    lon_min, lon_max, lat_min, lat_max = g.bounds()
    assert 96.0 < lon_min < 97.0 and 125.0 < lon_max < 126.0
    assert -3.0 < lat_min < 0.0 and 18.0 < lat_max < 18.5


def test_sample_latlon_grid_reproduces_coarse_nodes(fy3h_geo):
    """双线性插值在粗格点上必须严格等于原值，且行列号与粗网格对齐。"""
    _, lat, lon, _, _ = fy3h_geo
    grid = geo.sample_latlon_grid(lat, lon, (8000, 8192), 20, stride=20)
    assert grid.shape == (400, 410)
    assert grid.stride == 20
    assert grid.rows[0] == 0 and grid.cols[0] == 0
    assert np.allclose(grid.lat, lat, atol=1e-5, equal_nan=True)
    assert np.allclose(grid.lon, lon, atol=1e-5, equal_nan=True)


def test_sample_latlon_grid_full_resolution_auto_stride(fy3h_geo):
    """不给 stride 时自动抽稀：8000×8192 全分辨率 → 1600×1639（stride=5），不超内存上限。"""
    _, lat, lon, _, _ = fy3h_geo
    grid = geo.sample_latlon_grid(lat, lon, (8000, 8192), 20)
    assert grid.shape == (1600, 1639)
    assert grid.stride == 5
    assert grid.shape[0] * grid.shape[1] <= 4_000_000
    assert grid.rows[-1] < 8000 and grid.cols[-1] < 8192

    # 插值结果必须落在粗网格范围之内（不产生外推），经度随列号单调东移
    assert np.nanmin(grid.lat) >= lat.min() - 1e-4
    assert np.nanmax(grid.lat) <= lat.max() + 1e-4
    dlon = np.diff(grid.lon[0])
    assert np.all(dlon >= 0), "经度应随列号单调东移"
    # 粗网格只有 410 列（覆盖到第 8180 列），之后的行/列按设计截断到最后一个格点
    assert int((dlon == 0).sum()) <= 5, "只有最东边几个抽稀列会被截断"

    # 行号增大 → 向南 → 总体纬度递减。注意 FY-3H 的真实定位有扫描抖动（±0.007°），
    # 所以远场不是严格单调，只能断言「总体下降 + 局部跳动有界」。
    lat_col = grid.lat[:, 0]
    assert lat_col[0] - lat_col[-1] > 17.0, "从 18.3°N 一路降到 1.0°N"
    assert np.all(np.diff(lat_col) <= 0.05), "向南的总体趋势不能被抖动打断"
    assert np.all(np.diff(lat_col) >= -0.15)


def test_sample_latlon_grid_take_matches_data(fy3h_geo):
    """``grid.take(data)`` 等价于 ``data[np.ix_(rows, cols)]``，且 rows/cols 是**全分辨率**行号。"""
    _, lat, lon, dn, _ = fy3h_geo
    grid = geo.sample_latlon_grid(lat, lon, (8000, 8192), 20, stride=8)
    assert grid.shape == dn.shape, "抽稀步长要和数据子样一致才能配对"
    assert grid.stride == 8
    assert int(grid.rows[-1]) < 8000 and int(grid.cols[-1]) < 8192

    # rows/cols 指向原图，用同比例的小合成图验证取值（真图 131 MB，这里不重复读）
    small = geo.sample_latlon_grid(lat, lon, (800, 820), 20, stride=8)
    canvas = np.arange(800 * 820, dtype=np.float32).reshape(800, 820)
    assert np.array_equal(small.take(canvas), canvas[np.ix_(small.rows, small.cols)])

    # 拿抽稀子样去 take 会明确报错（避免 render 端悄悄取错像素）
    with pytest.raises(ValueError, match="全分辨率"):
        grid.take(dn)


# ---------------------------------------------------------------- FY-4B 标称投影

def test_nominal_geos_center_is_sub_satellite_point():
    """星下点：图像正中心 → (0°, 105°)。格心在 (n-1)/2，允许半个像元的偏差。"""
    rows = np.array([5495, 5496])
    cols = np.array([5495, 5496])
    lat, lon = geo.nominal_geos_lonlat(FY4B_SHAPE, FY4B_SUB_LON, FY4B_SUB_LAT, FY4B_HEIGHT,
                                       rows=rows, cols=cols)
    assert np.all(np.isfinite(lat))
    assert np.allclose(lat, 0.0, atol=0.01)
    assert np.allclose(lon, FY4B_SUB_LON, atol=0.01)

    # 中心行的经度对称（以东/西两个方向各走 N 个像元，经度变化量应相等）
    lat_row, lon_row = geo.nominal_geos_lonlat(
        FY4B_SHAPE, FY4B_SUB_LON, FY4B_SUB_LAT, FY4B_HEIGHT,
        rows=np.array([5495]), cols=np.array([5495 - 2000, 5495, 5495 + 2000]),
    )
    assert lon_row[0, 0] < lon_row[0, 1] < lon_row[0, 2]
    assert abs((lon_row[0, 1] - lon_row[0, 0]) - (lon_row[0, 2] - lon_row[0, 1])) < 1e-3


def test_nominal_geos_limb_geometry():
    """圆盘边缘几何（独立解析解交叉验证）。

    1) 圆盘半径：地球半角 arcsin(a/(a+H)) = 8.7005°，标称像元 1000 m → 0.0016011°/px，
       理论半径 5434.2 px；实测第一列有限值在 62，中心 (10992−1)/2 = 5495.5 → 5433.5 px。
    2) 边缘点经度：地心张角 ψ 由 ``sin(θ+ψ) = (a+H)·sinθ/a`` 给出，不是「视角半角 8.7°」；
       最后一个落在圆盘内的像元 θ = 8.6992° → ψ = 80.3°（实测 80.40°，差 0.08° 来自椭球
       扁率与半像元的行偏移），所以断言必须用解析式，而不是直接拿 81.3° 比。
    3) 圆盘外必须是 NaN。
    """
    lat_row, lon_row = geo.nominal_geos_lonlat(
        FY4B_SHAPE, FY4B_SUB_LON, FY4B_SUB_LAT, FY4B_HEIGHT,
        rows=np.array([5495]), cols=np.arange(FY4B_SHAPE[1]),
    )
    finite = np.isfinite(lat_row[0])
    n_finite = int(finite.sum())
    assert 10_850 < n_finite < 10_880, f"地球圆盘约 10868 列宽，实测 {n_finite}"

    west = int(np.argmax(finite))
    east = FY4B_SHAPE[1] - 1 - int(np.argmax(finite[::-1]))
    center = (FY4B_SHAPE[1] - 1) / 2.0
    radius_px = center - west
    theory_px = np.degrees(np.arcsin(geo.WGS84_SEMIMAJOR / (geo.WGS84_SEMIMAJOR + FY4B_HEIGHT))) / np.degrees(
        FY4B_PIXEL / FY4B_HEIGHT
    )
    assert abs(radius_px - theory_px) < 1.5, f"圆盘半径 {radius_px:.1f} px vs 理论 {theory_px:.1f} px"
    assert abs((east - center) - radius_px) < 1.0, "东西两侧应严格对称"

    # 地心张角：用解析式校验（球近似，赤道面上与椭球一致）
    a, h = geo.WGS84_SEMIMAJOR, FY4B_HEIGHT
    for theta_deg in (2.0, 4.0, 6.0):
        col = int(round(center + theta_deg / np.degrees(FY4B_PIXEL / FY4B_HEIGHT)))
        theta = (col - center) * (FY4B_PIXEL / FY4B_HEIGHT)          # 该像元的精确扫描角
        psi = np.degrees(np.arcsin(np.clip((a + h) * np.sin(theta) / a, -1.0, 1.0))) - np.degrees(theta)
        got = np.degrees(
            np.arccos(
                np.clip(
                    np.cos(np.deg2rad(float(lat_row[0, col])))
                    * np.cos(np.deg2rad(float(lon_row[0, col]) - FY4B_SUB_LON)),
                    -1.0, 1.0,
                )
            )
        )
        assert abs(got - psi) < 0.05, f"θ={theta_deg}°: 实测 ψ={got:.3f}°，解析 {psi:.3f}°"

    # 圆盘外 → NaN（四角一定在地球外）
    lat_c, lon_c = geo.nominal_geos_lonlat(
        FY4B_SHAPE, FY4B_SUB_LON, FY4B_SUB_LAT, FY4B_HEIGHT,
        rows=np.array([0, 10991]), cols=np.array([0, 10991]),
    )
    assert np.isnan(lat_c).all() and np.isnan(lon_c).all()


def test_nominal_geos_roundtrip_with_inverse():
    """lonlat → (row, col) → lonlat 往返误差 < 1e-6°（前向/反算自洽）。"""
    lats = np.array([0.0, 5.0, -5.0, 30.0, -30.0, 45.0])
    lons = np.array([105.0, 110.0, 100.0, 105.0, 105.0, 80.0])
    row, col = geo.lonlat_to_nominal_rowcol(lats, lons, FY4B_SHAPE, FY4B_SUB_LON,
                                            FY4B_SUB_LAT, FY4B_HEIGHT)
    assert np.all(np.isfinite(row)) and np.all(np.isfinite(col))
    assert 0 <= row.min() and row.max() < FY4B_SHAPE[0]
    assert 0 <= col.min() and col.max() < FY4B_SHAPE[1]

    step = FY4B_PIXEL / FY4B_HEIGHT
    lat2, lon2 = geo.geos_scan_to_lonlat(
        (col - (FY4B_SHAPE[1] - 1) / 2) * step,
        -((row - (FY4B_SHAPE[0] - 1) / 2) * step),
        FY4B_SUB_LON, FY4B_SUB_LAT, FY4B_HEIGHT,
    )
    assert np.allclose(np.diag(lat2), lats, atol=1e-5)
    assert np.allclose(np.diag(lon2), lons, atol=1e-5)


def test_nominal_geos_matches_fy4b_disk_mask():
    """用 FY-4B 自己的圆盘形状校验标称投影：抽稀行后掩膜一致率 > 99.5%。"""
    import h5py

    path = _sample(FY4B)
    rows = np.arange(0, FY4B_SHAPE[0], 8)
    with h5py.File(path, "r") as f:
        dn = np.asarray(f["/Data/NOMChannel01"][rows, :], dtype=np.uint16)
    valid = dn != 65535

    lat, lon = geo.nominal_geos_lonlat(FY4B_SHAPE, FY4B_SUB_LON, FY4B_SUB_LAT, FY4B_HEIGHT, rows=rows)
    predicted = np.isfinite(lat)
    agree = float((predicted == valid).mean())
    assert agree > 0.995, f"圆盘掩膜一致率仅 {agree:.4f}"
    assert abs(float(predicted.mean()) - float(valid.mean())) < 0.002
    assert np.nanmax(np.abs(lat)) < 81.5, "可见地球纬度范围应≤81.3°"
    assert -180.0 <= np.nanmin(lon) and np.nanmax(lon) <= 180.0


def test_nominal_geos_matches_fy2g_disk_mask():
    """FY-2G 2288² 全圆盘（5 km 标称像元）同样对得上：一致率 > 99%。"""
    import h5py

    path = _sample(FY2G)
    with h5py.File(path, "r") as f:
        dn = np.asarray(f["/NOMChannelIR1"][()], dtype=np.uint16)
    valid = dn != 65535

    lat, lon = geo.nominal_geos_lonlat((2288, 2288), 105.0, 0.0, 35786000.0, pixel_size=5000.0)
    predicted = np.isfinite(lat)
    agree = float((predicted == valid).mean())
    assert agree > 0.99, f"圆盘掩膜一致率仅 {agree:.4f}"
    assert abs(float(predicted.mean()) - float(valid.mean())) < 0.01
    assert np.nanmax(np.abs(lat)) < 81.5


# ---------------------------------------------------------------- 重采样

def test_reproject_fy3h_brightness_field(fy3h_geo):
    """FY-3H 亮温 → 0.5° 等经纬网格：形状 (43, 60)、extent 对齐 0.5°、加权平均等于原图平均。"""
    _, lat, lon, _, bt = fy3h_geo
    grid_ll = geo.sample_latlon_grid(lat, lon, (8000, 8192), 20, stride=8)
    grid = geo.reproject_to_grid(bt, grid_ll.lat, grid_ll.lon, res=0.5)

    assert grid.shape == (43, 60)
    assert grid.res == pytest.approx(0.5)
    lon0, lon1, lat0, lat1 = grid.extent
    assert (lon0, lon1) == (96.0, 126.0)
    assert (lat0, lat1) == (-3.0, 18.5)

    assert np.isnan(grid.data).sum() > 0, "granule 边界外应有空洞"
    good = np.isfinite(grid.data)
    assert good.sum() > 1500
    assert 190.0 < float(np.nanmin(grid.data)) < 210.0
    assert 295.0 < float(np.nanmax(grid.data)) < 315.0

    # 加权平均必须与原始像元平均一致（证明没有丢点/重复计数）
    weighted = float(np.average(grid.data[good], weights=grid.counts[good]))
    assert weighted == pytest.approx(float(np.nanmean(bt)), rel=1e-6)
    assert int(grid.counts.sum()) == int(np.isfinite(bt).sum())

    # 坐标轴：纬度高在上（行 0 最北），经度东在右
    assert grid.lats[0] > grid.lats[-1]
    assert grid.lons[0] < grid.lons[-1]
    assert grid.data.shape == (grid.lats.size, grid.lons.size)


def test_reproject_resolution_changes_shape(fy3h_geo):
    """分辨率越小格子越多：1° → 0.25° 时格子数按面积比增长。"""
    _, lat, lon, _, bt = fy3h_geo
    grid_ll = geo.sample_latlon_grid(lat, lon, (8000, 8192), 20, stride=8)
    coarse = geo.reproject_to_grid(bt, grid_ll.lat, grid_ll.lon, res=1.0)
    fine = geo.reproject_to_grid(bt, grid_ll.lat, grid_ll.lon, res=0.25)
    assert coarse.res == 1.0 and fine.res == pytest.approx(0.25)
    ratio = (fine.shape[0] * fine.shape[1]) / (coarse.shape[0] * coarse.shape[1])
    assert 12.0 < ratio < 20.0, f"格子数比值异常: {ratio:.1f}"


def test_reproject_handles_antimeridian():
    """跨 180° 经线时自动折叠到 0–360，网格不会被劈成两半。"""
    lon = np.array([[-179.5, -179.2], [179.2, 179.5]])
    lat = np.array([[10.1, 10.1], [10.1, 10.1]])
    data = np.array([[1.0, 2.0], [3.0, 4.0]])
    grid = geo.reproject_to_grid(data, lat, lon, res=0.1)
    lon0, lon1, _, _ = grid.extent
    assert lon0 == pytest.approx(179.2, abs=1e-6)
    assert lon1 == pytest.approx(180.8, abs=1e-6)
    assert grid.shape[1] == 16, "179.2–180.8° 之间 0.1° 一档共 16 格"
    assert int(np.isfinite(grid.data).sum()) >= 2


def test_reproject_agg_and_min_count():
    """agg='sum' 给累加值，min_count 过滤孤立像元。"""
    lat = np.array([10.1, 10.3, 30.0])
    lon = np.array([100.1, 100.3, 120.0])
    data = np.array([1.0, 3.0, 7.0])
    mean = geo.reproject_to_grid(data, lat, lon, res=1.0)
    total = geo.reproject_to_grid(data, lat, lon, res=1.0, agg="sum")
    # 前两个点同处 (10°N,100°E) 那一格 → 平均 2.0；第三个点 7.0
    assert float(np.nansum(mean.data)) == pytest.approx(9.0, abs=1e-6)
    assert float(np.nansum(total.data)) == pytest.approx(11.0, abs=1e-6)

    only_pairs = geo.reproject_to_grid(data, lat, lon, res=1.0, min_count=2)
    assert int(np.isfinite(only_pairs.data).sum()) == 1, "只有 (10°N, 100°E) 那格有 2 个像元"


def test_reproject_nan_and_invalid_input():
    """NaN 数据不参与统计；全 NaN 抛出明确错误。"""
    lat = np.array([10.0, 10.1, np.nan])
    lon = np.array([100.0, 100.1, 100.2])
    data = np.array([5.0, np.nan, 9.0])
    grid = geo.reproject_to_grid(data, lat, lon, res=1.0)
    assert int(grid.counts.sum()) == 1
    assert float(np.nansum(grid.data)) == pytest.approx(5.0)

    with pytest.raises(ValueError):
        geo.reproject_to_grid(np.array([1.0]), np.array([np.nan]), np.array([np.nan]), res=1.0)
    with pytest.raises(ValueError):
        geo.reproject_to_grid(data, lat, lon, res=0.0)
