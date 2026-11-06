"""科学制图对话框的通道选择 + 制图工作台布局的回归测试。

对应两个用户实报缺陷：
1. 「导出科学制图」页的通道选择有问题：
   可见光 R/G/B 只列数据集、不能选通道，而且渲染时把通道号写死成
   ``visible_bands=(0, 1, 2)`` —— 等于 R 拿 b1(0.47µm，蓝端)、
   B 拿 b3(0.65µm，红端)，红蓝装反。
2. 「制图工作台」找不到导出按钮：
   三栏固定宽度合计恰等于窗口宽度，窗口略窄或有 DPI 缩放时右栏被挤出屏幕。
"""
from __future__ import annotations

import os

import pytest
from _sample_root import glob_samples

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets  # noqa: E402


def fb_width(window) -> int:
    return window.figurebench.width()


def _sample():
    hits = [h for h in glob_samples(r"FY3D_MERSI_GBAL_L1_*1000M_MS.HDF")
            if os.path.getsize(h) > 10_000_000]
    return hits[0] if hits else None


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(scope="module")
def window(app):
    from fysat.gui import theme
    from fysat.gui.mainwindow import MainWindow

    theme.apply_theme(app)
    w = MainWindow()
    w.resize(1600, 1000)
    w.show()          # 不 show 的话子控件不会布局，几何全是默认值
    f = _sample()
    if f is None:
        pytest.skip("缺 FY-3D MERSI 样本")
    w.load_file(f)
    import time
    t0 = time.time()
    while time.time() - t0 < 40:
        app.processEvents()
        arr = w.canvas.array()
        if w._ds is not None and arr is not None and tuple(arr.shape[:2]) != (600, 800):
            break
        QtWidgets.QApplication.processEvents()
    yield w
    w.close()


# ---------------- 1. 制图对话框的通道 ----------------

def test_dialog_defaults_to_true_color_bands(window):
    """默认必须是 b3/b2/b1（0.65/0.55/0.47µm），不能是 (0,1,2)。"""
    from fysat.gui.figdialog import ScienceFigureDialog

    dlg = ScienceFigureDialog(window, ds=window._ds, region_px=None)
    try:
        assert dlg._bands_from_ui() == (2, 1, 0), (
            f"可见光通道应为 (2,1,0)=b3/b2/b1，实际 {dlg._bands_from_ui()}")
        # 三个下拉都要指向可见光反射数据集
        for combo in (dlg.cmb_vis_r, dlg.cmb_vis_g, dlg.cmb_vis_b):
            assert "RefSB" in str(combo.currentData()), combo.currentData()
    finally:
        dlg.close()


def test_dialog_band_combo_has_labels_with_wavelength(window):
    """通道下拉要显示 b 号与波长，而不是空或纯数字。"""
    from fysat.gui.figdialog import ScienceFigureDialog

    dlg = ScienceFigureDialog(window, ds=window._ds, region_px=None)
    try:
        items = [dlg.cmb_vis_r_band.itemText(i)
                 for i in range(dlg.cmb_vis_r_band.count())]
        assert items, "可见光 R 的通道下拉是空的"
        assert any("b" in s for s in items), items
        assert any("µm" in s for s in items), items
        # 默认应停在 b3
        assert "b3" in dlg.cmb_vis_r_band.currentText(), dlg.cmb_vis_r_band.currentText()
    finally:
        dlg.close()


def test_dialog_thermal_channel_is_window_band(window):
    """红外默认应是 10.7µm 窗区（MERSI 是 b24）。"""
    from fysat.gui.figdialog import ScienceFigureDialog

    dlg = ScienceFigureDialog(window, ds=window._ds, region_px=None)
    try:
        txt = dlg.cmb_thermal_band.currentText()
        assert "b24" in txt, f"红外默认通道应为 b24(10.7µm)，实际 {txt}"
    finally:
        dlg.close()


def test_changing_dialog_band_changes_output(window, tmp_path):
    """改通道必须真的改变成图，而不是只改 UI。"""
    from fysat.gui.figdialog import ScienceFigureDialog

    dlg = ScienceFigureDialog(window, ds=window._ds, region_px=None)
    try:
        a = dlg._render(tmp_path / "a.png")
        dlg.cmb_vis_r_band.setCurrentIndex(0)      # R 换成 b1
        b = dlg._render(tmp_path / "b.png")
        assert a.exists() and b.exists()
        assert a.stat().st_size != b.stat().st_size or a.read_bytes() != b.read_bytes(), \
            "换了可见光 R 通道，输出却完全相同"
    finally:
        dlg.close()


# ---------------- 2. 制图工作台的布局与导出入口 ----------------

@pytest.mark.parametrize("width", [1920, 1600, 1366])
def test_figure_bench_right_panel_stays_visible(window, width):
    """右栏（含导出按钮）在任何常见窗口宽度下都不能被挤出去。"""
    window.screen_stack.setCurrentIndex(3)
    window.figurebench.set_dataset(window._ds, None)
    window.resize(width, 900)
    window.show()
    for _ in range(30):
        QtWidgets.QApplication.processEvents()
    assert fb_width(window) > 300, "工作台没有完成布局"

    fb = window.figurebench
    kids = [c for c in fb.children() if isinstance(c, QtWidgets.QWidget)]
    assert len(kids) >= 3, "制图工作台应有三栏"
    right = kids[2]
    assert right.width() >= 280, f"右栏只有 {right.width()}px，导出按钮会被裁掉"

    btn = fb.btn_export
    pos = btn.mapTo(fb, btn.rect().topLeft())
    assert pos.x() + btn.width() <= fb.width() + 2, \
        f"导出按钮右边缘 {pos.x() + btn.width()} 超出工作台宽度 {fb.width()}"


def test_main_window_has_always_reachable_figure_export(window):
    """除了右栏按钮，还要有一个不依赖布局的导出入口。"""
    assert hasattr(window, "act_figure_export"), "缺少全局「导出制图」动作"
    assert hasattr(window, "export_figure_bench"), "缺少对应槽函数"
    assert window.act_figure_export.shortcut().toString() != "", "应带快捷键"


def test_export_figure_bench_uses_export_to_when_available(window, tmp_path, monkeypatch):
    """全局入口应能真正出图（不弹对话框）。"""
    fb = window.figurebench
    window.screen_stack.setCurrentIndex(3)
    fb.set_dataset(window._ds, None)
    for _ in range(3):
        QtWidgets.QApplication.processEvents()

    if not hasattr(fb, "export_to"):
        pytest.skip("当前 FigureBench 不支持 export_to")
    out = tmp_path / "bench.png"
    fb.export_to(out)
    assert out.exists() and out.stat().st_size > 5000
