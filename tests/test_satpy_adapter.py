"""satpy 可选后端的适配测试。

三层断言，按"要不要装 satpy / 要不要真实数据"分开，保证**没装 satpy 时整套
依然可跑**（只是 skip），装了也不会因为缺样本而红：

1. **零依赖**：GEO 文件名推导、读取器推导、注册表接入、以及"没装 satpy 时
   必须抛 NotImplementedError"——这些在任何环境都跑。
2. **satpy + 真实样本**：FY-3D（无 GEO → 降级）与 FY-3H / FY-3C（有 GEO → 定位生效）。
   真实文件不在（Y: 盘没挂 / 样本被清）就 skip。

验收要点（对应任务书）：
- 能读出真实 FY-3D 通道；
- 能定标到反射率（默认归一到 0~1，`normalize_reflectance=False` 时是 %）；
- 有 GEO 时拿得到经纬度，没 GEO 时 `attrs["geo_missing"] is True` 且数据仍可读。
"""
from __future__ import annotations
from _sample_root import SAMPLE_ROOT

import glob
import importlib.util
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

from fysat.readers import kinds, open_file
from fysat.readers import satpy_adapter as SA

# 隔离安装目录（验收环境把 satpy 装在这里，主环境不装）。
SATPY_PATH = Path(r"E:\tmp\satpytest")
SAMPLE_ROOT = SAMPLE_ROOT


def _ensure_satpy() -> bool:
    """satpy 可用吗？不在 sys.path 上时补上隔离目录再判一次。"""
    try:
        if importlib.util.find_spec("satpy") is not None:
            return True
        if SATPY_PATH.is_dir() and str(SATPY_PATH) not in sys.path:
            sys.path.insert(0, str(SATPY_PATH))
        return importlib.util.find_spec("satpy") is not None
    except (ImportError, ValueError):        # sys.path/meta_path 被插了奇怪的钩子
        return False


HAS_SATPY = _ensure_satpy()
needs_satpy = pytest.mark.skipif(
    not HAS_SATPY, reason='未安装 satpy 可选依赖（pip install "fysat[satpy]"）')


@lru_cache(maxsize=None)
def find_samples(pattern: str, min_mb: float = 1.0) -> tuple[Path, ...]:
    """在样本根目录找所有匹配文件（跳过下载残件与缩略图），按路径排序。"""
    if not SAMPLE_ROOT.is_dir():
        return ()
    out: list[Path] = []
    for hit in sorted(glob.glob(str(SAMPLE_ROOT / "**" / pattern), recursive=True)):
        try:
            if Path(hit).stat().st_size >= min_mb * 1e6:
                out.append(Path(hit))
        except OSError:
            continue
    return tuple(out)


def find_sample(pattern: str, min_mb: float = 1.0) -> Path | None:
    hits = find_samples(pattern, min_mb)
    return hits[0] if hits else None


def _fy3d() -> Path:
    """FY-3D MERSI-2 1000M 全球样本（实测没有配套 GEO 文件）。"""
    if not HAS_SATPY:
        pytest.skip('未安装 satpy 可选依赖')
    p = find_sample("FY3D_MERSI_GBAL_L1_*_1000M_MS.HDF", min_mb=50)
    if p is None:
        pytest.skip("缺少 FY-3D MERSI-2 真实样本")
    return p


def _paired(platform: str, gran: bool) -> tuple[Path, Path]:
    """找一个"数据 + GEO"都在同一目录的样本对。

    同一个目录里常有不带 GEO 的时段（例如 FY-3C 只有 0025 有 GEO、0005 没有），
    所以要遍历所有候选，挑第一个能配上 GEO 的。
    """
    if not HAS_SATPY:
        pytest.skip('未安装 satpy 可选依赖')
    pattern = ("FY3H_MERSI_GRAN_L1_*_1000M_V0.hdf" if gran
               else "FY3C_MERSI_GBAL_L1_*_1000M_MS.HDF")
    hits = find_samples(pattern, min_mb=20)
    if not hits:
        pytest.skip(f"缺少 {platform} MERSI 真实样本")
    for main in hits:
        geo = SA.find_geo_file(main)
        if geo is not None:
            return main, geo
    pytest.skip(f"{len(hits)} 个 {platform} 样本都没有配套 GEO 文件")


