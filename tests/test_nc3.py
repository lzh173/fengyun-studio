# -*- coding: utf-8 -*-
"""NetCDF-3（CDF 经典格式）读取器测试。

1. 合成文件 —— 用 scipy 自己写一个 CDF-1 文件（二维经纬度 + 带定标的温度场），
   验证维度、属性映射、定标、填充值掩膜与 latlon_grid 定位。不依赖样本。
2. 真实样本 —— FY-3H GNOSO L1（``Y:\\download-data`` 下 14 个 .NC），验证
   CDF-1 全局属性、29 个变量的单位／有效范围／填充值、物理量量级与单点定位。
"""
from __future__ import annotations
from _sample_root import SAMPLE_ROOT

import glob
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from fysat.detect import sniff
from fysat.readers import nc3

SAMPLE_GLOB = str(SAMPLE_ROOT / r"**\FY3H_GNOSO_*.NC")


# ---------------------------------------------------------------- 合成文件


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory) -> Path:
    """写一个 CDF-1 文件：2 维经纬度网格 + 带 Slope/Intercept/FillValue 的温度场。"""
    from scipy.io import netcdf_file

    path = tmp_path_factory.mktemp("nc3") / "SYNTH_NC3_TEST.NC"
    lat = np.array([[10.0, 10.0, 10.0, 10.0],
                    [0.0, 0.0, 0.0, 0.0],
                    [-10.0, -10.0, -10.0, -10.0]], dtype="f4")
    lon = np.array([[100.0, 101.0, 102.0, 103.0]] * 3, dtype="f4")
    dn = np.array([[0, 1000, 2000, 3000],
                   [4000, 5000, 6000, 7000],
                   [8000, 9000, 10000, -1]], dtype="i2")   # -1 = 填充

    with netcdf_file(str(path), "w", version=1) as f:
        f.createDimension("time", 3)
        f.createDimension("lat", 3)
        f.createDimension("lon", 4)

        temp = f.createVariable("temperature", "h", ("lat", "lon"))
        temp[:] = dn
        temp.units = "K"
        temp.long_name = "Brightness temperature"
        temp.valid_range = np.array([0, 10000], dtype="i2")
        temp.FillValue = np.int16(-1)
        temp.Slope = np.float32(0.01)
        temp.Intercept = np.float32(200.0)

        t = f.createVariable("time", "d", ("time",))
        t[:] = np.array([0.0, 30.0, 60.0])
        t.units = "s"
        t.long_name = "seconds since start"

        la = f.createVariable("latitude", "f", ("lat", "lon"))
        la[:] = lat
        la.units = "degrees_north"
        lo = f.createVariable("longitude", "f", ("lat", "lon"))
        lo[:] = lon
        lo.units = "degrees_east"

        f.Satellite_Name = "FY-3H"
        f.Sensor_Identification_Code = "GNOS-II"
        f.Observing_Beginning_Date = "2026-10-19"
        f.Observing_Beginning_Time = "00:00:39.000"
        f.Observing_Ending_Date = "2026-10-19"
        f.Observing_Ending_Time = "00:02:08.000"
        f.dataLevel = "L1"
        f.dataName = "AE"
    return path


def test_synthetic_is_detected(synthetic):
    assert synthetic.read_bytes()[:4] == b"CDF\x01"
    assert sniff(synthetic) == "netcdf3"


def test_synthetic_structure(synthetic):
    ds = nc3.read(synthetic, load=False)
    assert ds.reader == "netcdf3"
    assert ds.attrs["dimensions"] == {"time": 3, "lat": 3, "lon": 4}
    assert ds.attrs["cdf_version"].startswith("CDF-1")
    assert len(ds.variables) == 4
    # load=False：不解码数据，但形状／类型仍在
    var = ds["temperature"]
    assert var.shape == (3, 4) and var.dtype == np.int16
    assert var.data.size == 0
    assert var.dims == ("lat", "lon")


