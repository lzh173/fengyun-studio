"""1B 读取器测试：合成文件做字节级往返验证 + 真实样本回归（无样本时自动跳过）。"""
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
from fysat.readers import oneb, open_file

FY1D_REC = 28400
NA18_REC = 22016

SAMPLE_FY1D = SAMPLE_ROOT / r"FY1D_AVHRR_HRPT_L1_ORB_MLT_NUL_20120329_0743_1100M_PJ.L1B"
SAMPLE_NA18 = Path(
    str(SAMPLE_ROOT / r"A202607300042001850\NA18_AVHRR_HRPT_L1_ORB_MLT_NUL_20180308_0054_1100M_PJ.L1B"))

need_fy1d = pytest.mark.skipif(not SAMPLE_FY1D.is_file(), reason="缺少 FY-1D 1B 样本")
need_na18 = pytest.mark.skipif(not SAMPLE_NA18.is_file(), reason="缺少 NOAA-18 1B 样本")


# ------------------------------------------------------------------ 合成样本


def _pack_fy1d_data(dn: np.ndarray) -> bytes:
    """(2048, 10) uint16 → 27308 B：每 4 字节 2bit 填充 + 3×10bit 样本。"""
    flat = dn.reshape(-1)
    words = []
    for i in range(0, flat.size, 3):
        trio = flat[i:i + 3]
        w = 0
        for j, v in enumerate(trio):
            w |= int(v) << (20 - 10 * j)
        words.append(w)
    return np.asarray(words, dtype=">u4").tobytes()