# ================================================================ 零依赖：注册表

def test_registry_contains_satpy_alongside_existing_readers():
    """satpy 以可选方式注册，且不能顶掉原有 5 个读取器。"""
    registered = set(kinds())
    assert "satpy" in registered
    # 原有读取器（hdf5/netcdf4 必在；其余是 try/except 可选注册，正常环境都该在）
    assert {"hdf5", "netcdf4"} <= registered
    assert {"netcdf3", "fy2_csv", "oneb", "awx"} <= registered, \
        f"原有读取器被破坏了：{sorted(registered)}"


def test_open_file_routes_explicit_kind_to_satpy(monkeypatch, tmp_path):
    """kind="satpy" 必须被注册表分派到适配器（这里用"satpy 不可用"的桩验证路由）。"""
    monkeypatch.setitem(sys.modules, "satpy", None)      # import satpy → ImportError
    with pytest.raises(NotImplementedError, match="satpy"):
        open_file(tmp_path / "whatever.hdf", kind="satpy", load=False)


def test_open_file_default_behaviour_unchanged(tmp_path):
    """不给 kind 时仍按魔数分派：不认识的扩展名照样报原来的错。"""
    p = tmp_path / "not_a_real_file.bin"
    p.write_bytes(b"\x00" * 32)
    with pytest.raises(NotImplementedError, match="暂不支持的容器类型"):
        open_file(p)


# ================================================================ 零依赖：未安装 satpy

def test_read_without_satpy_raises_not_implemented(monkeypatch, tmp_path):
    """没装 satpy 时 read() 必须抛 NotImplementedError，而不是崩在别处。"""
    monkeypatch.setitem(sys.modules, "satpy", None)
    with pytest.raises(NotImplementedError, match="satpy"):
        SA.read(tmp_path / "FY3D_MERSI_GBAL_L1_20260810_0635_1000M_MS.HDF", load=False)


def test_load_array_without_satpy_raises(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "satpy", None)
    with pytest.raises(NotImplementedError, match="satpy"):
        SA.load_array(tmp_path / "x.HDF", "1")


# ================================================================ 零依赖：GEO 推导

def test_geo_filename_1000m_to_geo1k(tmp_path):
    data = tmp_path / "FY3D_MERSI_GBAL_L1_20260810_0635_1000M_MS.HDF"
    geo = tmp_path / "FY3D_MERSI_GBAL_L1_20260810_0635_GEO1K_MS.HDF"
    data.write_bytes(b"")
    geo.write_bytes(b"")
    assert SA.find_geo_file(data) == geo


def test_geo_filename_250m_to_geqk(tmp_path):
    data = tmp_path / "FY3D_MERSI_GBAL_L1_20260810_0635_0250M_MS.HDF"
    geo = tmp_path / "FY3D_MERSI_GBAL_L1_20260810_0635_GEOQK_MS.HDF"
    data.write_bytes(b"")
    geo.write_bytes(b"")
    assert SA.find_geo_file(data) == geo


def test_geo_filename_500m_to_geohk(tmp_path):
    """MERSI-RM（FY-3G）是 500M → GEOHK，不是 GEOQK。"""
    data = tmp_path / "FY3G_MERSI_GRAN_L1_20261031_0025_0500M_V1.hdf"
    geo = tmp_path / "FY3G_MERSI_GRAN_L1_20261031_0025_GEOHK_V1.hdf"
    data.write_bytes(b"")
    geo.write_bytes(b"")
    assert SA.find_geo_file(data) == geo


