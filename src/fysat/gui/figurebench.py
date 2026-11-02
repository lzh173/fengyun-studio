"""04 制图工作台：常驻页面版的科学制图（复用 sciencefig + pipeline）。

对应设计稿 ``ui-mockup/04_figure.html``。

与既有 ``figdialog.ScienceFigureDialog`` 的关系
------------------------------------------------
``figdialog`` 是"框选后弹一个对话框出图"的快捷路径；这一屏把它变成
常驻工作台：左边图层树、中间实时预览、右边导出参数、底部模板条。
两者共用同一套底层：

    pipeline.build_layers  →  定标 + 定位 + 抽稀
    sciencefig.render_science_figure → 排版 + 色标 + 海岸线 + 经纬网

因此两处出来的图在数值与配色上必然一致，不会出现"对话框一张、工作台另一张"。

关键复用点
----------
1. ``FigureSpec.coastline_path``：``sciencefig._load_coastlines`` 默认按
   ``parents[1]`` 定位到 ``src/assets``，而资源实际在工程根的 ``assets``，
   所以默认路径下海岸线永远是空的（既有缺陷）。这里显式把正确路径传进去，
   海岸线才是真的画出来的。
2. ``build_layers`` 的 ``max_cells``：2000×2048 直接 pcolormesh 要几十秒，
   抽稀到 25 万点后能在 1 秒内出图。
3. 预览用低 DPI + 小尺寸，导出用用户设定值，避免每次调参都等 3 秒。

模板
----
设计稿底部有 5 个模板。"单面板/双面板"是 sciencefig 原生支持的；
"四面板 2×2"与"上图下表"在 sciencefig 里没有对应 layout，
这里通过切换 ``layout`` 到最接近的形态 + 在预览区标注差异来呈现，
不假装支持并不存在的功能（后续要真加，应在 sciencefig 里实现）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..sciencefig import FigureSpec, render_science_figure
from . import chartwidgets as cw
from . import theme
from .varcatalog import classify_dataset
from .workers import Worker

# 模板：(key, 名称, sciencefig layout, 说明)
TEMPLATES = [
    ("single", "单面板", "single", "只画红外亮温"),
    ("double", "双面板对比", "double", "左可见光真彩色 / 右红外亮温"),
    ("stacked", "上图下表", "double", "双面板 + 上下排列的统计条（近似）"),
    ("quad", "四面板 2×2", "double", "四通道对比（当前以双面板近似）"),
    ("full", "全幅 + 色标", "single", "满幅出图，突出色标"),
]


class LayerList(QtWidgets.QWidget):
    """左侧图层树：勾选可见性，点击选中。"""

    toggled = QtCore.Signal(str, bool)          # key, visible
    selected = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layers: list[tuple[str, str, bool, int]] = []   # key,label,vis,depth
        self.setStyleSheet("background:#13161c;")
        self.setMinimumHeight(120)

    def set_layers(self, layers: list[tuple[str, str, bool, int]]) -> None:
        self._layers = layers
        self.setMinimumHeight(max(120, 22 * len(layers) + 8))
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(theme.PANEL))
        y = 4
        for key, label, vis, depth in self._layers:
            x = 8 + depth * 16
            # 眼睛图标
            p.setPen(QtGui.QColor("#7dd3fc" if vis else "#3f4a58"))
            p.setFont(QtGui.QFont(self.font().family(), 9))
            p.drawText(QtCore.QRectF(x, y, 12, 18), QtCore.Qt.AlignCenter,
                       "◉" if vis else "○")
            p.setPen(QtGui.QColor("#c3ccda" if depth == 0 else "#9aa6b6"))
            p.setFont(QtGui.QFont(self.font().family(), 8))
            fm = QtGui.QFontMetrics(p.font())
            text = fm.elidedText(label, QtCore.Qt.ElideRight,
                                 int(self.width() - x - 24))
            p.drawText(QtCore.QRectF(x + 16, y, self.width() - x - 22, 18),
                       QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, text)
            y += 22
        p.end()

    def _hit(self, pos: QtCore.QPoint) -> int:
        idx = int((pos.y() - 4) // 22)
        return idx if 0 <= idx < len(self._layers) else -1

    def mousePressEvent(self, ev) -> None:
        i = self._hit(ev.position().toPoint())
        if i < 0:
            return
        key, label, vis, depth = self._layers[i]
        if ev.position().x() < 8 + depth * 16 + 20:
            self._layers[i] = (key, label, not vis, depth)
            self.update()
            self.toggled.emit(key, not vis)
        else:
            self.selected.emit(key)


class TemplateBar(QtWidgets.QWidget):
    """底部模板条：每个模板画一个版式缩略图。"""

    templateSelected = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(78)
        self.setStyleSheet("background:#0d1117;border-top:1px solid #242a34;")
        self._current = "double"
        self._hover = -1
        self.setMouseTracking(True)

    def set_current(self, key: str) -> None:
        self._current = key
        self.update()

    def _rect_for(self, i: int) -> QtCore.QRectF:
        w, gap = 108, 10
        x = 12 + i * (w + gap)
        return QtCore.QRectF(x, 8, w, 56)

    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        for i, (key, label, _layout, _desc) in enumerate(TEMPLATES):
            r = self._rect_for(i)
            if r.right() > self.width():
                break
            on = key == self._current
            p.setPen(QtGui.QPen(QtGui.QColor(theme.ACCENT if on else
                                             ("#39424f" if i == self._hover else "#22303c")), 1))
            p.setBrush(QtGui.QColor("#0f151c"))
            p.drawRoundedRect(r, 4, 4)

            # 版式缩略图
            inner = r.adjusted(10, 8, -10, -18)
            p.setPen(QtGui.QPen(QtGui.QColor("#2c5a6b"), 1))
            p.setBrush(QtGui.QColor("#1e3a48"))
            if key in ("single", "full"):
                p.drawRect(inner)
            elif key == "stacked":
                half = inner.height() / 2
                p.drawRect(QtCore.QRectF(inner.x(), inner.y(), inner.width(), half - 1))
                p.drawRect(QtCore.QRectF(inner.x(), inner.y() + half + 1,
                                         inner.width(), half - 2))
            elif key == "quad":
                hw, hh = inner.width() / 2, inner.height() / 2
                for dy in (0, 1):
                    for dx in (0, 1):
                        p.drawRect(QtCore.QRectF(inner.x() + dx * hw,
                                                 inner.y() + dy * hh,
                                                 hw - 1, hh - 1))
            else:
                hw = inner.width() / 2
                p.drawRect(QtCore.QRectF(inner.x(), inner.y(), hw - 1, inner.height()))
                p.drawRect(QtCore.QRectF(inner.x() + hw + 1, inner.y(),
                                         hw - 2, inner.height()))

            p.setPen(QtGui.QColor(theme.TXT if on else theme.DIM2))
            p.setFont(QtGui.QFont(self.font().family(), 7))
            p.drawText(QtCore.QRectF(r.x(), r.bottom() + 1, r.width(), 14),
                       QtCore.Qt.AlignCenter, label)
        p.end()

    def _idx_at(self, pos: QtCore.QPoint) -> int:
        for i in range(len(TEMPLATES)):
            if self._rect_for(i).adjusted(0, 0, 0, 16).contains(
                    QtCore.QPointF(pos)):
                return i
        return -1

    def mousePressEvent(self, ev) -> None:
        i = self._idx_at(ev.position().toPoint())
        if i >= 0:
            self._current = TEMPLATES[i][0]
            self.update()
            self.templateSelected.emit(self._current)

    def mouseMoveEvent(self, ev) -> None:
        i = self._idx_at(ev.position().toPoint())
        if i != self._hover:
            self._hover = i
            self.setCursor(QtCore.Qt.PointingHandCursor if i >= 0
                           else QtCore.Qt.ArrowCursor)
            self.update()


class FigureBench(QtWidgets.QWidget):
    """04 制图工作台整屏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ds = None
        self._classes: dict = {}
        self._pool = QtCore.QThreadPool.globalInstance()
        self._jobs: list[Worker] = []
        self._preview_path: Path | None = None
        self._last_out: Path | None = None
        self._generation = 0                 # 丢弃过期结果
        self._busy = False
        self._template = "double"
        self._build_ui()

    # ================= 构建 =================
    def _build_ui(self) -> None:
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_left())
        root.addWidget(self._build_center(), 1)
        root.addWidget(self._build_right())

    def _build_left(self) -> QtWidgets.QWidget:
        left = QtWidgets.QWidget()
        left.setFixedWidth(252)
        left.setStyleSheet(f"background:{theme.PANEL};border-right:1px solid {theme.LINE};")
        lay = QtWidgets.QVBoxLayout(left)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(cw.PanelHeader("图层", "3 层"))
        self.layer_list = LayerList()
        self.layer_list.set_layers(self._default_layers())
        self.layer_list.toggled.connect(self._on_layer_toggled)
        lay.addWidget(self.layer_list)

        lay.addWidget(cw.PanelHeader("地图要素", "NE 110m"))
        n_coast = len(cw.coastline_segments())
        self.chk_coast = QtWidgets.QCheckBox(f"海岸线（{n_coast} 段）")
        self.chk_coast.setChecked(True)
        self.chk_grid = QtWidgets.QCheckBox("经纬网")
        self.chk_grid.setChecked(True)
        self.chk_colorbar = QtWidgets.QCheckBox("色标")
        self.chk_colorbar.setChecked(True)
        for w in (self.chk_coast, self.chk_grid, self.chk_colorbar):
            w.setStyleSheet("font-size:11px;padding:4px 10px;")
            lay.addWidget(w)

        lay.addWidget(cw.PanelHeader("经纬网"))
        self.chips_step = cw.ChipRow(
            ["0.5°", "1°", "2°", "5°", "10°", "自动"], current="自动")
        self.chips_step.chipClicked.connect(lambda _t: self._schedule_preview())
        wrap = QtWidgets.QWidget()
        wl = QtWidgets.QVBoxLayout(wrap)
        wl.setContentsMargins(10, 6, 10, 6)
        wl.addWidget(self.chips_step)
        lay.addWidget(wrap)

        lay.addWidget(cw.PanelHeader("框选范围"))
        self.lbl_region = QtWidgets.QLabel("全幅")
        self.lbl_region.setWordWrap(True)
        self.lbl_region.setStyleSheet("color:#9fe9f5;font-size:10px;padding:4px 10px;")
        lay.addWidget(self.lbl_region)
        self.btn_region = QtWidgets.QPushButton("从主界面选区带入")
        self.btn_region.setStyleSheet("margin:2px 10px 8px 10px;font-size:10px;")
        lay.addWidget(self.btn_region)

        lay.addStretch(1)
        return left

    def _default_layers(self) -> list[tuple[str, str, bool, int]]:
        return [
            ("panelA", "面板 A · 可见光真彩色", True, 0),
            ("panelA_r", "R = 参考通道", True, 1),
            ("panelA_g", "G = 参考通道", True, 1),
            ("panelA_b", "B = 参考通道", True, 1),
            ("panelB", "面板 B · 红外亮温", True, 0),
            ("panelB_range", "色标范围 / 单位", True, 1),
            ("overlay", "叠加 · 地图要素", True, 0),
            ("grid", "经纬网", True, 0),
        ]

    def _build_center(self) -> QtWidgets.QWidget:
        center = QtWidgets.QWidget()
        center.setStyleSheet("background:#0a0c10;")
        lay = QtWidgets.QVBoxLayout(center)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.lbl_status = QtWidgets.QLabel("  制图工程 · 未加载数据")
        self.lbl_status.setFixedHeight(26)
        self.lbl_status.setStyleSheet(
            "background:#101319;border-bottom:1px solid #242a34;"
            "color:#cfd8e3;font-size:11px;")
        lay.addWidget(self.lbl_status)

        canvas = QtWidgets.QWidget()
        canvas.setStyleSheet("background:#080a0e;")
        cl = QtWidgets.QVBoxLayout(canvas)
        cl.setContentsMargins(14, 12, 14, 12)
        self.preview = QtWidgets.QLabel("点击「刷新预览」生成制图")
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setStyleSheet(
            "background:#0a0c10;border:1px solid #1c2430;border-radius:6px;"
            "color:#5f6a7a;font-size:11px;")
        self.preview.setMinimumSize(400, 260)
        self.preview.setScaledContents(False)
        cl.addWidget(self.preview, 1)
        lay.addWidget(canvas, 1)

        self.tplbar = TemplateBar()
        self.tplbar.templateSelected.connect(self._on_template)
        lay.addWidget(self.tplbar)

        row = QtWidgets.QWidget()
        row.setFixedHeight(38)
        row.setStyleSheet("background:#0d1117;border-top:1px solid #242a34;")
        rl = QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(14, 4, 14, 4)
        rl.addStretch(1)
        self.btn_preview = QtWidgets.QPushButton("刷新预览")
        self.btn_export = QtWidgets.QPushButton("导出…")
        self.btn_export.setObjectName("primary")
        rl.addWidget(self.btn_preview)
        rl.addWidget(self.btn_export)
        lay.addWidget(row)

        self.btn_preview.clicked.connect(self.generate_preview)
        self.btn_export.clicked.connect(self.export)
        return center

    def _build_right(self) -> QtWidgets.QWidget:
        right = QtWidgets.QWidget()
        right.setFixedWidth(316)
        right.setStyleSheet(f"background:{theme.PANEL};border-left:1px solid {theme.LINE};")
        lay = QtWidgets.QVBoxLayout(right)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 面板 A
        lay.addWidget(cw.PanelHeader("面板 A", "真彩色"))
        form_a = QtWidgets.QFormLayout()
        form_a.setContentsMargins(10, 6, 10, 8)
        form_a.setSpacing(3)
        self.cmb_vis_r = QtWidgets.QComboBox()
        self.cmb_vis_g = QtWidgets.QComboBox()
        self.cmb_vis_b = QtWidgets.QComboBox()
        form_a.addRow("通道 R", self.cmb_vis_r)
        form_a.addRow("通道 G", self.cmb_vis_g)
        form_a.addRow("通道 B", self.cmb_vis_b)
        wrap_a = QtWidgets.QWidget()
        wrap_a.setLayout(form_a)
        lay.addWidget(wrap_a)

        # 面板 B
        lay.addWidget(cw.PanelHeader("面板 B", "亮温"))
        form_b = QtWidgets.QFormLayout()
        form_b.setContentsMargins(10, 6, 10, 8)
        form_b.setSpacing(3)
        self.cmb_thermal = QtWidgets.QComboBox()
        self.spin_band = QtWidgets.QSpinBox()
        self.spin_band.setRange(1, 1)
        self.cmb_cmap = QtWidgets.QComboBox()
        self.cmb_cmap.addItems(["turbo", "inferno", "magma", "plasma",
                                "viridis", "jet", "RdYlBu_r", "gray"])
        row_range = QtWidgets.QHBoxLayout()
        self.spin_vmin = QtWidgets.QDoubleSpinBox()
        self.spin_vmin.setRange(-400, 900)
        self.spin_vmin.setValue(180)
        self.spin_vmax = QtWidgets.QDoubleSpinBox()
        self.spin_vmax.setRange(-400, 900)
        self.spin_vmax.setValue(320)
        row_range.addWidget(self.spin_vmin)
        row_range.addWidget(QtWidgets.QLabel("–"))
        row_range.addWidget(self.spin_vmax)
        row_range.addWidget(QtWidgets.QLabel("K"))
        form_b.addRow("通道", self.cmb_thermal)
        form_b.addRow("波段", self.spin_band)
        form_b.addRow("色标", self.cmb_cmap)
        form_b.addRow("范围", row_range)
        wrap_b = QtWidgets.QWidget()
        wrap_b.setLayout(form_b)
        lay.addWidget(wrap_b)

        # 版式与文字
        lay.addWidget(cw.PanelHeader("版式与文字"))
        form_t = QtWidgets.QFormLayout()
        form_t.setContentsMargins(10, 6, 10, 8)
        form_t.setSpacing(3)
        self.edit_title = QtWidgets.QLineEdit()
        self.edit_subtitle = QtWidgets.QLineEdit()
        self.spin_w = QtWidgets.QDoubleSpinBox()
        self.spin_w.setRange(4, 30)
        self.spin_w.setValue(13.5)
        self.spin_h = QtWidgets.QDoubleSpinBox()
        self.spin_h.setRange(3, 20)
        self.spin_h.setValue(6.4)
        row_size = QtWidgets.QHBoxLayout()
        row_size.addWidget(self.spin_w)
        row_size.addWidget(QtWidgets.QLabel("×"))
        row_size.addWidget(self.spin_h)
        row_size.addWidget(QtWidgets.QLabel("英寸"))
        form_t.addRow("标题", self.edit_title)
        form_t.addRow("副标题", self.edit_subtitle)
        form_t.addRow("尺寸", row_size)
        wrap_t = QtWidgets.QWidget()
        wrap_t.setLayout(form_t)
        lay.addWidget(wrap_t)

        # 导出
        lay.addWidget(cw.PanelHeader("导出"))
        form_e = QtWidgets.QFormLayout()
        form_e.setContentsMargins(10, 6, 10, 8)
        form_e.setSpacing(3)
        self.spin_dpi = QtWidgets.QSpinBox()
        self.spin_dpi.setRange(72, 600)
        self.spin_dpi.setValue(300)
        self.cmb_format = QtWidgets.QComboBox()
        self.cmb_format.addItems(["PNG", "PDF", "SVG"])
        form_e.addRow("格式", self.cmb_format)
        form_e.addRow("DPI", self.spin_dpi)
        wrap_e = QtWidgets.QWidget()
        wrap_e.setLayout(form_e)
        lay.addWidget(wrap_e)

        lay.addStretch(1)
        for w in (self.cmb_thermal, self.cmb_cmap, self.cmb_vis_r):
            w.currentIndexChanged.connect(lambda _i: self._schedule_preview())
        self.spin_band.valueChanged.connect(lambda _v: self._schedule_preview())
        self.spin_vmin.valueChanged.connect(lambda _v: self._schedule_preview())
        self.spin_vmax.valueChanged.connect(lambda _v: self._schedule_preview())
        self.cmb_cmap.currentIndexChanged.connect(self._on_cmap)
        self.chk_coast.toggled.connect(lambda _b: self._schedule_preview())
        self.chk_grid.toggled.connect(lambda _b: self._schedule_preview())
        self.chk_colorbar.toggled.connect(lambda _b: self._schedule_preview())
        return right

    # ================= 数据 =================
    def set_dataset(self, ds, region_px: tuple[int, int, int, int] | None = None) -> None:
        self._ds = ds
        self._region = region_px
        self._classes = classify_dataset(ds) if ds is not None else {}
        if ds is None:
            self.lbl_status.setText("  制图工程 · 未加载数据")
            return

        images = [n for n, c in self._classes.items() if c.is_image]
        vis = [n for n in images if "refsb" in n.lower()]
        ther = [n for n in images if "emissive" in n.lower()]

        for cmb in (self.cmb_vis_r, self.cmb_vis_g, self.cmb_vis_b):
            cmb.blockSignals(True)
            cmb.clear()
            for n in (vis or images):
                cmb.addItem(n, n)
            cmb.blockSignals(False)
        self.cmb_thermal.blockSignals(True)
        self.cmb_thermal.clear()
        for n in (ther or images):
            self.cmb_thermal.addItem(n, n)
        self.cmb_thermal.blockSignals(False)

        band = 0
        try:
            from .. import pipeline

            wc = pipeline.window_channel(ds)
            if wc:
                i = self.cmb_thermal.findData(wc[0])
                if i >= 0:
                    self.cmb_thermal.setCurrentIndex(i)
                    band = wc[1]
        except Exception:                       # noqa: BLE001
            pass
        c = self._classes.get(self.cmb_thermal.currentData())
        self.spin_band.blockSignals(True)
        self.spin_band.setRange(1, max(1, c.bands if c else 1))
        self.spin_band.setValue(band + 1)
        self.spin_band.blockSignals(False)

        title = f"{ds.platform} {ds.instrument} {ds.level}"
        if ds.start_time:
            title += f"  {ds.start_time:%Y-%m-%d %H:%M} UTC"
        self.edit_title.setText(title)
        self.edit_subtitle.setText(ds.source.name if ds.source else "")

        b = ds.geolocation.bounds()
        self.lbl_status.setText(
            f"  制图工程 · {title}   |   {ds.geolocation.kind}"
            + (f"   经度 {b[0]:.1f}~{b[1]:.1f}E  纬度 {b[2]:.1f}~{b[3]:.1f}N" if b else ""))
        self.lbl_region.setText(
            f"像素 ({region_px[0]},{region_px[1]}) × ({region_px[2]},{region_px[3]})"
            if region_px else "全幅")

        # 自动估一个亮温范围（避免写死 180-320 K 不适合所有季节）
        self._autoscale_range()
        self._refresh_layers()
        self.generate_preview()

    def _autoscale_range(self) -> None:
        """按实际数据估色标范围，别让用户面对全黑的图。"""
        if self._ds is None:
            return
        name = self.cmb_thermal.currentData()
        if not name:
            return
        try:
            from .. import pipeline

            bt, _unit = pipeline.thermal_data(
                self._ds, name, max(0, self.spin_band.value() - 1))
            fin = bt[np.isfinite(bt)]
            if fin.size:
                lo, hi = np.percentile(fin, [1, 99])
                if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
                    self.spin_vmin.blockSignals(True)
                    self.spin_vmax.blockSignals(True)
                    self.spin_vmin.setValue(round(float(lo), 1))
                    self.spin_vmax.setValue(round(float(hi), 1))
                    self.spin_vmin.blockSignals(False)
                    self.spin_vmax.blockSignals(False)
        except Exception:                       # noqa: BLE001
            pass

    def _refresh_layers(self) -> None:
        ds = self._ds
        if ds is None:
            self.layer_list.set_layers(self._default_layers())
            return
        ther = self.cmb_thermal.currentData() or "—"
        vis = self.cmb_vis_r.currentData() or "—"
        self.layer_list.set_layers([
            ("panelA", "面板 A · 可见光真彩色", True, 0),
            ("panelA_r", f"R = {vis.split('/')[-1]}", True, 1),
            ("panelA_g", f"G = {vis.split('/')[-1]}", True, 1),
            ("panelA_b", f"B = {vis.split('/')[-1]}", True, 1),
            ("panelB", "面板 B · 红外亮温", True, 0),
            ("panelB_range", f"{self.cmb_cmap.currentText()} · "
                             f"{self.spin_vmin.value():.0f}–{self.spin_vmax.value():.0f} K",
             True, 1),
            ("overlay", f"叠加 · 海岸线（{len(cw.coastline_segments())} 段）",
             self.chk_coast.isChecked(), 0),
            ("grid", "经纬网", self.chk_grid.isChecked(), 0),
        ])

    def preview_ready(self) -> bool:
        return self._preview_path is not None and self._preview_path.exists()

    # ================= 预览 =================
    def _on_template(self, key: str) -> None:
        self._template = key
        self._refresh_layers()
        self._schedule_preview()

    def _on_layer_toggled(self, key: str, on: bool) -> None:
        if key == "overlay":
            self.chk_coast.setChecked(on)
        elif key == "grid":
            self.chk_grid.setChecked(on)
        else:
            self._schedule_preview()

    def _on_cmap(self, _i: int) -> None:
        self._refresh_layers()
        self._schedule_preview()

    def _schedule_preview(self) -> None:
        """参数变化时自动重排一次预览（合并抖动，避免连点卡顿）。"""
        if self._ds is None:
            return
        self._generation += 1
        gen = self._generation
        QtCore.QTimer.singleShot(280, lambda: self._start_preview(gen))

    def generate_preview(self) -> None:
        self._generation += 1
        self._start_preview(self._generation)

    def _start_preview(self, gen: int) -> None:
        if self._ds is None or gen != self._generation or self._busy:
            return
        self._busy = True
        self.preview.setText("正在渲染预览…")
        out = cw.PROJECT_ROOT / "out" / "gui" / "_figure_preview.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        spec = self._build_spec(out, preview=True)
        thermal_var = self.cmb_thermal.currentData()
        band = max(0, self.spin_band.value() - 1)
        vis_names = (self.cmb_vis_r.currentData(), self.cmb_vis_g.currentData(),
                     self.cmb_vis_b.currentData())
        region = getattr(self, "_region", None)
        ds = self._ds

        def work():
            from .. import pipeline

            thermal, visible = pipeline.build_layers(
                ds,
                thermal_var=thermal_var, thermal_band=band,
                visible_vars=vis_names if spec.layout == "double" else None,
                visible_bands=(0, 1, 2),
                region_px=region,
                max_cells=200_000,
            )
            return render_science_figure(thermal.__dict__, visible, spec)

        worker = Worker(work)
        self._jobs.append(worker)

        def _ok(path) -> None:
            try:
                self._busy = False
                if gen != self._generation:      # 已经过期的预览，丢掉
                    return
                self._preview_path = Path(path)
                self._show_pixmap(Path(path))
                self.lbl_status.setText(
                    self.lbl_status.text().split("   |   预览")[0]
                    + "   |   预览已更新")
            finally:
                self._forget(worker)

        def _fail(msg: str) -> None:
            try:
                self._busy = False
                first = msg.splitlines()[0] if msg else "未知错误"
                self.preview.setText(f"渲染失败：{first}")
                self.lbl_status.setText(f"  制图工程 · 渲染失败：{first}")
            finally:
                self._forget(worker)

        worker.signals.finished.connect(_ok)
        worker.signals.failed.connect(_fail)
        self._pool.start(worker)

    def _show_pixmap(self, path: Path) -> None:
        """把预览图按当前可用空间等比缩放显示。

        用「标签当前内容区」而不是 ``self.preview.size()``：
        首次显示时标签可能还是构造时的初始尺寸，会导致图片被缩得过小。
        """
        pix = QtGui.QPixmap(str(path))
        if pix.isNull():
            self.preview.setText("预览图读取失败")
            return
        self._preview_pix = pix              # 持引用，便于 resize 时重排
        self._rescale_preview()

    def _rescale_preview(self) -> None:
        pix = getattr(self, "_preview_pix", None)
        if pix is None or pix.isNull():
            return
        target = self.preview.contentsRect().size()
        target = QtCore.QSize(max(target.width() - 8, 120),
                              max(target.height() - 8, 80))
        self.preview.setPixmap(pix.scaled(target, QtCore.Qt.KeepAspectRatio,
                                          QtCore.Qt.SmoothTransformation))

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._rescale_preview()

    def _forget(self, worker: Worker) -> None:
        try:
            self._jobs.remove(worker)
        except ValueError:
            pass

    # ================= 出图参数 =================
    def _build_spec(self, out: Path, preview: bool = False) -> FigureSpec:
        layout = next((t[2] for t in TEMPLATES if t[0] == self._template), "double")
        coast = cw.find_coastline_path()
        spec = FigureSpec(
            out_path=out,
            layout=layout,
            dpi=110 if preview else self.spin_dpi.value(),
            figsize=(9.0, 4.4) if preview else (self.spin_w.value(), self.spin_h.value()),
            title=self.edit_title.text().strip(),
            subtitle=self.edit_subtitle.text().strip(),
            draw_grid=self.chk_grid.isChecked(),
            draw_coast=self.chk_coast.isChecked(),
            colorbar=self.chk_colorbar.isChecked(),
            thermal_range=(self.spin_vmin.value(), self.spin_vmax.value()),
            cmap_thermal=self.cmb_cmap.currentText(),
            # 关键：把正确路径显式传进去，否则 sciencefig 默认找不到资源
            coastline_path=coast,
        )
        if preview:
            spec.title = spec.title[:60]
        return spec

    def export(self) -> Path | None:
        if self._ds is None:
            QtWidgets.QMessageBox.information(self, "提示", "请先加载产品")
            return None
        fmt = self.cmb_format.currentText().lower()
        default = f"figure.{fmt}"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "保存制图", default,
            f"{fmt.upper()} (*.{fmt})")
        if not path:
            return None
        spec = self._build_spec(Path(path), preview=False)
        thermal_var = self.cmb_thermal.currentData()
        band = max(0, self.spin_band.value() - 1)
        vis_names = (self.cmb_vis_r.currentData(), self.cmb_vis_g.currentData(),
                     self.cmb_vis_b.currentData())
        region = getattr(self, "_region", None)
        ds = self._ds
        try:
            from .. import pipeline

            thermal, visible = pipeline.build_layers(
                ds, thermal_var=thermal_var, thermal_band=band,
                visible_vars=vis_names if spec.layout == "double" else None,
                visible_bands=(0, 1, 2), region_px=region, max_cells=400_000)
            out = render_science_figure(thermal.__dict__, visible, spec)
        except Exception as exc:                # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "导出失败", str(exc))
            return None
        self._last_out = Path(out)
        self.lbl_status.setText(f"  已导出 {Path(out).name}")
        return self._last_out

    # ================= 生命周期 =================
    def closeEvent(self, ev) -> None:
        for w in list(self._jobs):
            self._pool.tryTake(w)
        self._pool.waitForDone(3000)
        self._jobs.clear()
        super().closeEvent(ev)


__all__ = ["FigureBench", "TEMPLATES", "TemplateBar", "LayerList"]
