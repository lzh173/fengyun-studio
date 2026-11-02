"""四屏 GUI 的离屏测试：构建、真实数据渲染、截图非空白。

这些测试不需要显示器：
    set QT_QPA_PLATFORM=offscreen
    set TMP=E:\\tmp & set TEMP=E:\\tmp      (C 盘满时必须)

覆盖四屏：
- 01 主界面：MainWindow + 四屏堆叠 + 画布海岸线/经纬网叠加 + 三层数据树
- 02 分析工作台：2×2 四视口联动 + LUT + 统计 + 直方图/剖面
- 03 解码工作台：输入队列 + 七步流水线 + 字段表 + 日志 + 校验
- 04 制图工作台：图层树 + 模板条 + 实时预览（真科学图）

以及共享控件库 chartwidgets 的纯单元测试（色标/统计/直方图/剖面/LUT/
地理映射/海岸线加载）。

为什么这些测试值得存在
----------------------
GUI 最容易出「构建成功但一片空白」的问题：控件建了、信号连了，
但 paintEvent 里什么都没画，或者线程池结果没回到主线程。
所以除了断言对象存在，还必须抓图并检查像素多样性。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6 import QtCore, QtGui, QtWidgets                  # noqa: E402

from fysat.readers import open_file                           # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "out" / "gui"

SAMPLES = [
    r"Y:\download-data\C202611011426140096\FY3D_MERSI_GBAL_L1_20260810_0635_1000M_MS.HDF",
    r"Y:\download-data\FY3H_MERSI_GRAN_L1_20261023_0520_1000M_V0.hdf",
]


# ---------------- 公共夹具 ----------------

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
        pytest.skip("缺真实样本")
    return p


@pytest.fixture(scope="module")
def ds(sample_path):
    return open_file(sample_path, load=False)


def wait_until(app, predicate, timeout_s: float = 120.0) -> bool:
    """跑事件循环直到 predicate 为真（后台线程结果靠事件循环投递）。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 100)
        if predicate():
            return True
        QtCore.QThread.msleep(20)
    return bool(predicate())


def settle(app, ms: int = 300) -> None:
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        QtCore.QThread.msleep(10)


def image_stats(widget, resize: bool = True) -> tuple[int, int, int]:
    """抓图并统计 (宽, 高, 不同颜色数)。颜色数用来判断是不是空白。

    resize=False 用于尺寸被 setFixedWidth/Height 锁定的控件（如色标条）：
    强制 resize 会被 Qt 忽略，断言尺寸反而会失败。
    """
    if resize:
        widget.resize(max(widget.width(), 900), max(widget.height(), 600))
    QtWidgets.QApplication.instance().processEvents()
    pix = widget.grab()
    assert not pix.isNull(), "grab 返回空 pixmap"
    img = pix.toImage().convertToFormat(QtGui.QImage.Format_RGB32)
    buf = img.constBits()
    arr = np.frombuffer(buf, dtype=np.uint8)
    arr = arr.reshape((img.height(), img.bytesPerLine()))[:, : img.width() * 4]
    arr = arr.reshape(img.height(), img.width(), 4)[:, :, :3]
    uniq = len(np.unique(arr.reshape(-1, 3), axis=0))
    return img.width(), img.height(), uniq


# ==================== chartwidgets 单元测试 ====================

def test_coastline_asset_is_found():
    """海岸线资源必须能被找到（sciencefig 的默认路径有 bug，这里走自己的定位）。"""
    from fysat.gui import chartwidgets as cw

    p = cw.find_coastline_path()
    assert p is not None and p.exists(), "找不到海岸线资源"
    segs = cw.coastline_segments()
    assert len(segs) > 50, f"海岸线段数异常：{len(segs)}"
    assert all(s.ndim == 2 and s.shape[1] >= 2 for s in segs)


def test_colorbar_and_lut_render(app):
    from fysat.gui import chartwidgets as cw

    bar = cw.ColorBarWidget()
    bar.set_range(180.0, 320.0, "turbo", label="CH24", unit="K")
    bar.resize(96, 320)
    # 色标条宽度是 setFixedWidth(96) 锁死的，不能强制 resize
    w, h, uniq = image_stats(bar, resize=False)
    assert w == 96 and h >= 120
    assert uniq > 20, f"色标条疑似空白（{uniq} 色）"

    grid = cw.LutGrid(cols=3)
    grid.resize(300, 220)
    _, _, uniq2 = image_stats(grid, resize=False)
    assert uniq2 > 30, f"LUT 网格疑似空白（{uniq2} 色）"


