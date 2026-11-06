"""AWX 2.1 读取器测试：合成文件（定标表全覆盖）+ 真实样本回归（无样本时跳过）。"""
from __future__ import annotations
from _sample_root import SAMPLE_ROOT

import struct
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from fysat import cli
from fysat.detect import sniff
from fysat.model import SatDataset
from fysat.readers import awx, open_file

SAMPLE_DIR = SAMPLE_ROOT / r"A202610310424037331"
SAMPLE_AWX = SAMPLE_DIR / "MST2_SEC_VIS_LCN_20151204_0032.AWX"
SAMPLE_AWX2 = SAMPLE_DIR / "MST2_SEC_VIS_LCN_20151204_0101.AWX"

need_awx = pytest.mark.skipif(not SAMPLE_AWX.is_file(), reason="缺少 AWX 样本")

L1 = 40
L2 = 64 + 2048        # 描述部分 + 定标表
PAD = 408
REC = 512
HDR_RECS = (L1 + L2 + PAD) // REC     # = 5
W = H = 512


def _i16(v: int) -> bytes:
    return struct.pack("<h", v)


def _write_awx(path: Path, dn: np.ndarray, *, channel: int = 4, projection: int = 1,
               lut_cover: int = 255, sat: bytes = b"FY2G") -> None:
    """造一个最小 AWX 2.1 静止图像产品（小端、8 bit、无压缩、带定标表无定位块）。"""
    l1 = bytearray(L1)
    l1[0:12] = b"TEST0001.AWX"
    struct.pack_into("<h", l1, 12, 0)                  # 小端
    struct.pack_into("<h", l1, 14, L1)
    struct.pack_into("<h", l1, 16, L2)
    struct.pack_into("<h", l1, 18, PAD)
    struct.pack_into("<h", l1, 20, REC)
    struct.pack_into("<h", l1, 22, HDR_RECS)
    struct.pack_into("<h", l1, 24, (W * H) // REC if channel else (3 * W * H) // REC)
    struct.pack_into("<h", l1, 26, 1)                  # 静止气象卫星图像产品
    struct.pack_into("<h", l1, 28, 0)                  # 未压缩
    l1[30:38] = b"SAT2004\x00"
    struct.pack_into("<h", l1, 38, 1)                  # 质量标记

    l2 = bytearray(L2)
    l2[0:8] = (sat + b"\x00" * 8)[:8]
    struct.pack_into("<5h", l2, 8, 2020, 1, 2, 3, 4)   # 年/月/日/时/分
    struct.pack_into("<h", l2, 18, channel)
    struct.pack_into("<h", l2, 20, projection)
    struct.pack_into("<h", l2, 22, W)
    struct.pack_into("<h", l2, 24, H)
    struct.pack_into("<h", l2, 26, 0)                  # 左上角扫描线号
    struct.pack_into("<h", l2, 28, 0)                  # 左上角象元号
    struct.pack_into("<h", l2, 30, 1)                  # 抽样率
    struct.pack_into("<4h", l2, 32, 6052, -64, 8659, 16177)   # 北/南/西/东（×100）
    struct.pack_into("<h", l2, 40, 3000)               # 投影中心纬度 30.00
    struct.pack_into("<h", l2, 42, 11000)               # 投影中心经度 110.00
    struct.pack_into("<h", l2, 44, 3000)               # 标准纬度 1
    struct.pack_into("<h", l2, 46, 6000)               # 标准纬度 2
    struct.pack_into("<h", l2, 48, 1300)               # 水平分辨率 13 km
    struct.pack_into("<h", l2, 50, 1300)
    struct.pack_into("<h", l2, 52, 0)                  # 未叠加地理网格
    struct.pack_into("<h", l2, 54, 255)
    struct.pack_into("<h", l2, 56, 0)                  # 无调色表
    struct.pack_into("<h", l2, 58, 2048)               # 定标表 2048 B
    struct.pack_into("<h", l2, 60, 0)                  # 无定位块
    # 定标表：DN i → i*10（0.01% 单位 → 255 对应 25.50%），覆盖 1..lut_cover
    lut = np.zeros(1024, dtype="<u2")
    lut[1:lut_cover + 1] = np.arange(1, lut_cover + 1, dtype=np.uint16) * 10
    l2[64:64 + 2048] = lut.tobytes()

    body = bytes(l1) + bytes(l2) + bytes(PAD) + dn.astype(np.uint8).tobytes()
    assert len(body) == HDR_RECS * REC + W * H
    path.write_bytes(body)


def _write_polar_awx(path: Path, dn: np.ndarray, *, bpp: int = 2) -> None:
    """造一个极轨图像产品 AWX（类别 2，88 B 描述部分，每像元 2 字节）。"""
    l2_len = 88 + 2048
    hdr_recs = 6
    pad = hdr_recs * REC - L1 - l2_len
    l1 = bytearray(L1)
    l1[0:12] = b"TEST0002.AWX"
    struct.pack_into("<h", l1, 12, 0)
    struct.pack_into("<h", l1, 14, L1)
    struct.pack_into("<h", l1, 16, l2_len)
    struct.pack_into("<h", l1, 18, pad)
    struct.pack_into("<h", l1, 20, REC)
    struct.pack_into("<h", l1, 22, hdr_recs)
    struct.pack_into("<h", l1, 24, (W * H * bpp) // REC)     # 产品数据记录数
    struct.pack_into("<h", l1, 26, 2)                    # 极轨图像产品
    struct.pack_into("<h", l1, 28, 0)
    l1[30:38] = b"SAT2004\x00"

    l2 = bytearray(l2_len)
    l2[0:8] = b"FY-1D\x00\x00\x00"
    struct.pack_into("<5h", l2, 8, 2020, 2, 3, 4, 5)      # 开始时间
    struct.pack_into("<5h", l2, 18, 2020, 2, 3, 4, 25)    # 结束时间
    struct.pack_into("<h", l2, 28, 4)                     # 通道号 可见光
    struct.pack_into("<3h", l2, 30, 0, 0, 0)              # R/G/B 通道号
    struct.pack_into("<h", l2, 36, 1)                     # 升轨
    struct.pack_into("<h", l2, 38, 12345)                 # 轨道号
    struct.pack_into("<h", l2, 40, bpp)                   # 每像元字节数
    struct.pack_into("<h", l2, 42, 4)                     # 等经纬度投影
    struct.pack_into("<h", l2, 44, 3)                     # 产品类型
    struct.pack_into("<h", l2, 46, W)
    struct.pack_into("<h", l2, 48, H)
    struct.pack_into("<h", l2, 50, 0)
    struct.pack_into("<h", l2, 52, 0)
    struct.pack_into("<h", l2, 54, 1)
    struct.pack_into("<4h", l2, 56, 4000, 1000, 7000, 12000)
    struct.pack_into("<h", l2, 64, 2500)
    struct.pack_into("<h", l2, 66, 9500)
    struct.pack_into("<h", l2, 68, 0)
    struct.pack_into("<h", l2, 70, 0)
    struct.pack_into("<h", l2, 72, 110)
    struct.pack_into("<h", l2, 74, 110)
    struct.pack_into("<h", l2, 76, 0)
    struct.pack_into("<h", l2, 78, 0)
    struct.pack_into("<h", l2, 80, 0)                     # 无调色表
    struct.pack_into("<h", l2, 82, 2048)                  # 定标表
    struct.pack_into("<h", l2, 84, 0)                     # 无定位块
    lut = np.zeros(1024, dtype="<u2")
    lut[0:1024] = (np.arange(1024) * 15000 // 1023).astype(np.uint16)
    l2[88:88 + 2048] = lut.tobytes()

    body = bytes(l1) + bytes(l2) + bytes(pad) + dn.astype("<u2").tobytes()
    assert len(body) == hdr_recs * REC + W * H * bpp
    path.write_bytes(body)


@pytest.fixture(scope="module")
def synthetic_awx(tmp_path_factory) -> tuple[Path, np.ndarray]:
    yy, xx = np.mgrid[0:H, 0:W]
    dn = ((np.sin(xx / 40.0) + np.cos(yy / 55.0) + 2) * 60).astype(np.uint8)
    p = tmp_path_factory.mktemp("awx") / "FY2G_SYN_VIS.AWX"
    _write_awx(p, np.clip(dn, 0, 255))
    return p, np.clip(dn, 0, 255)


# ------------------------------------------------------------------ 合成样本测试


def test_registry_dispatch(synthetic_awx):
    p = synthetic_awx[0]
    assert sniff(p) == "awx"
    ds = open_file(p, load=False)
    assert isinstance(ds, SatDataset) and ds.reader == "awx"


def test_synthetic_header(synthetic_awx):
    ds = awx.read(synthetic_awx[0])
    assert ds.attrs["byte_order"] == "little-endian"
    assert ds.attrs["format_string"] == "SAT2004"
    assert ds.attrs["product_category_name"] == "静止气象卫星图像产品"
    assert ds.attrs["compression_name"] == "未压缩"
    assert ds.attrs["image_width"] == W and ds.attrs["image_height"] == H
    assert ds.attrs["channel"] == 4 and ds.attrs["channel_name"] == "VIS"
    assert ds.attrs["projection_name"] == "兰勃托投影"
    assert ds.attrs["geographic_range_deg"]["north"] == pytest.approx(60.52)
    assert ds.attrs["projection_center_deg"] == {"lat": 30.0, "lon": 110.0}
    assert ds.attrs["resolution_km"] == {"x": 13.0, "y": 13.0}
    assert ds.attrs["block_lengths"] == {"palette": 0, "calibration": 2048, "navigation": 0}
    assert ds.start_time == datetime(2020, 1, 2, 3, 4)
    assert ds.platform == "FY2G"
    assert ds.instrument == "VISSR"


def test_synthetic_raster_roundtrip(synthetic_awx):
    p, dn = synthetic_awx
    ds = awx.read(p, load=True)
    vis = ds.variables["VIS"]
    assert vis.shape == (H, W)
    assert vis.dtype == np.uint8
    assert vis.unit == "count"
    np.testing.assert_array_equal(vis.data, dn)      # 光栅必须逐字节可逆


def test_synthetic_calibration_applied_when_covered(synthetic_awx):
    """定标表覆盖 1..255（本样本 DN ≤ 255）→ to_physical 应全部有效。"""
    ds = awx.read(synthetic_awx[0])
    ph = awx.to_physical(ds)
    assert ph.shape == (H, W)
    assert np.isfinite(ph).all()
    assert ph.min() == pytest.approx(0.0)
    assert ph.max() == pytest.approx(float(ds.variables["VIS"].data.max()) * 10 * 0.01, rel=1e-5)
    lut = ds.variables["calibration_lut"]
    assert lut.shape == (1024,)
    assert lut.attrs["nonzero_range"] == (1, 255)
    # 覆盖完整时不应出现"超出定标表"的告警
    assert not any("超出定标表" in u["reason"] for u in ds.attrs["unparsed"])


def test_synthetic_load_false_shapes(synthetic_awx, tmp_path):
    p = synthetic_awx[0]
    ds = awx.read(p, load=False)
    vis = ds.variables["VIS"]
    assert vis.data.size == 0
    assert vis.source_shape == (H, W) and vis.shape == (H, W)
    assert ds.variables["calibration_lut"].data.size == 1024   # 定标表很小，始终解析


def test_synthetic_three_channel_composite(tmp_path):
    """通道号 = 0 → 三通道合成，应按 R/G/B 三个平面解析。"""
    p = tmp_path / "SYN_RGB.AWX"
    rgb = np.random.default_rng(3).integers(0, 256, size=(3, H, W)).astype(np.uint8)
    _write_awx(p, rgb[0], channel=0)
    raw = p.read_bytes()
    p.write_bytes(raw[:HDR_RECS * REC] + rgb.tobytes())
    ds = awx.read(p)
    assert set(ds.variables) >= {"R", "G", "B"}
    for i, name in enumerate(("R", "G", "B")):
        np.testing.assert_array_equal(ds.variables[name].data, rgb[i])
    assert ds.attrs["channel_name"] == "RGB"


def test_synthetic_16bit_raster(tmp_path):
    """极轨产品声明"每像元 2 字节" → 应按 u16 解析，且通道/时间/轨道号取自极轨布局。"""
    p = tmp_path / "SYN_POLAR16.AWX"
    dn16 = ((np.arange(H * W, dtype=np.uint16) * 7) % 1024).reshape(H, W)
    _write_polar_awx(p, dn16, bpp=2)
    ds = awx.read(p)
    assert ds.attrs["product_category"] == 2
    assert ds.attrs["bytes_per_pixel_declared"] == 2
    assert ds.attrs["channel"] == 4 and ds.attrs["projection_name"] == "等经纬度投影"
    assert ds.start_time == datetime(2020, 2, 3, 4, 5)
    assert ds.end_time == datetime(2020, 2, 3, 4, 25)
    assert ds.attrs["orbit_number"] == 12345
    assert ds.attrs["image_width"] == W and ds.attrs["image_height"] == H
    vis = ds.variables["VIS"]
    assert vis.dtype == np.uint16 and vis.shape == (H, W)
    np.testing.assert_array_equal(vis.data, dn16)
    # 定标表覆盖 0..1023（极轨 10 bit 产品）→ 物理量应全部有效
    ph = awx.to_physical(ds)
    assert np.isfinite(ph).all()
    assert ph.max() == pytest.approx(150.0, rel=1e-3)
    assert any("极轨" in u["field"] for u in ds.attrs["unparsed"])   # 无样本验证要如实标注


def test_unsupported_category_raises(tmp_path):
    p = tmp_path / "SYN_GRID.AWX"
    _write_awx(p, np.zeros((H, W), dtype=np.uint8))
    raw = bytearray(p.read_bytes())
    struct.pack_into("<h", raw, 26, 3)      # 格点场定量产品
    p.write_bytes(bytes(raw))
    with pytest.raises(NotImplementedError, match="格点场定量产品"):
        awx.read(p)


def test_lut_coverage_helper():
    lut = np.array([0, 0, 9, 19, 0, 0], dtype=np.uint16)
    assert awx._lut_coverage(lut) == (2, 3)
    assert awx._lut_coverage(np.zeros(8, dtype=np.uint16)) is None
    assert awx._lut_coverage(None) is None


def test_compressed_raster_is_reported_not_guessed(tmp_path):
    p = tmp_path / "SYN_RLE.AWX"
    _write_awx(p, np.zeros((H, W), dtype=np.uint8))
    raw = bytearray(p.read_bytes())
    struct.pack_into("<h", raw, 28, 1)      # 行程编码压缩
    p.write_bytes(bytes(raw))
    ds = awx.read(p)
    fields = [u["field"] for u in ds.attrs["unparsed"]]
    assert "图象数据段" in fields
    assert ds.variables["VIS"].data.size == 0 or ds.variables["VIS"].data.shape == (H, W)


def test_load_array_helper(synthetic_awx):
    p, dn = synthetic_awx
    np.testing.assert_array_equal(awx.load_array(p, "VIS"), dn)
    with pytest.raises(KeyError):
        awx.load_array(p, "NOPE")


def test_list_tree(synthetic_awx):
    """`cli ls` 需要和 hdf5.list_tree 同格式的行。"""
    rows = awx.list_tree(synthetic_awx[0])
    assert rows and all({"path", "kind"} <= set(r) for r in rows)
    paths = {r["path"] for r in rows}
    assert "/VIS" in paths and "/calibration_lut" in paths
    vis = next(r for r in rows if r["path"] == "/VIS")
    assert vis["shape"] == [H, W] and vis["dtype"] == "uint8"
    assert len(awx.list_tree(synthetic_awx[0], max_items=2)) == 2


# ------------------------------------------------------------------ 真实样本回归


@need_awx
def test_real_awx_structure():
    ds = awx.read(SAMPLE_AWX)
    assert ds.reader == "awx"
    assert ds.attrs["byte_order"] == "little-endian"
    assert ds.attrs["format_string"] == "SAT2004"
    assert ds.attrs["image_width"] == 512 and ds.attrs["image_height"] == 512
    assert ds.attrs["record_length"] == 512
    assert ds.attrs["header_records"] == 6
    assert ds.attrs["header_bytes"] == 3072
    assert ds.attrs["data_bytes_expected"] == ds.attrs["data_bytes_actual"] == 512 * 512
    assert ds.attrs["channel"] == 4
    assert ds.attrs["projection_name"] == "兰勃托投影"
    # 卫星名：头 MST1 / 文件名 MST2，两处都要保留
    assert ds.platform == "MST2"
    assert ds.attrs["satellite_name_header"] == "MST1"
    assert ds.level == "L1"
    assert any(s.startswith("/DPCMTST/L1/") for s in ds.attrs["extension_strings"])


@need_awx
def test_real_awx_raster():
    ds = awx.read(SAMPLE_AWX)
    vis = ds.variables["VIS"]
    assert vis.shape == (512, 512) and vis.dtype == np.uint8
    assert 100 < int(vis.data.max()) <= 255            # 8 bit 数据，样本实测最大 180
    # 真实图象必然空间连续（邻像元/行间相关都不该为 0）
    a = vis.data.astype(np.float32)
    assert float(np.corrcoef(a[:, :-1].ravel(), a[:, 1:].ravel())[0, 1]) > 0.5
    assert float(np.corrcoef(a[:-1].ravel(), a[1:].ravel())[0, 1]) > 0.5


@need_awx
def test_real_awx_calibration_gap_is_reported():
    ds = awx.read(SAMPLE_AWX)
    cov = ds.attrs["calibration"]["coverage"]
    assert cov is not None and cov[1] < 255            # 定标表只覆盖到 63（6 bit 产品）
    lut = ds.variables["calibration_lut"].data
    assert lut[:cov[1] + 1].max() > 0
    assert np.all(lut[cov[1] + 1:] == 0)
    reasons = " ".join(u["reason"] for u in ds.attrs["unparsed"])
    assert "超出定标表" in reasons                     # 必须如实报告不一致
    # 覆盖范围内可以换算，范围外必须是 NaN（不外推）
    ph = awx.to_physical(ds)
    dn = ds.variables["VIS"].data
    assert np.isnan(ph[dn > cov[1]]).all()
    assert np.isfinite(ph[dn <= cov[1]]).all()
    assert 0 <= np.nanmax(ph) <= 7.0                   # 覆盖范围内最多 6.06%


@need_awx
def test_real_awx_nominal_geolocation():
    ds = awx.read(SAMPLE_AWX)
    geo = ds.geolocation
    assert geo.kind == "nominal"
    assert geo.bounds() is None                        # 没有 nav 网格 → 不伪造经纬度
    gr = geo.params["geographic_range_deg"]
    assert gr["north"] == pytest.approx(60.52)
    assert gr["south"] == pytest.approx(-0.64)
    assert gr["west"] == pytest.approx(86.59)
    assert gr["east"] == pytest.approx(161.77)
    assert geo.params["center_deg"] == {"lat": 30.0, "lon": 110.0}
    assert awx.read(SAMPLE_AWX, geo="none").geolocation.kind == "none"


@need_awx
@pytest.mark.skipif(not SAMPLE_AWX2.is_file(), reason="缺少第二个 AWX 样本")
def test_two_samples_share_header_but_differ_in_data():
    a = awx.read(SAMPLE_AWX)
    b = awx.read(SAMPLE_AWX2)
    assert a.start_time != b.start_time
    assert a.attrs["image_width"] == b.attrs["image_width"] == 512
    assert a.attrs["channel"] == b.attrs["channel"] == 4
    assert not np.array_equal(a.variables["VIS"].data, b.variables["VIS"].data)


@need_awx
def test_cli_info_awx(capsys):
    assert cli.main(["info", str(SAMPLE_AWX)]) == 0
    out = capsys.readouterr().out
    assert "awx" in out and "MST2" in out and "VIS" in out
    assert "(512, 512)" in out
