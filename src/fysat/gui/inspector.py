"""属性检查器：产品信息 / 影像变量 / 辅助表 / 显示设置。

关键设计：变量按用途分类（见 varcatalog），
「变量」页只列可成像的，辅助表单独一页，RGB 下拉框只放同网格影像。
早期版本把 Calibration/* 也塞进 RGB 下拉，用户一选就因尺寸不符崩溃。
"""
from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..render import COLORMAPS, PRESETS
from .bandindex import band_labels, resolve_preset
from .varcatalog import classify_dataset, describe_class, rgb_choices

STRETCH_PRESETS = [
    ("2% – 98%（推荐）", (2.0, 98.0)),
    ("0.5% – 99.5%（保留极值）", (0.5, 99.5)),
    ("0% – 100%（全量程）", (0.0, 100.0)),
    ("10% – 90%（高对比）", (10.0, 90.0)),
]


class Inspector(QtWidgets.QWidget):
    """右侧面板：产品信息 / 影像变量 / 辅助表 / 显示设置。"""

    variableSelected = QtCore.Signal(str, int)      # 变量名, 通道号
    displayChanged = QtCore.Signal(dict)
    rgbRequested = QtCore.Signal(tuple, tuple)      # 三个变量名, 三个通道号

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ds = None
        self._classes: dict = {}
        self._current: str | None = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.tabs = QtWidgets.QTabWidget()
        lay.addWidget(self.tabs)

        self.tabs.addTab(self._build_info_tab(), "属性")
        self.tabs.addTab(self._build_vars_tab(), "变量")
        self.tabs.addTab(self._build_display_tab(), "显示")
        self.tabs.addTab(self._build_aux_tab(), "辅助")

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

    # ---------- 影像变量页 ----------
    def _build_vars_tab(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self.var_hint = QtWidgets.QLabel("尚无数据")
        self.var_hint.setStyleSheet("color:#8b95a5;font-size:11px;")
        lay.addWidget(self.var_hint)

        self.var_table = QtWidgets.QTableWidget(0, 4)
        self.var_table.setHorizontalHeaderLabels(["变量", "形状", "类型"])
        self.var_table.setColumnWidth(0, 190)
        self.var_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
        self.var_table.horizontalHeader().setStretchLastSection(True)
        self.var_table.setColumnWidth(1, 100)
        self.var_table.verticalHeader().setVisible(False)
        self.var_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.var_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.var_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.var_table.setAlternatingRowColors(True)
        self.var_table.itemSelectionChanged.connect(self._on_var_row_changed)
        lay.addWidget(self.var_table, 1)

        # 通道选择（多通道变量才有用）
        self.band_row = QtWidgets.QWidget()
        bl = QtWidgets.QHBoxLayout(self.band_row)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(QtWidgets.QLabel("通道"))
        self.band_spin = QtWidgets.QSpinBox()
        self.band_spin.setRange(1, 1)
        self.band_spin.valueChanged.connect(self._on_band_changed)
        bl.addWidget(self.band_spin)
        self.band_label = QtWidgets.QLabel("—")
        self.band_label.setStyleSheet("color:#8b95a5;")
        bl.addWidget(self.band_label, 1)
        lay.addWidget(self.band_row)
        self.band_row.setVisible(False)

        return w

    # ---------- 辅助表页 ----------
    def _build_aux_tab(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        hint = QtWidgets.QLabel("校准系数、坐标轴、质量码等辅助数据（不能直接成像）")
        hint.setStyleSheet("color:#8b95a5;font-size:11px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.aux_table = QtWidgets.QTableWidget(0, 4)
        self.aux_table.setHorizontalHeaderLabels(["变量", "形状", "类型"])
        self.aux_table.setColumnWidth(0, 190)
        self.aux_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
        self.aux_table.horizontalHeader().setStretchLastSection(True)
        self.aux_table.setColumnWidth(1, 100)
        self.aux_table.verticalHeader().setVisible(False)
        self.aux_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.aux_table.setAlternatingRowColors(True)
        lay.addWidget(self.aux_table, 1)
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
        self.gamma_slider.setRange(20, 300)
        self.gamma_slider.setValue(100)
        self.gamma_label = QtWidgets.QLabel("1.00")
        gam_row = QtWidgets.QHBoxLayout()
        gam_row.addWidget(self.gamma_slider, 1)
        gam_row.addWidget(self.gamma_label)
        f2.addRow("伽马", gam_row)
        lay.addWidget(g2)

        g3 = QtWidgets.QGroupBox("RGB 合成")
        f3 = QtWidgets.QFormLayout(g3)
        hint = QtWidgets.QLabel("只列出同网格的影像通道")
        hint.setStyleSheet("color:#8b95a5;font-size:10px;")
        f3.addRow(hint)
        # R/G/B 每行 = [数据集下拉] + [通道下拉]
        # MERSI 的通道被拆在 4 个多通道堆栈里，只选数据集会让三个通道
        # 都取第 0 层 —— 合成结果退化成灰度图。必须能选到具体通道。
        self.rgb_r, self.rgb_r_band = self._make_rgb_row(f3, "R")
        self.rgb_g, self.rgb_g_band = self._make_rgb_row(f3, "G")
        self.rgb_b, self.rgb_b_band = self._make_rgb_row(f3, "B")
        self.rgb_btn = QtWidgets.QPushButton("合成 RGB")
        f3.addRow(self.rgb_btn)
        self.lbl_rgb_plan = QtWidgets.QLabel("")
        self.lbl_rgb_plan.setWordWrap(True)
        self.lbl_rgb_plan.setStyleSheet("color:#8b95a5;font-size:10px;")
        f3.addRow(self.lbl_rgb_plan)
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
        self.preset_combo.currentIndexChanged.connect(self._apply_preset)
        for combo, band in ((self.rgb_r, self.rgb_r_band),
                            (self.rgb_g, self.rgb_g_band),
                            (self.rgb_b, self.rgb_b_band)):
            combo.currentIndexChanged.connect(
                lambda _i, c=combo, b=band: self._sync_band_combo(c, b))
        return w

    # ---------- 数据绑定 ----------
    def set_dataset(self, ds) -> None:
        self._ds = ds
        self._classes = classify_dataset(ds)
        self._fill_info(ds)
        self._fill_vars(ds)
        self._fill_aux(ds)
        # 载入后立刻填充 RGB 下拉。早期只在"点变量行"时才填，
        # 于是刚打开文件时三个下拉都是空的，RGB 合成等于不可用。
        self._fill_rgb_choices(None)

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
            self.attr_table.setItem(i, 1, QtWidgets.QTableWidgetItem(
                str(text).replace("[", "").replace("]", "")))

    def _fill_vars(self, ds) -> None:
        """只列可成像的变量。"""
        names = [n for n, c in self._classes.items() if c.is_image]
        self.var_table.setRowCount(len(names))
        for i, n in enumerate(names):
            c = self._classes[n]
            item = QtWidgets.QTableWidgetItem(n)
            item.setToolTip(n)
            self.var_table.setItem(i, 0, item)
            self.var_table.setItem(i, 1, QtWidgets.QTableWidgetItem(str(c.shape)))
            self.var_table.setItem(i, 2, QtWidgets.QTableWidgetItem(describe_class(c)))

        n_img = len(names)
        self.var_hint.setText(
            f"可成像 {n_img} 个 · 多通道变量请用下方通道选择器" if n_img
            else "此文件没有可直接成像的二维影像")

    def _fill_aux(self, ds) -> None:
        names = [n for n, c in self._classes.items() if not c.is_image]
        self.aux_table.setRowCount(len(names))
        for i, n in enumerate(names):
            c = self._classes[n]
            item = QtWidgets.QTableWidgetItem(n)
            item.setToolTip(n)
            self.aux_table.setItem(i, 0, item)
            self.aux_table.setItem(i, 1, QtWidgets.QTableWidgetItem(str(c.shape)))
            self.aux_table.setItem(i, 2, QtWidgets.QTableWidgetItem(describe_class(c)))

    # ---------- RGB 合成 ----------
    def _make_rgb_row(self, form, label: str):
        """建一行「数据集下拉 + 通道下拉」。"""
        row = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        combo = QtWidgets.QComboBox()
        band = QtWidgets.QComboBox()
        band.setFixedWidth(96)
        band.setToolTip("该数据集内部的通道（b 号 + 中心波长）")
        h.addWidget(combo, 1)
        h.addWidget(band)
        form.addRow(label, row)
        return combo, band

    def _sync_band_combo(self, combo, band) -> None:
        """数据集变了就刷新它的通道下拉。"""
        name = combo.currentData()
        labels = band_labels(self._ds, name) if (self._ds and name) else []
        band.blockSignals(True)
        band.clear()
        for i, lab in enumerate(labels):
            band.addItem(lab, i)
        band.setEnabled(len(labels) > 1)
        band.blockSignals(False)

    def _apply_preset(self, _index: int = 0) -> None:
        """把选中的合成配方填进三个下拉（变量 + 通道）。"""
        key = self.preset_combo.currentData()
        if not key or self._ds is None:
            return
        comp = self._presets.get(key)
        if comp is None:
            self.lbl_rgb_plan.setText(f"{key}：当前数据缺少所需通道，无法合成")
            return
        if not comp.ready:
            self.lbl_rgb_plan.setText(
                f"{comp.label}：缺少通道 {comp.missing()}（该仪器可能没有这些波段）")
            return
        for combo, band, ref in ((self.rgb_r, self.rgb_r_band, comp.refs[0]),
                                 (self.rgb_g, self.rgb_g_band, comp.refs[1]),
                                 (self.rgb_b, self.rgb_b_band, comp.refs[2])):
            pos = combo.findData(ref.variable)
            if pos < 0:
                combo.addItem(ref.variable, ref.variable)
                pos = combo.count() - 1
            combo.setCurrentIndex(pos)
            self._sync_band_combo(combo, band)
            band.setCurrentIndex(ref.index)
        self.lbl_rgb_plan.setText(f"{comp.label}：{comp.desc}")

    def _refresh_presets(self) -> None:
        """按当前产品的**分产品合成配方**填充预设下拉。

        不同仪器的合成互不相同（GHI 有严格真彩色、AGRI 只能伪彩、
        AVHRR 只有一个可见光通道），配方来自 composites/composites.yml，
        通道号由 bands.yml 的查找表解析成实际数据集+下标。
        """
        self._presets = {}
        if self._ds is None:
            return
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("（预设组合）", None)

        try:
            from .. import composites as _comp

            items = [c for c in _comp.composites_for(self._ds) if c.kind == "rgb"]
        except Exception:                       # noqa: BLE001
            items = []

        for c in items:
            self._presets[c.key] = c
            label = c.label if c.ready else f"{c.label}（不可用）"
            self.preset_combo.addItem(label, c.key)
            i = self.preset_combo.count() - 1
            item = self.preset_combo.model().item(i)
            if item is not None:
                item.setEnabled(c.ready)
                item.setToolTip(c.desc if c.ready
                                else f"缺少通道 {c.missing()}")
        self.preset_combo.blockSignals(False)

    def _fill_rgb_choices(self, base_shape: tuple | None) -> None:
        """按当前影像的形状填充 RGB 下拉，避免用户选出尺寸不匹配的组合。"""
        choices = rgb_choices(self._ds, base_shape) if self._ds else []
        for combo in (self.rgb_r, self.rgb_g, self.rgb_b):
            combo.clear()
            for label, value in choices:
                combo.addItem(label, value)
        if len(choices) >= 3:
            self.rgb_r.setCurrentIndex(2)
            self.rgb_g.setCurrentIndex(0)
            self.rgb_b.setCurrentIndex(1)
        # 同步每行的通道下拉
        for combo, band in ((self.rgb_r, self.rgb_r_band),
                            (self.rgb_g, self.rgb_g_band),
                            (self.rgb_b, self.rgb_b_band)):
            self._sync_band_combo(combo, band)
        self._refresh_presets()


    def _on_var_row_changed(self) -> None:
        rows = self.var_table.selectionModel().selectedRows()
        if not rows:
            return
        name = self.var_table.item(rows[0].row(), 0).text()
        self._current = name
        c = self._classes.get(name)

        if c and c.kind == "band_stack" and c.bands > 1:
            self.band_row.setVisible(True)
            self.band_spin.blockSignals(True)
            self.band_spin.setRange(1, c.bands)
            self.band_spin.setValue(1)
            self.band_spin.blockSignals(False)
            self.band_label.setText(f"共 {c.bands} 个通道")
        else:
            self.band_row.setVisible(False)

        self._fill_rgb_choices(c.shape if c else None)
        self.variableSelected.emit(name, 0)

    def _on_band_changed(self, val: int) -> None:
        if self._current:
            self.variableSelected.emit(self._current, val - 1)

    def _on_gamma(self, val: int) -> None:
        self.gamma_label.setText(f"{val/100:.2f}")
        self._emit_display()

    def _emit_display(self) -> None:
        if self._ds is None:
            return
        self.displayChanged.emit(self.display_params())

    def _emit_rgb(self) -> None:
        names = (self.rgb_r.currentData(), self.rgb_g.currentData(),
                 self.rgb_b.currentData())
        if any(n is None for n in names):
            return
        bands = (self.rgb_r_band.currentData(),
                 self.rgb_g_band.currentData(),
                 self.rgb_b_band.currentData())
        if any(b is None for b in bands):
            return
        # 三个通道全指向同一数据集的同一层 → 合成必然退化成灰度，直接拦下
        if len(set(zip(names, bands))) == 1:
            QtWidgets.QMessageBox.information(
                self, "无法合成",
                "R/G/B 三个通道指向了同一个数据集的同一个通道。\n"
                "MERSI 的通道分散在 EV_250_Aggr.1KM_RefSB(1-4)、"
                "EV_1KM_RefSB(5-19)、EV_1KM_Emissive(20-23)、"
                "EV_250_Aggr.1KM_Emissive(24-25) 四个数据集里，\n"
                "请为 R/G/B 分别选择不同的通道（或用「预设」）。")
            return
        self.rgbRequested.emit(tuple(names), tuple(int(b) for b in bands))

    def display_params(self) -> dict:
        pct = STRETCH_PRESETS[self.stretch_combo.currentIndex()][1]
        return {
            "cmap": self.cmap_combo.currentText(),
            "stretch": pct,
            "gamma": self.gamma_slider.value() / 100.0,
        }

    def current_variable(self) -> str | None:
        return self._current