def test_lut_selection_emits():
    from fysat.gui import chartwidgets as cw

    grid = cw.LutGrid(cmaps=["gray", "turbo", "inferno"], cols=3)
    grid.resize(300, 120)
    got: list[str] = []
    grid.lutSelected.connect(got.append)
    # 直接走内部逻辑，避免依赖真实鼠标事件坐标
    grid.mousePressEvent(_fake_mouse_event(QtCore.QPoint(20, 12)))
    assert got, "点击 LUT 未发出 lutSelected"


def test_summarize_ignores_nan():
    from fysat.gui import chartwidgets as cw

    a = np.array([[1.0, 2.0], [np.nan, 4.0]], dtype=np.float32)
    st = cw.summarize(a)
    assert st.n_total == 4
    assert st.n_valid == 3
    assert st.vmin == pytest.approx(1.0)
    assert st.vmax == pytest.approx(4.0)
    assert st.mean == pytest.approx(7.0 / 3.0)
    assert st.valid_pct == pytest.approx(75.0)


def test_summarize_empty_and_all_nan():
    from fysat.gui import chartwidgets as cw

    empty = cw.summarize(np.zeros((0, 0), np.float32))
    assert empty.n_total == 0 and empty.n_valid == 0
    nan_only = cw.summarize(np.full((4, 4), np.nan, np.float32))
    assert nan_only.n_valid == 0


def test_histogram_and_profile_render(app):
    from fysat.gui import chartwidgets as cw

    hist = cw.HistogramWidget()
    hist.set_data(np.random.default_rng(0).normal(250, 20, 5000), bins=64,
                  vrange=(220, 280))
    hist.resize(360, 160)
    _, _, u1 = image_stats(hist)
    assert u1 > 10, f"直方图疑似空白（{u1} 色）"

    prof = cw.ProfileWidget()
    prof.set_profile(np.sin(np.linspace(0, 20, 800)) * 40 + 250)
    prof.resize(360, 160)
    _, _, u2 = image_stats(prof)
    assert u2 > 5, f"剖面疑似空白（{u2} 色）"


def test_stats_grid_render(app):
    from fysat.gui import chartwidgets as cw

    g = cw.StatsGrid()
    g.set_stat(cw.summarize(np.random.default_rng(1).normal(0, 1, 1000)))
    g.resize(300, 96)
    _, _, uniq = image_stats(g)
    assert uniq > 5


def test_panel_header_and_chips(app):
    from fysat.gui import chartwidgets as cw

    h = cw.PanelHeader("测试", "3")
    h.resize(240, 26)
    assert "测试" in h.lbl.text()
    h.set_badge("9")
    assert h.badge.text() == "9"

    row = cw.ChipRow(["a", "b", "c"], current="b")
    assert row.selected() == ["b"]
    got: list[str] = []
    row.chipClicked.connect(got.append)
    row._on_click("c")
    assert row.selected() == ["c"] and got == ["c"]


def test_geo_mapper_rejects_out_of_frame(app, ds):
    """境外经纬度必须映射成 NaN，不能被 KDTree 吸附到影像边缘。

    这是实际踩过的坑：不做粗筛时南极洲海岸线会被吸到图上画出一圈假线条。
    """
    from fysat.gui import chartwidgets as cw

    m = cw.GeoGridMapper(ds, (300, 400))
    assert m.available
    rows, cols = m.to_pixel(np.array([130.0]), np.array([20.0]))
    assert np.isfinite(rows[0]) and np.isfinite(cols[0])
    assert 0 <= rows[0] < 300 and 0 <= cols[0] < 400

    far_r, far_c = m.to_pixel(np.array([-60.0]), np.array([-70.0]))
    assert not np.isfinite(far_r[0]) and not np.isfinite(far_c[0])


def test_canvas_overlay_draws_on_canvas(app, ds):
    """叠加层必须真的画在画布上（这是 QGraphicsView 子控件的老坑）。"""
    from fysat.gui import chartwidgets as cw
    from fysat.gui.imageview import ImageCanvas

    canvas = ImageCanvas()
    canvas.resize(560, 420)
    canvas.show()
    canvas.set_array(np.full((300, 400, 3), 40, np.uint8))
    app.processEvents()

    ov = cw.CanvasOverlay(canvas)
    ov.set_dataset(ds, (300, 400))
    ov.set_show_coast(True)
    ov.set_show_grid(True)
    ov.raise_()
    app.processEvents()

    assert ov.isVisible()
    assert ov.geometry().width() > 100

    pix = ov.grab()
    img = pix.toImage()
    lit = sum(1 for y in range(0, img.height(), 2)
              for x in range(0, img.width(), 2)
              if img.pixelColor(x, y).value() > 25)
    assert lit > 20, f"叠加层没画出内容（亮点 {lit}）"
    canvas.close()


