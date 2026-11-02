"""02 分析工作台：2×2 四视口联动 + LUT 色标库 + 统计 + 直方图/剖面。

对应设计稿 ``ui-mockup/02_workspace.html``。

设计要点
--------
1. **四视口**：A/B/C 是影像视口，D 是分析视口（直方图 + 剖面）。
2. **联动**：缩放/平移在视口间同步；游标移动时所有视口显示同一像素的取值，
   并把活动视口的统计送进右侧「统计摘要」。
3. **通道选择**：每视口独立选变量与通道。FY-3 MERSI 的 ``EV_1KM_Emissive``
   是 4 通道、``EV_1KM_RefSB`` 是 15 通道，必须按通道取切片，
   否则会把多条带竖着拼成横条图（见 workers.render_variable 的注释）。
4. **统计只看有效像元**：``display_band`` 已把填充值/越界值转成 NaN，
   ``chartwidgets.summarize`` 用 nan 语义统计。
5. **渲染走线程池**：2000×2048 渲染约 0.3-0.7 s，四视口同开必须异步。
   注意 QRunnable 要由 ``self._jobs`` 持引用，且 Worker 的 Signals
   不能随 runner 销毁（workers.py 已固定 autoDelete=False）。

为什么不改 imageview.py
-----------------------
联动的实现只要共享 ``QTransform`` 即可；海岸线/经纬网用 viewport 上的
透明子控件（``chartwidgets.CanvasOverlay``）。这样既不需要动既有画布，
也不会影响主界面与 191 项既有测试。
"""
from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..render import COLORMAPS, Stretch, display_band
from . import chartwidgets as cw
from . import theme
from .imageview import ImageCanvas
from .varcatalog import classify_dataset, describe_class
from .workers import Worker, render_variable

MAX_PREVIEW = 1400        # 视口内预览的最大边长，再大就降采样


def _downsample(arr: np.ndarray, max_size: int = MAX_PREVIEW):
    h, w = arr.shape[:2]
    step = max(1, int(np.ceil(max(h, w) / float(max_size))))
    return (arr[::step, ::step], step) if step > 1 else (arr, 1)


def _calibrate(ds, var, name: str, band: int, cmap: str, st: Stretch):
    """把变量渲染成 uint8 预览，同时给出用于统计/色标的物理量数组。

    为什么要专门走一趟定标
    ----------------------
    直接 ``display_band(var, physical=True)`` 只做 DN*scale+offset，
    对 MERSI 的红外通道得到的是**辐亮度**（0.01~1.5 mW/(m²·cm⁻¹·sr)），
    不是亮温；可见光通道得到的是**反射率**（0~1）。画出来能用，但
    色标写「1.348」对用户没有意义。

    因此：红外通道改用 ``pipeline.thermal_data`` 得亮温（K），
    可见光通道用 ``pipeline.visible_data`` 得反射率（%），
    拿不到再退回 ``display_band``。这条链路与 `pipeline.build_layers`
    （04 制图工作台用的那条）完全一致，保证两屏数值可对照。
    """
    from ..render import apply_cmap, display_band, stretch

    data = None
    unit = var.unit or ""
    low = name.lower()
    try:
        from .. import pipeline

        if "emissive" in low:
            data, unit = pipeline.thermal_data(ds, name, band)
        elif "refsb" in low or "refs" in low:
            data, unit = pipeline.visible_data(ds, name, band)
    except Exception:                           # noqa: BLE001
        data = None

    if data is None or not np.isfinite(data).any():
        data = display_band(var, index=band, physical=True)
        unit = var.unit or ""

    small, _step = _downsample(np.asarray(data, dtype=np.float32))
    g = stretch(small, st)
    if cmap:
        rgb = apply_cmap(g, cmap)
    else:
        rgb = (g * 255 + 0.5).astype(np.uint8)
    return rgb, small, unit


