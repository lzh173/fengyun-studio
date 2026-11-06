"""04 制图工作台的导出 / 版式 / 图层开关回归测试。

这一屏以前的核心毛病是「看着能用、实际用不了」：
导出直接弹 ``QFileDialog``（脚本与批量都做不了）、模板条点了不换版式、
图层复选框只改 UI 状态。所以本文件的断言尽量落在**输出文件**上，
而不是 UI 属性上：

1. ``export_to()`` 不弹任何对话框就能出图（且会按格式补后缀）
2. ``single`` / ``double`` 两种版式真的出不同版面的图（像素尺寸 + 像素内容）
3. 海岸线 / 经纬网 / 色标 三个开关分别改变成图像素
4. 色标下拉框、经纬网间隔真的生效（这两个以前也只看 UI 状态）
5. 未实现的模板必须置灰 + tooltip 说明「尚未实现」，点了也不能切换
6. PNG 里能读回 ``fysat.*`` 溯源字段
7. ``set_region`` / 选区带入会真的改变成图

跑法（无显示器）::

    set QT_QPA_PLATFORM=offscreen
    set TMP=E:\\tmp & set TEMP=E:\\tmp
    E:\\venv\\fysat\\Scripts\\python.exe -m pytest tests/test_figurebench_export.py -q
"""
from __future__ import annotations
from _sample_root import SAMPLE_ROOT

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("PIL.Image")

from PIL import Image                                            # noqa: E402
from PySide6 import QtCore, QtWidgets                             # noqa: E402

from fysat.gui.figurebench import (                               # noqa: E402
    TEMPLATES,
    FigureBench,
    template_enabled,
)

OUT = Path(__file__).resolve().parents[1] / "out" / "gui" / "export"
SAMPLES = [
    str(SAMPLE_ROOT / r"C202611011426140096\FY3D_MERSI_GBAL_L1_20260810_0635_1000M_MS.HDF"),
    str(SAMPLE_ROOT / r"0-IDM-download\FY3H_MERSI_GRAN_L1_20261030_0300_1000M_V0.hdf"),
]

# 测试用低 DPI：断言的是"版式与开关是否改变成图"，不是印刷质量
TEST_DPI = 72


# ==================== 夹具 ====================

@pytest.fixture(scope="module")
def app():
    inst = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from fysat.gui import theme

    theme.apply_theme(inst)
    yield inst


def _sample() -> str | None:
    for p in SAMPLES:
        if Path(p).exists():
            return p
    return None


@pytest.fixture(scope="module")
def sample_path() -> str:
    p = _sample()
    if p is None:
        pytest.skip("缺真实样本（Y:\\download-data 下没有 FY-3 MERSI L1）")
    return p


@pytest.fixture(scope="module")
def ds(sample_path):
    from fysat.readers import open_file

    return open_file(sample_path, load=False)


def wait_until(app, predicate, timeout_s: float = 180.0) -> bool:
    import time

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        if predicate():
            return True
        QtCore.QThread.msleep(20)
    return bool(predicate())


@pytest.fixture(scope="module")
def bench(app, ds):
    """一个已经加载真实数据、预览已就绪的工作台。"""
    w = FigureBench()
    w.resize(1500, 900)
    w.show()
    w.spin_dpi.setValue(TEST_DPI)
    w.set_dataset(ds)
    assert wait_until(app, lambda: w.preview_ready() and not w._busy), "预览超时"
    OUT.mkdir(parents=True, exist_ok=True)
    yield w
    w.close()


# ==================== 工具 ====================