def test_synthetic_attributes_and_calibration(synthetic):
    ds = nc3.read(synthetic)
    var = ds["temperature"]
    assert var.unit == "K"
    assert var.long_name == "Brightness temperature"
    assert var.scale_factor == pytest.approx(0.01)
    assert var.add_offset == pytest.approx(200.0)
    assert var.valid_range == (0.0, 10000.0)
    assert var.fill_value == pytest.approx(-1.0)
    assert var.data[0, 0] == 0 and var.data[2, 2] == 10000

    phys = var.physical()
    print("physical:\n", np.round(phys, 3))
    assert phys[0, 0] == pytest.approx(200.0)
    assert phys[1, 1] == pytest.approx(250.0)
    assert np.isnan(phys[2, 3]), "填充值必须被掩成 NaN"
    assert int(np.isnan(phys).sum()) == 1


def test_synthetic_geolocation(synthetic):
    ds = nc3.read(synthetic)
    geo = ds.geolocation
    assert geo.kind == "latlon_grid", "二维经纬度变量应识别为 latlon_grid"
    assert geo.is_nav
    lo0, lo1, la0, la1 = geo.bounds()
    print("bounds:", geo.bounds())
    assert (lo0, lo1) == pytest.approx((100.0, 103.0))
    assert (la0, la1) == pytest.approx((-10.0, 10.0))
    assert geo.params["lat_name"] == "latitude"


def test_synthetic_time_and_platform(synthetic):
    ds = nc3.read(synthetic)
    # 文件名的下划线写法 "Satellite_Name" 也要认
    assert ds.platform == "FY-3H"
    assert ds.level == "L1" and ds.product == "AE"
    assert ds.attrs["Observing_Beginning_Date"] == "2026-10-19"


def test_synthetic_read_variable_and_list(synthetic):
    rows = nc3.list_variables(synthetic)
    assert {r["name"] for r in rows} == {"temperature", "time", "latitude", "longitude"}
    # 顺序必须与 read() 的变量顺序一致（scipy 按文件内部顺序给出，记录变量在后）
    assert [r["name"] for r in rows] == list(nc3.read(synthetic, load=False).variables)
    temp_row = next(r for r in rows if r["name"] == "temperature")
    assert temp_row["shape"] == [3, 4] and temp_row["unit"] == "K"
    back = nc3.read_variable(synthetic, "temperature")
    assert np.array_equal(back, nc3.read(synthetic)["temperature"].data)
    with pytest.raises(KeyError):
        nc3.read_variable(synthetic, "nope")


def test_reject_wrong_magic(tmp_path):
    bad = tmp_path / "not_nc.nc"
    bad.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 64)
    with pytest.raises(ValueError, match="NetCDF-3"):
        nc3.read(bad)


def test_reject_cdf5(tmp_path):
    cdf5 = tmp_path / "cdf5.nc"
    cdf5.write_bytes(b"CDF\x05" + b"\x00" * 64)
    with pytest.raises(NotImplementedError, match="CDF-5"):
        nc3.read(cdf5)


# ---------------------------------------------------------------- 真实样本


@pytest.fixture(scope="module")
def sample() -> Path:
    hits = sorted(glob.glob(SAMPLE_GLOB, recursive=True))
    if not hits:
        pytest.skip(f"未找到 FY-3 GNOSO 样本（{SAMPLE_GLOB}）")
    for hit in hits:
        if "20261019_0000_ANC31" in hit:
            return Path(hit)
    return Path(hits[0])


def test_sample_container(sample):
    head = sample.read_bytes()[:4]
    print(f"{sample.name} 魔数 {head!r}  {sample.stat().st_size:,} B")
    assert head[:3] == b"CDF" and head[3] in (1, 2)
    assert sniff(sample) == "netcdf3"


def test_sample_variables_contract(sample):
    ds = nc3.read(sample, load=False)
    dims = ds.attrs["dimensions"]
    print("维度:", dims)
    assert len(dims) == 1 and "time" in dims, "GNOSO 只有一个 time 维"
    n_time = dims["time"]
    assert 500 < n_time < 20000, f"剖面采样点数异常：{n_time}"

    print(f"变量 {len(ds.variables)} 个")
    missing_unit, missing_fill, missing_valid = [], [], []
    for var in ds.variables.values():
        if not var.unit:
            missing_unit.append(var.name)
        if var.fill_value is None:
            missing_fill.append(var.name)
        if var.valid_range is None:
            missing_valid.append(var.name)
        assert var.shape == (n_time,), f"{var.name} 形状应为 (time,)"
        assert var.dims == ("time",)
    assert not missing_unit, f"缺单位：{missing_unit}"
    assert not missing_fill, f"缺填充值：{missing_fill}"
    assert not missing_valid, f"缺有效范围：{missing_valid}"


