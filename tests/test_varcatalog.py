"""变量分类与三维数据渲染的回归测试。

对应三个真实 bug（用户实测反馈）：
1. FY-3D 的 EV_1KM_RefSB (15,2000,2048) 被当二维图像渲染 → 15 个通道拼成横条
2. RGB 下拉框混入 Calibration/* 校准表 → 选中后尺寸不符崩溃
3. 变量列表把校准表/坐标/质量码与真影像混在一起
"""
from __future__ import annotations

import glob

import numpy as np
import pytest

from fysat.gui.varcatalog import (
    classify,
    classify_dataset,
    describe_class,
    image_names,
    rgb_choices,
)
from fysat.gui.workers import render_rgb, render_variable
from fysat.model import SatDataset, Variable
from fysat.render import band_of, display_band, n_bands


# ---------------- 分类规则 ----------------

@pytest.mark.parametrize("name,shape,expect", [
    ("Data/EV_1KM_RefSB", (15, 2000, 2048), "band_stack"),
    ("Data/NOMChannel02", (2748, 2748), "image"),
    ("Calibration/VIS_Cal_Coeff", (19, 3), "table"),
    ("Calibration/CALChannel01", (4096,), "table"),
    ("Calibration/BB_DN_average", (25, 200), "table"),
    ("NOMObs/NOMObsTime", (10992, 2), "table"),
    ("QA/QA_Frame_Flag", (200,), "qa"),
    ("Geolocation/Latitude", (400, 410), "coord"),   # 逐像元定位场，不是影像
    ("Geolocation/Longitude", (400, 410), "coord"),  # 同上
])
def test_classify_rules(name, shape, expect):
    assert classify(name, shape).kind == expect


def test_thin_arrays_are_not_images():
    """(200, 1) 这种极窄数组不是影像。"""
    assert classify("QA/QA_Frame_Flag", (200, 1)).kind == "qa"
    assert classify("mystery", (200, 2)).kind == "table"


def test_band_count_detection():
    v = Variable(name="x", data=np.zeros((15, 20, 30), np.uint16), source_shape=(15, 20, 30))
    assert n_bands(v) == 15

    v2 = Variable(name="y", data=np.zeros((200, 300), np.uint16), source_shape=(200, 300))
    assert n_bands(v2) == 1


# ---------------- 三维取通道 ----------------

def test_band_of_slices_channel_dim():
    arr = np.arange(3 * 10 * 12, dtype=np.uint16).reshape(3, 10, 12)
    v = Variable(name="x", data=arr, source_shape=arr.shape)

    assert band_of(v, 0).shape == (10, 12)
    assert band_of(v, 2).shape == (10, 12)
    assert np.array_equal(band_of(v, 1), arr[1])


def test_display_band_applies_scale_and_mask():
    arr = np.zeros((3, 20, 30), dtype=np.uint16)
    arr[0, 0, 0] = 100
    arr[0, 0, 1] = 65535          # 填充值
    arr[0, 1, 0] = 200
    arr[0, 1, 1] = 300
    v = Variable(name="x", data=arr, source_shape=arr.shape,
                 scale_factor=0.01, fill_value=65535, valid_range=(0, 4095))

    out = display_band(v, 0)
    assert out.shape == (20, 30)
    assert pytest.approx(float(out[0, 0])) == 1.0          # 100 * 0.01
    assert np.isnan(out[0, 1])                              # 填充值 → NaN
    assert pytest.approx(float(out[1, 0])) == 2.0
    assert pytest.approx(float(out[1, 1])) == 3.0


def test_render_variable_returns_2d_image_for_band_stack():
    """核心回归：三维通道栈必须渲染成二维图像，而不是拼成横条。"""
    arr = (np.random.default_rng(0).random((15, 40, 60)) * 4000).astype(np.uint16)
    v = Variable(name="x", data=arr, source_shape=arr.shape)

    out = render_variable(v, cmap="gray", band=0)
    assert out.ndim == 3 and out.shape[:2] == (40, 60), \
        f"应得到 (40,60,3) 的图，实际 {out.shape}"

    out5 = render_variable(v, cmap="gray", band=5)
    assert out5.shape == (40, 60, 3)


# ---------------- RGB 选通道 ----------------