def test_geo_filename_gran_v0(tmp_path):
    """GRAN 产品（FY-3F/H）GEO 段同样是 GEO1K，但尾部是 _V0。"""
    data = tmp_path / "FY3H_MERSI_GRAN_L1_20261030_0300_1000M_V0.hdf"
    geo = tmp_path / "FY3H_MERSI_GRAN_L1_20261030_0300_GEO1K_V0.hdf"
    data.write_bytes(b"")
    geo.write_bytes(b"")
    assert SA.find_geo_file(data) == geo


def test_geo_filename_agri_fdi_to_geo(tmp_path):
    """AGRI 的定位文件把 L1-_FDI- 换成 L1-_GEO-（best-effort，本地无样本可验数据）。"""
    data = tmp_path / ("FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_MULT_NOM_"
                       "20261020000000_20261020001459_4000M_V0001.HDF")
    geo = tmp_path / ("FY4B-_AGRI--_N_DISK_1050E_L1-_GEO-_MULT_NOM_"
                      "20261020000000_20261020001459_4000M_V0001.HDF")
    data.write_bytes(b"")
    geo.write_bytes(b"")
    assert SA.find_geo_file(data) == geo


def test_geo_missing_returns_none(tmp_path):
    data = tmp_path / "FY3D_MERSI_GBAL_L1_20260810_0635_1000M_MS.HDF"
    data.write_bytes(b"")
    assert SA.find_geo_file(data) is None


def test_geo_explicit_path_wins(tmp_path):
    data = tmp_path / "FY3D_MERSI_GBAL_L1_20260810_0635_1000M_MS.HDF"
    explicit = tmp_path / "my_geo.HDF"
    data.write_bytes(b"")
    explicit.write_bytes(b"")
    assert SA.find_geo_file(data, geo_path=explicit) == explicit


def test_geo_never_returns_the_data_file_itself(tmp_path):
    """名字里已经带 GEO1K 的文件不能再被推成自己的 GEO。"""
    data = tmp_path / "FY3D_MERSI_GBAL_L1_20260810_0635_GEO1K_MS.HDF"
    data.write_bytes(b"")
    assert SA.find_geo_file(data) is None


def test_geo_extra_dirs_are_searched(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "geo").mkdir()
    data = tmp_path / "data" / "FY3D_MERSI_GBAL_L1_20260810_0635_1000M_MS.HDF"
    geo = tmp_path / "geo" / "FY3D_MERSI_GBAL_L1_20260810_0635_GEO1K_MS.HDF"
    data.write_bytes(b"")
    geo.write_bytes(b"")
    assert SA.find_geo_file(data, extra_dirs=[tmp_path / "geo"]) == geo


# ================================================================ 零依赖：读取器推导

@pytest.mark.parametrize(("filename", "expected"), [
    ("FY3A_MERSI_GBAL_L1_20200101_0000_1000M_MS.HDF", "fy3a_mersi1_l1b"),
    ("FY3C_MERSI_GBAL_L1_20150530_0025_1000M_MS.HDF", "fy3c_mersi1_l1b"),
    ("FY3D_MERSI_GBAL_L1_20260810_0635_1000M_MS.HDF", "mersi2_l1b"),
    ("FY3E_MERSI_GRAN_L1_20230101_0000_1000M_V0.hdf", "mersi_ll_l1b"),
    ("FY3F_MERSI_GRAN_L1_20261101_1235_1000M_V0.hdf", "mersi3_l1b"),
    ("FY3H_MERSI_GRAN_L1_20261030_0300_1000M_V0.hdf", "mersi3_l1b"),
    ("FY3G_MERSI_GRAN_L1_20261031_0025_0500M_V1.hdf", "mersi_rm_l1b"),
    ("FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_MULT_NOM_2026102_4000M_V0001.HDF",
     "agri_fy4b_l1"),
])
def test_reader_inference(filename, expected):
    assert SA.reader_candidates(filename)[0] == expected


def test_reader_inference_rejects_unknown():
    with pytest.raises(NotImplementedError, match="不认识"):
        SA.reader_candidates("FY2G_CSV_20261030_0000.AWX")


