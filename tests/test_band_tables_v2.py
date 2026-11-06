"""波段表 v2 的**反向校验**：用真实文件检查表里写的数值对不对。

这个测试的意义在于：波段表是"文件内通道-物理波段表"，
所以它必须能被真实文件证实，而不是只和文档自说自话。

三类校验：
1. 结构校验：每个仪器的 channels 键连续、type 合法、in_file 段齐全
2. 文件校验（verified_in_file: true 的仪器）：表里的数值必须与文件属性一致
   - MERSI  ← 全局 Effect_Center_WaveLength
   - AVHRR  ← 每个 CHnn 的 wavelength_um
   - MWRI   ← 全局 Chs_Central_Frequency
3. 未验证项必须显式标注，不能假装确定
"""
from __future__ import annotations

import os

import numpy as np
import pytest
from _sample_root import glob_samples

from fysat import composites

VALID_TYPES = {"reflective", "thermal", "microwave", "pan", "other"}
VALID_LOCATE = {"stack_band_name", "nomchannel", "named", "ndarray_stack", "none"}


# ---------------- 1. 结构校验 ----------------

def test_schema_version_is_v2():
    bands = composites._bands()
    assert bands.get("schema_version") == 2


def test_every_instrument_has_in_file_section():
    """「文件内」是本表的核心，每个仪器都必须写清楚在文件里怎么找。"""
    for key, inst in composites.instruments().items():
        assert "in_file" in inst, f"{key} 缺少 in_file 段"
        locate = inst["in_file"].get("locate")
        assert locate in VALID_LOCATE, f"{key} 的 locate={locate} 不合法"
        assert "verified_in_file" in inst["in_file"], f"{key} 未声明 verified_in_file"


def test_channel_numbers_are_contiguous():
    for key in composites.instruments():
        chans = sorted(composites.band_table(key))
        if not chans:
            continue
        assert chans == list(range(1, len(chans) + 1)), \
            f"{key} 的通道号不连续: {chans}"


def test_channel_types_are_valid():
    for key in composites.instruments():
        for ch, spec in composites.band_table(key).items():
            assert spec.get("type") in VALID_TYPES, f"{key} ch{ch} type={spec.get('type')}"


def test_optical_channels_have_wavelength():
    for key in composites.instruments():
        if composites.quantity_of(key) != "wavelength_um":
            continue
        for ch, spec in composites.band_table(key).items():
            has_value = ("um" in spec) or ("range" in spec)
            # 允许"显式未知"：标了 verified:false 且写了 note 的通道可以没有数值
            explicitly_unknown = spec.get("verified") is False and spec.get("note")
            assert has_value or explicitly_unknown, (
                f"{key} ch{ch} 既无 um/range，也没标成显式未知")


def test_microwave_channels_have_frequency():
    for ch, spec in composites.band_table("mwri").items():
        assert "ghz" in spec, f"mwri ch{ch} 缺 ghz"


def test_unverified_entries_have_note():
    """标了 verified: false 的必须写明为什么不确定。"""
    for key in composites.instruments():
        for ch, spec in composites.band_table(key).items():
            if spec.get("verified") is False:
                assert spec.get("note"), f"{key} ch{ch} 标了未验证却没写 note"


def test_mainstream_instruments_covered():
    """v1 至少覆盖这些主流仪器。"""
    need = {"mersi", "agri", "ghi", "vissr", "avhrr_noaa", "mwri"}
    have = set(composites.instruments())
    assert need <= have, f"缺少: {need - have}"


# ---------------- 2. 用真实文件校验数值 ----------------

def _find(pat, min_mb=0.5):
    hits = [h for h in glob_samples(pat)
            if os.path.getsize(h) > min_mb * 1e6]
    return hits[0] if hits else None


def test_mersi_matches_file_attribute():
    """MERSI 的 25 个波长必须与文件全局属性 Effect_Center_WaveLength 一致。"""
    f = _find("FY3D_MERSI_GBAL_L1_*1000M_MS.HDF", 10)
    if not f:
        pytest.skip("缺 FY-3D MERSI 样本")
    from fysat.readers import open_file

    ds = open_file(f, load=False)
    raw = np.ravel(np.asarray(ds.attrs["Effect_Center_WaveLength"]))
    table = composites.band_table("mersi")

    assert len(raw) == 25, f"文件属性有 {len(raw)} 个波长"
    assert len(table) == 25
    for ch in range(1, 26):
        want = float(raw[ch - 1])
        got = composites.band_wavelength("mersi", ch)
        assert got == pytest.approx(want, abs=5e-3), (
            f"b{ch}: 表里写 {got}µm，文件属性是 {want}µm")