def _array(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB")).astype(np.int16)


def _changed_ratio(a: np.ndarray, b: np.ndarray) -> float:
    """两个 RGB 数组里"肉眼可见变化"的像素占比（单通道差 > 8 记为变化）。"""
    assert a.shape == b.shape, f"尺寸不一致：{a.shape} vs {b.shape}"
    diff = np.abs(a - b).sum(axis=2)
    return float((diff > 8).mean())


def _export(bench: FigureBench, path: Path) -> tuple[Path, np.ndarray]:
    out = Path(bench.export_to(path))
    assert out.exists(), f"导出文件不存在：{out}"
    assert out.stat().st_size > 5000, f"导出文件过小（{out.stat().st_size} B）：{out}"
    return out, _array(out)


def _reset(bench: FigureBench, template: str = "single") -> None:
    """把界面恢复到确定状态（测试之间互不依赖）。"""
    bench.chk_coast.setChecked(True)
    bench.chk_grid.setChecked(True)
    bench.chk_colorbar.setChecked(True)
    bench.cmb_cmap.setCurrentText("turbo")
    bench.cmb_format.setCurrentText("PNG")
    bench.spin_dpi.setValue(TEST_DPI)
    bench.set_template(template)
    # 让 set_template 排下的延迟预览作废：测试里同步导出，不希望后台线程
    # 在大图渲染上抢锁（也让每个测试只依赖自己设的状态）。
    bench._generation += 10


# ==================== 1. 可脚本化导出 ====================

def test_export_to_never_opens_a_dialog(bench, tmp_path, monkeypatch):
    """export_to 是纯逻辑入口：不允许碰 QFileDialog / QMessageBox。"""

    def _boom(*a, **kw):        # noqa: ANN002, ANN003
        raise AssertionError("export_to 不应该弹对话框（脚本/批量/测试都依赖它）")

    for name in ("getSaveFileName", "getOpenFileName", "getExistingDirectory"):
        monkeypatch.setattr(QtWidgets.QFileDialog, name, staticmethod(_boom))
    for name in ("information", "critical", "warning", "question"):
        monkeypatch.setattr(QtWidgets.QMessageBox, name, staticmethod(_boom))

    _reset(bench, "single")
    out, _arr = _export(bench, tmp_path / "no_dialog.png")
    assert out.suffix.lower() == ".png"
    assert bench.last_export_path() == out


def test_export_to_appends_suffix_from_format(bench, tmp_path):
    """路径没后缀时按「导出 · 格式」补上，避免写出一个无扩展名文件。"""
    _reset(bench, "single")
    bench.cmb_format.setCurrentText("PNG")
    out = Path(bench.export_to(tmp_path / "no_suffix"))
    assert out.suffix.lower() == ".png" and out.exists()


def test_export_to_requires_dataset(app, tmp_path):
    """没有数据时应当明确报错，而不是弹对话框或写出一张空图。"""
    w = FigureBench()
    try:
        with pytest.raises(RuntimeError):
            w.export_to(tmp_path / "nope.png")
    finally:
        w.close()


# ==================== 2. 版式真的不同 ====================

def test_single_and_double_render_different_panels(bench, tmp_path):
    """单面板必须真的只有 1 个面板：画布尺寸与像素都与双面板不同。

    sciencefig 的 ``layout`` 决定 ``plt.subplots(1, ncols)``，两模板的推荐
    画布尺寸也不同（8×6.4 vs 13.5×6.4），所以：
    - 同 DPI 下高度相同、宽度相差约一个面板宽
    - 单面板宽高比 ≈ 1.25，双面板 ≈ 2.1
    """
    _reset(bench, "single")
    p_single, a_single = _export(bench, tmp_path / "tpl_single.png")
    _reset(bench, "double")
    p_double, a_double = _export(bench, tmp_path / "tpl_double.png")

    with Image.open(p_single) as im:
        ws, hs = im.size
    with Image.open(p_double) as im:
        wd, hd = im.size

    assert hs == hd, f"两个模板高度应一致（同一 figsize 高）：{hs} vs {hd}"
    assert wd > ws * 1.5, f"双面板宽度应约为单面板 1.7 倍：{wd} vs {ws}"
    assert ws / hs < 1.6, f"单面板应接近方形，实际 {ws}x{hs}"
    assert wd / hd > 1.9, f"双面板应是长条，实际 {wd}x{hd}"
    assert a_single.shape != a_double.shape, "两种版式的成图尺寸竟然相同"


# ==================== 3. 图层开关真的改变成图 ====================

def test_colorbar_toggle_changes_output(bench, tmp_path):
    _reset(bench, "single")
    _p, base = _export(bench, tmp_path / "cbar_on.png")
    bench.chk_colorbar.setChecked(False)
    assert bench.layer_list.state_of("colorbar") is False, "图层树状态没跟着复选框变"
    _p, off = _export(bench, tmp_path / "cbar_off.png")
    bench.chk_colorbar.setChecked(True)
    ratio = _changed_ratio(base, off)
    assert ratio > 0.10, f"关掉色标后成图几乎没变（{ratio:.3%}），开关是假的"


def test_grid_toggle_changes_output(bench, tmp_path):
    _reset(bench, "single")
    _p, base = _export(bench, tmp_path / "grid_on.png")
    bench.chk_grid.setChecked(False)
    assert bench.layer_list.state_of("grid") is False
    _p, off = _export(bench, tmp_path / "grid_off.png")
    bench.chk_grid.setChecked(True)
    ratio = _changed_ratio(base, off)
    assert ratio > 0.005, f"关掉经纬网后成图几乎没变（{ratio:.3%}）"


def test_coast_toggle_changes_output(bench, sample_path, tmp_path):
    """海岸线开关必须真的落笔（选样本需覆盖陆地/海岸线）。"""
    if "FY3D" not in Path(sample_path).name:
        pytest.skip("当前样本（FY3H 西太平洋段）经纬度框内没有可画的海岸线，"
                    "改用 FY3D 样本才能验证海岸线开关")
    _reset(bench, "single")
    _p, base = _export(bench, tmp_path / "coast_on.png")
    bench.chk_coast.setChecked(False)
    assert bench.layer_list.state_of("overlay") is False
    _p, off = _export(bench, tmp_path / "coast_off.png")
    bench.chk_coast.setChecked(True)
    ratio = _changed_ratio(base, off)
    assert ratio > 0.001, f"关掉海岸线后成图几乎没变（{ratio:.4%}），海岸线没画出来"


def test_layer_tree_only_toggles_real_switches(bench):
    """图层树里"只读状态"行不能伪装成可切换按钮。"""
    _reset(bench, "single")
    keys = bench.layer_list.togglable_keys()
    assert set(keys) == {"overlay", "grid", "colorbar"}, (
        f"可切换行应只包含真的会改变成图的项，实际 {keys}")
    # 通道名之类的只读行仍然显示，但不可切换
    states = {k: v for k, v, _d, _t in [(r[0], r[2], r[3], r[4])
                                        for r in bench.layer_list.layers()]}
    assert "panelA_r" in states and "panelB_range" in states
    # 关掉面板 A 等价于单面板：会真的改变 layout
    _reset(bench, "double")
    assert bench._effective_layout() == "double"
    bench.chk_coast.setChecked(True)
    bench._on_layer_toggled("panelA", False)
    assert bench._effective_layout() == "single", "关掉面板 A 没有退化成单面板"
    bench._on_layer_toggled("panelA", True)
    assert bench._effective_layout() == "double"


# ==================== 4. 其它"以前只改 UI"的参数 ====================

def test_cmap_selection_changes_output(bench, tmp_path):
    """pipeline 里 ThermalLayer.cmap 写死 turbo，界面选色标曾经完全不生效。"""
    _reset(bench, "single")
    _p, turbo = _export(bench, tmp_path / "cmap_turbo.png")
    bench.cmb_cmap.setCurrentText("gray")
    _p, gray = _export(bench, tmp_path / "cmap_gray.png")
    bench.cmb_cmap.setCurrentText("turbo")
    ratio = _changed_ratio(turbo, gray)
    assert ratio > 0.20, f"换色标后成图几乎没变（{ratio:.3%}）"


def test_grid_step_changes_output(bench, tmp_path):
    """经纬网间隔以前只触发重渲染、从不传给 FigureSpec.grid_step。"""
    _reset(bench, "single")
    _p, auto = _export(bench, tmp_path / "step_auto.png")
    bench._on_grid_step("10°")
    assert bench._grid_step == 10.0
    _p, step10 = _export(bench, tmp_path / "step_10.png")
    bench._on_grid_step("自动")
    assert bench._grid_step is None
    ratio = _changed_ratio(auto, step10)
    assert ratio > 0.002, f"改经纬网间隔后成图几乎没变（{ratio:.4%}）"


# ==================== 5. 未实现的模板必须置灰 ====================

def test_unimplemented_templates_are_disabled_and_labelled(app):
    """没实现的模板：按钮置灰、tooltip 说明、点下去也切不过去。"""
    unimplemented = [t for t in TEMPLATES if not template_enabled(t[0])]
    assert unimplemented, "若全都实现了，这个测试就该改成只断言 implemented"

    w = FigureBench()
    try:
        before = w._template
        for key, _label, _layout, _desc, _impl in unimplemented:
            btn = w.tplbar.button(key)
            assert btn is not None, f"模板条里找不到 {key}"
            assert not btn.isEnabled(), f"未实现的模板 {key} 竟然可点"
            assert "尚未实现" in w.tplbar.tooltip_of(key), (
                f"{key} 的 tooltip 没有说明尚未实现：{w.tplbar.tooltip_of(key)!r}")
            btn.click()
            app.processEvents()
        assert w._template == before, "点了置灰模板后当前模板被改掉了"

        # 已实现的模板可以点，并且会切换
        for key in [t[0] for t in TEMPLATES if template_enabled(t[0])]:
            assert w.tplbar.button(key).isEnabled(), f"已实现模板 {key} 不该置灰"
            w.tplbar.button(key).click()
            app.processEvents()
            assert w._template == key
    finally:
        w.close()


def test_implemented_templates_match_sciencefig_layouts():
    """契约：实现的模板只能落在 sciencefig 真支持的 layout 上。"""
    from fysat.gui.figurebench import SUPPORTED_LAYOUTS

    for key, _label, layout, _desc, impl in TEMPLATES:
        assert layout in SUPPORTED_LAYOUTS
        if impl:
            assert template_enabled(key)
        else:
            assert not template_enabled(key)


# ==================== 6. 导出带溯源 ====================

def test_exported_png_carries_provenance(bench, tmp_path):
    from fysat.provenance import read_png_provenance

    _reset(bench, "single")
    out, _arr = _export(bench, tmp_path / "prov.png")
    prov = read_png_provenance(out)

    assert prov.get("software") == "FY-Sat Studio", f"溯源字段缺失：{prov}"
    assert prov.get("software_version")
    assert prov.get("generated_at", "").endswith("Z")
    assert prov.get("layout") == "single"
    assert prov.get("template") == "single"
    assert prov.get("draw_coast") in {"0", "1"}
    if bench._ds is not None and getattr(bench._ds, "platform", ""):
        assert prov.get("platform"), "溯源里缺少数据平台"


def test_provenance_footer_is_composed(bench, tmp_path):
    """页脚是 PDF/SVG 里唯一的溯源载体：必须真的被拼出来并挂到导出上。"""
    from fysat.gui.figurebench import _footer_from_provenance

    _reset(bench, "single")
    bench.export_to(tmp_path / "footer.png")
    footer = _footer_from_provenance(bench._provenance)
    assert "FY-Sat Studio" in footer, f"页脚没有软件署名：{footer!r}"
    assert len(footer) <= 110, "页脚过长会溢出画布"
    prov = bench.provenance()
    assert prov.get("figure_bench") == "04 制图工作台"


# ==================== 7. 选区带入 ====================

def test_set_region_changes_output(bench, tmp_path):
    _reset(bench, "single")
    bench.set_region(None)
    assert bench.region() is None
    _p, full = _export(bench, tmp_path / "region_full.png")

    box = (400, 900, 300, 900)          # 行 400–900 × 列 300–900
    bench.set_region(box)
    assert bench.region() == box
    assert "400" in bench.lbl_region.text()
    _p, sub = _export(bench, tmp_path / "region_box.png")
    bench.set_region(None)

    ratio = _changed_ratio(full, sub)
    assert ratio > 0.10, f"换成框选区域后成图几乎没变（{ratio:.3%}）"


def test_adopt_selection_reads_mainwindow_selection(app, ds):
    """主界面框选 → 制图工作台：只读 MainWindow._selection。"""
    holder = QtWidgets.QWidget()
    holder._selection = (10, 110, 20, 220)
    holder._ds = ds
    try:
        w = FigureBench(holder)
        w._ds = ds                        # 有数据集才允许带入（避免触发无用渲染）
        assert w.adopt_selection() == (10, 110, 20, 220)
        assert w.region() == (10, 110, 20, 220)
        # 主界面没有框选时返回 None，不报错、也不改范围
        holder._selection = None
        w.set_region(None)
        assert w.adopt_selection() is None
        assert w.region() is None
        # 无主窗口（单屏）时也不能炸
        solo = FigureBench()
        try:
            assert solo.adopt_selection() is None
            solo.set_region((1, 2, 3, 4))
            assert solo.region() == (1, 2, 3, 4)
        finally:
            solo._ds = None
            solo.close()
        w._ds = None                      # 让 set_region 排下的预览作废
    finally:
        holder.close()


def test_show_event_adopts_selection(app, ds):
    """切到 04 屏（showEvent）时要自动去读主界面选区。"""
    w = FigureBench()
    w._ds = ds
    calls: list[int] = []
    w.adopt_selection = lambda window=None: calls.append(1) or None
    try:
        w.show()
        app.processEvents()
        assert calls, "showEvent 没有调用 adopt_selection（切屏不会带入选区）"
    finally:
        w.close()
