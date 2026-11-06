"""GUI 测试：在 offscreen 模式下验证界面能构建、能加载、能截图。

这些测试不需要显示器，CI 里也能跑：
    set QT_QPA_PLATFORM=offscreen
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from _sample_root import glob_samples

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6 import QtWidgets  # noqa: E402

from fysat.gui import ALLOWED_QT_MODULES, theme  # noqa: E402
from fysat.gui.imageview import ndarray_to_qimage  # noqa: E402
from fysat.gui.mainwindow import ExportDialog, MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    inst = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply_theme(inst)
    yield inst


@pytest.fixture
def win(app):
    w = MainWindow()
    w.resize(1600, 1000)
    yield w
    w.close()


# ---------------- 许可证相关 ----------------

def test_no_gpl_qt_modules_imported():
    """确认没有引入 GPL-only 的 Qt 模块（会导致整个软件被 GPL 传染）。"""
    import sys

    gpl_modules = ["QtCharts", "QtDataVisualization", "QtVirtualKeyboard",
                   "QtQuick3D", "QtMultimediaWidgets"]
    for m in gpl_modules:
        full = f"PySide6.{m}"
        assert full not in sys.modules, f"引入了 GPL-only 模块 {full}"


def test_no_pyqt():
    """PyQt 是 GPL，与本项目的 LGPL 方案不兼容，绝不能出现。"""
    import sys

    bad = [m for m in sys.modules if m.startswith(("PyQt5", "PyQt6"))]
    assert not bad, f"检测到 GPL 的 PyQt: {bad}"


def test_allowed_modules_whitelist():
    assert "QtWidgets" in ALLOWED_QT_MODULES
    assert "QtCharts" not in ALLOWED_QT_MODULES


# ---------------- 界面构建 ----------------

def test_mainwindow_builds(win):
    assert "FY-Sat Studio" in win.windowTitle()
    assert win.canvas is not None
    assert win.explorer is not None
    assert win.inspector is not None
    # 属性 / 变量 / 显示 / 辅助\n    assert win.inspector.tabs.count() == 4


def test_statusbar_labels_exist(win):
    """状态栏标签必须在信号连接前建好，否则 _on_zoom 会 AttributeError。"""
    assert win.lbl_zoom is not None
    assert win.lbl_pixel is not None
    win._on_zoom(123.4)
    assert "123" in win.lbl_zoom.text()


def test_export_dialog_has_exactly_three_kinds(win):
    dlg = ExportDialog(win, "Data/NOMChannel02")
    assert set(dlg.radios) == {"tiff", "png_full", "png_compressed"}
    assert dlg.kind() == "png_full"          # 默认全画质
    dlg.radios["png_compressed"].setChecked(True)
    assert dlg.level.isEnabled()
    dlg.radios["tiff"].setChecked(True)
    assert not dlg.level.isEnabled()          # TIFF 不显示压缩强度
    dlg.close()


# ---------------- 图像转换 ----------------

def test_ndarray_to_qimage_rgb():
    import numpy as np

    a = np.zeros((10, 20, 3), np.uint8)
    img = ndarray_to_qimage(a)
    assert img.width() == 20 and img.height() == 10


def test_ndarray_to_qimage_uint16():
    import numpy as np

    a = (np.random.rand(8, 8) * 65535).astype(np.uint16)
    img = ndarray_to_qimage(a)
    assert img.width() == 8 and img.height() == 8


def test_ndarray_to_qimage_float_fallback():
    import numpy as np

    a = np.random.rand(6, 6).astype(np.float32) * 300
    img = ndarray_to_qimage(a)          # 浮点应安全降级成灰度
    assert not img.isNull()


# ---------------- 真实文件加载 ----------------

@pytest.fixture(scope="module")
def real_file():

    hits = glob_samples(r"FY3F_MERSI_GRAN_L1_*.HDF")
    if not hits:
        pytest.skip("缺真实样本")
    return hits[0]


def _wait_until(app, predicate, timeout_s: float = 60.0) -> bool:
    """跑事件循环直到 predicate 为真（后台线程的结果靠事件循环投递）。"""
    import time

    from PySide6 import QtCore

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 100)
        if predicate():
            return True
        QtCore.QThread.msleep(20)
    return predicate()


def test_load_real_file(win, app, real_file):
    """端到端：打开真实产品 → 属性面板填充 → 自动渲染第一个变量。"""
    win.load_file(real_file)
    ok = _wait_until(app, lambda: win._ds is not None and win.canvas.array() is not None)
    assert ok, f"未能加载数据集（状态: {win.lbl_status.text()}）"
    assert win.inspector.info_table.rowCount() > 0
    assert win.inspector.var_table.rowCount() > 0


def test_screenshot(win, app, real_file, tmp_path):
    """离屏截图，确认界面真的画出来了（不是空白）。"""
    win.load_file(real_file)
    _wait_until(app, lambda: win.canvas.array() is not None)
    win.resize(1600, 1000)
    app.processEvents()

    pix = win.grab()
    assert not pix.isNull()
    out = Path(tmp_path) / "gui.png"
    assert pix.save(str(out))

    from PySide6 import QtGui

    img = QtGui.QImage(str(out))
    assert img.width() > 800 and img.height() > 500

    # 不是纯色空白：统计像素种类
    colors = set()
    for y in range(0, img.height(), 40):
        for x in range(0, img.width(), 40):
            colors.add(img.pixel(x, y))
    assert len(colors) > 10, f"截图疑似空白，只有 {len(colors)} 种颜色"
