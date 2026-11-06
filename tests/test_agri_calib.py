"""FY-4 AGRI / GHI 辐射定标测试。

依据 FY4B_AGRI_DISK_L1_4KM_HDF_V1.0.md 第 3 章「相关物理量转换方法」：

  3.1 太阳反射波段（NOMChannel01-06）
      (1) 反射率     rho = DN*SCALE + OFFSET        （CALIBRATION_COEF）
          或查表    CALChannelNN 为 DN→反射率 的查找表
      (2) 辐亮度     L = rho * ESUN / pi
      (3) 表观反射率  rho_TOA = rho * d / cos(theta)
  3.2 热红外波段（NOMChannel07-15）
      (1) 亮温       CALChannelNN 为 DN→亮温(K) 的查找表
      (2) 辐亮度     L = DN*SCALE + OFFSET

实测（FY-4B AGRI 4000M）：
  CALChannel01  0 → 1.143        反射率是 0~1.14 的小数，不是百分数
  CALChannel07  405 → 200 (K)    热通道 LUT 直接是亮温
  填充值 65534 = 地球内无效，65535 = 地球外无效
"""
from __future__ import annotations

import os

import numpy as np
import pytest
from _sample_root import glob_samples

from fysat import calib, pipeline


def _find(pat, min_mb=0.5):
    hits = [h for h in glob_samples(pat)
            if os.path.getsize(h) > min_mb * 1e6]
    return hits[0] if hits else None


def _open(pat, min_mb=0.5):
    f = _find(pat, min_mb)
    if not f:
        pytest.skip(f"缺样本 {pat}")
    from fysat.readers import open_file

    return open_file(f, load=False)


# ---------------- 结构识别 ----------------

def test_detects_agri_calibration():
    ds = _open(r"FY4B-*AGRI*FDI*4000M*.HDF")
    cal = calib.agri_calibration(ds)
    assert cal is not None
    assert cal["coef"].shape == (15, 2), f"AGRI 应有 15 个通道的斜率截距，实际 {cal['coef'].shape}"
    assert cal["esun"] is not None and cal["esun"].size >= 6


def test_detects_ghi_calibration():
    ds = _open(r"FY4B-*GHI*0500M*.HDF")
    cal = calib.agri_calibration(ds)
    assert cal is not None
    assert cal["coef"].shape == (6, 2)


def test_mersi_is_not_mistaken_for_agri():
    """MERSI 没有 CALIBRATION_COEF，不能被误判成 AGRI 产品。"""
    ds = _open(r"FY3D_MERSI_GBAL_L1_*1000M_MS.HDF", 10)
    assert calib.agri_calibration(ds) is None


# ---------------- 反射率 ----------------

def test_agri_reflectance_formula_and_range():
    """rho = DN*SCALE + OFFSET，结果应为 0~1 量级（不是百分数）。"""
    ds = _open(r"FY4B-*AGRI*FDI*4000M*.HDF")
    var = ds.load("Data/NOMChannel02")
    rho = calib.agri_reflectance(ds, np.asarray(var.data), 2, var.valid_range)
    v = rho[np.isfinite(rho)]
    assert v.size > 1000
    assert v.max() < 2.0, f"反射率最大 {v.max():.3f}，像是没做 0~1 归一化"
    assert v.max() > 0.1, f"反射率最大只有 {v.max():.4f}，定标可能没生效"
    # 夜间/暗像元会略负（offset 造成），不应远小于 0
    assert v.min() > -0.2


def test_agri_lut_matches_formula():
    """查找表法（CALChannelNN）与公式法（COEF）在同一 DN 上应基本一致。

    文档给了两种等价方法，实测差异应当很小；差异大说明通道号对错了。
    """
    ds = _open(r"FY4B-*AGRI*FDI*4000M*.HDF")
    cal = calib.agri_calibration(ds)
    for ch in (1, 2, 3):
        lut = calib.agri_channel_table(ds, ch)
        assert lut is not None and lut.size == 4096
        scale, offset = cal["coef"][ch - 1]
        dns = np.array([100, 500, 1000, 2000, 3000], dtype=float)
        by_formula = dns * scale + offset
        by_lut = np.interp(dns, np.arange(lut.size), lut)
        assert np.allclose(by_formula, by_lut, atol=0.02), (
            f"ch{ch}: 公式法 {by_formula} vs 查表法 {by_lut}")


def test_pipeline_visible_data_uses_agri_calibration():
    """pipeline.visible_data 对 AGRI 必须返回 0~1 反射率，而不是原始 DN。"""
    ds = _open(r"FY4B-*AGRI*FDI*4000M*.HDF")
    refl, unit = pipeline.visible_data(ds, "Data/NOMChannel02", 0)
    assert unit == "1"
    v = refl[np.isfinite(refl)]
    assert v.max() < 2.0, f"p99={np.percentile(v,99):.3f}，像是没定标"
    assert v.max() > 0.1


