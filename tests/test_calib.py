"""定标模块验证 —— 全部拿官方 L1 真实样本断言（没有样本时自动 skip）。

样本
----
* FY-3H MERSI L1 250M  ``Y:\\download-data\\FY3H_MERSI_GRAN_L1_20261022_1810_0250M_V0.hdf``
  （任务书里写的是 ``Y:\\QQ_DW\\...20261101_0405...``，本机已移到 download-data 下同日存档）
* FY-4B AGRI L1 FDI 1KM ``Y:\\download-data\\FY4B-...MULT_NOM_20261030154500_..._1000M_V0001.HDF``
* FY-2G FDI L1          ``Y:\\download-data\\C202610181401129865\\FY2G_FDI_ALL_NOM_20261018_1300.hdf``
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from _sample_root import SAMPLE_ROOT

from fysat import calib
from fysat.readers import open_file

FY3H = SAMPLE_ROOT / r"FY3H_MERSI_GRAN_L1_20261022_1810_0250M_V0.hdf"
FY4B = SAMPLE_ROOT / (
    r"FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_MULT_NOM_"
    r"20261030154500_20261030155959_1000M_V0001.HDF"
)
FY2G = SAMPLE_ROOT / r"C202610181401129865\FY2G_FDI_ALL_NOM_20261018_1300.hdf"

# MERSI-II 第 24 通道等效中心波长（文件全局属性 Effect_Center_WaveLength 第 24 项）
FY3H_B24_WAVELENGTH = 10.7342


def _sample(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"缺少真实样本: {path}")
    return path


# ---------------------------------------------------------------- FY-3H 热红外

@pytest.fixture(scope="module")
def fy3h_b24():
    """FY-3H EV_250_Emissive_b24 的辐亮度与亮温（整幅 8000×8192，只算一次）。

    大数组算完就地统计、随即释放，避免测试进程占着 600 MB 不放。
    """
    path = _sample(FY3H)
    ds = open_file(path, load=False)
    var = ds.load("Data/EV_250_Emissive_b24")
    radiance = calib.radiance_linear(
        var.data, var.scale_factor, var.add_offset or 0.0, fill=calib.FY3_BAD_DN
    )
    bt = calib.radiance_to_bt(radiance, FY3H_B24_WAVELENGTH)
    stats = {
        "n_valid": int(np.isfinite(bt).sum()),
        "n_nan": int(np.isnan(bt).sum()),
        "nan_is_fill": bool(np.array_equal(np.isnan(bt), var.data == 65535)),
        "l_min": float(np.nanmin(radiance)),
        "l_max": float(np.nanmax(radiance)),
        "bt_min": float(np.nanmin(bt)),
        "bt_max": float(np.nanmax(bt)),
        "bt_median": float(np.nanmedian(bt)),
        "bt_p1": float(np.nanpercentile(bt, 1)),
        "dtype": bt.dtype,
    }
    del radiance, bt
    return ds, var, stats


def test_metadata_matches_official_granule():
    """文件属性：Slope = 0.01（mW/(m²·cm⁻¹·sr)）、FillValue = 65535、波长 10.7342 µm。"""
    import h5py

    path = _sample(FY3H)
    ds = open_file(path, load=False)
    var = ds["Data/EV_250_Emissive_b24"]
    assert var.scale_factor == pytest.approx(0.01, rel=1e-6)
    assert var.add_offset in (None, 0.0)
    assert var.fill_value == 65535
    assert var.valid_range == (0, 25000)

    with h5py.File(path, "r") as f:
        wavelengths = np.asarray(f.attrs["Effect_Center_WaveLength"], dtype=float)
    assert wavelengths.size == 25, "MERSI-II 共 25 个通道"
    assert wavelengths[23] == pytest.approx(FY3H_B24_WAVELENGTH, abs=1e-4)


def test_fy3h_b24_brightness_temperature_range(fy3h_b24):
    """FY-3H CH24 亮温必须落在大气窗区合理区间 180–330 K（实测 187.28–311.78 K）。"""
    _, _, st = fy3h_b24
    assert st["dtype"] == np.float32
    assert st["n_valid"] == 65_464_000, "整幅 6560 万像元，只有 7.2 万缺测"

    assert st["l_min"] == pytest.approx(7.51, abs=0.01)
    assert st["l_max"] == pytest.approx(132.58, abs=0.01)

    assert st["bt_min"] > 180.0, f"亮温下限异常: {st['bt_min']:.2f} K"
    assert st["bt_max"] < 330.0, f"亮温上限异常: {st['bt_max']:.2f} K"
    assert st["bt_min"] == pytest.approx(187.28, abs=0.5)
    assert st["bt_max"] == pytest.approx(311.78, abs=0.5)
    assert 285.0 < st["bt_median"] < 295.0, f"中位亮温异常: {st['bt_median']:.2f} K"
    assert st["bt_p1"] > 200.0, "1% 分位不该低于 200 K"


def test_fy3h_b24_fill_becomes_nan(fy3h_b24):
    """65535（缺测）必须变成 NaN，其余像元保持有限值。"""
    _, _, st = fy3h_b24
    assert st["n_nan"] == 72_000
    assert st["nan_is_fill"], "NaN 掩膜应与 FillValue 掩膜逐像元一致"


def test_planck_inverse_roundtrip():
    """普朗克正/反演互逆，且 300 K @10.73 µm 的辐亮度在量级上正确（实测 111.75 mW/(m²·sr·cm⁻¹)）。"""
    bt = np.array([180.0, 220.0, 260.0, 300.0, 320.0], dtype=np.float32)
    radiance = calib.planck_radiance(bt, FY3H_B24_WAVELENGTH)
    assert np.all(radiance > 0)
    assert radiance[3] == pytest.approx(111.75, rel=0.01)
    back = calib.radiance_to_bt(radiance, FY3H_B24_WAVELENGTH)
    assert np.allclose(back, bt, atol=0.01), f"往返误差过大: {back}"


def test_radiance_to_bt_edge_cases():
    """L ≤ 0 / NaN 一律 NaN，避免把缺测画成 0 K。"""
    out = calib.radiance_to_bt(np.array([0.0, -1.0, np.nan, 100.0], dtype=np.float32), 10.7342)
    assert np.isnan(out[:3]).all()
    assert 250.0 < float(out[3]) < 320.0


# ---------------------------------------------------------------- FY-3H 可见光

def test_fy3h_vis_coefficients_give_reflectance_percent():
    """VIS_Cal_Coeff = [截距, 斜率, 二次项]，19 个反射通道在 DN=0..4095 上都应该是 0–120%。"""
    import h5py

    path = _sample(FY3H)
    with h5py.File(path, "r") as f:
        coeff = np.asarray(f["/Calibration/VIS_Cal_Coeff"][()], dtype=np.float64)
    assert coeff.shape == (19, 3)

    dn_ramp = np.arange(0, 4096, dtype=np.uint16)
    for band in range(coeff.shape[0]):
        rho = calib.reflectance_linear(dn_ramp, coeff[band])
        assert np.all(np.isfinite(rho))
        assert -10.0 < rho.min() <= 5.0, f"第 {band + 1} 通道 DN=0 反射率异常"
        # 窄带海洋水色通道（8–14）满量程只有 ~11–37%，宽通道 ~95–110%
        assert 5.0 < rho.max() < 130.0, f"第 {band + 1} 通道满量程反射率异常: {rho.max():.2f}%"

    rho1 = calib.reflectance_linear(dn_ramp, coeff[0])
    assert rho1[0] == pytest.approx(-2.323, abs=0.01), "截距应等于系数表第一项"
    assert rho1[-1] == pytest.approx(109.40, abs=0.05), f"实测 {rho1[-1]:.2f}%"
    assert np.all(np.diff(rho1) > 0), "线性系数下反射率应随 DN 单调上升"


def test_fy3h_vis_band_is_night_in_this_granule():
    """这颗 granule 是夜间（18:10 UTC），EV_250_RefSB 全 0 → 反射率就是系数的截距。

    真实数据上跑一遍，验证管道在「全黑」输入下不炸、且结果与系数完全一致。
    """
    import h5py

    path = _sample(FY3H)
    with h5py.File(path, "r") as f:
        coeff = np.asarray(f["/Calibration/VIS_Cal_Coeff"][()], dtype=np.float64)
        dn = f["/Data/EV_250_RefSB_b1"][()]
    assert dn.max() == 0, "该 granule 夜间，反射波段应为全 0"
    rho = calib.reflectance_linear(dn[::500, ::500], coeff[0])
    assert np.allclose(rho, coeff[0][0], atol=1e-4)


# ---------------------------------------------------------------- FY-4B 查找表

def test_fy4b_ch01_lut_reflectance_percent():
    """FY-4B CALChannel01 是 DN→反射率(0–1.15) 的查找表，×100 之后必须落在 0–100%（实测 ≤69%）。"""
    import h5py

    path = _sample(FY4B)
    with h5py.File(path, "r") as f:
        lut = np.asarray(f["/Calibration/CALChannel01"][()], dtype=np.float32)
        dn = f["/Data/NOMChannel01"][()]
    assert lut.shape == (4096,)
    assert 1.0 < lut.max() < 1.5, "AGRI 可见光反射率可达 1.14（深对流/耀斑）"

    # 单点锚值：DN=1000 → 0.262868 → 26.2868%；满量程 4095 → 114.31%
    assert calib.reflectance_from_lut(1000, lut) == pytest.approx(26.2868, abs=1e-3)
    assert calib.reflectance_from_lut(4095, lut) == pytest.approx(114.31, abs=0.05)

    # 圆盘统计：整读一次，抽稀 4 倍算分布（6000 万像元级别的数组不进内存两次）
    valid = dn != 65535
    assert int(valid.sum()) == 92_456_770, "非填充像元应占圆盘 76.5%"
    dn_max = int(dn[valid].max())
    assert dn_max == 2501
    assert calib.reflectance_from_lut(dn_max, lut) == pytest.approx(68.976, abs=1e-3)

    rho = calib.reflectance_from_lut(dn[::4, ::4], lut, fill=65535, valid_range=(0, 4095))
    good = np.isfinite(rho)
    assert good.any()
    assert rho[good].min() >= 0.0
    assert rho[good].max() <= 100.0, f"实测最大 {rho[good].max():.2f}%"
    assert 0.2 < float(np.median(rho[good])) < 0.5, "本 granule（22:45 北京时）圆盘整体偏暗"


def test_fy4b_lut_linear_vs_nearest():
    """LUT 相邻两点插值与最近邻差异应小于一个 DN 的斜率（0.0003/ DN）。"""
    import h5py

    path = _sample(FY4B)
    with h5py.File(path, "r") as f:
        lut = np.asarray(f["/Calibration/CALChannel01"][()], dtype=np.float32)
    dn = np.arange(0, 4096, dtype=np.float32) + 0.5
    linear = calib.lookup_table(dn, lut, kind="linear")
    nearest = calib.lookup_table(dn, lut, kind="nearest")
    diff = np.abs(linear - nearest)
    assert np.nanmax(diff) < 0.0005, f"插值/最近邻差 {np.nanmax(diff):.6f}"


# ---------------------------------------------------------------- FY-2G 查找表

def test_fy2g_ir_lut_brightness_temperature():
    """FY-2G CALChannelIR1 (1,1024) 直接按 DN 查表；本 granule 实测 174–305 K。"""
    import h5py

    path = _sample(FY2G)
    with h5py.File(path, "r") as f:
        lut = np.asarray(f["/CALChannelIR1"][()], dtype=np.float32)
        dn = f["/NOMChannelIR1"][()]
    assert lut.shape == (1, 1024)
    # FY-2 的定标表是「计数值越大越冷」的递减表，直接索引即可，不要反转
    # （表尾 8 项已到 119.55 K 的下限，是平的）
    assert np.all(np.diff(lut.ravel()) <= 0), "FY-2 计数值→亮温表应为单调不增"
    assert np.all(np.diff(lut.ravel())[:-8] < 0), "表头必须严格递减"

    bt = calib.bt_from_lut(dn, lut, fill=65535, valid_range=(0, 1023))
    good = np.isfinite(bt)
    assert int((~good).sum()) == 1_547_601 == int((dn == 65535).sum())
    hot = bt[good]
    assert hot.min() > 150.0 and hot.max() < 340.0, f"实测 {hot.min():.2f}–{hot.max():.2f} K"
    assert hot.min() == pytest.approx(173.93, abs=0.05)
    assert hot.max() == pytest.approx(304.59, abs=0.05)
    assert 275.0 < float(np.median(hot)) < 285.0, f"中位亮温 {np.median(hot):.2f} K"
    assert float(np.percentile(hot, 1)) < 230.0, "应有冷云顶（FY-2 圆盘上的对流云）"


def test_fy2g_vis_lut_is_already_percent():
    """FY-2G CALChannelVIS 直接给百分比反射率（0–118%），不需要再 ×100。

    这张表不是线性的（FY-2 可见光定标本身就是计数值的二次函数，54 项间隙逐渐变大），
    所以只能整表查、不能拿首段斜率外推。
    """
    import h5py

    path = _sample(FY2G)
    with h5py.File(path, "r") as f:
        lut = np.asarray(f["/CALChannelVIS"][()], dtype=np.float32).ravel()
        dn = f["/NOMChannelVIS"][()]
    assert lut.shape == (64,)
    assert lut[0] == 0.0 and lut.max() == pytest.approx(118.3942, abs=1e-3)

    rho = calib.reflectance_from_lut(dn, lut, percent=False, fill=255, valid_range=(0, 63))
    good = np.isfinite(rho)
    assert good.all(), "本 granule 没有填充像元"
    assert rho.min() >= 0.0
    assert rho.max() <= 120.0, f"实测最大 {rho.max():.2f}%"
    assert rho.max() == pytest.approx(float(lut[int(dn.max())]), abs=1e-4)
    assert 0.0 <= float(np.median(rho)) <= 5.0, "夜间可见光整体很暗"


# ---------------------------------------------------------------- 通用行为

def test_lookup_table_out_of_range_is_nan():
    """越界 DN 不能静默截断：< 0 或 ≥ LUT 长度都输出 NaN。"""
    lut = np.array([10.0, 20.0, 30.0], dtype=np.float32)
    out = calib.lookup_table(np.array([0, 1, 2, 3, -1], dtype=np.int32), lut, kind="nearest")
    assert out[:3].tolist() == [10.0, 20.0, 30.0]
    assert np.isnan(out[3]) and np.isnan(out[4])


def test_lookup_table_nan_and_lut_fill():
    lut = np.array([10.0, -1.0, 30.0, 40.0], dtype=np.float32)
    out = calib.lookup_table(np.array([0, 1, 2]), lut, kind="nearest", lut_fill=-1.0)
    assert out[0] == 10.0 and out[2] == 30.0
    assert np.isnan(out[1])

    out_nan = calib.lookup_table(np.array([np.nan, 2.0]), lut, kind="linear")
    assert np.isnan(out_nan[0]) and out_nan[1] == 30.0


def test_dn_to_float_masks_and_dtype():
    dn = np.array([65535, 65534, 65533, 1234], dtype=np.uint16)
    out = calib.dn_to_float(dn, valid_range=(0, 4095))
    assert out.dtype == np.float32
    assert np.isnan(out[:3]).all()
    assert out[3] == 1234.0

    # 不做填充值/范围判断时原样保留
    raw = calib.dn_to_float(dn, fill=None)
    assert np.array_equal(raw, dn.astype(np.float32))


def test_quadratic_coefficients():
    """二次项（部分可见光/微波通道使用）也要支持。"""
    coeff = [1.0, 2e-3, 1e-6]
    dn = np.array([0, 1000, 2000], dtype=np.float32)
    out = calib.reflectance_linear(dn, coeff)
    assert out[0] == pytest.approx(1.0)
    assert out[1] == pytest.approx(1.0 + 2.0 + 1.0)
    assert out[2] == pytest.approx(1.0 + 4.0 + 4.0)


def test_bad_coefficients_raise():
    with pytest.raises(ValueError):
        calib.reflectance_linear(np.zeros(3), [1.0])
    with pytest.raises(ValueError):
        calib.reflectance_linear(np.zeros(3), [1.0, 2.0, 3.0, 4.0])
    with pytest.raises(ValueError):
        calib.radiance_to_bt(np.ones(3), 0.0)


def test_tb_linear_microwave():
    """微波定标 TB = a0 + a1·DN + a2·DN²（逐通道逐扫描线系数直接用这个函数）。"""
    coeff = [150.0, 0.1]  # 例：150 K + 0.1 K/DN
    dn = np.array([0, 100, 2000], dtype=np.float32)
    tb = calib.tb_linear(dn, coeff)
    assert tb.tolist() == pytest.approx([150.0, 160.0, 350.0])