def _write_fy1d(path: Path, dn: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> None:
    """造一个最小 FY-1C/D 1B：TBM 记录 + 数据头 + N 条数据记录。"""
    n_scans = dn.shape[0]
    tbm = bytearray(b" " * FY1D_REC)
    tbm[30:74] = b"SMC.HRPT.\x00\x00\x00\x0012089.S0743.E0756.B2079494.PP.\x00"   # 44 B
    tbm[74:97] = b"T014061007501250743013Y"[:23]
    tbm[97:117] = b"1111111111          "[:20]
    tbm[400:414] = b"p1bm2974.f1d.\x00"   # 14 B
    assert len(tbm) == FY1D_REC

    hdr = bytearray(FY1D_REC)
    hdr[0] = 114           # FY-1D
    hdr[1] = 0
    struct.pack_into(">h", hdr, 2, 12)          # 2012 年
    struct.pack_into(">h", hdr, 4, 89)          # 第 89 天
    struct.pack_into(">I", hdr, 6, 27832324)    # 07:43:52.324
    struct.pack_into(">h", hdr, 10, n_scans)
    struct.pack_into(">h", hdr, 12, 12)
    struct.pack_into(">h", hdr, 14, 89)
    struct.pack_into(">I", hdr, 16, 28586826)
    struct.pack_into(">h", hdr, 198, 20794)
    struct.pack_into(">6h", hdr, 200, 2012, 3, 26, 23, 25, 2907)
    struct.pack_into(">i", hdr, 212, 7236908)
    struct.pack_into(">i", hdr, 216, 162620)
    struct.pack_into(">i", hdr, 220, 98754199)
    struct.pack_into(">8i", hdr, 256, 141345, 996263, 181858, 1255803,
                     543039, 755032, 615683, 1224605)

    records = []
    for i in range(n_scans):
        rec = bytearray(FY1D_REC)
        struct.pack_into(">h", rec, 0, i + 1)
        struct.pack_into(">h", rec, 2, 12)
        struct.pack_into(">h", rec, 4, 89)
        struct.pack_into(">I", rec, 6, 27832324 + 167 * i)
        struct.pack_into(">H", rec, 10, 0)
        # 定标系数（样本中逐条相同；此处给可辨识的常数）
        struct.pack_into(">10i", rec, 16, *[138727440] * 10)
        struct.pack_into(">10i", rec, 56, *[95455648] * 10)
        struct.pack_into(">51h", rec, 96, *([6000] * 51))       # 太阳天顶角 46.875°
        struct.pack_into(">51h", rec, 198, *([8000] * 51))      # 卫星天顶角 62.5°
        struct.pack_into(">51h", rec, 300, *([256] * 51))       # 相对方位角 2°
        struct.pack_into(">102h", rec, 402, *_interleave(lat[i], lon[i]))
        rec[1000:1000 + 27308] = _pack_fy1d_data(dn[i])
        records.append(rec)

    path.write_bytes(bytes(tbm) + bytes(hdr) + b"".join(bytes(r) for r in records))


def _interleave(a: np.ndarray, b: np.ndarray) -> list[int]:
    out: list[int] = []
    for x, y in zip(a.tolist(), b.tolist()):
        out.extend((int(x), int(y)))
    return out


def _write_na18(path: Path, dn: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> None:
    """造一个最小 NOAA-K/L/M/N 1B：1 条头记录 + N 条数据记录。"""
    n_scans = dn.shape[0]
    hdr = bytearray(NA18_REC)
    struct.pack_into(">h", hdr, 4, 1)                 # 格式版本
    struct.pack_into(">h", hdr, 6, 2005)
    struct.pack_into(">h", hdr, 8, 167)
    struct.pack_into(">h", hdr, 10, NA18_REC)         # 逻辑记录长度
    struct.pack_into(">h", hdr, 14, 1)                # 头记录数
    hdr[22:64] = b"/N1BD/N18/NOAA18_AVHRR_CHINA_L1_20180308_N00001"[:42].ljust(42, b"\x00")
    struct.pack_into(">h", hdr, 72, 13)               # NOAA-18
    struct.pack_into(">h", hdr, 74, 1)
    struct.pack_into(">h", hdr, 76, 3)                # HRPT
    struct.pack_into(">I", hdr, 80, 24904)
    struct.pack_into(">h", hdr, 84, 2018)
    struct.pack_into(">h", hdr, 86, 67)
    struct.pack_into(">I", hdr, 88, 3242454)
    struct.pack_into(">I", hdr, 92, 24904)
    struct.pack_into(">h", hdr, 96, 2018)
    struct.pack_into(">h", hdr, 98, 67)
    struct.pack_into(">I", hdr, 100, 3998454)
    struct.pack_into(">h", hdr, 128, n_scans)
    struct.pack_into(">h", hdr, 130, n_scans)
    struct.pack_into(">4i", hdr, 256, 1332, 81, 1298, 200)     # CH1/CH2 辐照度、等效带宽
    struct.pack_into(">i", hdr, 280, 266936)                  # CH3b 中心波数 ×100
    struct.pack_into(">i", hdr, 292, 92629)                   # CH4
    struct.pack_into(">i", hdr, 304, 83982)                   # CH5
    hdr[328:336] = b"WGS-72  "
    struct.pack_into(">h", hdr, 348, 2018)
    struct.pack_into(">h", hdr, 350, 64)
    struct.pack_into(">i", hdr, 356, 722660900)
    struct.pack_into(">i", hdr, 360, 151140)
    struct.pack_into(">i", hdr, 364, 9915830)

    # 可见光定标：业务/测试/发射前 三组 × 3 通道 × 5 系数
    vis = [540000014, -21300002, 1609999984, -553699968, 501,
           529000014, -20840002, 1587300002, -553100032, 500,
           260000000, -1000000, 1800000000, -800000000, 500]
    vis_block = [v for _group in range(3) for v in vis]
    # 红外定标：2 组 × 3 通道 × 3 系数 (a0, a1, a2)
    ir_block = [0, -2897, 2872545, 0, 0, 0,
                0, -190672, 183426376, 0, 0, 0,
                0, -198656, 194531188, 0, 0, 0]

    records = []
    for i in range(n_scans):
        rec = bytearray(NA18_REC)
        struct.pack_into(">h", rec, 0, i + 1)
        struct.pack_into(">h", rec, 2, 2018)
        struct.pack_into(">h", rec, 4, 67)
        struct.pack_into(">h", rec, 6, 0)
        struct.pack_into(">I", rec, 8, 3242454 + 167 * i)
        struct.pack_into(">H", rec, 12, 0)            # bit0=0 → 3A，升轨
        struct.pack_into(">I", rec, 24, 0)
        struct.pack_into(">45i", rec, 48, *vis_block)
        struct.pack_into(">18i", rec, 228, *ir_block)
        struct.pack_into(">3h", rec, 320, 10, -20, 30)
        struct.pack_into(">h", rec, 326, 8500)
        angles = []
        for k in range(oneb.NAV_POINTS):
            angles += [6000 + k, 3000 + k, 1000 + k]
        struct.pack_into(">153h", rec, 328, *angles)
        pairs = []
        for k in range(oneb.NAV_POINTS):
            pairs += [int(lat[i, k]), int(lon[i, k])]
        struct.pack_into(">102i", rec, 640, *pairs)
        rec[1264:1264 + 20480] = dn[i].astype(">u2").tobytes()
        records.append(rec)

    path.write_bytes(bytes(hdr) + b"".join(bytes(r) for r in records))


@pytest.fixture(scope="module")
def fy1d_synthetic(tmp_path_factory) -> tuple[Path, np.ndarray]:
    rng = np.random.default_rng(7)
    dn = rng.integers(0, 1024, size=(3, 2048, 10), dtype=np.uint16)
    lat = np.linspace(23.0, 20.0, oneb.NAV_POINTS)[None, :] - np.arange(3)[:, None] * 0.1
    lon = np.broadcast_to(np.linspace(125.0, 105.0, oneb.NAV_POINTS)[None, :], lat.shape)
    p = tmp_path_factory.mktemp("oneb") / "SYN_FY1D.L1B"
    _write_fy1d(p, dn, np.round(lat * 128), np.round(lon * 128))
    return p, dn


@pytest.fixture(scope="module")
def na18_synthetic(tmp_path_factory) -> tuple[Path, np.ndarray]:
    rng = np.random.default_rng(11)
    dn = rng.integers(0, 1024, size=(3, 2048, 5), dtype=np.uint16)
    lat = (np.linspace(65.0, 64.0, oneb.NAV_POINTS)[None, :] - np.arange(3)[:, None] * 0.05) * 1e4
    lon = np.broadcast_to(np.linspace(90.0, 140.0, oneb.NAV_POINTS)[None, :], lat.shape) * 1e4
    p = tmp_path_factory.mktemp("oneb") / "SYN_NA18.L1B"
    _write_na18(p, dn, np.round(lat), np.round(lon))
    return p, dn


# ------------------------------------------------------------------ 合成样本测试


def test_detect_variant(fy1d_synthetic, na18_synthetic):
    assert oneb.detect_variant(fy1d_synthetic[0]) == "fy1d"
    assert oneb.detect_variant(na18_synthetic[0]) == "noaa"


def test_registry_dispatch(fy1d_synthetic):
    """readers.__init__ 的自动分派要能认出 .L1B → oneb。"""
    p = fy1d_synthetic[0]
    assert sniff(p) == "oneb"
    ds = open_file(p, load=False, max_scans=1)
    assert isinstance(ds, SatDataset) and ds.reader == "oneb"


def test_fy1d_synthetic_roundtrip(fy1d_synthetic):
    p, dn = fy1d_synthetic
    ds = oneb.read(p, load=True)
    assert ds.attrs["variant"] == "fy1d"
    assert len(ds.variables) == 10
    assert ds.attrs["record_length"] == FY1D_REC
    assert ds.attrs["n_scans"] == 3
    for c in range(10):
        v = ds.variables[f"CH{c + 1}"]
        assert v.shape == (3, 2048)
        assert v.dtype == np.uint16
        assert v.unit == "count"
        assert v.valid_range == (0.0, 1023.0)
        np.testing.assert_array_equal(v.data, dn[..., c])   # 位解包必须完全可逆


def test_fy1d_synthetic_metadata(fy1d_synthetic):
    ds = oneb.read(fy1d_synthetic[0], load=False)
    assert ds.platform == "FY-1D"
    assert ds.instrument == "AVHRR"
    assert ds.level == "L1"
    assert ds.start_time == datetime(2012, 3, 29, 7, 43, 52, 324000)
    assert ds.end_time is not None and ds.end_time > ds.start_time
    assert ds.attrs["tbm_name"].startswith("SMC.HRPT")
    assert ds.attrs["satellite_id"] == 114
    assert ds.attrs["orbit_number"] == 20794
    assert abs(ds.attrs["semi_major_km"] - 7236.908) < 1e-3
    assert ds.attrs["calibration"]["raw_i32"][0] == 138727440
    assert ds.attrs["unparsed"], "未解析字段必须如实记录"
    # load=False 时数据为空但形状保留
    v = ds.variables["CH1"]
    assert v.data.size == 0 and v.source_shape == (3, 2048) and v.shape == (3, 2048)


def test_fy1d_synthetic_geolocation(fy1d_synthetic):
    ds = oneb.read(fy1d_synthetic[0], load=False)
    geo = ds.geolocation
    assert geo.kind == "latlon_grid"
    assert geo.lat.shape == (3, 2048) and geo.lon.shape == (3, 2048)
    b = geo.bounds()
    assert 19.0 < b[2] < b[3] < 24.0      # 纬度
    assert 104.0 < b[0] < b[1] < 126.0    # 经度
    assert np.isfinite(geo.lat).all() and np.isfinite(geo.lon).all()
    # 51 个定位点插值后应保持单调（沿扫描方向经度递减）
    assert geo.lon[0, 0] > geo.lon[0, -1]
    # geo="none" / "nav" 两条分支
    assert oneb.read(fy1d_synthetic[0], load=False, geo="none").geolocation.kind == "none"
    nav = oneb.read(fy1d_synthetic[0], load=False, geo="nav").geolocation
    assert nav.lat.shape == (3, oneb.NAV_POINTS)


def test_fy1d_max_scans(fy1d_synthetic):
    ds = oneb.read(fy1d_synthetic[0], max_scans=2)
    assert ds.attrs["n_scans"] == 2
    assert ds.variables["CH1"].shape == (2, 2048)
    assert ds.variables["CH1"].data.shape == (2, 2048)


def test_na18_synthetic_roundtrip(na18_synthetic):
    p, dn = na18_synthetic
    ds = oneb.read(p, load=True)
    assert ds.attrs["variant"] == "noaa"
    assert len(ds.variables) == 5
    assert ds.attrs["record_length"] == NA18_REC
    assert ds.platform == "NOAA-18"
    assert ds.instrument == "AVHRR"
    for c in range(5):
        v = ds.variables[f"CH{c + 1}"]
        assert v.shape == (3, 2048)
        np.testing.assert_array_equal(v.data, dn[..., c])


def test_na18_synthetic_metadata_and_geo(na18_synthetic):
    ds = oneb.read(na18_synthetic[0], load=True)
    assert ds.start_time == datetime(2018, 3, 8, 0, 54, 2, 454000)
    assert ds.attrs["dataset_name"].startswith("/N1BD/N18/")
    assert ds.attrs["reference_ellipsoid"] == "WGS-72"
    assert abs(ds.attrs["inclination_deg"] - 99.1583) < 1e-4
    assert abs(ds.attrs["central_wavenumber_cm1"]["CH4"] - 926.29) < 1e-6
    assert ds.attrs["ch3_selection"].tolist() == [0, 0, 0]
    geo = ds.geolocation
    assert geo.kind == "latlon_grid" and geo.lat.shape == (3, 2048)
    b = geo.bounds()
    assert 63.0 < b[2] < 66.0 and 89.0 < b[0] < 141.0


def test_na18_calibration_helpers(na18_synthetic):
    """合成样本用真实 NOAA 定标系数 → 物理量应落在合理区间。"""
    ds = oneb.read(na18_synthetic[0], load=True)
    refl = oneb.reflectance(ds)
    assert set(refl) == {"CH1", "CH2", "CH3"}
    for name, arr in refl.items():
        assert arr.shape == (3, 2048)
        assert np.isfinite(arr).all()
        assert arr.min() > -100 and arr.max() < 400      # 反射率百分比
    bt = oneb.brightness_temperature(ds)
    assert set(bt) == {"CH3b", "CH4", "CH5"}
    for name, arr in bt.items():
        assert arr.shape == (3, 2048)
        assert np.isfinite(arr).mean() > 0.99            # 极少数无效 DN 给 NaN
        assert 100 < np.nanmedian(arr) < 400             # 亮温 K
    # 定标系数确实进了 variable attrs
    cal = ds.variables["CH1"].attrs["calibration_groups"]["operational"]
    assert abs(cal["slope1"] - 0.054) < 1e-8
    assert cal["crossover_counts"] == 501


def test_na18_bt_matches_planck_reference(na18_synthetic):
    """CH4 定点校验：DN=765 → 约 297 K（与文档/样本一致）。"""
    ds = oneb.read(na18_synthetic[0], load=True)
    ds.variables["CH4"].data[:] = 765
    bt = oneb.brightness_temperature(ds)["CH4"]
    assert 290 < float(np.median(bt)) < 305


def test_unknown_variant_raises(tmp_path):
    p = tmp_path / "junk.L1B"
    p.write_bytes(b"\x00" * 1000)
    with pytest.raises(ValueError):
        oneb.read(p)


def test_load_array_helper(fy1d_synthetic):
    p, dn = fy1d_synthetic
    arr = oneb.load_array(p, "CH4")
    np.testing.assert_array_equal(arr, dn[..., 3])
    with pytest.raises(KeyError):
        oneb.load_array(p, "NOPE")


def test_list_tree(fy1d_synthetic, na18_synthetic):
    """`cli ls` 需要和 hdf5.list_tree 同格式的行。"""
    for p, n_ch in ((fy1d_synthetic[0], 10), (na18_synthetic[0], 5)):
        rows = oneb.list_tree(p)
        assert rows and all({"path", "kind"} <= set(r) for r in rows)
        datasets = [r for r in rows if r["kind"] == "dataset"]
        assert len(datasets) == n_ch
        assert all(r["shape"] == [3, 2048] for r in datasets)
        assert all(r["dtype"] == "uint16" for r in datasets)
    assert len(oneb.list_tree(fy1d_synthetic[0], max_items=3)) == 3


# ------------------------------------------------------------------ 真实样本回归


@need_fy1d
def test_real_fy1d_info():
    ds = oneb.read(SAMPLE_FY1D, load=False)
    assert ds.platform == "FY-1D"
    assert ds.instrument == "AVHRR"
    assert ds.level == "L1"
    assert len(ds.variables) == 10
    assert ds.attrs["record_length"] == FY1D_REC
    assert ds.attrs["n_records"] == SAMPLE_FY1D.stat().st_size // FY1D_REC
    n = ds.attrs["n_scans"]
    assert 1000 < n < 6000
    assert ds.variables["CH1"].source_shape == (n, 2048)
    assert ds.start_time is not None and ds.start_time.year == 2012
    geo = ds.geolocation
    assert geo.kind == "latlon_grid"
    lon_min, lon_max, lat_min, lat_max = geo.bounds()
    assert 70 < lon_min < lon_max < 130
    assert 10 < lat_min < lat_max < 70
    # 头部四角经纬度应与定位网格范围一致（±3 度）
    corners = ds.attrs["corner_latlon_deg"]
    assert abs(min(c[1] for c in corners) - lon_min) < 3
    assert abs(max(c[0] for c in corners) - lat_max) < 3


@need_fy1d
def test_real_fy1d_data_slice():
    ds = oneb.read(SAMPLE_FY1D, max_scans=40)
    for name, var in ds.variables.items():
        assert var.data.shape == (40, 2048)
        assert var.data.dtype == np.uint16
        assert var.data.max() <= 1023           # 10 bit
        assert var.data.min() >= 0
    # AVHRR 热红外通道行间相关应很高（帧结构解对的重要判据）
    ch4 = ds.variables["CH4"].data.astype(np.float32)
    r = float(np.corrcoef(ch4[:-1].ravel(), ch4[1:].ravel())[0, 1])
    assert r > 0.9, f"CH4 行间相关 {r:.3f} 过低，说明解包或记录长度不对"
    ch1 = ds.variables["CH1"].data.astype(np.float32)
    r1 = float(np.corrcoef(ch1[:, :-1].ravel(), ch1[:, 1:].ravel())[0, 1])
    assert r1 > 0.5, f"CH1 邻像元相关 {r1:.3f} 过低"
    assert ds.attrs["n_scans_declared"] > 0
    assert isinstance(ds.attrs["scan_number_gaps"], list)


@need_na18
def test_real_na18_info():
    ds = oneb.read(SAMPLE_NA18, load=False)
    assert ds.platform == "NOAA-18"
    assert ds.instrument == "AVHRR"
    assert len(ds.variables) == 5
    assert ds.attrs["record_length"] == NA18_REC
    assert ds.attrs["n_records"] == SAMPLE_NA18.stat().st_size // NA18_REC
    assert ds.attrs["dataset_name"].startswith("/N1BD/")
    assert ds.attrs["reference_ellipsoid"] == "WGS-72"
    assert abs(ds.attrs["inclination_deg"] - 99.16) < 0.05
    assert abs(ds.attrs["semi_major_km"] - 7226.6) < 1.0
    assert ds.start_time is not None and ds.start_time.year == 2018
    lon_min, lon_max, lat_min, lat_max = ds.geolocation.bounds()
    assert -180 < lon_min < lon_max < 180 and -90 < lat_min < lat_max < 90


@need_na18
def test_real_na18_calibration_is_physical():
    ds = oneb.read(SAMPLE_NA18, max_scans=120)
    bt = oneb.brightness_temperature(ds)
    assert 200 < float(np.median(bt["CH4"])) < 330     # 11 um 亮温
    assert 180 < float(np.median(bt["CH5"])) < 330
    refl = oneb.reflectance(ds)
    assert -10 < float(np.median(refl["CH1"])) < 100
    # CH5 在多数晴空场景比 CH4 冷（水汽吸收）
    assert float(np.median(bt["CH5"])) < float(np.median(bt["CH4"])) + 5
    ch3 = ds.variables["CH3"].data
    assert ch3.max() <= 1023
    assert ds.attrs["ch3a_fraction"] in (0.0, 1.0)


@need_fy1d
def test_cli_info_fy1d(capsys):
    assert cli.main(["info", str(SAMPLE_FY1D)]) == 0
    out = capsys.readouterr().out
    assert "FY-1D" in out and "AVHRR" in out and "CH1" in out and "CH10" in out


@need_na18
def test_cli_info_na18(capsys):
    assert cli.main(["info", str(SAMPLE_NA18)]) == 0
    out = capsys.readouterr().out
    assert "NOAA-18" in out and "CH5" in out and "latlon_grid" in out


@need_na18
def test_cli_info_json():
    """--json 输出必须可序列化（summary 里含 numpy 时也要过得去）。"""
    import json

    ds = oneb.read(SAMPLE_NA18, load=False)
    payload = json.loads(json.dumps(ds.summary(), ensure_ascii=False, default=str))
    assert payload["platform"] == "NOAA-18"
    assert payload["n_vars"] == 5
    assert len(payload["vars"]) == 5
