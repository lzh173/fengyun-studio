"""主窗口：左边数据源、中间画布、右边属性，底部状态栏。

所有耗时操作（打开文件、渲染）都走线程池，UI 不阻塞。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .. import __version__
from ..export import KINDS, ExportOptions, export
from ..readers import open_file
from ..render import Stretch
from . import theme
from .explorer import Explorer
from .imageview import ImageCanvas
from .inspector import Inspector
from .workers import Worker, render_rgb, render_variable


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"FY-Sat Studio {__version__} — 风云卫星解码分析平台")
        self.resize(1600, 1000)

        self._pool = QtCore.QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(max(2, QtCore.QThread.idealThreadCount() - 2))
        self._ds = None
        self._current_var: str | None = None
        self._jobs: list[Worker] = []          # 持有引用，否则 QRunnable 会被回收

        self._build_actions()
        self._build_ui()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        # 状态栏最后建好，此时才能接画布信号：
        # 早于状态栏控件连接到槽会在 _emit_zoom 时抛 AttributeError
        self.canvas.pixelHovered.connect(self._on_pixel)
        self.canvas.zoomChanged.connect(self._on_zoom)
        self.canvas.rectSelected.connect(self._on_rect)

    # ================= 构建 =================
    def _build_actions(self) -> None:
        self.act_open = QtGui.QAction("打开产品", self)
        self.act_open.setShortcut("Ctrl+O")
        self.act_open.triggered.connect(self.open_file_dialog)

        self.act_opendir = QtGui.QAction("打开目录", self)
        self.act_opendir.setShortcut("Ctrl+Shift+O")
        self.act_opendir.triggered.connect(lambda: self.explorer._choose_dir())

        self.act_export = QtGui.QAction("导出…", self)
        self.act_export.setShortcut("Ctrl+E")
        self.act_export.triggered.connect(self.export_dialog)

        self.act_fit = QtGui.QAction("适应窗口", self)
        self.act_fit.setShortcut("F")
        self.act_fit.triggered.connect(lambda: self.canvas.fit_to_window())

        self.act_actual = QtGui.QAction("1:1", self)
        self.act_actual.setShortcut("1")
        self.act_actual.triggered.connect(lambda: self.canvas.zoom_actual())

        self.act_zoom_in = QtGui.QAction("放大", self)
        self.act_zoom_in.triggered.connect(lambda: self.canvas.scale(1.25, 1.25))

        self.act_zoom_out = QtGui.QAction("缩小", self)
        self.act_zoom_out.triggered.connect(lambda: self.canvas.scale(1 / 1.25, 1 / 1.25))

        self.act_select = QtGui.QAction("框选", self)
        self.act_select.setCheckable(True)
        self.act_select.triggered.connect(self._toggle_select)

        self.act_quit = QtGui.QAction("退出", self)
        self.act_quit.setShortcut("Ctrl+Q")
        self.act_quit.triggered.connect(self.close)

        self.act_about = QtGui.QAction("关于 / 许可证", self)
        self.act_about.triggered.connect(self.show_about)

    def _build_ui(self) -> None:
        self.explorer = Explorer()
        self.canvas = ImageCanvas()
        self.inspector = Inspector()

        self.explorer.fileActivated.connect(self.load_file)

        dock_left = QtWidgets.QDockWidget("数据源", self)
        dock_left.setWidget(self.explorer)
        dock_left.setMinimumWidth(320)
        dock_left.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable
                              | QtWidgets.QDockWidget.DockWidgetFloatable)

        dock_right = QtWidgets.QDockWidget("属性", self)
        dock_right.setWidget(self.inspector)
        dock_right.setMinimumWidth(340)
        dock_right.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable
                               | QtWidgets.QDockWidget.DockWidgetFloatable)

        self.setCentralWidget(self.canvas)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock_left)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock_right)

        self.inspector.variableSelected.connect(self.display_variable)
        self.inspector.displayChanged.connect(self._on_display_changed)
        self.inspector.rgbRequested.connect(self.display_rgb)

        # 初始欢迎页
        self._show_placeholder()

    def _build_menu(self) -> None:
        mb = self.menuBar()
        m_file = mb.addMenu("文件")
        m_file.addAction(self.act_open)
        m_file.addAction(self.act_opendir)
        m_file.addSeparator()
        m_file.addAction(self.act_export)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)

        m_view = mb.addMenu("视图")
        m_view.addAction(self.act_fit)
        m_view.addAction(self.act_actual)
        m_view.addAction(self.act_zoom_in)
        m_view.addAction(self.act_zoom_out)
        m_view.addSeparator()
        m_view.addAction(self.act_select)

        m_help = mb.addMenu("帮助")
        m_help.addAction(self.act_about)

    def _build_toolbar(self) -> None:
        tb = QtWidgets.QToolBar("主工具栏")
        tb.setMovable(False)
        tb.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        tb.addAction(self.act_open)
        tb.addAction(self.act_opendir)
        tb.addSeparator()
        tb.addAction(self.act_fit)
        tb.addAction(self.act_actual)
        tb.addAction(self.act_zoom_in)
        tb.addAction(self.act_zoom_out)
        tb.addSeparator()
        tb.addAction(self.act_select)
        tb.addSeparator()
        tb.addAction(self.act_export)
        self.addToolBar(tb)

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.lbl_status = QtWidgets.QLabel("就绪")
        self.lbl_pixel = QtWidgets.QLabel("—")
        self.lbl_zoom = QtWidgets.QLabel("—")
        self.lbl_range = QtWidgets.QLabel("")
        sb.addWidget(self.lbl_status, 1)
        sb.addPermanentWidget(self.lbl_range)
        sb.addPermanentWidget(self.lbl_pixel)
        sb.addPermanentWidget(self.lbl_zoom)

    # ================= 占位 =================
    def _show_placeholder(self) -> None:
        img = np.zeros((600, 800, 3), dtype=np.uint8)
        img[:, :] = (12, 14, 18)
        self.canvas.set_array(img)

    # ---------- 后台任务 ----------
    def _submit(self, worker: Worker, on_ok, on_fail=None) -> None:
        """提交后台任务并保持引用，直到它结束。

        QRunnable 若不被 Python 侧持有引用，可能在跑到一半被 GC，
        表现为"任务提交了但永远不完成"。
        """
        self._jobs.append(worker)

        def _done(result):
            try:
                on_ok(result)
            finally:
                self._forget(worker)

        def _failed(msg):
            try:
                (on_fail or self._on_error)(msg)
            finally:
                self._forget(worker)

        worker.signals.finished.connect(_done)
        worker.signals.failed.connect(_failed)
        self._pool.start(worker)

    def _forget(self, worker: Worker) -> None:
        try:
            self._jobs.remove(worker)
        except ValueError:
            pass

    def closeEvent(self, ev) -> None:
        """关闭前等未完成任务收尾。

        否则窗口销毁后后台线程仍在 emit，会报
        "Signal source has been deleted"。
        """
        for w in list(self._jobs):
            self._pool.tryTake(w)      # 还没开始的直接摘出来，不跑了
        self._pool.waitForDone(3000)   # 正在跑的给它 3 秒收尾
        self._jobs.clear()
        super().closeEvent(ev)

    # ================= 打开 =================
    def open_file_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "打开卫星产品", "",
            "卫星产品 (*.hdf *.HDF *.h5 *.H5 *.nc *.NC *.dat *.DAT *.l1b *.L1B *.awx *.AWX);;全部 (*.*)")
        if path:
            self.load_file(path)

    def load_file(self, path: str) -> None:
        self.lbl_status.setText(f"正在打开 {Path(path).name} …")
        self.setCursor(QtCore.Qt.WaitCursor)

        def work():
            ds = open_file(path, load=False)
            return ds

        self._submit(Worker(work), lambda ds: self._on_loaded(ds, path))

    def _on_loaded(self, ds, path: str) -> None:
        self.unsetCursor()
        self._ds = ds
        self.inspector.set_dataset(ds)
        name = Path(path).name
        self.lbl_status.setText(
            f"{ds.platform} {ds.instrument} {ds.level} · {len(ds.variables)} 变量 · {name}")
        b = ds.geolocation.bounds()
        if b:
            self.lbl_range.setText(f"经度 {b[0]:.2f}~{b[1]:.2f}  纬度 {b[2]:.2f}~{b[3]:.2f}")
        else:
            self.lbl_range.setText(ds.geolocation.kind)

        # 自动显示第一个二维变量
        for v in ds.variables.values():
            if len(v.shape) == 2:
                self.display_variable(v.name)
                break

    # ================= 显示 =================
    def display_variable(self, name: str) -> None:
        if self._ds is None:
            return
        self._current_var = name
        var = self._ds.variables[name]
        params = self.inspector.display_params()
        self.lbl_status.setText(f"渲染 {name} {tuple(var.shape)} …")
        self.setCursor(QtCore.Qt.WaitCursor)

        st = Stretch(method="percentile", pct=params["stretch"], gamma=params["gamma"])

        def work():
            v = self._ds.load(name)
            return render_variable(v, cmap=params["cmap"], st=st)

        self._submit(Worker(work), self._on_rendered)

    def display_rgb(self, names: tuple[str, str, str]) -> None:
        if self._ds is None:
            return
        params = self.inspector.display_params()
        self.lbl_status.setText(f"合成 RGB {names} …")
        self.setCursor(QtCore.Qt.WaitCursor)

        st = Stretch(method="percentile", pct=(1.0, 99.0), gamma=params["gamma"])

        def work():
            return render_rgb(self._ds.load, names, st=st)

        self._submit(Worker(work), self._on_rendered)

    def _on_rendered(self, arr) -> None:
        self.unsetCursor()
        if arr is None:
            return
        self.canvas.set_array(arr)
        self.lbl_status.setText("渲染完成")

    def _on_display_changed(self, _params: dict) -> None:
        if self._current_var:
            self.display_variable(self._current_var)

    def _on_error(self, msg: str) -> None:
        self.unsetCursor()
        self.lbl_status.setText("出错")
        QtWidgets.QMessageBox.critical(self, "错误", msg.splitlines()[0] if msg else "未知错误")

    # ================= 交互 =================
    def _on_pixel(self, r: int, c: int, v: float) -> None:
        self.lbl_pixel.setText(f"({r}, {c}) = {v:.4g}")

    def _on_zoom(self, pct: float) -> None:
        self.lbl_zoom.setText(f"{pct:.0f}%")

    def _on_rect(self, rect: QtCore.QRect) -> None:
        self.lbl_status.setText(f"已框选 {rect.width()} × {rect.height()} 像素")

    def _toggle_select(self, checked: bool) -> None:
        self.canvas.set_select_mode(checked)
        self.lbl_status.setText("框选模式：拖拽选择区域，Esc 退出" if checked else "就绪")

    # ================= 导出 =================
    def export_dialog(self) -> None:
        if self._ds is None or self._current_var is None:
            QtWidgets.QMessageBox.information(self, "提示", "请先打开产品并选择变量")
            return

        dlg = ExportDialog(self, self._current_var)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        opts = dlg.options()
        path = opts.path
        name = self._current_var
        ds = self._ds

        self.lbl_status.setText(f"导出 {Path(path).name} …")
        self.setCursor(QtCore.Qt.WaitCursor)

        def work():
            var = ds.load(name)
            from ..provenance import build_provenance
            from ..render import display_array

            opts.provenance = build_provenance(ds, variable=name, extra={"format": opts.kind})
            if opts.kind == "tiff":
                data = var.data                     # 保留原始位深/DN
            else:
                data = display_array(var, physical=True)
            return export(data, opts)

        self._submit(Worker(work), self._on_exported)

    def _on_exported(self, out: Path) -> None:
        self.unsetCursor()
        size = out.stat().st_size / 1e6
        self.lbl_status.setText(f"已导出 {out.name} ({size:.2f} MB)")

    # ================= 关于 =================
    def show_about(self) -> None:
        from ..gui import ALLOWED_QT_MODULES

        QtWidgets.QMessageBox.about(
            self, "关于 FY-Sat Studio",
            f"<h3>FY-Sat Studio {__version__}</h3>"
            "<p>风云卫星官方数据解码 · 分析 · 制图</p>"
            "<p><b>许可证</b><br>"
            "本程序使用 PySide6（Qt for Python），按其 LGPLv3 条款动态链接使用。<br>"
            "Qt 版权归 The Qt Company 所有。详细声明见随包 THIRD_PARTY_NOTICES.md。</p>"
            f"<p><b>允许使用的 Qt 模块</b><br>{', '.join(sorted(ALLOWED_QT_MODULES))}</p>"
            "<p>本程序不包含任何 GPL-only 的 Qt 模块。</p>",
        )


class ExportDialog(QtWidgets.QDialog):
    """导出对话框：只提供三种形式。"""

    def __init__(self, parent=None, var_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"导出 — {var_name}")
        self.setMinimumWidth(460)
        self._var_name = var_name

        lay = QtWidgets.QVBoxLayout(self)

        g_kind = QtWidgets.QGroupBox("导出形式")
        v = QtWidgets.QVBoxLayout(g_kind)
        self.radios: dict[str, QtWidgets.QRadioButton] = {}
        for key, meta in KINDS.items():
            rb = QtWidgets.QRadioButton(f"{meta['label']}")
            rb.setToolTip(meta["desc"])
            self.radios[key] = rb
            v.addWidget(rb)
        self.radios["png_full"].setChecked(True)
        self.radios["png_compressed"].toggled.connect(self._sync_enabled)
        lay.addWidget(g_kind)

        g_png = QtWidgets.QGroupBox("PNG 压缩设置（仅“压缩强度可调”生效）")
        f = QtWidgets.QFormLayout(g_png)
        self.level = QtWidgets.QSpinBox()
        self.level.setRange(0, 9)
        self.level.setValue(6)
        self.level.setToolTip("0=最快最大，9=最慢最小；PNG 无损，不影响画质")
        f.addRow("压缩强度", self.level)

        self.scale = QtWidgets.QDoubleSpinBox()
        self.scale.setRange(0.05, 1.0)
        self.scale.setSingleStep(0.05)
        self.scale.setValue(1.0)
        self.scale.setToolTip("1.0 = 原始分辨率；小于 1 会缩放（仅此形式支持）")
        f.addRow("缩放比例", self.scale)
        lay.addWidget(g_png)

        g_out = QtWidgets.QGroupBox("输出")
        f2 = QtWidgets.QFormLayout(g_out)
        row = QtWidgets.QHBoxLayout()
        self.path_edit = QtWidgets.QLineEdit()
        btn = QtWidgets.QPushButton("浏览…")
        btn.clicked.connect(self._choose_path)
        row.addWidget(self.path_edit, 1)
        row.addWidget(btn)
        f2.addRow("文件", row)
        lay.addWidget(g_out)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        self._sync_enabled()

    def _sync_enabled(self) -> None:
        on = self.radios["png_compressed"].isChecked()
        self.level.setEnabled(on)
        self.scale.setEnabled(on)

    def _choose_path(self) -> None:
        kind = self.kind()
        ext = KINDS[kind]["ext"]
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "保存为", f"{self._var_name.replace('/', '_')}{ext}",
            f"{KINDS[kind]['label']} (*{ext})")
        if path:
            self.path_edit.setText(path)

    def kind(self) -> str:
        for k, rb in self.radios.items():
            if rb.isChecked():
                return k
        return "png_full"

    def options(self) -> ExportOptions:
        p = self.path_edit.text().strip()
        if not p:
            p = f"{self._var_name.replace('/', '_')}"
        return ExportOptions(
            kind=self.kind(),
            path=p,
            compress_level=self.level.value(),
            scale=self.scale.value(),
        )