def test_avhrr_matches_per_channel_attribute():
    """AVHRR 每个通道的 wavelength_um 属性必须与表里的 range 吻合。"""
    f = _find("NA18_AVHRR_HRPT*.L1B", 10)
    if not f:
        pytest.skip("缺 NOAA-18 样本")
    from fysat.readers import open_file

    ds = open_file(f, load=False)

    # 文件里 CH1..CH5，其中 CH3 在本样本是 3B
    expect = {"CH1": 1, "CH2": 2, "CH3": 4, "CH4": 5, "CH5": 6}
    table = composites.band_table("avhrr_noaa")
    for name, ch in expect.items():
        attr = ds.variables[name].attrs.get("wavelength_um")
        assert attr, f"{name} 缺 wavelength_um 属性"
        lo, hi = [float(x) for x in str(attr).replace("~", "-").split("-")]
        want = table[ch]["range"]
        assert want == pytest.approx([lo, hi], abs=0.02), (
            f"{name} 文件属性 {attr}，表里 ch{ch} 是 {want}")


def test_avhrr_wavenumber_consistent_with_wavelength():
    """热通道另有波数属性，换算成波长后应与波长区间自洽。"""
    f = _find("NA18_AVHRR_HRPT*.L1B", 10)
    if not f:
        pytest.skip("缺 NOAA-18 样本")
    from fysat.readers import open_file

    ds = open_file(f, load=False)
    wn = ds.attrs.get("central_wavenumber_cm1")
    if not wn or not isinstance(wn, dict):
        pytest.skip("本样本无 central_wavenumber_cm1")
    mapping = {"CH4": 5, "CH5": 6}
    for name, ch in mapping.items():
        if name not in wn:
            continue
        um = 1e4 / float(wn[name])
        lo, hi = composites.band_table("avhrr_noaa")[ch]["range"]
        assert lo - 0.05 <= um <= hi + 0.05, (
            f"{name}: 波数换算 {um:.3f}µm 不在表里的 {lo}-{hi}µm 区间")


def test_mwri_frequency_count_matches_file():
    """MWRI 的频点数必须与文件全局属性 Chs_Central_Frequency 一致。"""
    f = _find("FY3H_MWRI-_ORBA*010KM*.HDF", 1)
    if not f:
        pytest.skip("缺 FY-3H MWRI 样本")
    from fysat.readers import open_file

    ds = open_file(f, load=False)
    raw = ds.attrs.get("Chs_Central_Frequency")
    if raw is None:
        pytest.skip("本样本无 Chs_Central_Frequency")
    text = str(raw).strip("[]'\"")
    parts = [x for x in text.replace(" ", "").split(",") if x]
    table = composites.band_table("mwri")
    assert len(parts) == len(table), (
        f"文件属性有 {len(parts)} 个频点，表里 {len(table)} 个：{parts}")
    # 前 5 个是纯数字的成像频点
    for i in range(5):
        want = float(parts[i])
        got = composites.band_frequency("mwri", i + 1)
        assert got == pytest.approx(want, abs=1e-3), f"mwri ch{i+1}: 表 {got} vs 文件 {want}"


# ---------------- 3. in_file 定位可用性 ----------------

def test_locate_strategy_present_per_instrument():
    """每种 locate 策略都要有说明字段，下游才能用它去文件里找。"""
    for key, inst in composites.instruments().items():
        info = inst["in_file"]
        loc = info["locate"]
        if loc == "stack_band_name":
            assert info.get("band_name_attr"), f"{key} 缺 band_name_attr"
        elif loc == "nomchannel":
            assert info.get("dataset_pattern"), f"{key} 缺 dataset_pattern"
        elif loc == "named":
            assert info.get("name_patterns"), f"{key} 缺 name_patterns"


def test_mersi_stack_segments_documented():
    """MERSI 的四个通道分段必须写在 in_file 里（它是理解 MERSI 的关键）。"""
    info = composites.in_file_info("mersi")
    segs = info.get("segments") or {}
    assert segs, "in_file 缺 segments（MERSI 的通道分散在 4 个数据集里，必须记录）"
    values = set(segs.values())
    for seg in ("1,2,3,4", "5-19", "20,21,22,23", "24,25"):
        assert seg in values, f"未记录分段 {seg}，实际 {values}"