def test_load_false_rejects_percent_mode(tmp_path):
    """惰性加载无法携带"不归一化"选项，必须提前挡住，避免单位与数据错位。"""
    with pytest.raises(ValueError, match="归一化"):
        SA.read(tmp_path / "x.hdf", load=False, normalize_reflectance=False)


# ================================================================ 真实样本：FY-3D（无 GEO）

@needs_satpy
def test_fy3d_reflectance_is_normalized_to_fraction():
    """FY-3D 可见光：satpy 原始值是 %，适配器默认折成 0~1。"""
    p = _fy3d()
    ds = SA.read(p, names=["1", "2", "3"], geo_step=1)

    assert sorted(ds.names()) == ["1", "2", "3"]
    for name, wl in (("1", 0.470), ("2", 0.550), ("3", 0.650)):
        v = ds[name]
        assert v.unit == "1", f"默认应归一化成无量纲反射率，实际 {v.unit!r}"
        assert v.attrs["satpy_calibration"] == "reflectance"
        assert v.attrs["wavelength_central"] == pytest.approx(wl, abs=0.02)
        arr = v.physical()
        assert arr.shape == v.source_shape == (2000, 2048)
        assert np.isfinite(arr).mean() > 0.9, "反射率不该大面积为 NaN"
        # 0~1 量级：允许少量负值（定标噪声）与略超 1（云顶）
        assert np.nanmin(arr) > -0.2
        assert 0.3 < np.nanmax(arr) < 1.6


@needs_satpy
def test_fy3d_percent_mode_matches_satpy_native():
    """normalize_reflectance=False 时保持 satpy 原生 %，与产品解码路径（单位 %）对齐。"""
    p = _fy3d()
    ds = SA.read(p, names=["1"], normalize_reflectance=False)
    v = ds["1"]
    assert v.unit == "%"
    assert v.attrs["satpy_units"] == "%"
    assert v.attrs["reflectance_normalized"] is False
    assert np.nanmax(v.data) > 1.5, "原生 % 应明显大于 1"


@needs_satpy
def test_fy3d_brightness_temperature_band():
    """红外通道自动选亮度温度，单位 K —— 不是反射率。"""
    p = _fy3d()
    ds = SA.read(p, names=["20"])
    v = ds["20"]
    assert v.attrs["satpy_calibration"] == "brightness_temperature"
    assert v.unit == "K"
    assert 180.0 < np.nanmin(v.data) < 280.0
    assert 280.0 < np.nanmax(v.data) < 340.0


@needs_satpy
def test_fy3d_all_bands_enumerate_without_loading():
    """load=False 只登记形状：19 个反射/红外通道都在，且没把数据读进来。"""
    p = _fy3d()
    ds = SA.read(p, load=False)
    assert len(ds.variables) >= 19
    assert {"1", "3", "20", "25"} <= set(ds.names())
    v = ds["1"]
    assert v.data.size == 0, "load=False 不应读数据"
    assert v.source_shape == (2000, 2048) and v.shape == (2000, 2048)
    assert ds.attrs["failed_datasets"] == {}
    assert all(v.attrs["wavelength_central"] for v in ds.variables.values())


@needs_satpy
def test_fy3d_geo_missing_flag_is_consistent():
    """没有配套 GEO 时必须 geo_missing=True、定位为 none，但数据照读。"""
    p = _fy3d()
    ds = SA.read(p, load=False)
    geo_on_disk = SA.find_geo_file(p)

    assert ds.attrs["geo_missing"] is (geo_on_disk is None)
    assert ds.attrs["geo_file"] == (str(geo_on_disk) if geo_on_disk else "")
    if geo_on_disk is None:
        assert ds.geolocation.kind == "none"
        assert not ds.geolocation.is_nav
        assert ds.geolocation.bounds() is None