# ---------------- 亮温 ----------------

def test_agri_bt_is_kelvin():
    """热通道 CALChannelNN 是 DN→亮温(K) 查找表，结果必须落在物理区间。"""
    ds = _open(r"FY4B-*AGRI*FDI*4000M*.HDF")
    for ch, lo, hi in ((13, 150, 350), (7, 180, 380), (15, 150, 340)):
        var = ds.load(f"Data/NOMChannel{ch:02d}")
        bt = calib.agri_bt(ds, np.asarray(var.data), ch, var.valid_range)
        v = bt[np.isfinite(bt)]
        assert v.size > 1000, f"ch{ch} 有效像元太少"
        assert lo < np.median(v) < hi, (
            f"ch{ch} 亮温中位 {np.median(v):.1f}K 不在 {lo}~{hi}K")
        assert v.min() > 50 and v.max() < 500, f"ch{ch} 亮温越界 {v.min()}~{v.max()}"


def test_agri_bt_decreasing_with_dn():
    """亮温查找表随 DN 单调下降（DN 越大代表辐亮度越高但该 LUT 是 K 值）。"""
    ds = _open(r"FY4B-*AGRI*FDI*4000M*.HDF")
    lut = calib.agri_channel_table(ds, 13)
    assert lut is not None
    # 实测 ch13: 首=339.7 尾=110，即随 DN 递减
    assert lut[0] > lut[-1], f"ch13 LUT 首 {lut[0]} 尾 {lut[-1]}，方向与实测不符"


def test_pipeline_thermal_data_uses_agri_lut():
    ds = _open(r"FY4B-*AGRI*FDI*4000M*.HDF")
    bt, unit = pipeline.thermal_data(ds, "Data/NOMChannel13", 0)
    assert unit == "K"
    v = bt[np.isfinite(bt)]
    assert 150 < np.median(v) < 350


# ---------------- 辐亮度与 ESUN ----------------

def test_agri_radiance_formula():
    """热通道辐亮度 L = DN*SCALE + OFFSET，应为 W/(m2·sr·µm) 量级。"""
    ds = _open(r"FY4B-*AGRI*FDI*4000M*.HDF")
    var = ds.load("Data/NOMChannel13")
    L = calib.agri_radiance(ds, np.asarray(var.data), 13, var.valid_range)
    v = L[np.isfinite(v := L)] if False else L[np.isfinite(L)]
    assert v.size > 1000
    # 10.8µm 窗区地表辐亮度量级约 5~15 W/(m2·sr·µm)
    assert 0 < np.median(v) < 40, f"辐亮度中位 {np.median(v):.2f}"


def test_agri_esun_available():
    ds = _open(r"FY4B-*AGRI*FDI*4000M*.HDF")
    e2 = calib.agri_solar_irradiance(ds, 2)
    assert e2 is not None and 500 < e2 < 3000, f"ch2 ESUN={e2}"


# ---------------- 填充值 ----------------

def test_agri_fill_values_are_masked():
    """65534（地球内无效）与 65535（地球外无效）都必须变成 NaN。"""
    ds = _open(r"FY4B-*AGRI*FDI*4000M*.HDF")
    dn = np.array([[100, 65534], [65535, 800]], dtype=np.float64)
    rho = calib.agri_reflectance(ds, dn, 2)
    assert np.isfinite(rho[0, 0])
    assert not np.isfinite(rho[0, 1]), "65534 未被掩掉"
    assert not np.isfinite(rho[1, 0]), "65535 未被掩掉"

    bt = calib.agri_bt(ds, dn, 13)
    assert np.isfinite(bt[0, 0])
    assert not np.isfinite(bt[0, 1]) and not np.isfinite(bt[1, 0])


# ---------------- 回归：不能影响 MERSI ----------------

def test_mersi_path_unchanged():
    """加入 AGRI 分支后，MERSI 的定标结果必须保持原样。"""
    ds = _open(r"FY3D_MERSI_GBAL_L1_*1000M_MS.HDF", 10)
    refl, unit = pipeline.visible_data(ds, "Data/EV_250_Aggr.1KM_RefSB", 2)
    v = refl[np.isfinite(refl)]
    assert unit == "1"
    assert 0.5 < v.max() < 1.2, f"MERSI 反射率最大 {v.max():.3f}"

    bt, bunit = pipeline.thermal_data(ds, "Data/EV_250_Aggr.1KM_Emissive", 0)
    b = bt[np.isfinite(bt)]
    assert bunit == "K"
    assert 150 < np.median(b) < 350
