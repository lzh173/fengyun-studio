"""属性检查器：变量列表 + 属性表 + 显示参数。"""
from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..render import COLORMAPS, PRESETS

STRETCH_PRESETS = [
    ("2% – 98%（推荐）", (2.0, 98.0)),
    ("0.5% – 99.5%（保留极值）", (0.5, 99.5)),
    ("0% – 100%（全量程）", (0.0, 100.0)),
    ("10% – 90%（高对比）", (10.0, 90.0)),
]


class Inspector(QtWidgets.QWidget):
    """右侧面板：产品信息 / 变量 / 显示设置。"""

    variableSelected = QtCore.Signal(str)
    displayChanged = QtCore.Signal(dict)      # {'cmap':..., 'stretch':(...), 'gamma':...}
    rgbRequested = QtCore.Signal(tuple)       # 三个通道名

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ds = None
        self._current: str | None = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.tabs = QtWidgets.QTabWidget()
        lay.addWidget(self.tabs)

        self.tabs.addTab(self._build_info_tab(), "属性")
        self.tabs.addTab(self._build_vars_tab(), "变量")
        self.tabs.addTab(self._build_display_tab(), "显示")

    # ---------- 属性页 ----------
    def _build_info_tab(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)

        self.info_table = QtWidgets.QTableWidget(0, 2)
        self.info_table.setHorizontalHeaderLabels(["项", "值"])
        self.info_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.info_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.info_table.verticalHeader().setVisible(False)
        self.info_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.info_table.setAlternatingRowColors(True)
        lay.addWidget(self.info_table)

        self.attr_table = QtWidgets.QTableWidget(0, 2)
        self.attr_table.setHorizontalHeaderLabels(["全局属性", "值"])
        self.attr_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.attr_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.attr_table.verticalHeader().setVisible(False)
        self.attr_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.attr_table.setAlternatingRowColors(True)
        lay.addWidget(self.attr_table, 1)
        return w

    # ---------- 变量页 ----------
    def _build_vars_tab(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)

        self.var_table = QtWidgets.QTableWidget(0, 4)
        self.var_table.setHorizontalHeaderLabels(["变量", "形状", "类型", "单位"])
        # 第 0 列给足宽度：变量名常带 Data/ 前缀，Stretch 会把它压缩到看不见
        self.var_table.setColumnWidth(0, 210)
        self.var_table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Interactive)
        for i in (1, 2, 3):
            self.var_table.horizontalHeader().setSectionResizeMode(
                i, QtWidgets.QHeaderView.ResizeToContents)
        self.var_table.verticalHeader().setVisible(False)
        self.var_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.var_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.var_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.var_table.setAlternatingRowColors(True)
        self.var_table.itemSelectionChanged.connect(self._on_var_row_changed)
        lay.addWidget(self.var_table)
        return w

    # ---------- 显示页 ----------
    def _build_display_tab(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        g1 = QtWidgets.QGroupBox("色标")
        f1 = QtWidgets.QFormLayout(g1)
        self.cmap_combo = QtWidgets.QComboBox()
        self.cmap_combo.addItems(COLORMAPS)
        f1.addRow("配色", self.cmap_combo)
        lay.addWidget(g1)

        g2 = QtWidgets.QGroupBox("拉伸")
        f2 = QtWidgets.QFormLayout(g2)
        self.stretch_combo = QtWidgets.QComboBox()
        for label, _ in STRETCH_PRESETS:
            self.stretch_combo.addItem(label)
        f2.addRow("区间", self.stretch_combo)

        self.gamma_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.gamma_slider.setRange(20, 300)          # 0.2 – 3.0
        self.gamma_slider.setValue(100)
        self.gamma_label = QtWidgets.QLabel("1.00")
        gam_row = QtWidgets.QHBoxLayout()
        gam_row.addWidget(self.gamma_slider, 1)
        gam_row.addWidget(self.gamma_label)
        f2.addRow("伽马", gam_row)
        lay.addWidget(g2)

        g3 = QtWidgets.QGroupBox("RGB 合成")
        f3 = QtWidgets.QFormLayout(g3)
        self.rgb_r = QtWidgets.QComboBox()
        self.rgb_g = QtWidgets.QComboBox()
        self.rgb_b = QtWidgets.QComboBox()
        f3.addRow("R", self.rgb_r)
        f3.addRow("G", self.rgb_g)
        f3.addRow("B", self.rgb_b)
        self.rgb_btn = QtWidgets.QPushButton("合成 RGB")
        f3.addRow(self.rgb_btn)
        self.preset_combo = QtWidgets.QComboBox()
        self.preset_combo.addItem("（预设组合）", None)
        for key, p in PRESETS.items():
            self.preset_combo.addItem(p["label"], key)
        f3.addRow("预设", self.preset_combo)
        lay.addWidget(g3)

        lay.addStretch(1)

        self.cmap_combo.currentTextChanged.connect(self._emit_display)
        self.stretch_combo.currentIndexChanged.connect(self._emit_display)
        self.gamma_slider.valueChanged.connect(self._on_gamma)
        self.rgb_btn.clicked.connect(self._emit_rgb)
        return w

    # ---------- 数据绑定 ----------
    def set_dataset(self, ds) -> None:
        self._ds = ds
        self._fill_info(ds)
        self._fill_vars(ds)
        self._fill_rgb_choices(ds)

    def _fill_info(self, ds) -> None:
        rows = [
            ("卫星", ds.platform or "—"),
            ("仪器", ds.instrument or "—"),
            ("层级", ds.level or "—"),
            ("产品", ds.product or "—"),
            ("时间", ds.start_time.strftime("%Y-%m-%d %H:%M:%S") if ds.start_time else "—"),
            ("读取器", ds.reader or "—"),
            ("变量数", str(len(ds.variables))),
            ("定位", ds.geolocation.kind),
        ]
        b = ds.geolocation.bounds()
        if b:
            rows.append(("范围", f"经度 {b[0]:.2f}~{b[1]:.2f}  纬度 {b[2]:.2f}~{b[3]:.2f}"))
        if ds.source:
            rows.append(("文件", ds.source.name))
            rows.append(("大小", f"{ds.source.stat().st_size/1e6:.1f} MB"))

        self.info_table.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.info_table.setItem(i, 0, QtWidgets.QTableWidgetItem(k))
            self.info_table.setItem(i, 1, QtWidgets.QTableWidgetItem(str(v)))

        attrs = ds.attrs or {}
        keys = sorted(attrs.keys())[:120]
        self.attr_table.setRowCount(len(keys))
        for i, k in enumerate(keys):
            v = attrs[k]
            text = np.asarray(v).reshape(-1)[:4].tolist() if isinstance(v, np.ndarray) else str(v)
            self.attr_table.setItem(i, 0, QtWidgets.QTableWidgetItem(str(k)))
            self.attr_table.setItem(i, 1, QtWidgets.QTableWidgetItem(str(text).replace("[", "").replace("]", "")))

    def _fill_vars(self, ds) -> None:
        names = list(ds.variables)
        self.var_table.setRowCount(len(names))
        for i, n in enumerate(names):
            v = ds.variables[n]
            item = QtWidgets.QTableWidgetItem(n)
            item.setToolTip(n)
            self.var_table.setItem(i, 0, item)
            self.var_table.setItem(i, 1, QtWidgets.QTableWidgetItem(str(tuple(v.shape))))
            self.var_table.setItem(i, 2, QtWidgets.QTableWidgetItem(str(v.dtype)))
            self.var_table.setItem(i, 3, QtWidgets.QTableWidgetItem(v.unit))

    def _fill_rgb_choices(self, ds) -> None:
        names = [n for n, v in ds.variables.items() if len(v.shape) == 2]
        for combo in (self.rgb_r, self.rgb_g, self.rgb_b):
            combo.clear()
            combo.addItems(names)
        if len(names) >= 3:
            self.rgb_r.setCurrentIndex(2)
            self.rgb_g.setCurrentIndex(0)
            self.rgb_b.setCurrentIndex(1)

    # ---------- 信号 ----------
    def _on_var_row_changed(self) -> None:
        rows = self.var_table.selectionModel().selectedRows()
        if not rows:
            return
        name = self.var_table.item(rows[0].row(), 0).text()
        self._current = name
        self.variableSelected.emit(name)

    def _on_gamma(self, val: int) -> None:
        self.gamma_label.setText(f"{val/100:.2f}")
        self._emit_display()

    def _emit_display(self) -> None:
        if self._ds is None:
            return
        pct = STRETCH_PRESETS[self.stretch_combo.currentIndex()][1]
        self.displayChanged.emit({
            "cmap": self.cmap_combo.currentText(),
            "stretch": pct,
            "gamma": self.gamma_slider.value() / 100.0,
        })

    def _emit_rgb(self) -> None:
        self.rgbRequested.emit((
            self.rgb_r.currentText(),
            self.rgb_g.currentText(),
            self.rgb_b.currentText(),
        ))

    def display_params(self) -> dict:
        pct = STRETCH_PRESETS[self.stretch_combo.currentIndex()][1]
        return {
            "cmap": self.cmap_combo.currentText(),
            "stretch": pct,
            "gamma": self.gamma_slider.value() / 100.0,
        }

    def current_variable(self) -> str | None:
        return self._current