class ViewportPane(QtWidgets.QFrame):
    """一个视口：标题栏（变量/通道选择）+ 画布 + 底部统计条。"""

    selected = QtCore.Signal(int)                        # 被点选
    renderRequested = QtCore.Signal(int)                 # 请求渲染本视口
    pixelHovered = QtCore.Signal(int, int, int, float)   # 视口号, row, col, value
    zoomed = QtCore.Signal(int, float)                   # 视口号, 缩放百分比

    def __init__(self, index: int, tag: str = "", parent=None):
        super().__init__(parent)
        self.index = index
        self.tag = tag
        self.setObjectName("vp")
        self.setStyleSheet(
            'QFrame#vp{border:1px solid #1e2632;border-radius:7px;background:#07090d;}'
            'QFrame#vp[active="true"]{border-color:#1f6b80;}')

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_header())

        self.canvas = ImageCanvas()
        self.canvas.setMinimumHeight(80)

        # 画布 + 右侧竖直色标条（设计稿里色标在画布右边）
        body = QtWidgets.QWidget()
        body.setStyleSheet("background:transparent;border:none;")
        bl = QtWidgets.QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        bl.addWidget(self.canvas, 1)
        self.colorbar = cw.ColorBarWidget()
        self.colorbar.setFixedWidth(84)
        self.colorbar.hide()                  # 有数据后才显示
        bl.addWidget(self.colorbar)
        lay.addWidget(body, 1)

        lay.addWidget(self._build_footer())

        self._var_name: str | None = None
        self._band = 0
        self._classes: dict = {}
        self._array: np.ndarray | None = None
        self._stat = cw.StatSummary()
        self._overlay: cw.CanvasOverlay | None = None
        self._badges: cw.CanvasBadges | None = None

        self.cmb_var.currentIndexChanged.connect(self._on_var_changed)
        self.spin_band.valueChanged.connect(self._on_band_changed)
        self.canvas.pixelHovered.connect(self._on_hover)
        self.canvas.zoomChanged.connect(lambda pct: self.zoomed.emit(self.index, pct))

    # ---- 子构建 ----
    def _build_header(self) -> QtWidgets.QWidget:
        head = QtWidgets.QWidget()
        head.setFixedHeight(24)
        head.setStyleSheet("background:#10141a;border-bottom:1px solid #1a212b;")
        hl = QtWidgets.QHBoxLayout(head)
        hl.setContentsMargins(8, 0, 8, 0)
        hl.setSpacing(5)

        lbl_tag = QtWidgets.QLabel(self.tag)
        lbl_tag.setStyleSheet("color:#9fe9f5;font-weight:700;font-size:10px;"
                              "background:transparent;border:none;")
        self.lbl_title = QtWidgets.QLabel("—")
        self.lbl_title.setStyleSheet("color:#e2e8f0;font-size:10px;font-weight:600;"
                                     "background:transparent;border:none;")
        self.lbl_title.setMinimumWidth(90)
        self.cmb_var = QtWidgets.QComboBox()
        self.cmb_var.setFixedHeight(19)
        self.cmb_var.setMinimumWidth(140)
        self.cmb_var.setStyleSheet("font-size:9px;padding:0 3px;")
        self.spin_band = QtWidgets.QSpinBox()
        self.spin_band.setFixedHeight(19)
        self.spin_band.setFixedWidth(52)
        self.spin_band.setRange(1, 1)
        self.spin_band.setStyleSheet("font-size:9px;padding:0 2px;")
        self.lbl_meta = QtWidgets.QLabel("")
        self.lbl_meta.setStyleSheet("color:#5f6a7a;font-size:9px;"
                                    "background:transparent;border:none;")

        hl.addWidget(lbl_tag)
        hl.addWidget(self.cmb_var, 1)
        hl.addWidget(self.spin_band)
        hl.addWidget(self.lbl_meta)
        return head

    def _build_footer(self) -> QtWidgets.QWidget:
        foot = QtWidgets.QWidget()
        foot.setFixedHeight(19)
        foot.setStyleSheet("background:#0d1117;border-top:1px solid #1a212b;")
        fl = QtWidgets.QHBoxLayout(foot)
        fl.setContentsMargins(8, 0, 8, 0)
        fl.setSpacing(8)
        self.lbl_stats = QtWidgets.QLabel("—")
        self.lbl_stats.setStyleSheet(
            "color:#6f7b8c;font-size:9px;font-family:Consolas,monospace;"
            "background:transparent;border:none;")
        self.lbl_hint = QtWidgets.QLabel("")
        self.lbl_hint.setStyleSheet("color:#5f6a7a;font-size:9px;"
                                    "background:transparent;border:none;")
        fl.addWidget(self.lbl_stats, 1)
        fl.addWidget(self.lbl_hint)
        return foot

    # ---- 状态 ----
    def set_active(self, on: bool) -> None:
        self.setProperty("active", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def current_var(self) -> str | None:
        return self._var_name

    def current_band(self) -> int:
        return self._band

    def array(self) -> np.ndarray | None:
        return self._array

    def stat(self) -> cw.StatSummary:
        return self._stat

    def overlay(self) -> cw.CanvasOverlay | None:
        return self._overlay

    def ensure_overlays(self) -> None:
        """懒创建海岸线/经纬网叠加层与角标（必须在有图之后才有意义）。"""
        if self._overlay is None:
            self._overlay = cw.CanvasOverlay(self.canvas)
        if self._badges is None:
            self._badges = cw.CanvasBadges(self.canvas)

    def raise_overlays(self) -> None:
        """把叠加层提到最上层。

        QGraphicsView 会在自己的 viewport 上直接绘制场景内容，
        叠加层虽然已是同级子控件，但 z 序可能被 viewport 压住，
        因此每次数据更新后显式 raise。
        """
        for w in (self._overlay, self._badges):
            if w is not None and w.isVisible():
                w.raise_()

    # ---- 数据 ----
    def set_classes(self, ds, classes: dict) -> None:
        """填充变量下拉框（只列可成像的影像变量）。"""
        self._classes = classes
        names = [n for n, c in classes.items() if c.is_image]
        self.cmb_var.blockSignals(True)
        self.cmb_var.clear()
        for n in names:
            self.cmb_var.addItem(n, n)
        self.cmb_var.blockSignals(False)
        if names:
            self.cmb_var.setCurrentIndex(0)
            self._on_var_changed(0)
        else:
            self.lbl_title.setText("无可成像变量")
            self.lbl_stats.setText("—")

    def select_variable(self, name: str, band: int = 0) -> None:
        i = self.cmb_var.findData(name)
        if i < 0:
            return
        self.cmb_var.setCurrentIndex(i)
        if band:
            self.spin_band.setValue(band + 1)

    def _on_var_changed(self, _idx: int) -> None:
        name = self.cmb_var.currentData()
        if not name:
            return
        self._var_name = name
        c = self._classes.get(name)
        bands = max(1, c.bands if c else 1)
        self.spin_band.blockSignals(True)
        self.spin_band.setRange(1, bands)
        self.spin_band.setValue(1)
        self.spin_band.blockSignals(False)
        self.spin_band.setEnabled(bands > 1)
        self._band = 0
        self.lbl_title.setText(name.split("/")[-1])
        if c:
            self.lbl_meta.setText(f"{describe_class(c)} · {tuple(c.shape)}")
        self.renderRequested.emit(self.index)

    def _on_band_changed(self, val: int) -> None:
        self._band = int(val) - 1
        self.renderRequested.emit(self.index)

    def set_rendered(self, arr: np.ndarray, stat: cw.StatSummary) -> None:
        self._array = arr
        self._stat = stat
        self.canvas.set_array(arr, keep_view=True)
        self.lbl_stats.setText(
            f"min {cw.fmt_tick(stat.vmin)}  max {cw.fmt_tick(stat.vmax)}  "
            f"mean {cw.fmt_tick(stat.mean)}  σ {cw.fmt_tick(stat.std)}  "
            f"有效 {stat.valid_pct:.1f}%")

    def set_colorbar(self, stat: cw.StatSummary, cmap: str, unit: str = "") -> None:
        """显示竖直色标条，范围用 2%–98% 分位（与拉伸区间一致）。"""
        if not np.isfinite(stat.vmin) or not np.isfinite(stat.vmax) or stat.n_valid == 0:
            self.colorbar.hide()
            return
        lo = stat.p02 if np.isfinite(stat.p02) else stat.vmin
        hi = stat.p98 if np.isfinite(stat.p98) else stat.vmax
        if not np.isfinite(hi) or hi <= lo:
            lo, hi = stat.vmin, stat.vmax
        self.colorbar.set_range(lo, hi, cmap, label=self.lbl_title.text(), unit=unit)
        self.colorbar.show()

    def set_hint(self, text: str) -> None:
        self.lbl_hint.setText(text)

    def set_badge_texts(self, tl: str = "", br: str = "") -> None:
        self.ensure_overlays()
        if self._badges is not None:
            self._badges.set_badges(tl=tl, br=br)

    def _on_hover(self, r: int, c: int, v: float) -> None:
        self.selected.emit(self.index)
        self.pixelHovered.emit(self.index, r, c, v)

    def mousePressEvent(self, ev) -> None:
        self.selected.emit(self.index)
        super().mousePressEvent(ev)


class AnalysisWorkspace(QtWidgets.QWidget):
    """02 分析工作台整屏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ds = None
        self._classes: dict = {}
        self._pool = QtCore.QThreadPool.globalInstance()
        self._jobs: list[Worker] = []          # 持引用，否则 QRunnable 会被 GC
        self._active = 0
        self._panes: list[ViewportPane] = []
        self._cmap = "turbo"
        self._stretch = (2.0, 98.0)
        self._gamma = 1.0
        self._inflight: set[int] = set()
        self._sync_zoom = True
        self._syncing = False

        self._build_ui()

    # ================= 构建 =================
    def _build_ui(self) -> None:
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_left())
        root.addWidget(self._build_center(), 1)
        root.addWidget(self._build_right())

        self.cmb_stretch.currentIndexChanged.connect(self._on_display)
        self.sld_gamma.valueChanged.connect(self._on_gamma)
        self.chk_coast.toggled.connect(self._on_overlay_changed)
        self.chk_grid.toggled.connect(self._on_overlay_changed)
        self.chk_sync.toggled.connect(self._on_sync_toggled)
        self.btn_export.clicked.connect(self.export_active)

    def _build_left(self) -> QtWidgets.QWidget:
        left = QtWidgets.QWidget()
        left.setFixedWidth(206)
        left.setStyleSheet(f"background:{theme.PANEL};border-right:1px solid {theme.LINE};")
        ll = QtWidgets.QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)

        ll.addWidget(cw.PanelHeader("视口", "4"))
        self.lst_views = QtWidgets.QListWidget()
        self.lst_views.setFixedHeight(100)
        self.lst_views.setStyleSheet(
            "QListWidget{background:transparent;border:none;font-size:11px;}"
            "QListWidget::item{padding:5px 8px;border-radius:5px;color:#c3ccda;}"
            "QListWidget::item:selected{background:#14303c;color:#a9ecf6;}")
        for tag, name in (("A", "主视口"), ("B", "对比通道"),
                          ("C", "第二通道"), ("D", "统计 / 剖面")):
            self.lst_views.addItem(f"{tag}   {name}")
        self.lst_views.setCurrentRow(0)
        self.lst_views.currentRowChanged.connect(self._on_view_row)
        ll.addWidget(self.lst_views)

        ll.addWidget(cw.PanelHeader("图层", "A"))
        self.chk_coast = QtWidgets.QCheckBox("海岸线")
        self.chk_coast.setChecked(True)
        self.chk_grid = QtWidgets.QCheckBox("经纬网")
        self.chk_grid.setChecked(True)
        self.chk_sync = QtWidgets.QCheckBox("缩放联动")
        self.chk_sync.setChecked(True)
        for w in (self.chk_coast, self.chk_grid, self.chk_sync):
            w.setStyleSheet("font-size:11px;padding:4px 10px;")
            ll.addWidget(w)

        ll.addWidget(cw.PanelHeader("会话"))
        self.lbl_session = QtWidgets.QLabel("未加载产品")
        self.lbl_session.setWordWrap(True)
        self.lbl_session.setStyleSheet("color:#5f6a7a;font-size:10px;padding:6px 10px;")
        ll.addWidget(self.lbl_session)
        ll.addStretch(1)
        return left

    def _build_center(self) -> QtWidgets.QWidget:
        center = QtWidgets.QWidget()
        center.setStyleSheet("background:#0a0c10;")
        grid = QtWidgets.QGridLayout(center)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(6)

        for i, tag in enumerate(("A", "B", "C", "D")):
            pane = ViewportPane(i, tag)
            pane.selected.connect(self._set_active)
            pane.renderRequested.connect(self._render_pane)
            pane.pixelHovered.connect(self._on_pixel)
            pane.zoomed.connect(self._on_zoom)
            self._panes.append(pane)
            grid.addWidget(pane, i // 2, i % 2)

        # D 视口换成分析面板（隐藏它的画布）
        self._panes[3].canvas.hide()
        self.analysis_panel = self._build_analysis_panel()
        self._panes[3].layout().insertWidget(2, self.analysis_panel, 1)
        return center

    def _build_analysis_panel(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(4)
        self.hist = cw.HistogramWidget()
        self.profile = cw.ProfileWidget()
        lay.addWidget(self.hist, 1)
        lay.addWidget(self.profile, 1)
        return w

    def _build_right(self) -> QtWidgets.QWidget:
        right = QtWidgets.QWidget()
        right.setFixedWidth(244)
        right.setStyleSheet(f"background:{theme.PANEL};border-left:1px solid {theme.LINE};")
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        rl.addWidget(cw.PanelHeader("LUT 色标库", str(len(COLORMAPS))))
        self.lut_grid = cw.LutGrid(cols=3)
        self.lut_grid.lutSelected.connect(self._on_lut)
        rl.addWidget(self.lut_grid)

        rl.addWidget(cw.PanelHeader("统计摘要", "A"))
        self.stats_grid = cw.StatsGrid()
        self.stats_grid.setFixedHeight(94)
        rl.addWidget(self.stats_grid)

        rl.addWidget(cw.PanelHeader("拉伸"))
        form = QtWidgets.QWidget()
        fl = QtWidgets.QFormLayout(form)
        fl.setContentsMargins(10, 6, 10, 6)
        fl.setSpacing(6)
        self.cmb_stretch = QtWidgets.QComboBox()
        for label, pct in (("2% – 98%", (2.0, 98.0)), ("0.5% – 99.5%", (0.5, 99.5)),
                           ("0% – 100%", (0.0, 100.0)), ("10% – 90%", (10.0, 90.0))):
            self.cmb_stretch.addItem(label, pct)
        self.sld_gamma = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sld_gamma.setRange(20, 300)
        self.sld_gamma.setValue(100)
        self.lbl_gamma = QtWidgets.QLabel("1.00")
        self.lbl_gamma.setStyleSheet("color:#9fe9f5;font-size:10px;")
        grow = QtWidgets.QHBoxLayout()
        grow.addWidget(self.sld_gamma, 1)
        grow.addWidget(self.lbl_gamma)
        fl.addRow("区间", self.cmb_stretch)
        fl.addRow("伽马", grow)
        rl.addWidget(form)

        rl.addStretch(1)
        self.btn_export = QtWidgets.QPushButton("导出当前视图")
        self.btn_export.setObjectName("primary")
        self.btn_export.setFixedHeight(30)
        self.btn_export.setStyleSheet("margin:8px;")
        rl.addWidget(self.btn_export)
        return right

    # ================= 数据 =================
    def set_dataset(self, ds) -> None:
        """绑定数据集；D 视口不参与影像渲染。"""
        self._ds = ds
        self._classes = classify_dataset(ds) if ds is not None else {}
        for pane in self._panes[:3]:
            pane.set_classes(ds, self._classes)

        if ds is None:
            self.lbl_session.setText("未加载产品")
            return

        default = self._best_default()
        for pane in self._panes[:3]:
            if default:
                pane.select_variable(default[0], default[1])
            pane.ensure_overlays()
            pane.set_badge_texts(
                tl=f"{self._ds.platform} {self._ds.instrument} {self._ds.level}",
                br=self._ds.geolocation.kind)

        b = ds.geolocation.bounds()
        rng = (f"经度 {b[0]:.2f}~{b[1]:.2f}\n纬度 {b[2]:.2f}~{b[3]:.2f}"
               if b else ds.geolocation.kind)
        n_img = sum(1 for c in self._classes.values() if c.is_image)
        self.lbl_session.setText(
            f"{ds.platform} {ds.instrument} {ds.level}\n{rng}\n"
            f"{len(ds.variables)} 变量 · {n_img} 可成像")

    def _best_default(self) -> tuple[str, int] | None:
        """优先窗区红外通道（10.7 µm），否则第一个可成像变量。

        ``pipeline`` 属于核心业务层，可能因其他模块的改动暂时 import 失败；
        这里兜底到「第一个可成像变量」，保证 GUI 不会因为核心层的问题整体不可用。
        """
        if self._ds is None:
            return None
        try:
            from .. import pipeline

            wc = pipeline.window_channel(self._ds)
            if wc:
                return wc
        except Exception:                       # noqa: BLE001
            pass
        # 退而求其次：优先名字里带 Emissive 的（红外），否则第一个可成像变量
        for n, c in self._classes.items():
            if c.is_image and "emissive" in n.lower():
                return n, 0
        for n, c in self._classes.items():
            if c.is_image:
                return n, 0
        return None

    # ================= 渲染 =================
    def _render_pane(self, index: int) -> None:
        if self._ds is None or index >= 3:
            return
        pane = self._panes[index]
        name = pane.current_var()
        if not name or index in self._inflight:
            return

        self._inflight.add(index)
        band = pane.current_band()
        cmap = self._cmap
        st = Stretch(method="percentile", pct=self._stretch, gamma=self._gamma)
        ds = self._ds

        def work():
            var = ds.load(name)
            arr, data, unit = _calibrate(ds, var, name, band, cmap, st)
            return arr, cw.summarize(data), unit

        worker = Worker(work)
        self._jobs.append(worker)

        def _ok(result) -> None:
            try:
                arr, stat, unit = result
                pane.set_rendered(arr, stat)
                pane.set_hint(unit)
                pane.set_colorbar(stat, self._cmap, unit)
                # 叠加层必须用「实际显示的数组形状」建映射：
                # 预览有降采样（MAX_PREVIEW），用变量原始形状会让经纬度整体错位。
                ov = pane.overlay()
                if ov is not None:
                    ov.set_dataset(self._ds, tuple(arr.shape[:2]))
                    ov.set_show_coast(self.chk_coast.isChecked())
                    ov.set_show_grid(self.chk_grid.isChecked())
                pane.raise_overlays()
                if index == min(self._active, 2):
                    self.stats_grid.set_stat(stat)
                    self._sync_analysis(stat, pane)
            finally:
                self._inflight.discard(index)
                self._forget(worker)

        def _fail(msg: str) -> None:
            try:
                pane.lbl_stats.setText(f"渲染失败：{msg.splitlines()[0]}")
            finally:
                self._inflight.discard(index)
                self._forget(worker)

        worker.signals.finished.connect(_ok)
        worker.signals.failed.connect(_fail)
        self._pool.start(worker)

    def _forget(self, worker: Worker) -> None:
        try:
            self._jobs.remove(worker)
        except ValueError:
            pass

    # ================= 交互 =================
    def _set_active(self, index: int) -> None:
        if index >= 3:
            index = 0
        self._active = index
        for p in self._panes:
            p.set_active(p.index == index)
        self.lst_views.blockSignals(True)
        self.lst_views.setCurrentRow(index)
        self.lst_views.blockSignals(False)
        pane = self._panes[index]
        self.stats_grid.set_stat(pane.stat())
        if pane.array() is not None:
            self._sync_analysis(pane.stat(), pane)

    def _on_view_row(self, row: int) -> None:
        if 0 <= row < len(self._panes):
            self._set_active(min(row, 2))

    def _sync_analysis(self, stat: cw.StatSummary, pane: ViewportPane) -> None:
        """把活动视口的数据送进直方图与剖面。"""
        arr = pane.array()
        if arr is None:
            return
        gray = arr[..., 0].astype(np.float32) if arr.ndim == 3 else arr.astype(np.float32)
        title = pane.lbl_title.text()
        self.hist.set_data(gray, bins=128, vrange=(stat.p02, stat.p98),
                           title=f"直方图 · {title}")
        mid = gray.shape[0] // 2
        self.profile.set_profile(gray[mid, :].astype(np.float64),
                                 title=f"沿第 {mid} 行剖面 · {title}",
                                 subtitle=f"样本 {gray.shape[1]}")

    def _on_pixel(self, index: int, r: int, c: int, v: float) -> None:
        if index != self._active and index < 3:
            self._set_active(index)

    def _on_zoom(self, index: int, pct: float) -> None:
        """缩放联动：把源视口的变换原样套给其它影像视口。"""
        if not self._sync_zoom or self._syncing or index >= 3:
            return
        src = self._panes[index].canvas
        m = src.transform()
        self._syncing = True
        try:
            for pane in self._panes[:3]:
                if pane.index == index:
                    continue
                pane.canvas.setTransform(QtGui.QTransform(m))
                pane.canvas._emit_zoom()
        finally:
            self._syncing = False

    def _on_sync_toggled(self, on: bool) -> None:
        self._sync_zoom = bool(on)

    def _on_lut(self, cmap: str) -> None:
        self._cmap = cmap
        for i in range(3):
            self._render_pane(i)

    def _on_display(self, _idx: int) -> None:
        self._stretch = self.cmb_stretch.currentData() or (2.0, 98.0)
        for i in range(3):
            self._render_pane(i)

    def _on_gamma(self, val: int) -> None:
        self._gamma = val / 100.0
        self.lbl_gamma.setText(f"{self._gamma:.2f}")
        for i in range(3):
            self._render_pane(i)

    def _on_overlay_changed(self, _on: bool) -> None:
        for pane in self._panes[:3]:
            ov = pane.overlay()
            if ov is not None:
                ov.set_show_coast(self.chk_coast.isChecked())
                ov.set_show_grid(self.chk_grid.isChecked())

    def export_active(self) -> "QtGui.QImage | None":
        """把活动视口的渲染结果存成 PNG，返回 QImage（测试可直接取用）。"""
        pane = self._panes[min(self._active, 2)]
        arr = pane.array()
        if arr is None:
            return None
        import numpy as np  # noqa: F401  (局部 import 便于单独使用)

        rgb = np.ascontiguousarray(arr)
        if rgb.ndim == 2:
            h, w = rgb.shape
            img = QtGui.QImage(rgb.data, w, h, w, QtGui.QImage.Format_Grayscale8).copy()
        else:
            h, w = rgb.shape[:2]
            img = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format_RGB888).copy()
        out = self.output_dir() / f"workspace_view_{pane.tag}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out))
        return img

    @staticmethod
    def output_dir():
        return cw.PROJECT_ROOT / "out" / "gui"

    # ================= 生命周期 =================
    def closeEvent(self, ev) -> None:
        for w in list(self._jobs):
            self._pool.tryTake(w)          # 未开始的直接摘掉
        self._pool.waitForDone(2000)
        self._jobs.clear()
        super().closeEvent(ev)


__all__ = ["AnalysisWorkspace", "ViewportPane"]