@needs_satpy
def test_fy3d_lazy_load_fills_variable_in_place():
    """SatDataset.load() 走 readers.satpy_adapter.load_array()，单位与 read() 一致。"""
    p = _fy3d()
    ds = SA.read(p, load=False, names=["2"])
    assert ds.reader == SA.READER_NAME, "reader 名必须能被 model.load() 映射到本模块"

    v = ds.load("2")
    assert v.data.size > 0
    assert v.data.shape == (2000, 2048)
    assert v.dtype == np.float32
    assert v.unit == "1"                      # 与 read(load=True) 的归一化口径一致
    assert 0.3 < np.nanmax(v.data) < 1.6


@needs_satpy
def test_open_file_kind_satpy_end_to_end():
    p = _fy3d()
    ds = open_file(p, kind="satpy", load=False, names=["1"])
    assert ds.reader == SA.READER_NAME
    assert ds.attrs["source_backend"] == "satpy"
    assert "1" in ds.names()


# ================================================================ 真实样本：有 GEO（定位生效）

@needs_satpy
def test_fy3h_geo_pairing_gives_geolocation():
    """FY-3H GRAN + GEO1K：GEO 自动配对成功 → 有经纬度，geo_missing=False。"""
    main, geo = _paired("FY-3H", gran=True)
    ds = SA.read(main, names=["1"], geo_step=4)

    assert ds.attrs["geo_missing"] is False
    assert Path(ds.attrs["geo_file"]) == geo
    assert ds.geolocation.kind == "latlon_grid"
    assert ds.geolocation.is_nav
    assert ds.geolocation.step == 4
    assert ds.geolocation.lat.dtype == np.float32

    lon0, lon1, lat0, lat1 = ds.geolocation.bounds()
    assert -180.0 <= lon0 < lon1 <= 180.0
    assert -90.0 <= lat0 < lat1 <= 90.0
    assert ds["1"].unit == "1"


@needs_satpy
def test_fy3c_geo_pairing_gives_geolocation():
    """FY-3C MERSI-1 + GEO1K：老平台同样能配对（读取器 fy3c_mersi1_l1b）。"""
    main, geo = _paired("FY-3C", gran=False)
    ds = SA.read(main, names=["1"], geo_step=4)

    assert ds.attrs["satpy_reader"] == "fy3c_mersi1_l1b"
    assert ds.attrs["geo_missing"] is False
    assert ds.geolocation.is_nav
    lon0, lon1, lat0, lat1 = ds.geolocation.bounds()
    assert -180.0 <= lon0 < lon1 <= 180.0
    assert -90.0 <= lat0 < lat1 <= 90.0


@needs_satpy
def test_include_aux_exposes_angles_without_loading_data():
    """include_aux=True 时把天顶角/经纬度也登记成变量（形状正确、数据仍未读）。"""
    main, _geo = _paired("FY-3H", gran=True)
    ds = SA.read(main, load=False, names=["1"], include_aux=True, geo_step=8)

    assert {"1", "solar_zenith_angle", "satellite_zenith_angle"} <= set(ds.names())
    v = ds["solar_zenith_angle"]
    assert v.unit == "degree"
    assert v.data.size == 0, "load=False 时辅助变量也不该读数据"
    assert v.source_shape == ds["1"].source_shape
    assert ds.variables["1"].data.size == 0


@needs_satpy
def test_unknown_band_name_raises_with_available_list():
    p = _fy3d()
    with pytest.raises(KeyError, match="没有可读的通道"):
        SA.read(p, names=["999"])


@pytest.mark.skipif(not HAS_SATPY, reason="未安装 satpy 可选依赖")
def test_geolocation_none_still_usable_by_pipeline():
    """降级路径要和 pipeline 兼容：无定位时 geo_grid 返回 (None, None) 而不是抛异常。"""
    from fysat import pipeline

    p = _fy3d()
    ds = SA.read(p, load=False)
    if ds.geolocation.is_nav:            # 万一样本目录里补了 GEO 文件
        pytest.skip("该样本已有 GEO，测不到降级分支")
    lat, lon = pipeline.geo_grid(ds, (100, 100))
    assert lat is None and lon is None