def _fake_mouse_event(pos: QtCore.QPoint) -> QtGui.QMouseEvent:
    return QtGui.QMouseEvent(
        QtCore.QEvent.MouseButtonPress, QtCore.QPointF(pos), QtCore.QPointF(pos),
        QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)


# ==================== 01 主界面 ====================

def test_mainwindow_has_four_screens(app):
    from fysat.gui.mainwindow import (
        SCREEN_ANALYSIS, SCREEN_DECODE, SCREEN_FIGURE, SCREEN_MAIN, MainWindow,
    )

    w = MainWindow()
    w.resize(1600, 1000)
    assert w.screen_stack.count() == 4
    assert w.screen_stack.widget(SCREEN_MAIN) is w.screen_main
    assert type(w.screen_stack.widget(SCREEN_ANALYSIS)).__name__ == "AnalysisWorkspace"
    assert type(w.screen_stack.widget(SCREEN_DECODE)).__name__ == "DecodeBench"
    assert type(w.screen_stack.widget(SCREEN_FIGURE)).__name__ == "FigureBench"
    w.close()


def test_mainwindow_switches_screens(app, ds):
    from fysat.gui.mainwindow import SCREEN_ANALYSIS, SCREEN_MAIN, MainWindow

    w = MainWindow()
    w.resize(1600, 1000)
    w._ds = ds
    w.goto_screen(SCREEN_ANALYSIS)
    assert w.screen_stack.currentIndex() == SCREEN_ANALYSIS
    # 窗口未 show() 时 isVisible() 恒为 False，所以用 isHidden() 判断显隐
    assert w._dock_right.isHidden()               # 工作台屏隐藏属性面板
    w.goto_screen(SCREEN_MAIN)
    assert w.screen_stack.currentIndex() == SCREEN_MAIN
    assert not w._dock_right.isHidden()
    w.close()


def test_datatree_three_levels(app, sample_path):
    """数据树必须是「目录 → 卫星/仪器 → 文件」三层，而不是只按容器分组。"""
    from fysat.gui.datatree import DataTree

    tree = DataTree()
    tree.add_source(Path(sample_path).parent)
    assert tree.file_count() > 0
    root_count = tree.tree.topLevelItemCount()
    assert root_count >= 1, "顶层应有数据源目录节点"

    top = tree.tree.topLevelItem(0)
    assert top.childCount() >= 1, "第二层应有卫星/仪器分组"
    group = top.child(0)
    assert group.childCount() >= 1, "第三层应有产品文件"
    assert group.text(0).strip(), "第二层节点应有卫星/仪器名"
    # 文件名节点带真实路径
    leaf = group.child(0)
    assert leaf.data(0, QtCore.Qt.UserRole + 1), "文件节点应带路径数据"
    tree.deleteLater()


def test_main_screenshot_not_blank(app, sample_path):
    """01 主界面真实加载 + 截图非空白。"""
    from fysat.gui.mainwindow import MainWindow

    w = MainWindow()
    w.resize(1600, 1000)
    w.show()
    w.load_file(sample_path)
    assert wait_until(app, lambda: w._ds is not None and w.canvas.array() is not None), \
        f"未能加载并渲染（状态：{w.lbl_status.text()}）"
    settle(app, 500)
    width, height, uniq = image_stats(w)
    assert width > 1200 and height > 700
    assert uniq > 200, f"主界面截图疑似空白（{uniq} 色）"
    OUT.mkdir(parents=True, exist_ok=True)
    assert w.grab().save(str(OUT / "01_main.png"))
    w.close()


# ==================== 02 分析工作台 ====================

def test_workspace_builds(app):
    from fysat.gui.workspace import AnalysisWorkspace

    w = AnalysisWorkspace()
    w.resize(1400, 900)
    assert len(w._panes) == 4
    for i, p in enumerate(w._panes):
        assert p.index == i
    assert w.lut_grid.current_cmap()
    w.close()


