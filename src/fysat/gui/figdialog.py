"""科学制图对话框：把画布框选区域导出成出版级图文。

这是用户提出的核心需求：
    「快捷导出科学图片，可以框选一部分地方，快捷导出图片」

流程：
  画布框选 → 本对话框（选版式/区域/参数）→ 实时预览 → 导出
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..sciencefig import FigureSpec, render_science_figure
from .bandindex import band_labels, resolve_preset
from .varcatalog import classify_dataset


class ScienceFigureDialog(QtWidgets.QDialog):
    """科学制图向导。"""

    def __init__(self, parent=None, ds=None, region_px: tuple[int, int, int, int] | None = None,
                 current_var: str | None = None, current_band: int = 0):
        super().__init__(parent)
        self.setWindowTitle("导出科学制图")
        self.resize(980, 760)
        self._ds = ds
        self._region = region_px
        self._preview_path: Path | None = None
        self._last_out: Path | None = None

        self._build_ui()
        if ds is not None:
            self._fill_from_dataset(ds, current_var, current_band)

    # ---------- UI ----------
    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        root.addWidget(split, 1)

        # 左：参数
        form_w = QtWidgets.QWidget()
        form = QtWidgets.QVBoxLayout(form_w)
        form.setContentsMargins(0, 0, 8, 0)

        g_region = QtWidgets.QGroupBox("区域")
        f_region = QtWidgets.QFormLayout(g_region)
        self.lbl_region = QtWidgets.QLabel("全幅")
        self.lbl_region.setStyleSheet("color:#9fe9f5;")
        f_region.addRow("当前选区", self.lbl_region)
        self.chk_use_selection = QtWidgets.QCheckBox("只用框选区域")
        self.chk_use_selection.setChecked(self._region is not None)
        f_region.addRow(self.chk_use_selection)
        form.addWidget(g_region)

        g_layout = QtWidgets.QGroupBox("版式")
        f_layout = QtWidgets.QFormLayout(g_layout)
        self.cmb_layout = QtWidgets.QComboBox()
        self.cmb_layout.addItem("双面板（可见光 + 红外）", "double")
        self.cmb_layout.addItem("单面板（仅红外）", "single")
        f_layout.addRow("布局", self.cmb_layout)

        self.spin_w = QtWidgets.QDoubleSpinBox()
        self.spin_w.setRange(4, 30)
        self.spin_w.setValue(13.5)
        self.spin_h = QtWidgets.QDoubleSpinBox()
        self.spin_h.setRange(3, 20)
        self.spin_h.setValue(6.4)
        size_row = QtWidgets.QHBoxLayout()
        size_row.addWidget(self.spin_w)
        size_row.addWidget(QtWidgets.QLabel("×"))
        size_row.addWidget(self.spin_h)
        size_row.addWidget(QtWidgets.QLabel("英寸"))
        f_layout.addRow("尺寸", size_row)

        self.spin_dpi = QtWidgets.QSpinBox()
        self.spin_dpi.setRange(72, 600)
        self.spin_dpi.setValue(300)
        f_layout.addRow("DPI", self.spin_dpi)
        form.addWidget(g_layout)

        g_data = QtWidgets.QGroupBox("数据通道")
        f_data = QtWidgets.QFormLayout(g_data)
        # 每个数据通道 = [数据集下拉] + [通道下拉]
        # MERSI 的通道分散在 4 个多通道堆栈里，只给数据集的话
        # 要么三行选到同一个变量（合成退化），要么通道号被写死。
        self.cmb_thermal, self.cmb_thermal_band = self._make_channel_row(
            f_data, "红外通道")
        self.cmb_vis_r, self.cmb_vis_r_band = self._make_channel_row(f_data, "可见光 R")
        self.cmb_vis_g, self.cmb_vis_g_band = self._make_channel_row(f_data, "可见光 G")
        self.cmb_vis_b, self.cmb_vis_b_band = self._make_channel_row(f_data, "可见光 B")
        form.addWidget(g_data)

        g_style = QtWidgets.QGroupBox("样式")
        f_style = QtWidgets.QFormLayout(g_style)
        self.chk_coast = QtWidgets.QCheckBox("海岸线")
        self.chk_coast.setChecked(True)
        self.chk_grid = QtWidgets.QCheckBox("经纬网")
        self.chk_grid.setChecked(True)
        f_style.addRow(self.chk_coast)
        f_style.addRow(self.chk_grid)

        self.spin_vmin = QtWidgets.QDoubleSpinBox()
        self.spin_vmin.setRange(-300, 500)
        self.spin_vmin.setValue(180)
        self.spin_vmax = QtWidgets.QDoubleSpinBox()
        self.spin_vmax.setRange(-300, 600)
        self.spin_vmax.setValue(315)
        range_row = QtWidgets.QHBoxLayout()
        range_row.addWidget(self.spin_vmin)
        range_row.addWidget(QtWidgets.QLabel("–"))
        range_row.addWidget(self.spin_vmax)
        range_row.addWidget(QtWidgets.QLabel("K"))
        f_style.addRow("色标范围", range_row)

        self.cmb_cmap = QtWidgets.QComboBox()
        self.cmb_cmap.addItems(["turbo", "inferno", "RdYlBu_r", "gray", "jet", "coolwarm"])
        f_style.addRow("色标", self.cmb_cmap)
        form.addWidget(g_style)

        g_text = QtWidgets.QGroupBox("标题")
        f_text = QtWidgets.QFormLayout(g_text)
        self.edit_title = QtWidgets.QLineEdit()
        self.edit_subtitle = QtWidgets.QLineEdit()
        f_text.addRow("标题", self.edit_title)
        f_text.addRow("副标题", self.edit_subtitle)
        form.addWidget(g_text)

        form.addStretch(1)
        split.addWidget(form_w)

        # 右：预览
        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.preview = QtWidgets.QLabel("点击「生成预览」查看效果")
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setMinimumSize(560, 420)
        self.preview.setStyleSheet("background:#0a0c10;border:1px solid #1c2430;border-radius:6px;")
        self.preview.setScaledContents(False)
        rl.addWidget(self.preview, 1)
        split.addWidget(right)
        split.setSizes([360, 620])

        # 底部按钮
        bar = QtWidgets.QHBoxLayout()
        self.btn_preview = QtWidgets.QPushButton("生成预览")
        self.btn_export = QtWidgets.QPushButton("导出…")
        self.btn_export.setObjectName("primary")
        self.btn_close = QtWidgets.QPushButton("关闭")
        bar.addWidget(self.btn_preview)
        bar.addStretch(1)
        bar.addWidget(self.btn_export)
        bar.addWidget(self.btn_close)
        root.addLayout(bar)

        self.btn_preview.clicked.connect(self.generate_preview)
        self.btn_export.clicked.connect(self.export)
        self.btn_close.clicked.connect(self.reject)
        self.chk_use_selection.toggled.connect(self._sync_region_label)

    # ---------- 数据填充 ----------
    def _make_channel_row(self, form, label: str):
        """建一行「数据集下拉 + 通道下拉」。"""
        row = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        combo = QtWidgets.QComboBox()
        band = QtWidgets.QComboBox()
        band.setFixedWidth(104)
        band.setToolTip("该数据集内部的通道（b 号 + 中心波长）")
        h.addWidget(combo, 1)
        h.addWidget(band)
        form.addRow(label, row)
        combo.currentIndexChanged.connect(
            lambda _i, c=combo, b=band: self._sync_band(c, b))
        return combo, band

    def _sync_band(self, combo, band) -> None:
        """数据集换了就刷新它的通道下拉。"""
        name = combo.currentData()
        labels = band_labels(self._ds, name) if (self._ds and name) else []
        band.blockSignals(True)
        band.clear()
        for i, lab in enumerate(labels):
            band.addItem(lab, i)
        band.setEnabled(len(labels) > 1)
        band.blockSignals(False)

    def _bands_from_ui(self) -> tuple[int, int, int]:
        """读 R/G/B 三个通道下拉的实际通道号。"""
        out = []
        for band in (self.cmb_vis_r_band, self.cmb_vis_g_band, self.cmb_vis_b_band):
            v = band.currentData()
            out.append(int(v) if v is not None else 0)
        return tuple(out)  # type: ignore[return-value]

    def _fill_from_dataset(self, ds, current_var: str | None, current_band: int) -> None:
        from .. import pipeline

        classes = classify_dataset(ds)
        images = [n for n, c in classes.items() if c.is_image]

        # 红外候选：带 Emissive 的
        thermal_cands = [n for n in images if "emissive" in n.lower()]
        vis_cands = [n for n in images if "refsb" in n.lower() or "refs" in n.lower()]

        self.cmb_thermal.clear()
        for n in (thermal_cands or images):
            self.cmb_thermal.addItem(n, n)

        # 默认选 10.7µm 窗区通道，并让用户能看到/更改具体是哪个通道
        wc = pipeline.window_channel(ds)
        if wc and wc[0] in images:
            idx = self.cmb_thermal.findData(wc[0])
            if idx >= 0:
                self.cmb_thermal.setCurrentIndex(idx)
        self._sync_band(self.cmb_thermal, self.cmb_thermal_band)
        self._thermal_band = current_band
        if wc:
            pos = self.cmb_thermal_band.findData(int(wc[1]))
            if pos >= 0:
                self.cmb_thermal_band.setCurrentIndex(pos)
                self._thermal_band = int(wc[1])

        # 可见光三通道默认套用真彩色方案（b3/b2/b1 = 0.65/0.55/0.47 µm）。
        # 早期这里把通道号写死成 (0,1,2) 并当作 R,G,B —— 等于把红端和蓝端装反，
        # 而且三个下拉只能选数据集，用户根本改不了。
        for combo in (self.cmb_vis_r, self.cmb_vis_g, self.cmb_vis_b):
            combo.clear()
            for n in (vis_cands or images):
                combo.addItem(n, n)

        plan = resolve_preset(ds, "true_color")
        if plan is not None:
            for combo, band, name, idx in (
                    (self.cmb_vis_r, self.cmb_vis_r_band, plan.names[0], plan.bands[0]),
                    (self.cmb_vis_g, self.cmb_vis_g_band, plan.names[1], plan.bands[1]),
                    (self.cmb_vis_b, self.cmb_vis_b_band, plan.names[2], plan.bands[2])):
                pos = combo.findData(name)
                if pos < 0:
                    combo.addItem(name, name)
                    pos = combo.count() - 1
                combo.setCurrentIndex(pos)
                self._sync_band(combo, band)
                band.setCurrentIndex(idx)
        else:
            for combo, band in ((self.cmb_vis_r, self.cmb_vis_r_band),
                                (self.cmb_vis_g, self.cmb_vis_g_band),
                                (self.cmb_vis_b, self.cmb_vis_b_band)):
                self._sync_band(combo, band)

        # 标题
        if ds.source:
            self.edit_title.setText(
                f"{ds.platform} {ds.instrument} {ds.level}  {ds.start_time:%Y-%m-%d %H:%Mz}" if ds.start_time
                else f"{ds.platform} {ds.instrument}")
            self.edit_subtitle.setText(ds.source.name)

        self._sync_region_label()

    def _sync_region_label(self) -> None:
        use = self.chk_use_selection.isChecked()
        self.chk_use_selection.setEnabled(self._region is not None)
        if use and self._region:
            r0, r1, c0, c1 = self._region
            self.lbl_region.setText(f"像素 ({r0},{r1}) × ({c0},{c1})  {r1-r0} × {c1-c0}")
        else:
            self.lbl_region.setText("全幅")

    def set_region(self, region: tuple[int, int, int, int] | None) -> None:
        self._region = region
        self.chk_use_selection.setChecked(region is not None)
        self._sync_region_label()

    # ---------- 出图 ----------
    def _build_spec(self, out_path: Path) -> FigureSpec:
        return FigureSpec(
            out_path=out_path,
            layout=self.cmb_layout.currentData(),
            dpi=self.spin_dpi.value(),
            figsize=(self.spin_w.value(), self.spin_h.value()),
            title=self.edit_title.text().strip(),
            subtitle=self.edit_subtitle.text().strip(),
            draw_grid=self.chk_grid.isChecked(),
            draw_coast=self.chk_coast.isChecked(),
            thermal_range=(self.spin_vmin.value(), self.spin_vmax.value()),
            cmap_thermal=self.cmb_cmap.currentText(),
        )

    def generate_preview(self) -> None:
        if self._ds is None:
            return
        out = Path(__file__).resolve().parents[3] / "out" / "preview_science.png"
        try:
            self._render(out, preview=True)
        except Exception as exc:                     # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "生成预览失败", str(exc))
            return

        pix = QtGui.QPixmap(str(out))
        if not pix.isNull():
            self.preview.setPixmap(pix.scaled(self.preview.size(),
                                              QtCore.Qt.KeepAspectRatio,
                                              QtCore.Qt.SmoothTransformation))
            self._preview_path = out

    def _render(self, out: Path, preview: bool = False) -> Path:
        from .. import pipeline
        from ..provenance import build_provenance

        ds = self._ds
        region = self._region if self.chk_use_selection.isChecked() else None

        thermal_var = self.cmb_thermal.currentData()
        vis_names = (self.cmb_vis_r.currentData(),
                     self.cmb_vis_g.currentData(),
                     self.cmb_vis_b.currentData())

        # 通道号一律从下拉读，不再用写死的值
        tb = self.cmb_thermal_band.currentData()
        thermal_band = int(tb) if tb is not None else getattr(self, "_thermal_band", 0)

        spec = self._build_spec(out)
        if preview:
            spec.dpi = 110
            spec.figsize = (9.0, 4.4)

        thermal, visible = pipeline.build_layers(
            ds,
            thermal_var=thermal_var, thermal_band=thermal_band,
            visible_vars=vis_names if spec.layout == "double" else None,
            visible_bands=self._bands_from_ui(),
            region_px=region,
            max_cells=250_000,
        )
        return render_science_figure(thermal.__dict__, visible, spec)

    def export(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "保存科学制图", "science_figure.png",
            "PNG 图片 (*.png);;PDF 矢量 (*.pdf);;SVG 矢量 (*.svg)")
        if not path:
            return
        try:
            out = self._render(Path(path))
        except Exception as exc:                     # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "导出失败", str(exc))
            return
        self._last_out = out
        QtWidgets.QMessageBox.information(
            self, "完成", f"已导出\n{out}\n({out.stat().st_size/1e3:.0f} KB)")
        self.accept()