def test_sample_global_attrs(sample):
    ds = nc3.read(sample, load=False)
    a = ds.attrs
    assert a["Satellite Name"] == "FY-3H"
    assert a["Sensor Identification Code"] == "GNOS-II"
    assert a["Dataset Name"] == "GNOS-II L1 AE Data"
    assert a["dataLevel"] == "L1"
    print("全局属性数:", len(a))
    assert len(a) > 50, "GNOSO 全局属性应有几十个"
    assert ds.platform == "FY-3H" and ds.level == "L1" and ds.product == "AE"
    assert ds.start_time == datetime(2026, 10, 19, 0, 0, 39)
    assert ds.end_time == datetime(2026, 10, 19, 0, 2, 8)


def test_sample_values(sample):
    ds = nc3.read(sample)
    print(f"{'变量':<14}{'min':>14}{'max':>14}  unit")
    for name in ("time", "TPH", "xLeo", "zGnss", "exL1"):
        v = ds[name]
        d = v.data
        print(f"{name:<14}{d.min():>14.4g}{d.max():>14.4g}  {v.unit}")
    # 掩星时间序列：0~240 s（文档 valid_range）
    t = ds["time"].data
    assert t.min() >= -1.0 and t.max() <= 240.0
    assert np.all(np.diff(t) > 0), "时间应单调递增"
    # 切点高度（TPH）范围：对流层到平流层，实测 -157 ~ +107 km
    tph = ds["TPH"].data
    assert -1000.0 < tph.min() < 0 < tph.max() < 1500.0
    # LEO 位置应在地球附近（km）
    for name in ("xLeo", "yLeo", "zLeo"):
        assert np.all(np.abs(ds[name].data) < 7378.0)
    # GNSS 位置应在 GNSS 轨道附近
    assert np.all(np.abs(ds["zGnss"].data) < 26564.0)
    # 定标系数：GNOSO 的 Slope=1、Intercept=0，物理量即原值
    assert ds["TPH"].scale_factor == pytest.approx(1.0)
    assert ds["TPH"].add_offset == pytest.approx(0.0)
    # 全填充变量：physical() 必须全是 NaN
    v = ds["exLC_C1C2"]
    assert np.isnan(v.physical()).all(), "整列 9.969e36 的变量应全部掩成 NaN"
    assert "nc_default_fill" in v.attrs


def test_sample_geolocation(sample):
    ds = nc3.read(sample)
    geo = ds.geolocation
    print("定位:", geo.kind, geo.params)
    assert geo.kind == "nominal"
    assert geo.params["occ_lat"] == pytest.approx(23.895)
    assert geo.params["occ_lon"] == pytest.approx(-167.052)
    assert geo.params["gnssName"] == "BDS"
    assert -90 <= geo.params["occ_lat"] <= 90
    assert -180 <= geo.params["occ_lon"] <= 180


def test_sample_every_variable_loadable(sample):
    ds = nc3.read(sample)
    n = ds.attrs["dimensions"]["time"]
    for name, var in ds.variables.items():
        assert var.data.shape == (n,), f"{name} 数据长度不符"
        assert var.data.size == n
        # 掩膜后的物理量不应残留巨大的默认填充值
        phys = var.physical()
        assert np.all(np.abs(phys[np.isfinite(phys)]) < 1e30), f"{name} 残留填充值"


def test_cli_info(sample, capsys):
    from fysat.cli import main

    assert main(["info", str(sample)]) == 0
    out = capsys.readouterr().out
    print(out)
    assert "netcdf3" in out
    assert "FY-3H" in out and "GNOSO" in out and "L1" in out
    assert "共 29 个" in out