def test_workspace_renders_four_viewports(app, ds):
    """四视口都要出图，且统计量来自真实物理量（亮温应为几百 K 而不是 0.01 量级）。"""
    from fysat.gui.workspace import AnalysisWorkspace

    w = AnalysisWorkspace()
    w.resize(1500, 900)
    w.show()
    w.set_dataset(ds)
    ok = wait_until(
        app,
        lambda: all(p.array() is not None for p in w._panes[:3]),
        timeout_s=180.0)
    assert ok, "视口 A/B/C 未能全部渲染"

    for p in w._panes[:3]:
        arr = p.array()
        assert arr is not None and arr.ndim == 3 and arr.shape[2] == 3
        st = p.stat()
        assert st.n_valid > 0
        assert st.valid_pct > 50.0

    st = w._panes[0].stat()
    # 物理量为亮温时应在 100~400 K；若退回未定标 DN 会是 0~65535 或
    # 辐亮度 0.01~1.5，下面的区间能同时抓住这两种退化
    assert 100.0 < st.mean < 400.0, (
        f"统计均值 {st.mean:.4g} 不像亮温，定标链可能退化了")
    w.close()


def test_workspace_charts_filled(app, ds):
    """活动视口的统计/直方图/剖面要跟着更新。"""
    from fysat.gui.workspace import AnalysisWorkspace

    w = AnalysisWorkspace()
    w.resize(1400, 900)
    w.show()
    w.set_dataset(ds)
    assert wait_until(app, lambda: w._panes[0].array() is not None, timeout_s=180.0)
    settle(app, 400)

    assert w.hist._counts is not None and w.hist._counts.size > 0
    assert w.profile._y is not None and w.profile._y.size > 0
    assert w.stats_grid.stat().n_valid > 0

    _, _, uniq = image_stats(w)
    assert uniq > 300, f"分析工作台截图疑似空白（{uniq} 色）"
    OUT.mkdir(parents=True, exist_ok=True)
    assert w.grab().save(str(OUT / "02_workspace.png"))
    w.close()


def test_workspace_lut_switch_triggers_rerender(app, ds):
    from fysat.gui.workspace import AnalysisWorkspace

    w = AnalysisWorkspace()
    w.resize(1400, 900)
    w.show()
    w.set_dataset(ds)
    assert wait_until(app, lambda: w._panes[0].array() is not None, timeout_s=180.0)
    before = w._cmap
    other = "inferno" if before != "inferno" else "gray"
    w._on_lut(other)
    assert w._cmap == other
    assert wait_until(app, lambda: len(w._inflight) == 0, timeout_s=120.0)
    w.close()


# ==================== 03 解码工作台 ====================

def test_decode_bench_builds(app):
    from fysat.gui.decodebench import STEP_NAMES, DecodeBench

    assert len(STEP_NAMES) == 7
    w = DecodeBench()
    w.resize(1500, 900)
    assert w.is_idle()
    assert w.stepbar is not None
    assert w.tbl_fields.columnCount() == 8
    w.close()


def test_decode_bench_decodes_real_file(app, sample_path, ds):
    """真实文件走完七步：字段表填充、校验生成、日志有内容、截图非空白。"""
    from fysat.gui.decodebench import STEP_NAMES, DecodeBench

    w = DecodeBench()
    w.resize(1600, 940)
    w.show()
    w.add_files([sample_path])
    assert len(w._items) == 1
    w.run_queue()
    assert wait_until(app, lambda: w.is_idle(), timeout_s=240.0), "解码未结束"

    item = w._items[0]
    assert item.status == "done", f"解码失败：{item.error}"
    assert item.step == len(STEP_NAMES), f"只走到第 {item.step} 步"
    assert len(item.fields) == len(ds.variables)
    assert item.checks, "没有生成一致性校验"
    assert any(c[1] for c in item.checks), "所有校验都没通过"

    # 字段表的数值必须来自真实元数据
    assert w.tbl_fields.rowCount() == len(item.fields)
    assert w.tbl_fields.item(0, 0) is not None

    # 日志至少有这么几条：识别 / 完成
    assert w.log.blockCount() >= 2, f"日志只有 {w.log.blockCount()} 行"

    settle(app, 400)
    _, _, uniq = image_stats(w)
    assert uniq > 100, f"解码工作台截图疑似空白（{uniq} 色）"
    OUT.mkdir(parents=True, exist_ok=True)
    assert w.grab().save(str(OUT / "03_decode.png"))
    w.close()


def test_decode_bench_handles_bad_file(app, tmp_path):
    """坏文件必须被判 failed 并写日志，而不是让异常冒到主线程。"""
    from fysat.gui.decodebench import DecodeBench

    bad = Path(tmp_path) / "broken.HDF"
    bad.write_bytes(b"\x89HDF\r\n\x1a\n" + b"not really hdf5" * 10)

    w = DecodeBench()
    w.resize(1200, 800)
    w.add_files([str(bad)])
    w.run_queue()
    assert wait_until(app, lambda: w.is_idle(), timeout_s=120.0)
    assert w._items[0].status == "failed"
    assert w._items[0].error
    w.close()


