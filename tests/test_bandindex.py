"""通道索引与 RGB 预设的回归测试。

对应缺陷（用户实报）：
1. MERSI 的通道分散在 4 个多通道堆栈里，而 RGB 下拉框只能选数据集，
   于是 R/G/B 常常都指向同一个数据集的第 0 层 → 合成退化成灰度图。
2. 预设组合（真彩色等）只有符号名（b3/vis/ir），没有任何代码把它们
   解析成真实变量+通道 → 点了没反应。
3. set_dataset 从不填充 RGB 下拉，刚打开文件时三个下拉都是空的。
"""
from __future__ import annotations

import glob

import numpy as np
import pytest

from fysat.gui import bandindex as bi


# ---------------- band_name 解析 ----------------

@pytest.mark.parametrize("raw,want", [
    (b"1,2,3,4", [1, 2, 3, 4]),
    (b"20,21,22,23", [20, 21, 22, 23]),
    (b"5-19", list(range(5, 20))),
    (b"24,25", [24, 25]),
    (b"1-25", list(range(1, 26))),
    (b"none", []),
    (b"NANA", []),
    ("", []),
    (None, []),
])
def test_parse_band_name(raw, want):
    assert bi._parse_band_name(raw) == want


# ---------------- 假数据集上的索引与预设 ----------------

class _Var:
    def __init__(self, shape, band_name=None, attrs=None):
        self.shape = tuple(shape)
        self.attrs = dict(attrs or {})
        if band_name is not None:
            self.attrs["band_name"] = band_name


class _FakeDS:
    """按真实 FY-3 MERSI 的结构造一个最小数据集。"""

    def __init__(self):
        self.variables = {
            "Data/EV_250_Aggr.1KM_RefSB": _Var((4, 100, 120), b"1,2,3,4"),
            "Data/EV_1KM_RefSB": _Var((15, 100, 120), b"5-19"),
            "Data/EV_1KM_Emissive": _Var((4, 100, 120), b"20,21,22,23"),
            "Data/EV_250_Aggr.1KM_Emissive": _Var((2, 100, 120), b"24,25"),
            "Geolocation/Latitude": _Var((20, 24), b"none"),
        }
        # 标称中心波长（与文件里的 Effect_Center_WaveLength 同序）
        self.attrs = {
            "Effect_Center_WaveLength": np.array(
                [0.470, 0.550, 0.650, 0.865,   # b1-b4
                 1.380, 1.640, 2.130, 0.412, 0.444, 0.490, 0.556, 0.671,
                 0.708, 0.746, 0.865, 0.906, 0.936, 0.938, 1.029,  # b5-b19
                 3.796, 4.051, 7.215, 8.553,   # b20-b23
                 10.714, 11.963], dtype=np.float32),  # b24-b25
        }


def test_band_index_covers_all_25_channels():
    idx = bi.band_index(_FakeDS())
    assert sorted(idx) == list(range(1, 26))
    # 抽查几个关键通道落在正确的数据集与下标
    assert idx[1].variable == "Data/EV_250_Aggr.1KM_RefSB" and idx[1].index == 0
    assert idx[3].variable == "Data/EV_250_Aggr.1KM_RefSB" and idx[3].index == 2
    assert idx[5].variable == "Data/EV_1KM_RefSB" and idx[5].index == 0
    assert idx[20].variable == "Data/EV_1KM_Emissive" and idx[20].index == 0
    assert idx[24].variable == "Data/EV_250_Aggr.1KM_Emissive" and idx[24].index == 0


def test_band_index_skips_non_image_variables():
    idx = bi.band_index(_FakeDS())
    assert "Geolocation/Latitude" not in {r.variable for r in idx.values()}


def test_symbol_resolution_uses_wavelength():
    ds = _FakeDS()
    assert bi.resolve_symbol(ds, "b3").wavelength == pytest.approx(0.650, abs=1e-3)
    assert bi.resolve_symbol(ds, "vis").band == 3      # 0.65 µm
    assert bi.resolve_symbol(ds, "green").band == 2    # 0.55 µm
    assert bi.resolve_symbol(ds, "blue").band == 1     # 0.47 µm
    assert bi.resolve_symbol(ds, "ir").band == 24      # 10.7 µm 窗区
    assert bi.resolve_symbol(ds, "ir_short").band == 20  # 3.8 µm


def test_true_color_preset_picks_three_different_bands():
    """真彩色必须是 b3/b2/b1，而且落在同一个数据集里。"""
    plan = bi.resolve_preset(_FakeDS(), "true_color")
    assert plan is not None
    assert plan.bands == (2, 1, 0)          # 数组下标
    assert {r.band for r in plan.refs} == {3, 2, 1}
    assert len({r.variable for r in plan.refs}) == 1
    # 三个通道互不相同才是有效合成
    assert len(set(zip(plan.names, plan.bands))) == 3


def test_unavailable_presets_are_excluded_not_faked():
    """缺通道/需波段差值的预设必须解析不出来，而不是给出错误组合。"""
    plans = {p.key for p in bi.available_presets(_FakeDS())}
    assert "true_color" in plans
    assert "dust" not in plans        # 需要 11-12µm 差值，暂不支持
    assert bi.resolve_preset(_FakeDS(), "dust") is None


def test_band_labels_show_band_number_and_wavelength():
    labels = bi.band_labels(_FakeDS(), "Data/EV_250_Aggr.1KM_RefSB")
    assert len(labels) == 4
    assert "b3" in labels[2] and "0.650" in labels[2]


# ---------------- 真实文件 ----------------

def _real_file():
    hits = [h for h in glob.glob(r"Y:\download-data\**\FY3D_MERSI_GBAL_L1_*1000M_MS.HDF",
                                 recursive=True)]
    hits = [h for h in hits if __import__("os").path.getsize(h) > 10_000_000]
    return hits[0] if hits else None


def test_real_mersi_band_index():
    f = _real_file()
    if not f:
        pytest.skip("缺 FY-3D MERSI 样本")
    from fysat.readers import open_file

    ds = open_file(f, load=False)
    idx = bi.band_index(ds)
    # 真实文件里 MERSI 有 25 个通道
    assert len(idx) == 25, f"只识别出 {len(idx)} 个通道: {sorted(idx)}"
    # b1 必须是 0.47µm 附近的可见光
    assert 0.44 < idx[1].wavelength < 0.50
    # b24 必须是 10.7µm 窗区（亮温窗区）
    assert 10.0 < idx[24].wavelength < 11.0

    plan = bi.resolve_preset(ds, "true_color")
    assert plan is not None
    assert plan.bands == (2, 1, 0)
    assert all("EV_250" in n for n in plan.names), plan.names
