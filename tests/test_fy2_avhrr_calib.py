"""FY-2 与 NOAA AVHRR 的定标测试，以及界面「物理量」列的判定。

依据与实测：
- FY-2 FDI 自带 CALChannel 查找表
    CALChannelIR1  1024 点  333.5 K → 119.6 K
    CALChannelVIS    64 点  0 → 118.4 (%)
    FY-2 CSV 容器**没有**定标表（reader 里 calibration_tables_present=False）→ 只能出 DN
- NOAA AVHRR 可见光用两段线性（calibration_groups['operational']）
    slope1=0.054, intercept1=-2.13, crossover_counts=501,
    slope2=0.161, intercept2=-55.37，单位 %
  热通道（CH3/CH4/CH5）的 1B 系数缩放在文档里表述不完整 → 暂不定标，界面标"待定标"
"""
from __future__ import annotations

import os

import numpy as np
import pytest
from _sample_root import glob_samples

from fysat import calib, pipeline
from fysat.gui.varcatalog import physical_label


def _find(pat, min_mb=0.005):
    hits = [h for h in glob_samples(pat)
            if os.path.getsize(h) > min_mb * 1e6]
    return hits[0] if hits else None


def _open(pat, min_mb=0.005):
    f = _find(pat, min_mb)
    if not f:
        pytest.skip(f"缺样本 {pat}")
    from fysat.readers import open_file

    return open_file(f, load=False)


# ---------------- FY-2 查找表 ----------------

def test_fy2_lut_present_and_shaped():
    ds = _open(r"FY2G_FDI_ALL_NOM_*.hdf", 0.01)
    for ch in ("IR1", "IR2", "IR3", "IR4"):
        lut = calib.fy2_lut(ds, ch)
        assert lut is not None, f"{ch} 缺查找表"
        assert lut.size == 1024, f"{ch} 查找表应为 1024 点，实际 {lut.size}"
    vis = calib.fy2_lut(ds, "VIS")
    assert vis is not None and vis.size == 64


def test_fy2_ir_lut_is_kelvin():
    """IR 查找表值域应是亮温 K（实测 119.6~333.5）。"""
    ds = _open(r"FY2G_FDI_ALL_NOM_*.hdf", 0.01)
    lut = calib.fy2_lut(ds, "IR1")
    assert 100 < lut.min() < 200, f"IR1 最小 {lut.min():.1f}"
    assert 300 < lut.max() < 400, f"IR1 最大 {lut.max():.1f}"
    assert calib.fy2_channel_kind(ds, "IR1") == "K"


def test_fy2_vis_lut_is_percent():
    """VIS 查找表值域应是反射率百分数（实测 0~118.4）。"""
    ds = _open(r"FY2G_FDI_ALL_NOM_*.hdf", 0.01)
    lut = calib.fy2_lut(ds, "VIS")
    assert lut.min() >= 0 and 100 < lut.max() < 200
    assert calib.fy2_channel_kind(ds, "VIS") == "%"


def test_pipeline_fy2_bt_and_reflectance():
    ds = _open(r"FY2G_FDI_ALL_NOM_*.hdf", 0.01)

    bt, unit = pipeline.thermal_data(ds, "NOMChannelIR1", 0)
    v = bt[np.isfinite(bt)]
    assert unit == "K"
    assert 150 < np.median(v) < 330, f"IR1 亮温中位 {np.median(v):.1f}K"
    assert v.max() < 400

    refl, runit = pipeline.visible_data(ds, "NOMChannelVIS", 0)
    r = refl[np.isfinite(refl)]
    assert runit == "1"
    assert r.max() <= 1.5, f"VIS 反射率应归一化到 0~1，最大 {r.max():.3f}"


def test_fy2_csv_has_no_lut():
    """CSV 容器没有定标表，必须老实返回 None 而不是编一个。"""
    ds = _open(r"FY2G_CSV*.DAT", 0.05)
    assert calib.fy2_lut(ds, "IR1") is None


# ---------------- NOAA AVHRR 可见光 ----------------

def test_avhrr_two_segment_calibration():
    """两段线性：DN<=crossover 用 slope1/intercept1，否则用 slope2/intercept2。"""
    ds = _open(r"NA18_AVHRR_HRPT*.L1B", 0.05)
    var = ds.variables["CH1"]
    g = calib.avhrr_calibration_group(var)
    assert g is not None and "slope1" in g

    s1, i1 = g["slope1"], g["intercept1"]
    s2, i2 = g["slope2"], g["intercept2"]
    xover = g["crossover_counts"]
    assert s2 > s1, "第二段斜率应更大（实测 0.161 > 0.054）"

    dn = np.array([[0, xover], [xover + 1, 900]], dtype=np.float64)
    out, unit = calib.avhrr_reflectance(var, dn)
    assert out[0, 0] == pytest.approx(i1, abs=1e-3)
    assert out[0, 1] == pytest.approx(xover * s1 + i1, abs=1e-3)
    assert out[1, 0] == pytest.approx((xover + 1) * s2 + i2, abs=1e-3)
    assert unit == "%"


def test_pipeline_avhrr_reflectance_normalized():
    ds = _open(r"NA18_AVHRR_HRPT*.L1B", 0.05)
    refl, unit = pipeline.visible_data(ds, "CH1", 0)
    v = refl[np.isfinite(refl)]
    assert unit == "1"
    assert v.max() < 2.0, f"应归一化到 0~1，最大 {v.max():.3f}"
    assert v.max() > 0.3, f"最大只有 {v.max():.3f}，定标可能没生效"


def test_avhrr_fill_masked():
    ds = _open(r"NA18_AVHRR_HRPT*.L1B", 0.05)
    var = ds.variables["CH1"]
    dn = np.array([[100, 1023], [65535, 500]], dtype=np.float64)
    out, _ = calib.avhrr_reflectance(var, dn)
    assert np.isfinite(out[0, 0])
    assert not np.isfinite(out[0, 1]), "1023 填充值未掩"
    assert not np.isfinite(out[1, 0]), "65535 填充值未掩"


# ---------------- 界面「物理量」列 ----------------

def test_physical_label_mersi():
    ds = _open(r"FY3D_MERSI_GBAL_L1_*1000M_MS.HDF", 10)
    assert physical_label(ds, "Data/EV_250_Aggr.1KM_RefSB") == "反射率"
    assert physical_label(ds, "Data/EV_1KM_Emissive") == "亮温 K"


def test_physical_label_agri_ghi():
    ds = _open(r"FY4B-*AGRI*FDI*4000M*.HDF", 0.5)
    assert physical_label(ds, "Data/NOMChannel02") == "反射率"
    assert physical_label(ds, "Data/NOMChannel13") == "亮温 K"


def test_physical_label_fy2_and_avhrr():
    d2 = _open(r"FY2G_FDI_ALL_NOM_*.hdf", 0.01)
    assert physical_label(d2, "NOMChannelIR1") == "亮温 K"
    assert physical_label(d2, "NOMChannelVIS") == "反射率%"

    d3 = _open(r"NA18_AVHRR_HRPT*.L1B", 0.05)
    assert physical_label(d3, "CH1") == "反射率%"
    # 热通道尚未定标，必须如实标注，不能假装是物理量
    assert "待定标" in physical_label(d3, "CH4")


def test_physical_label_marks_uncalibrated():
    """没有定标表的产品必须标出来，避免用户以为拿到的是物理量。"""
    ds = _open(r"FY2G_CSV*.DAT", 0.05)
    assert "无定标" in physical_label(ds, "IR1")