def test_decode_bench_dedups_queue(app, sample_path):
    from fysat.gui.decodebench import DecodeBench

    w = DecodeBench()
    w.resize(1200, 800)
    w.add_files([sample_path, sample_path])
    assert len(w._items) == 1, "重复文件不应重复入队"
    w.close()


# ==================== 04 制图工作台 ====================

def test_figure_bench_builds(app):
    from fysat.gui.figurebench import TEMPLATES, FigureBench

    assert len(TEMPLATES) >= 4
    w = FigureBench()
    w.resize(1500, 900)
    assert w.tplbar is not None
    assert not w.preview_ready()
    w.close()


def test_figure_bench_makes_real_figure(app, ds):
    """实时预览要产出真正的科学图（白底 + 大量颜色），不是占位文字。"""
    from fysat.gui.figurebench import FigureBench

    w = FigureBench()
    w.resize(1600, 940)
    w.show()
    w.set_dataset(ds)
    ok = wait_until(app, lambda: w.preview_ready(), timeout_s=240.0)
    assert ok, "制图预览未生成"
    settle(app, 500)

    preview = w._preview_path
    assert preview is not None and preview.exists()
    img = QtGui.QImage(str(preview))
    assert not img.isNull() and img.width() > 300

    # 白底科学图：应有相当比例接近白色的像素
    from PySide6 import QtGui as _q

    im2 = _q.QImage(str(preview)).convertToFormat(_q.QImage.Format_RGB32)
    buf = im2.constBits()
    a = np.frombuffer(buf, dtype=np.uint8).reshape(
        im2.height(), im2.bytesPerLine())[:, : im2.width() * 4]
    a = a.reshape(im2.height(), im2.width(), 4)[:, :, :3]
    white = float((a.min(axis=2) > 235).mean())
    uniq = len(np.unique(a.reshape(-1, 3), axis=0))
    assert white > 0.05, f"科学图白底比例过低（{white:.3f}）"
    assert uniq > 2000, f"科学图颜色太少（{uniq}），可能是空图"

    OUT.mkdir(parents=True, exist_ok=True)
    assert w.grab().save(str(OUT / "04_figure.png"))
    w.close()


def test_figure_spec_passes_coastline_path(app, ds):
    """回归：sciencefig 默认路径找不到海岸线资源，必须显式传入。

    这条断言锁住那个既有 bug 的规避方案，防止以后有人删掉 coastline_path。
    """
    from fysat.gui import chartwidgets as cw
    from fysat.gui.figurebench import FigureBench

    w = FigureBench()
    w._ds = ds
    spec = w._build_spec(Path("x.png"), preview=True)
    assert spec.coastline_path is not None
    assert Path(spec.coastline_path).exists()
    assert Path(spec.coastline_path) == cw.find_coastline_path()
    w.close()


def test_figure_template_switch(app, ds):
    from fysat.gui.figurebench import TEMPLATES, FigureBench

    w = FigureBench()
    w.resize(1400, 900)
    w.show()
    w.set_dataset(ds)
    assert wait_until(app, lambda: w.preview_ready(), timeout_s=240.0)
    single = next(t[0] for t in TEMPLATES if t[2] == "single")
    w._on_template(single)
    assert w._template == single
    assert wait_until(app, lambda: not w._busy, timeout_s=240.0)
    w.close()


# ==================== 平台与资源卫生 ====================

def test_no_gpl_qt_modules_from_new_screens(app):
    """新增的四屏不得引入 GPL-only 的 Qt 模块。"""
    import sys

    for m in ("QtCharts", "QtDataVisualization", "QtVirtualKeyboard",
              "QtQuick3D", "QtMultimediaWidgets"):
        assert f"PySide6.{m}" not in sys.modules, f"引入了 GPL-only 模块 {m}"
    bad = [m for m in sys.modules if m.startswith(("PyQt5", "PyQt6"))]
    assert not bad, f"检测到 GPL 的 PyQt: {bad}"


def test_all_new_modules_import_cleanly():
    """五个新模块都要能独立 import（不依赖主窗口初始化顺序）。"""
    import importlib

    for name in ("chartwidgets", "workspace", "decodebench",
                 "figurebench", "datatree"):
        mod = importlib.import_module(f"fysat.gui.{name}")
        assert mod is not None