def _make_ds() -> SatDataset:
    ds = SatDataset(platform="FY-TEST", instrument="X")
    for i in range(3):
        name = f"Data/NOMChannel{i+1:02d}"
        ds.variables[name] = Variable(name=name, data=np.zeros((100, 120), np.uint16),
                                      source_shape=(100, 120))
    ds.variables["Calibration/CALChannel01"] = Variable(
        name="Calibration/CALChannel01", data=np.zeros((4096,), np.float32),
        source_shape=(4096,))
    ds.variables["Calibration/VIS_Cal_Coeff"] = Variable(
        name="Calibration/VIS_Cal_Coeff", data=np.zeros((19, 3), np.float32),
        source_shape=(19, 3))
    return ds


def test_rgb_choices_exclude_calibration_tables():
    """核心回归：校准表不能出现在 RGB 候选里。"""
    ds = _make_ds()
    choices = rgb_choices(ds)
    names = [v for _, v in choices]
    assert len(names) == 3
    assert all("Calibration" not in n for n in names), f"混入了校准表: {names}"


def test_rgb_choices_filter_by_shape():
    ds = _make_ds()
    ds.variables["Data/Other"] = Variable(name="Data/Other", data=np.zeros((50, 60), np.uint16),
                                          source_shape=(50, 60))
    choices = rgb_choices(ds, base_shape=(100, 120))
    names = [v for _, v in choices]
    assert "Data/Other" not in names, "不同形状的影像不该出现在同一组 RGB 候选里"


def test_render_rgb_rejects_mismatched_shapes():
    """尺寸不一致时必须给出可读错误，而不是 numpy 的晦涩报错。"""
    ds = _make_ds()
    ds.variables["Data/Tiny"] = Variable(name="Data/Tiny", data=np.zeros((15, 2), np.float32),
                                         source_shape=(15, 2))
    with pytest.raises(ValueError, match="尺寸不一致|不是二维"):
        render_rgb(ds.load, ("Data/NOMChannel01", "Data/Tiny", "Data/NOMChannel02"))


def test_render_rgb_works_with_consistent_shapes():
    ds = _make_ds()
    rgb = render_rgb(ds.load, ("Data/NOMChannel01", "Data/NOMChannel02", "Data/NOMChannel03"))
    assert rgb.shape == (100, 120, 3)
    assert rgb.dtype == np.uint8


def test_image_names_excludes_aux():
    ds = _make_ds()
    imgs = image_names(ds)
    assert len(imgs) == 3
    assert not any("Calibration" in n for n in imgs)


def test_describe_class_is_chinese():
    c = classify("Data/EV_1KM_RefSB", (15, 2000, 2048))
    assert "通道" in describe_class(c)


# ---------------- 真实文件 ----------------

@pytest.fixture(scope="module")
def fy3d_file():
    hits = glob.glob(r"Y:\download-data\**\FY3D_MERSI_GBAL_L1_*.HDF", recursive=True)
    if not hits:
        pytest.skip("缺 FY-3D 样本")
    return hits[0]


def test_real_fy3d_classification(fy3d_file):
    """真实 FY-3D 文件：影像变量必须被正确识别，辅助表不得混入。"""
    from fysat.readers import open_file

    ds = open_file(fy3d_file, load=False)
    classes = classify_dataset(ds)
    imgs = {n: c for n, c in classes.items() if c.is_image}
    aux = {n: c for n, c in classes.items() if not c.is_image}

    assert any(n.endswith("EV_1KM_RefSB") for n in imgs), "EV_1KM_RefSB 应被识别为影像"
    assert any("Vis_Cal_Coeff" in n or "VIS_Cal_Coeff" in n for n in aux), \
        "校准系数应被识别为辅助表"
    assert not any("Calibration" in n for n in imgs), f"辅助表混入了影像列表: {list(imgs)}"


def test_real_fy3d_band_render_is_2d(fy3d_file):
    """真实三维数据渲染后必须是二维图像。"""
    from fysat.readers import open_file

    ds = open_file(fy3d_file, load=False)
    var = ds.load("Data/EV_1KM_RefSB")
    out = render_variable(var, cmap="gray", band=0, max_size=512)
    h, w = out.shape[:2]
    assert h == w or abs(h - w) < 100, f"图像比例异常 {out.shape}，可能又被拼成横条了"
    assert h < 1000 and w < 1000, "应已降采样到 max_size 以内"
