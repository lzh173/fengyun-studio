"""FY-4B 产品族回归：不同分辨率档位的通道构成与 LUT 单位必须一致。

这个测试锁定几条容易踩的坑：
- 1000M 只有 3 个可见光通道，没有红外
- 4000M 才有全部 15 通道（含 7 个红外）
- 可见光 LUT 值域是 0~1.14（反射率 0~114%），不是 0~100
- 红外 LUT 值域是 110~405 K
"""
from __future__ import annotations

import glob
from pathlib import Path

import pytest
from _sample_root import SAMPLE_ROOT

from fysat.calib import lookup_table
from fysat.readers import open_file

ROOT = SAMPLE_ROOT


def find(pattern: str) -> Path | None:
    hits = glob.glob(str(Path(ROOT) / "**" / pattern), recursive=True)
    hits = [h for h in hits if Path(h).stat().st_size > 10_000_000]   # 排除下载残件
    return Path(hits[0]) if hits else None


@pytest.fixture(scope="module")
def fy4b_4000m():
    p = find("FY4B-*_4000M_V0001.HDF")
    if p is None:
        pytest.skip("缺 FY-4B 4000M 样本")
    return open_file(p, load=False)


@pytest.fixture(scope="module")
def fy4b_1000m():
    p = find("FY4B-*_1000M_V0001.HDF")
    if p is None:
        pytest.skip("缺 FY-4B 1000M 样本")
    return open_file(p, load=False)


def test_4000m_has_15_channels(fy4b_4000m):
    chans = [k for k in fy4b_4000m.variables if k.startswith("Data/NOMChannel")]
    assert len(chans) == 15, f"4000M 应有 15 个通道，实际 {len(chans)}"


def test_1000m_has_only_visible(fy4b_1000m):
    chans = [k for k in fy4b_1000m.variables if k.startswith("Data/NOMChannel")]
    assert len(chans) == 3, f"1000M 应只有 3 个可见光通道，实际 {len(chans)}"
    # 且这 3 个都应该是可见光 LUT（值域 0~2 之间，反射率 0~114%）
    for name in chans:
        ch = name.split("NOMChannel")[1]
        lut = fy4b_1000m.load(f"Calibration/CALChannel{ch}").data.reshape(-1)
        assert lut.max() < 2.0, f"{name} 的 LUT 最大值 {lut.max():.2f} 不像可见光反射率"


def test_visible_lut_is_fraction_not_percent(fy4b_4000m):
    """可见光 LUT 值域 0~1.14，若误当作 0~100 会得到 1% 量级的错误反射率。"""
    lut = fy4b_4000m.load("Calibration/CALChannel01").data.reshape(-1)
    assert 0.5 < lut.max() < 2.0, f"CH01 LUT 最大值 {lut.max():.3f} 不在 (0.5, 2.0)"


def test_thermal_lut_is_kelvin(fy4b_4000m):
    lut = fy4b_4000m.load("Calibration/CALChannel12").data.reshape(-1)
    assert 100.0 < lut.min() and lut.max() < 400.0, \
        f"CH12 LUT 值域 {lut.min():.1f}~{lut.max():.1f} 不像亮温(K)"


def test_calibrated_temperature_is_physical(fy4b_4000m):
    dn = fy4b_4000m.load("Data/NOMChannel12").data[::8, ::8]
    lut = fy4b_4000m.load("Calibration/CALChannel12").data.reshape(-1)
    bt = lookup_table(dn, lut, kind="nearest")
    valid = bt[bt == bt]
    assert valid.size > 0, "定标后无有效值"
    assert 150 < valid.min() and valid.max() < 350, \
        f"亮温 {valid.min():.1f}~{valid.max():.1f} K 超出物理范围"


def test_reflectance_range_is_sane(fy4b_4000m):
    """白天 granule 的反射率应在 0~1 之间（允许少量镜面反射超过 1）。"""
    dn = fy4b_4000m.load("Data/NOMChannel02").data[::8, ::8]
    lut = fy4b_4000m.load("Calibration/CALChannel02").data.reshape(-1)
    refl = lookup_table(dn, lut, kind="nearest")
    valid = refl[refl == refl]
    assert valid.size > 0
    assert -0.05 <= valid.min() and valid.max() <= 1.5, \
        f"反射率 {valid.min():.3f}~{valid.max():.3f} 超出合理范围"
