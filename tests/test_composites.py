"""通道-波段查找表与合成配方的测试。

数据依据（全部来自文档，写在 bands.yml 注释里）：
- MERSI: 文件属性 Effect_Center_WaveLength + FY-3D MERSI-II 文档
- AGRI : FY4B_AGRI_DISK_L1_4KM_HDF_V1.0.md 表1
- GHI  : FY-4B_REGX_GHI_0500M.md 表1
- VISSR: VISSR_AVHRR_Distribution_Format_AWX2.1.md
- AVHRR: noaa_1b_format.md 表5.2
"""
from __future__ import annotations

import os

import pytest
from _sample_root import glob_samples

from fysat import composites

# ---------------- 表完整性 ----------------

def test_all_instruments_present():
    inst = composites.instruments()
    for key in ("mersi", "agri", "ghi", "vissr", "avhrr_noaa"):
        assert key in inst, f"缺少仪器 {key}"


@pytest.mark.parametrize("inst,count", [
    ("mersi", 25), ("agri", 15), ("ghi", 6), ("vissr", 5), ("avhrr_noaa", 6),
])
def test_channel_counts(inst, count):
    assert len(composites.band_table(inst)) == count


@pytest.mark.parametrize("inst,ch,um", [
    ("mersi", 1, 0.470), ("mersi", 3, 0.650), ("mersi", 24, 10.714),
    ("agri", 1, 0.47), ("agri", 2, 0.65), ("agri", 13, 10.80),
    ("ghi", 2, 0.47), ("ghi", 3, 0.545), ("ghi", 4, 0.645),
])
def test_documented_wavelengths(inst, ch, um):
    w = composites.band_wavelength(inst, ch)
    assert w == pytest.approx(um, abs=1e-3), f"{inst} ch{ch} 应为 {um}µm，实际 {w}"


def test_range_only_channels_use_midpoint():
    """只给了波段范围的通道（AVHRR/FY-2）取中点作为代表波长。"""
    # AVHRR ch1 = 0.58-0.68 → 0.63
    assert composites.band_wavelength("avhrr_noaa", 1) == pytest.approx(0.63, abs=0.01)
    # FY-2 IR1 = 10.3-11.3 → 10.8
    assert composites.band_wavelength("vissr", 1) == pytest.approx(10.8, abs=0.05)


def test_unverified_channels_are_marked():
    """文档没直接给出波长的通道必须标 verified: false，不能假装确定。"""
    vissr = composites.band_table("vissr")
    assert vissr[3].get("verified") is False
    assert vissr[4].get("verified") is False
    ghi = composites.band_table("ghi")
    assert ghi[1].get("verified") is False


# ---------------- 配方 ----------------

def test_composites_reference_existing_channels():
    """每条配方引用的通道号必须在该仪器的波段表里存在。"""
    for inst, items in composites._composites()["composites"].items():
        table = composites.band_table(inst)
        for c in items:
            for ch in c["channels"]:
                assert int(ch) in table, f"{inst}/{c['key']} 引用了不存在的通道 {ch}"


def test_rgb_composites_have_three_channels():
    for inst, items in composites._composites()["composites"].items():
        for c in items:
            n = len(c["channels"])
            if c.get("kind") == "rgb":
                assert n == 3, f"{inst}/{c['key']} 是 rgb 但给了 {n} 个通道"
            else:
                assert n == 1, f"{inst}/{c['key']} 是 single 但给了 {n} 个通道"


def test_ghi_has_true_color_and_agri_does_not_fake_it():
    """GHI 有 0.47/0.545/0.645 三通道，能出严格真彩色；
    AGRI 没有绿色通道，只能给伪彩 —— 不能把伪彩叫"真彩色"。"""
    ghi = {c["key"] for c in composites._composites()["composites"]["ghi"]}
    agri = {c["key"]: c["label"] for c in composites._composites()["composites"]["agri"]}
    assert "true_color" in ghi
    assert "true_color" not in agri
    assert "伪彩" in agri["pseudo_color"]


# ---------------- 真实文件上的定位 ----------------

def _find(pat):
    hits = [h for h in glob_samples(pat)
            if os.path.getsize(h) > 1_000_000]
    return hits[0] if hits else None


def test_mersi_true_color_resolves_to_250m_bands():
    f = _find("FY3D_MERSI_GBAL_L1_*1000M_MS.HDF")
    if not f:
        pytest.skip("缺 FY-3D MERSI 样本")
    from fysat.readers import open_file

    ds = open_file(f, load=False)
    assert composites.instrument_of(ds) == "mersi"
    comp = composites.find(ds, "true_color")
    assert comp is not None and comp.ready
    assert comp.channels == (3, 2, 1)
    # 三个通道都要落在 250M 反射数据集里（真彩色 b1-b4 在那儿）
    assert all("EV_250" in r.variable for r in comp.refs), comp.summary()
    assert [r.index for r in comp.refs] == [2, 1, 0]


def test_ghi_channels_locate_to_nomchannel():
    f = _find("FY4B-*GHI*0500M*.HDF") or _find("FY4B-*GHI*0250M*.HDF")
    if not f:
        pytest.skip("缺 FY-4B GHI 样本")
    from fysat.readers import open_file

    ds = open_file(f, load=False)
    assert composites.instrument_of(ds) == "ghi"
    comp = composites.find(ds, "true_color")
    assert comp is not None, "GHI 应能解析真彩色"
    assert comp.ready, comp.summary()
    assert all("NOMChannel" in r.variable for r in comp.refs), comp.summary()


def test_agri_channels_locate():
    f = _find("FY4B-*AGRI*4000M*FDI*.HDF")
    if not f:
        pytest.skip("缺 FY-4B AGRI 样本")
    from fysat.readers import open_file

    ds = open_file(f, load=False)
    assert composites.instrument_of(ds) == "agri"
    ready = composites.ready_composites(ds)
    assert ready, "AGRI 应至少能解析出一条合成"
    window = composites.find(ds, "window_ir")
    assert window is not None and window.channels == (13,)


def test_avhrr_channels_locate():
    f = _find("NA18_AVHRR_HRPT*.L1B")
    if not f:
        pytest.skip("缺 NOAA-18 样本")
    from fysat.readers import open_file

    ds = open_file(f, load=False)
    assert composites.instrument_of(ds) == "avhrr_noaa"
    ready = composites.ready_composites(ds)
    assert len(ready) >= 3, f"AVHRR 应能解析多条合成，实际 {[c.key for c in ready]}"


def test_fy2_csv_channels_locate():
    f = _find("FY2G_CSV*.DAT")
    if not f:
        pytest.skip("缺 FY-2 CSV 样本")
    from fysat.readers import open_file

    ds = open_file(f, load=False)
    assert composites.instrument_of(ds) == "vissr"
    window = composites.find(ds, "window_ir")
    assert window is not None and window.ready
    assert window.refs[0].variable.endswith("IR1"), window.summary()
