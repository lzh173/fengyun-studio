"""主窗口：左边数据源、中间画布、右边属性，底部状态栏。

四屏结构
--------
1. **主界面**（本文件）：数据源树 → 画布 → 属性/变量/显示/辅助
2. **分析工作台** ``workspace.AnalysisWorkspace``：2×2 四视口联动 + LUT + 统计
3. **解码工作台** ``decodebench.DecodeBench``：输入队列 + 七步流水线 + 字段表
4. **制图工作台** ``figurebench.FigureBench``：图层树 + 实时预览 + 导出

后三屏放在 ``QStackedWidget`` 里，与主界面共用一个窗口，通过左侧
「工作台」切换条 / 菜单 / 工具栏切换。这样既保持了单窗口体验，
又避免四个独立 MainWindow 之间同步数据集的麻烦。

所有耗时操作（打开文件、渲染）都走线程池，UI 不阻塞。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .. import __version__
from ..export import KINDS, ExportOptions, export
from ..readers import open_file
from ..render import Stretch
from . import chartwidgets as cw
from . import theme
from .explorer import Explorer
from .imageview import ImageCanvas
from .inspector import Inspector
from .workers import Worker, render_rgb, render_variable

# 工作台索引（与 _build_screens 里的添加顺序一致）
SCREEN_MAIN = 0
SCREEN_ANALYSIS = 1
SCREEN_DECODE = 2
SCREEN_FIGURE = 3


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"FY-Sat Studio {__version__} — 风云卫星解码分析平台")
        self.resize(1600, 1000)

        self._pool = QtCore.QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(max(2, QtCore.QThread.idealThreadCount() - 2))
        self._ds = None
        self._current_var: str | None = None
        self._current_band: int = 0
        self._selection: tuple[int, int, int, int] | None = None
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
        self._load_last_source()

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

        self.act_science = QtGui.QAction("导出科学制图…", self)
        self.act_science.setShortcut("Ctrl+Shift+E")
        self.act_science.triggered.connect(self.science_figure_dialog)

        self.act_analysis = QtGui.QAction("分析工作台", self)
        self.act_analysis.setShortcut("Ctrl+2")
        self.act_analysis.triggered.connect(self.open_analysis_bench)

        self.act_decode = QtGui.QAction("解码工作台", self)
        self.act_decode.setShortcut("Ctrl+3")
        self.act_decode.triggered.connect(self.open_decode_bench)

        self.act_figure = QtGui.QAction("制图工作台", self)
        self.act_figure.setShortcut("Ctrl+4")
        self.act_figure.triggered.connect(self.open_figure_bench)

        # 制图工作台的导出入口。它的"导出…"按钮在右栏最底部，
        # 窗口较窄或系统有 DPI 缩放时右栏会被挤出可视区，
        # 用户就"找不到导出按钮"。这里再给一个永远可达的入口。
        self.act_figure_export = QtGui.QAction("导出制图…", self)
        self.act_figure_export.setShortcut("Ctrl+Shift+S")
        self.act_figure_export.triggered.connect(self.export_figure_bench)

        self.act_main_screen = QtGui.QAction("主界面", self)
        self.act_main_screen.setShortcut("Ctrl+1")
        self.act_main_screen.triggered.connect(lambda: self.goto_screen(SCREEN_MAIN))

        self.act_coast = QtGui.QAction("海岸线叠加", self)
        self.act_coast.setCheckable(True)
        self.act_coast.setChecked(True)
        self.act_coast.triggered.connect(lambda on: self.toggle_overlay("coast", on))

        self.act_graticule = QtGui.QAction("经纬网叠加", self)
        self.act_graticule.setCheckable(True)
        self.act_graticule.setChecked(True)
        self.act_graticule.triggered.connect(
            lambda on: self.toggle_overlay("grid", on))

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

        # ---- 左侧：工作台切换条 + 三层数据树 ----
        self.datatree = None
        left = QtWidgets.QWidget()
        ll = QtWidgets.QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)

        self._nav = self._build_nav()
        ll.addWidget(self._nav)

        # 数据源：新的三层数据树（目录 → 卫星/仪器 → 文件）。
        # 旧的 explorer 只保留**对象**（act_opendir 与既有测试仍要用到它），
        # 不再放进布局：它和 DataTree 各带一套"打开目录/刷新/过滤"，
        # 上下叠在一起会显示成两块重复的"数据源"面板。
        try:
            from .datatree import DataTree

            self.datatree = DataTree()
            self.datatree.fileActivated.connect(self.load_file)
            ll.addWidget(self.datatree, 1)
        except Exception:                       # noqa: BLE001
            self.datatree = None
            ll.addWidget(self.explorer, 1)

        # ---- 中间：四屏堆叠 ----
        self.screen_stack = QtWidgets.QStackedWidget()
        self._build_screens()

        dock_left = QtWidgets.QDockWidget("数据源", self)
        dock_left.setWidget(left)
        # 左右两侧最小宽度 320+340=660，加上中央 stack 的 943，
        # 会把窗口最小宽度顶到 1615px —— 1366/1280 屏幕或系统有 DPI
        # 缩放时，右侧"导出"区域被挤出屏幕（用户反馈"找不到导出按钮"）。
        # 收窄到 200/240，内容靠各自滚动条自适应。
        dock_left.setMinimumWidth(200)
        dock_left.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable
                              | QtWidgets.QDockWidget.DockWidgetFloatable)

        dock_right = QtWidgets.QDockWidget("属性", self)
        dock_right.setWidget(self.inspector)
        dock_right.setMinimumWidth(240)
        dock_right.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable
                               | QtWidgets.QDockWidget.DockWidgetFloatable)

        self.setCentralWidget(self.screen_stack)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock_left)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock_right)
        self._dock_left = dock_left
        self._dock_right = dock_right

        self.inspector.variableSelected.connect(self.display_variable)
        self.inspector.displayChanged.connect(self._on_display_changed)
        self.inspector.rgbRequested.connect(self.display_rgb)

        # 初始欢迎页
        self._show_placeholder()

    def _build_nav(self) -> QtWidgets.QWidget:
        """工作台切换条：主界面 / 分析 / 解码 / 制图。"""
        bar = QtWidgets.QWidget()
        bar.setFixedHeight(32)
        bar.setStyleSheet(f"background:#101319;border-bottom:1px solid {theme.LINE};")
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(2)
        self._nav_buttons: list[QtWidgets.QToolButton] = []
        for i, (label, tip) in enumerate((
                ("主界面", "01 主界面：数据源 / 画布 / 属性"),
                ("分析", "02 分析工作台：2×2 四视口 / LUT / 统计 / 剖面"),
                ("解码", "03 解码工作台：输入队列 / 七步流水线 / 字段表"),
                ("制图", "04 制图工作台：图层 / 预览 / 导出"))):
            btn = QtWidgets.QToolButton()
            btn.setText(label)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QToolButton{font-size:11px;padding:3px 10px;border-radius:5px;"
                "border:1px solid transparent;color:#8b95a5;}"
                "QToolButton:hover{background:#1c222c;color:#dfe5ee;}"
                "QToolButton:checked{background:#10333d;border-color:#1d5f70;"
                "color:#9fe9f5;font-weight:600;}")
            btn.clicked.connect(lambda _c=False, idx=i: self.goto_screen(idx))
            lay.addWidget(btn)
            self._nav_buttons.append(btn)
        lay.addStretch(1)
        return bar

    def _build_screens(self) -> None:
        """构建四屏并加入 stack。

        后三屏延迟导入：它们引用了 chartwidgets，而 chartwidgets 又依赖
        matplotlib / scipy（海岸线 KDTree）。放在函数里导入可以让
        「只想用主界面」的场景少加载一堆模块，也避免循环导入。
        """
        # 0. 主界面
        self.screen_main = QtWidgets.QWidget()
        ml = QtWidgets.QVBoxLayout(self.screen_main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        ml.addWidget(self.canvas)
        self.screen_stack.addWidget(self.screen_main)

        # 1. 分析工作台
        try:
            from .workspace import AnalysisWorkspace

            self.workspace = AnalysisWorkspace()
        except Exception as exc:                # noqa: BLE001
            self.workspace = self._error_screen("分析工作台", exc)
        self.screen_stack.addWidget(self.workspace)

        # 2. 解码工作台
        try:
            from .decodebench import DecodeBench

            self.decodebench = DecodeBench()
        except Exception as exc:                # noqa: BLE001
            self.decodebench = self._error_screen("解码工作台", exc)
        self.screen_stack.addWidget(self.decodebench)

        # 3. 制图工作台
        try:
            from .figurebench import FigureBench

            self.figurebench = FigureBench()
        except Exception as exc:                # noqa: BLE001
            self.figurebench = self._error_screen("制图工作台", exc)
        self.screen_stack.addWidget(self.figurebench)

    @staticmethod
    def _error_screen(name: str, exc: Exception) -> QtWidgets.QWidget:
        """某一屏构建失败时给出可见提示，而不是让整个程序起不来。"""
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lbl = QtWidgets.QLabel(f"{name} 初始化失败\n\n{type(exc).__name__}: {exc}")
        lbl.setAlignment(QtCore.Qt.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#f87171;font-size:12px;")
        lay.addWidget(lbl)
        return w

    def goto_screen(self, index: int) -> None:
        """切换工作台，并把当前数据集同步给对应屏。"""
        if not (0 <= index < self.screen_stack.count()):
            return
        self.screen_stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)
        # 主界面显示影像画布，工作台自己有画布。
        # 左右两块停靠面板都要在后三屏隐藏：
        # 每个工作台都自带更贴切的侧栏（02 是视口/图层、03 是队列/解析器、
        # 04 是图层树），主停靠面板留在那儿会与之重叠成两块"数据源"。
        on_main = index == SCREEN_MAIN
        self._dock_right.setVisible(on_main)
        if getattr(self, "_dock_left", None) is not None:
            self._dock_left.setVisible(on_main)
        if index == SCREEN_ANALYSIS and self._ds is not None:
            self.workspace.set_dataset(self._ds)
        elif index == SCREEN_FIGURE and self._ds is not None:
            self.figurebench.set_dataset(self._ds, self._selection)
        self._current_screen = index

    def _build_menu(self) -> None:
        mb = self.menuBar()
        m_file = mb.addMenu("文件")
        m_file.addAction(self.act_open)
        m_file.addAction(self.act_opendir)
        m_file.addSeparator()
        m_file.addAction(self.act_science)
        m_file.addAction(self.act_figure_export)
        m_file.addAction(self.act_export)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)

        m_view = mb.addMenu("视图")
        m_view.addAction(self.act_fit)
        m_view.addAction(self.act_actual)
        m_view.addAction(self.act_zoom_in)
        m_view.addAction(self.act_zoom_out)
        m_view.addSeparator()
        m_view.addAction(self.act_coast)
        m_view.addAction(self.act_graticule)
        m_view.addSeparator()
        m_view.addAction(self.act_select)

        m_bench = mb.addMenu("工作台")
        m_bench.addAction(self.act_main_screen)
        m_bench.addAction(self.act_analysis)
        m_bench.addAction(self.act_decode)
        m_bench.addAction(self.act_figure)

        m_help = mb.addMenu("帮助")
        m_help.addAction(self.act_about)

    def _build_toolbar(self) -> None:
        tb = QtWidgets.QToolBar("主工具栏")
        tb.setMovable(False)
        tb.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        # 工具栏有 13 个动作，按最小尺寸算会把**整个窗口**的最小宽度撑到
        # 1600px 以上；1366/1280 的屏幕或系统有 DPI 缩放时，右侧面板会被
        # 挤出屏幕（用户就"找不到导出按钮"）。这里允许它收缩，
        # Qt 会自动把放不下的动作折叠进 "»" 溢出菜单。
        tb.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                         QtWidgets.QSizePolicy.Fixed)
        tb.setMinimumWidth(240)
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
        tb.addAction(self.act_analysis)
        tb.addAction(self.act_decode)
        tb.addAction(self.act_figure)
        tb.addSeparator()
        tb.addAction(self.act_science)
        tb.addAction(self.act_figure_export)
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

    def _load_last_source(self) -> None:
        """启动时尝试恢复上次的数据源目录（存在才用，不存在就留空）。

        刻意不弹对话框：用户没要求就别打扰。目录来自
        ``QSettings``，默认给本项目常见的数据落盘位置。
        """
        try:
            settings = QtCore.QSettings("FY-Sat", "Studio")
            last = settings.value("last_source", "", type=str)
        except Exception:                       # noqa: BLE001
            last = ""
        candidates = [last] if last else []
        candidates += [
            r"Y:\download-data",
            r"E:\CODEX-NOworkspaces\fy2_decoder",
        ]
        for c in candidates:
            if c and Path(c).exists() and self.datatree is not None:
                self.datatree.add_source(Path(c))
                break

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

        # 记住这次的数据源目录，下次启动直接恢复
        try:
            QtCore.QSettings("FY-Sat", "Studio").setValue(
                "last_source",
                str(ds.source.parent if ds.source else Path(path).parent))
        except Exception:                       # noqa: BLE001
            pass

        # 画布的叠加层（海岸线/经纬网）与四角角标
        self._ensure_overlays()

        # **把数据集传播到其它工作台**。
        # 早期版本只更新了 inspector，切到分析/制图工作台是全黑的，
        # 因为它们的 set_dataset 从未被调用。
        # 解码工作台：把打开的文件推进它的队列（它是队列式界面，
        # 不推的话切过去是空的，用户还得手动"添加文件"）
        db = getattr(self, "decodebench", None)
        if db is not None and hasattr(db, "add_files"):
            try:
                db.add_files([str(path)])
            except Exception as exc:            # noqa: BLE001
                print(f"[warn] 推入解码队列失败: {exc}", file=sys.stderr)

        for target in (getattr(self, "workspace", None),
                       getattr(self, "figurebench", None)):
            if target is None or not hasattr(target, "set_dataset"):
                continue
            try:
                target.set_dataset(ds)
            except Exception as exc:            # noqa: BLE001
                print(f"[warn] 向 {type(target).__name__} 传递数据集失败: {exc}",
                      file=sys.stderr)

        # 自动显示第一个可成像变量
        from .varcatalog import classify_dataset

        classes = classify_dataset(ds)
        for n, c in classes.items():
            if c.is_image:
                self.display_variable(n, 0)
                break

    def _ensure_overlays(self) -> None:
        """给主界面画布挂上海岸线/经纬网叠加层与四角信息角标。"""
        if getattr(self, "_overlay", None) is None:
            self._overlay = cw.CanvasOverlay(self.canvas)
            self._badges = cw.CanvasBadges(self.canvas)
        if self._ds is None:
            return
        arr = self.canvas.array()
        shape = tuple(arr.shape[:2]) if arr is not None else (2000, 2048)
        self._overlay.set_dataset(self._ds, shape)
        self._overlay.set_show_coast(True)
        self._overlay.set_show_grid(True)
        self._overlay.raise_()
        self._badges.set_badges(
            tl=f"{self._ds.platform} · {self._ds.instrument} · {self._ds.level}",
            tr="", bl="", br=self._ds.geolocation.kind)
        self._badges.raise_()

    def toggle_overlay(self, which: str, on: bool) -> None:
        """切换海岸线 / 经纬网叠加（菜单与工具栏共用）。"""
        if getattr(self, "_overlay", None) is None:
            return
        if which == "coast":
            self._overlay.set_show_coast(on)
        else:
            self._overlay.set_show_grid(on)

    # ================= 显示 =================
    def display_variable(self, name: str, band: int = 0) -> None:
        if self._ds is None:
            return
        self._current_var = name
        self._current_band = band
        var = self._ds.variables[name]
        params = self.inspector.display_params()
        tag = f" [通道 {band + 1}]" if len(tuple(var.shape)) == 3 else ""
        self.lbl_status.setText(f"渲染 {name}{tag} {tuple(var.shape)} …")
        self.setCursor(QtCore.Qt.WaitCursor)

        st = Stretch(method="percentile", pct=params["stretch"], gamma=params["gamma"])

        def work():
            v = self._ds.load(name)
            return render_variable(v, cmap=params["cmap"], st=st, band=band)

        self._submit(Worker(work), self._on_rendered)

    def display_rgb(self, names: tuple[str, str, str],
                    bands: tuple[int, int, int] = (0, 0, 0)) -> None:
        if self._ds is None:
            return
        params = self.inspector.display_params()
        self.lbl_status.setText(f"合成 RGB {names} …")
        self.setCursor(QtCore.Qt.WaitCursor)

        st = Stretch(method="percentile", pct=(1.0, 99.0), gamma=params["gamma"])

        def work():
            return render_rgb(self._ds.load, names, st=st, bands=bands, ds=self._ds)

        self._submit(Worker(work), self._on_rendered)

    def _on_rendered(self, arr) -> None:
        self.unsetCursor()
        # 画布换了数据后必须重建叠加层映射：
        # _ensure_overlays 在加载时用的是占位图尺寸(600x800)，
        # 真实影像(2000x2048)到位后若不重建，海岸线会按错误尺寸换算坐标。
        if arr is not None and getattr(self, "_overlay", None) is not None:
            try:
                self._ensure_overlays()
            except Exception:                   # noqa: BLE001
                pass
        if arr is None:
            return
        self.canvas.set_array(arr)
        self.lbl_status.setText("渲染完成")

    def _on_display_changed(self, _params: dict) -> None:
        if self._current_var:
            self.display_variable(self._current_var, self._current_band)

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
        self._selection = (rect.top(), rect.bottom() + 1, rect.left(), rect.right() + 1)
        self.lbl_status.setText(
            f"已框选 {rect.width()} × {rect.height()} 像素 —— "
            f"Ctrl+Shift+E 导出科学制图，或到「制图」工作台用此范围出图")
        # 有选区就把制图工作台的范围同步过去
        if self._ds is not None and hasattr(self, "figurebench"):
            try:
                self.figurebench.lbl_region.setText(
                    f"像素 ({self._selection[0]},{self._selection[1]}) × "
                    f"({self._selection[2]},{self._selection[3]})")
            except Exception:                   # noqa: BLE001
                pass

    def science_figure_dialog(self) -> None:
        """打开科学制图对话框（带当前框选区域）。"""
        if self._ds is None:
            QtWidgets.QMessageBox.information(self, "提示", "请先打开产品")
            return
        from .figdialog import ScienceFigureDialog

        dlg = ScienceFigureDialog(
            self, ds=self._ds, region_px=self._selection,
            current_var=self._current_var, current_band=self._current_band)
        dlg.exec()

    def open_figure_bench(self) -> None:
        """把当前产品与选区带到制图工作台（常驻页面版）。"""
        if self._ds is None:
            QtWidgets.QMessageBox.information(self, "提示", "请先打开产品")
            return
        self.goto_screen(SCREEN_FIGURE)

    def export_figure_bench(self) -> None:
        """从任意界面直接导出制图工作台当前的成品。

        制图工作台的「导出…」按钮在右栏底部，窗口较窄或系统有 DPI 缩放时
        右栏会被挤出可视区。这个入口保证导出随时可达。
        """
        if self._ds is None:
            QtWidgets.QMessageBox.information(self, "提示", "请先打开产品")
            return
        fb = getattr(self, "figurebench", None)
        if fb is None:
            QtWidgets.QMessageBox.information(self, "提示", "制图工作台不可用")
            return
        if hasattr(fb, "set_dataset"):
            fb.set_dataset(self._ds, self._selection)
        # 有 export()（弹一次对话框）就直接用；否则退回 export_to
        if hasattr(fb, "export"):
            fb.export()
        elif hasattr(fb, "export_to"):
            fb.export_to(Path.cwd() / "figure.png")

    def open_analysis_bench(self) -> None:
        if self._ds is None:
            QtWidgets.QMessageBox.information(self, "提示", "请先打开产品")
            return
        self.goto_screen(SCREEN_ANALYSIS)

    def open_decode_bench(self) -> None:
        """把当前文件的所在目录灌进解码队列。"""
        self.goto_screen(SCREEN_DECODE)
        if self._ds is not None and getattr(self._ds, "source", None):
            self.decodebench.add_files([str(self._ds.source)])

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
