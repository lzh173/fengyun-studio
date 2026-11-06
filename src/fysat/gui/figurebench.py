"""04 制图工作台：常驻页面版的科学制图（复用 sciencefig + pipeline）。

对应设计稿 ``ui-mockup/04_figure.html``。

与既有 ``figdialog.ScienceFigureDialog`` 的关系
-----------------------------------------------
``figdialog`` 是"框选后弹一个对话框出图"的快捷路径；这一屏把它变成
常驻工作台：左边图层树、中间实时预览、右边导出参数、底部模板条。
两者共用同一套底层：

    pipeline.build_layers  →  定标 + 定位 + 抽稀
    sciencefig.render_science_figure → 排版 + 色标 + 海岸线 + 经纬网

因此两处出来的图在数值与配色上必然一致，不会出现"对话框一张、工作台另一张"。

关键复用点
---------
1. ``FigureSpec.coastline_path``：``sciencefig._load_coastlines`` 默认按
   ``parents[1]`` 定位到 ``src/assets``，而资源实际在工程根的 ``assets``，
   所以默认路径下海岸线永远是空的（既有缺陷）。这里显式把正确路径传进去，
   海岸线才是真的画出来的。
2. ``build_layers`` 的 ``max_cells``：2000×2048 直接 pcolormesh 要几十秒，
   抽稀到 20~40 万点后能在 1 秒内出图。
3. 预览用低 DPI + 小尺寸，导出用用户设定值，避免每次调参都等 3 秒。

诚实性约定（本文件的第一原则）
-----------------------------
这一屏以前最大的问题是"看着能用、实际用不了"。所以每个可见入口都必须
要么真的生效，要么明确置灰：

1. **版式**：sciencefig 的 ``FigureSpec.layout`` 只有 ``single`` / ``double``。
   设计稿底部 5 个模板里，只有这两个有对应实现；``TEMPLATES`` 的第 5 个
   字段 ``implemented`` 记录这一点，没有实现的按钮 ``setEnabled(False)``
   置灰并 ``setToolTip("尚未实现…")``，点下去也不会改 ``self._template``。
2. **图层树**：只有真正会改变成图的行才画眼睛图标、才能点着切换
   （面板 A、海岸线、经纬网、色标）；通道名 / 色标范围这些"只读状态"
   行画成灰点，点击不再假装能切换。
3. **色标下拉框**：``pipeline.build_layers`` 产出的 ``ThermalLayer.cmap``
   写死 ``"turbo"``，而 ``sciencefig`` 取 ``t.get("cmap") or spec.cmap_thermal``，
   于是界面上选 inferno/gray 完全不生效。``_collect_layers`` 把用户选择
   覆盖回 ``thermal.cmap``，色标才真的会换。
4. **经纬网间隔**：「0.5°/1°/2°…」原来只触发一次重渲染、从不改参数
   （``FigureSpec.grid_step`` 有实现但没人传）。现在真的传进 spec。
5. **导出**：``export_to(path)`` 是纯逻辑，不弹任何对话框（脚本 / 批量 /
   测试都能调）；``export()`` 只负责弹一次保存对话框，然后转调
   ``export_to``。
6. **溯源**：导出时把 ``fysat.provenance.build_provenance`` 写进图页脚；
   PNG 另外嵌入 ``fysat.*`` tEXt 字段，可用
   ``fysat.provenance.read_png_provenance`` 读回。
7. **选区**：``set_region()`` + ``showEvent`` 会把主界面画布的框选矩形
   自动带进来（只读 ``MainWindow._selection``，不反向依赖其实现）。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..sciencefig import FigureSpec, render_science_figure
from . import chartwidgets as cw
from . import theme
from .varcatalog import classify_dataset
from .workers import Worker

# ======================= 模板定义 =======================
#
# (key, 名称, sciencefig layout, 说明, 是否真的实现)
#
# 只保留两个"真的会出不同版式"的模板：sciencefig 的 layout 只有
# single / double，另外三个在 sciencefig 里没有对应实现，硬塞只会得到
# 一张和别的模板一模一样的图 —— 那就是"能点但不生效"。
TEMPLATES: list[tuple[str, str, str, str, bool]] = [
    ("single", "单面板", "single", "只画红外亮温，近方形构图（1 面板）", True),
    ("double", "双面板对比", "double", "左可见光真彩色 / 右红外亮温（2 面板）", True),
    ("stacked", "上图下表", "double", "需要上下双栏 layout，sciencefig 尚未实现", False),
    ("quad", "四面板 2×2", "double", "需要 2×2 layout，sciencefig 尚未实现", False),
    ("full", "全幅 + 色标", "single", "与「单面板」版式完全相同，暂无独立实现", False),
]

# 模板的推荐画布尺寸（英寸）。切换模板会重置尺寸，保证两种版式的宽高比
# 真的不同（单面板近方形 / 双面板长条），而不是仅面板数变了。
TEMPLATE_SIZES: dict[str, tuple[float, float]] = {
    "single": (8.0, 6.4),
    "double": (13.5, 6.4),
}

# sciencefig 真正支持的版式
SUPPORTED_LAYOUTS = ("single", "double")

NOT_IMPLEMENTED_TEXT = "尚未实现：sciencefig 目前只支持「单面板 / 双面板」两种版式"

# 经纬网间隔（""/"自动" → None，由 sciencefig 自动选）
GRID_STEP_OPTIONS: dict[str, float | None] = {
    "0.5°": 0.5, "1°": 1.0, "2°": 2.0, "5°": 5.0, "10°": 10.0, "自动": None,
}

FORMAT_FILTERS = {
    "PNG": "PNG 图片 (*.png)",
    "PDF": "PDF 矢量 (*.pdf)",
    "SVG": "SVG 矢量 (*.svg)",
}

_PREVIEW_SIZES = {"single": (6.2, 4.3), "double": (9.0, 4.4)}

# matplotlib 的 Agg 后端与 pipeline 里的 HDF5 读取都不是线程安全的。
# 预览在 QThreadPool 里跑、导出在主线程跑，两者可能重叠（审查脚本就是
# 切完模板立刻导出），因此用一把模块级锁把"建层 + 渲染"整体串起来：
# 导出最多等预览几秒，换来不会因为并发渲染而崩。
_RENDER_LOCK = threading.RLock()


def template_layout(key: str) -> str:
    """模板 → sciencefig layout（未知模板退回 double）。"""
    for t in TEMPLATES:
        if t[0] == key:
            return t[2]
    return "double"


def template_enabled(key: str) -> bool:
    """该模板是否真的有实现（没实现的在 UI 上必须置灰）。"""
    for t in TEMPLATES:
        if t[0] == key:
            return bool(t[4]) and t[2] in SUPPORTED_LAYOUTS
    return False


def template_size(key: str) -> tuple[float, float]:
    return TEMPLATE_SIZES.get(key, TEMPLATE_SIZES["double"])


def _footer_from_provenance(prov: dict[str, str]) -> str:
    """把溯源字段压成一行页脚。

    页脚是 PDF/SVG 里唯一的溯源载体，但也不能把画布撑爆：
    取「软件 版本 | commit | modified | 平台 仪器 | 生成时间」五段，
    总长压到 ~100 字符 —— 8 英寸宽 @ 8.5 pt 也放得下（原先用
    ``key=value`` 拼到 165 字符，单面板图里会被右边缘切掉）。
    """
    if not prov:
        return ""
    parts: list[str] = []
    software = prov.get("software", "")
    version = prov.get("software_version", "")
    if software:
        parts.append(f"{software} {version}".strip())
    if prov.get("commit"):
        parts.append(f"commit {prov['commit']}")
    if prov.get("modified") == "yes":
        parts.append("modified")
    plat = " ".join(x for x in (prov.get("platform", ""),
                                prov.get("instrument", "")) if x)
    if plat:
        parts.append(plat)
    if prov.get("generated_at"):
        parts.append(prov["generated_at"])
    return "  |  ".join(parts)[:110]


def _embed_png_provenance(path: Path, prov: dict[str, str]) -> None:
    """把溯源字段作为 PNG tEXt 写进文件（sciencefig 不接 metadata，故后处理）。

    sciencefig 的 ``fig.savefig`` 不传 metadata，而这里又不能改
    sciencefig.py，所以在出图后用 Pillow 无损重写一遍 PNG，附上 tEXt。
    其它格式（PDF/SVG）的溯源由可见页脚承担。
    """
    if not prov:
        return
    from PIL import Image, PngImagePlugin

    from ..provenance import as_png_text

    info = PngImagePlugin.PngInfo()
    for key, value in as_png_text(prov).items():
        info.add_text(key, str(value))

    with Image.open(path) as im:
        im.load()
        dpi = im.info.get("dpi")
        kwargs: dict[str, Any] = {"pnginfo": info}
        if dpi:
            kwargs["dpi"] = dpi
        im.save(path, **kwargs)


class LayerList(QtWidgets.QWidget):
    """左侧图层树：勾选可见性，点击选中。

    行格式：``(key, label, visible, depth[, togglable])``，第 5 项缺省为
    ``True``。``togglable=False`` 的行是"只读状态"（例如通道名、色标范围），
    它们只画一个灰点，点击不会假装切换 —— 免得用户点了半天发现没反应。
    """

    toggled = QtCore.Signal(str, bool)          # key, visible
    selected = QtCore.Signal(str)

    ROW_H = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layers: list[tuple[str, str, bool, int, bool]] = []
        self.setStyleSheet("background:#13161c;")
        self.setMinimumHeight(120)
        self.setMouseTracking(True)

    # ---- 数据 ----
    @staticmethod
    def _normalise(row) -> tuple[str, str, bool, int, bool]:
        key, label, vis, depth = row[0], row[1], row[2], row[3]
        togglable = bool(row[4]) if len(row) > 4 else True
        return (str(key), str(label), bool(vis), int(depth), togglable)

    def set_layers(self, layers: list[tuple]) -> None:
        self._layers = [self._normalise(r) for r in layers]
        self.setMinimumHeight(max(120, self.ROW_H * len(self._layers) + 8))
        self.update()

    def layers(self) -> list[tuple[str, str, bool, int, bool]]:
        return list(self._layers)

    def togglable_keys(self) -> list[str]:
        return [k for k, _l, _v, _d, t in self._layers if t]

    def state_of(self, key: str) -> bool | None:
        for k, _l, vis, _d, _t in self._layers:
            if k == key:
                return vis
        return None

    # ---- 绘制 ----
    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(theme.PANEL))
        y = 4
        for _key, label, vis, depth, togglable in self._layers:
            x = 8 + depth * 16
            if togglable:
                p.setPen(QtGui.QColor("#7dd3fc" if vis else "#3f4a58"))
                glyph = "◉" if vis else "○"
            else:
                # 只读行：灰点，不给"可切换"的暗示
                p.setPen(QtGui.QColor("#39424f"))
                glyph = "·"
            p.setFont(QtGui.QFont(self.font().family(), 9))
            p.drawText(QtCore.QRectF(x, y, 12, 18), QtCore.Qt.AlignCenter, glyph)
            if togglable:
                color = QtGui.QColor("#c3ccda" if depth == 0 else "#9aa6b6")
            else:
                color = QtGui.QColor("#5a6472")
            p.setPen(color)
            p.setFont(QtGui.QFont(self.font().family(), 8))
            fm = QtGui.QFontMetrics(p.font())
            text = fm.elidedText(label, QtCore.Qt.ElideRight,
                                 int(self.width() - x - 24))
            p.drawText(QtCore.QRectF(x + 16, y, self.width() - x - 22, 18),
                       QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, text)
            y += self.ROW_H
        p.end()

    def _hit(self, pos: QtCore.QPoint) -> int:
        idx = int((pos.y() - 4) // self.ROW_H)
        return idx if 0 <= idx < len(self._layers) else -1

    # ---- 交互 ----
    def mousePressEvent(self, ev) -> None:
        i = self._hit(ev.position().toPoint())
        if i < 0:
            return
        key, _label, vis, depth, togglable = self._layers[i]
        on_eye = ev.position().x() < 8 + depth * 16 + 20
        if togglable and on_eye:
            self._layers[i] = (key, _label, not vis, depth, togglable)
            self.update()
            self.toggled.emit(key, not vis)
        else:
            self.selected.emit(key)

    def event(self, ev):
        """只读行给个说明性 tooltip，解释"为什么点了没反应"。"""
        if ev.type() == QtCore.QEvent.ToolTip:
            pos = ev.pos()
            i = self._hit(pos)
            if i >= 0:
                key, label, _vis, _depth, togglable = self._layers[i]
                tip = (f"点击左侧眼睛切换「{label}」" if togglable
                       else f"「{label}」是状态说明，请在右侧参数面板修改")
                QtWidgets.QToolTip.showText(ev.globalPos(), tip, self)
                return True
        return super().event(ev)


class TemplateBar(QtWidgets.QWidget):
    """底部模板条：每个模板一个带版式缩略图的按钮。

    用真正的 ``QToolButton`` 而不是自绘热区，是为了让"未实现"能真正
    ``setEnabled(False)`` 置灰（自绘控件做不到原生禁用），也顺带获得
    键盘可达性与原生 tooltip。
    """

    templateSelected = QtCore.Signal(str)

    BTN_W, BTN_H = 118, 74
    ICON_W, ICON_H = 100, 44

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(92)
        self.setStyleSheet("background:#0d1117;border-top:1px solid #242a34;")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        self._buttons: dict[str, QtWidgets.QToolButton] = {}
        self._current = "double"

        for key, label, layout, desc, implemented in TEMPLATES:
            btn = QtWidgets.QToolButton()
            btn.setObjectName(f"tpl_{key}")
            btn.setText(label)
            btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
            btn.setIconSize(QtCore.QSize(self.ICON_W, self.ICON_H))
            btn.setIcon(QtGui.QIcon(self._thumb(layout if implemented else key)))
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setFixedSize(self.BTN_W, self.BTN_H)
            btn.setStyleSheet(
                "QToolButton{font-size:10px;color:#a9b6c6;background:#0f151c;"
                "border:1px solid #22303c;border-radius:5px;padding:2px;}"
                "QToolButton:checked{color:#9fe9f5;border-color:#22d3ee;"
                "background:#10333d;}"
                "QToolButton:hover{border-color:#39424f;}"
                "QToolButton:disabled{color:#4e5764;background:#0b0f14;"
                "border-color:#1a222c;}")
            if template_enabled(key):
                btn.setCursor(QtCore.Qt.PointingHandCursor)
                btn.setToolTip(f"{desc}\n切换模板会把画布尺寸重置为推荐值")
            else:
                btn.setEnabled(False)
                btn.setCursor(QtCore.Qt.ArrowCursor)
                btn.setToolTip(NOT_IMPLEMENTED_TEXT)
            btn.clicked.connect(lambda _c=False, k=key: self._on_click(k))
            self._buttons[key] = btn
            lay.addWidget(btn)

        lay.addStretch(1)
        self.set_current(self._current)

    # ---- 缩略图 ----
    @classmethod
    def _thumb(cls, kind: str) -> QtGui.QPixmap:
        """按 layout 画版式缩略图。

        未实现的模板按钮由 Qt 统一画成灰态（``setEnabled(False)``），
        所以这里仍然按它"本来想表达"的版式画，只是永远点不动。
        """
        pm = QtGui.QPixmap(cls.ICON_W, cls.ICON_H)
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(4, 4, cls.ICON_W - 8, cls.ICON_H - 8)
        p.setPen(QtGui.QPen(QtGui.QColor("#2c5a6b"), 1))
        p.setBrush(QtGui.QColor("#1e3a48"))
        if kind == "stacked":
            half = r.height() / 2
            p.drawRect(QtCore.QRectF(r.x(), r.y(), r.width(), half - 1))
            p.drawRect(QtCore.QRectF(r.x(), r.y() + half + 1, r.width(), half - 2))
        elif kind == "quad":
            hw, hh = r.width() / 2, r.height() / 2
            for dy in (0, 1):
                for dx in (0, 1):
                    p.drawRect(QtCore.QRectF(r.x() + dx * hw, r.y() + dy * hh,
                                             hw - 1, hh - 1))
        elif kind == "double":
            hw = r.width() / 2
            p.drawRect(QtCore.QRectF(r.x(), r.y(), hw - 1, r.height()))
            p.drawRect(QtCore.QRectF(r.x() + hw + 1, r.y(), hw - 2, r.height()))
        else:
            p.drawRect(r)
        p.end()
        return pm

    # ---- 状态 ----
    def button(self, key: str) -> QtWidgets.QToolButton | None:
        return self._buttons.get(key)

    def is_enabled(self, key: str) -> bool:
        btn = self._buttons.get(key)
        return bool(btn is not None and btn.isEnabled())

    def tooltip_of(self, key: str) -> str:
        btn = self._buttons.get(key)
        return btn.toolTip() if btn is not None else ""

    def current(self) -> str:
        return self._current

    def set_current(self, key: str) -> None:
        btn = self._buttons.get(key)
        if btn is None:
            return
        self._current = key
        btn.setChecked(True)

    def _on_click(self, key: str) -> None:
        if not template_enabled(key):        # 置灰的模板不接受切换
            return
        self._current = key
        self.templateSelected.emit(key)


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
        self._provenance: dict[str, str] = {}
        self._generation = 0                 # 丢弃过期结果
        self._busy = False
        self._template = "double"
        self._panel_a = True                 # 图层树里的「面板 A」是否参与成图
        self._region: tuple[int, int, int, int] | None = None
        self._grid_step: float | None = None
        self._build_ui()

    # ================= 构建 =================
    def _build_ui(self) -> None:
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # 三栏合计恰好等于窗口宽度时，只要窗口略窄或系统有 DPI 缩放，
        # 固定宽度的右栏就会被整个挤出屏幕之外 —— 用户看到的就是
        # "制图工作台没有导出按钮"。所以中间栏必须允许收缩到很小，
        # 左/右栏保持固定宽度。
        left = self._build_left()
        center = self._build_center()
        right = self._build_right()
        center.setMinimumWidth(280)
        center.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                             QtWidgets.QSizePolicy.Preferred)
        root.addWidget(left)
        root.addWidget(center, 1)
        root.addWidget(right)
        self._update_layout_hint()

    def _build_left(self) -> QtWidgets.QWidget:
        left = QtWidgets.QWidget()
        left.setFixedWidth(236)
        left.setStyleSheet(f"background:{theme.PANEL};border-right:1px solid {theme.LINE};")
        lay = QtWidgets.QVBoxLayout(left)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.hdr_layers = cw.PanelHeader("图层", "")
        lay.addWidget(self.hdr_layers)
        self.layer_list = LayerList()
        self.layer_list.set_layers(self._default_layers())
        self.layer_list.toggled.connect(self._on_layer_toggled)
        lay.addWidget(self.layer_list)

        lay.addWidget(cw.PanelHeader("地图要素", "NE 110m"))
        n_coast = len(cw.coastline_segments())
        self.chk_coast = QtWidgets.QCheckBox(f"海岸线（{n_coast} 段）")
        self.chk_coast.setChecked(True)
        self.chk_coast.setToolTip(
            "叠加 Natural Earth 110m 海岸线（_frame_axes 逐段画线，会改变成图像素）")
        self.chk_grid = QtWidgets.QCheckBox("经纬网")
        self.chk_grid.setChecked(True)
        self.chk_grid.setToolTip("叠加经纬网与 °E/°N 刻度（会改变成图像素）")
        self.chk_colorbar = QtWidgets.QCheckBox("色标")
        self.chk_colorbar.setChecked(True)
        self.chk_colorbar.setToolTip("在红外面板右侧加竖直色标（会改变成图版面）")
        for w in (self.chk_coast, self.chk_grid, self.chk_colorbar):
            w.setStyleSheet("font-size:11px;padding:4px 10px;")
            lay.addWidget(w)

        lay.addWidget(cw.PanelHeader("经纬网间隔"))
        self.chips_step = cw.ChipRow(
            list(GRID_STEP_OPTIONS), current="自动")
        self.chips_step.chipClicked.connect(self._on_grid_step)
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
        self.btn_region.setToolTip("读取 01 主界面画布上的框选矩形；未框选时按全幅出图")
        self.btn_region.setStyleSheet("margin:2px 10px 8px 10px;font-size:10px;")
        self.btn_region.clicked.connect(self._on_pick_region)
        lay.addWidget(self.btn_region)

        lay.addStretch(1)

        for w in (self.chk_coast, self.chk_grid, self.chk_colorbar):
            w.toggled.connect(self._on_spec_toggle)
        return left

    def _panel_a_togglable(self) -> bool:
        """面板 A 只有当前模板是双面板时才真的能关（单面板本来就没有它）。"""
        return (template_layout(self._template) == "double"
                and template_enabled(self._template))

    def _default_layers(self) -> list[tuple]:
        """未加载数据时的图层树。可切换的只有真的会改变成图的 4 项。"""
        coast_on = self.chk_coast.isChecked() if hasattr(self, "chk_coast") else True
        grid_on = self.chk_grid.isChecked() if hasattr(self, "chk_grid") else True
        cbar_on = (self.chk_colorbar.isChecked()
                   if hasattr(self, "chk_colorbar") else True)
        panel_a_on = self._panel_a_togglable()
        return [
            ("panelA", "面板 A · 可见光真彩色", self._panel_a, 0, panel_a_on),
            ("panelA_r", "R ← 右侧「通道 R」", True, 1, False),
            ("panelA_g", "G ← 右侧「通道 G」", True, 1, False),
            ("panelA_b", "B ← 右侧「通道 B」", True, 1, False),
            ("panelB", "面板 B · 红外亮温（常开）", True, 0, False),
            ("panelB_range", "色标范围 ← 右侧参数", True, 1, False),
            ("overlay", "海岸线叠加", coast_on, 0, True),
            ("grid", "经纬网", grid_on, 0, True),
            ("colorbar", "色标", cbar_on, 0, True),
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
        # 预览图会远比可用空间大，若让 QLabel 按像素图定尺寸，
        # 它会把中间栏撑到图片宽度，把右栏挤出去。
        self.preview.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                                   QtWidgets.QSizePolicy.Ignored)
        self.preview.setMinimumSize(240, 160)
        self.preview.setScaledContents(False)
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
        self.lbl_layout = QtWidgets.QLabel("")
        self.lbl_layout.setStyleSheet("color:#7fc7d8;font-size:10px;background:transparent;")
        rl.addWidget(self.lbl_layout)
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
        right.setFixedWidth(300)
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
        self.cmb_cmap.setToolTip("色标真的会变：_collect_layers 会把该选择覆盖回 ThermalLayer.cmap")
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
        self.spin_w.setValue(TEMPLATE_SIZES["double"][0])
        self.spin_h = QtWidgets.QDoubleSpinBox()
        self.spin_h.setRange(3, 20)
        self.spin_h.setValue(TEMPLATE_SIZES["double"][1])
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
        for w in (self.cmb_thermal, self.cmb_cmap, self.cmb_vis_r,
                  self.cmb_vis_g, self.cmb_vis_b):
            w.currentIndexChanged.connect(lambda _i: self._schedule_preview())
        self.spin_band.valueChanged.connect(lambda _v: self._schedule_preview())
        self.spin_vmin.valueChanged.connect(lambda _v: self._schedule_preview())
        self.spin_vmax.valueChanged.connect(lambda _v: self._schedule_preview())
        self.cmb_cmap.currentIndexChanged.connect(self._on_cmap)
        return right

    # ================= 数据 =================
    def set_dataset(self, ds, region_px: tuple[int, int, int, int] | None = None) -> None:
        self._ds = ds
        self._region = tuple(region_px) if region_px else None
        self._panel_a = True
        self._classes = classify_dataset(ds) if ds is not None else {}
        if ds is None:
            self.lbl_status.setText("  制图工程 · 未加载数据")
            self._update_region_label()
            return

        images = [n for n, c in self._classes.items() if c.is_image]
        # 真彩色 b1-b4（0.47/0.55/0.65/0.87µm）在 **EV_250_Aggr.1KM_RefSB**，
        # 而 EV_1KM_RefSB 是 b5-b19（1.38µm 起全在短波红外），
        # 拿它做真彩色会得到一片青/黄绿的错误图像。
        vis = [n for n in images if "EV_250" in n and "refsb" in n.lower()]
        if not vis:
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
        self._update_region_label()

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
            rows = self._default_layers()
        else:
            ther = self.cmb_thermal.currentData() or "—"
            vis = self.cmb_vis_r.currentData() or "—"
            vis_leaf = vis.split("/")[-1]
            panel_a_on = self._panel_a_togglable()
            rows = [
                ("panelA", "面板 A · 可见光真彩色", self._panel_a, 0, panel_a_on),
                ("panelA_r", f"R = {vis_leaf}", True, 1, False),
                ("panelA_g", f"G = {vis_leaf}", True, 1, False),
                ("panelA_b", f"B = {vis_leaf}", True, 1, False),
                ("panelB", f"面板 B · {ther.split('/')[-1]}（常开）", True, 0, False),
                ("panelB_range", f"{self.cmb_cmap.currentText()} · "
                                 f"{self.spin_vmin.value():.0f}–{self.spin_vmax.value():.0f} K",
                 True, 1, False),
                ("overlay", f"海岸线（{len(cw.coastline_segments())} 段）",
                 self.chk_coast.isChecked(), 0, True),
                ("grid", "经纬网", self.chk_grid.isChecked(), 0, True),
                ("colorbar", "色标", self.chk_colorbar.isChecked(), 0, True),
            ]
        self.layer_list.set_layers(rows)
        n_toggle = sum(1 for r in rows if (len(r) > 4 and r[4]))
        self.hdr_layers.set_badge(f"{n_toggle} 可切换")
        self._update_layout_hint()

    def preview_ready(self) -> bool:
        return self._preview_path is not None and self._preview_path.exists()

    # ================= 版式 / 图层开关 =================
    def _effective_layout(self) -> str:
        """最终交给 sciencefig 的 layout（面板 A 关闭时退化为单面板）。"""
        layout = template_layout(self._template)
        if not template_enabled(self._template):
            layout = "double"
        if layout == "double" and not self._panel_a:
            return "single"
        return layout if layout in SUPPORTED_LAYOUTS else "double"

    def _update_layout_hint(self) -> None:
        if not hasattr(self, "lbl_layout"):
            return
        layout = self._effective_layout()
        text = f"版式 · {'双面板（2 面板）' if layout == 'double' else '单面板（1 面板）'}"
        if template_layout(self._template) == "double" and not self._panel_a:
            text += " · 面板 A 已关闭"
        self.lbl_layout.setText(text)

    def _on_template(self, key: str) -> None:
        if not template_enabled(key):
            return                          # 置灰模板不接受切换
        self._template = key
        w, h = template_size(key)
        for spin, val in ((self.spin_w, w), (self.spin_h, h)):
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)
        self.tplbar.set_current(key)
        if template_layout(key) == "double":
            self._panel_a = True            # 双面板当然要面板 A
        self._refresh_layers()
        self._schedule_preview()

    def set_template(self, key: str) -> None:
        """程序化切换模板（测试 / 批量用；等价于点击模板条）。"""
        self._on_template(key)
        self.tplbar.set_current(self._template)

    def _on_layer_toggled(self, key: str, on: bool) -> None:
        if key == "overlay":
            self.chk_coast.setChecked(on)
        elif key == "grid":
            self.chk_grid.setChecked(on)
        elif key == "colorbar":
            self.chk_colorbar.setChecked(on)
        elif key == "panelA":
            if not self._panel_a_togglable():
                return                      # 单面板版式下没有面板 A 可关
            self._panel_a = on
            self._refresh_layers()
            self._schedule_preview()
        else:
            self._schedule_preview()

    def _on_spec_toggle(self, _on: bool) -> None:
        """三个地图要素复选框：刷新图层树状态 + 重排预览。"""
        self._refresh_layers()
        self._schedule_preview()

    def _on_grid_step(self, text: str) -> None:
        self._grid_step = GRID_STEP_OPTIONS.get(text)
        self._schedule_preview()

    def _on_cmap(self, _i: int) -> None:
        self._refresh_layers()
        self._schedule_preview()

    # ================= 选区 =================
    def set_region(self, region_px: tuple[int, int, int, int] | None, *,
                   refresh: bool = True) -> None:
        """设置出图范围（像素 (r0, r1, c0, c1)；None = 全幅）。"""
        new = tuple(int(v) for v in region_px) if region_px else None
        changed = new != self._region
        self._region = new
        self._update_region_label()
        if refresh and changed and self._ds is not None:
            self._schedule_preview()

    def region(self) -> tuple[int, int, int, int] | None:
        return self._region

    def adopt_selection(self, window=None) -> tuple[int, int, int, int] | None:
        """把主界面画布的框选矩形带进制图工作台。

        只读 ``MainWindow._selection``，不反向依赖其实现：拿不到就返回 None
        （按全幅出图），所以没有主窗口时（测试 / 单屏）也不会炸。
        """
        w = window or self.window()
        sel = getattr(w, "_selection", None)
        if not sel:
            return None
        self.set_region(sel)
        return self._region

    def _on_pick_region(self) -> None:
        sel = self.adopt_selection()
        if sel is None:
            self.lbl_region.setText("全幅（主界面未框选）")
            self.lbl_status.setText("  制图工程 · 主界面没有框选区域，按全幅出图")
        else:
            self.lbl_status.setText(
                "  制图工程 · 已采用主界面选区 "
                f"({sel[0]},{sel[1]})×({sel[2]},{sel[3]})")

    def _update_region_label(self) -> None:
        r = self._region
        if r:
            self.lbl_region.setText(
                f"像素 行 {r[0]}–{r[1]} × 列 {r[2]}–{r[3]}"
                f"（{r[1] - r[0]} × {r[3] - r[2]}）")
        else:
            self.lbl_region.setText("全幅")

    # ================= 预览 =================
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

        def work():
            return self._render(spec, max_cells=200_000)

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

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        # 切到 04 屏时自动带上主界面的框选区域。
        # MainWindow.goto_screen 只在进入时传一次，之后用户再框选就靠这里同步。
        if self._ds is not None:
            try:
                self.adopt_selection()
            except Exception:               # noqa: BLE001
                pass

    def _forget(self, worker: Worker) -> None:
        try:
            self._jobs.remove(worker)
        except ValueError:
            pass

    # ================= 出图参数 =================
    def _build_spec(self, out: Path, preview: bool = False) -> FigureSpec:
        layout = self._effective_layout()
        coast = cw.find_coastline_path()
        if preview:
            dpi = 110
            figsize = _PREVIEW_SIZES.get(layout, _PREVIEW_SIZES["double"])
        else:
            dpi = self.spin_dpi.value()
            figsize = (self.spin_w.value(), self.spin_h.value())
        spec = FigureSpec(
            out_path=out,
            layout=layout,
            dpi=dpi,
            figsize=figsize,
            title=self.edit_title.text().strip(),
            subtitle=self.edit_subtitle.text().strip(),
            draw_grid=self.chk_grid.isChecked(),
            draw_coast=self.chk_coast.isChecked(),
            colorbar=self.chk_colorbar.isChecked(),
            grid_step=self._grid_step,
            thermal_range=(self.spin_vmin.value(), self.spin_vmax.value()),
            cmap_thermal=self.cmb_cmap.currentText(),
            # 关键：把正确路径显式传进去，否则 sciencefig 默认找不到资源
            coastline_path=coast,
        )
        if preview:
            spec.title = spec.title[:60]
        return spec

    # ================= 建层 + 渲染（预览/导出共用） =================
    def _collect_layers(self, max_cells: int) -> tuple[dict, dict | None]:
        """按当前界面参数构建图层数据（不含排版）。

        预览与导出共用这一条路径，保证"预览看到的"就是"导出的那张"。
        """
        from .. import pipeline

        if self._ds is None:
            raise RuntimeError("尚未加载产品")
        thermal_var = self.cmb_thermal.currentData()
        if not thermal_var:
            raise RuntimeError("没有可选的红外通道（该产品没有可成像数据集）")
        band = max(0, self.spin_band.value() - 1)
        layout = self._effective_layout()
        vis_names = (self.cmb_vis_r.currentData(), self.cmb_vis_g.currentData(),
                     self.cmb_vis_b.currentData())

        thermal, visible = pipeline.build_layers(
            self._ds,
            thermal_var=thermal_var, thermal_band=band,
            visible_vars=vis_names if layout == "double" else None,
            visible_bands=(2, 1, 0),        # b3/b2/b1 = 0.65/0.55/0.47µm
            region_px=self._region,
            max_cells=max_cells,
        )
        # build_layers 里的 ThermalLayer.cmap 写死 "turbo"，而 sciencefig 取
        # ``t.get("cmap") or spec.cmap_thermal`` —— 于是界面上选色标完全不生效。
        # 这里把用户选择覆盖回去，色标才真的会换。
        thermal.cmap = self.cmb_cmap.currentText()
        return thermal.__dict__, visible

    def _render(self, spec: FigureSpec, max_cells: int) -> Path:
        """建层 + 渲染，整段串行化（matplotlib / HDF5 都不是线程安全的）。"""
        with _RENDER_LOCK:
            thermal, visible = self._collect_layers(max_cells)
            return render_science_figure(thermal, visible, spec)

    # ================= 溯源 =================
    def provenance(self) -> dict[str, str]:
        """当前出图参数的溯源字段（fysat.provenance.build_provenance）。"""
        from ..provenance import build_provenance

        extra = {
            "figure_bench": "04 制图工作台",
            "template": self._template,
            "layout": self._effective_layout(),
            "thermal_var": self.cmb_thermal.currentData() or "",
            "thermal_band": str(max(0, self.spin_band.value() - 1)),
            "cmap": self.cmb_cmap.currentText(),
            "dpi": str(self.spin_dpi.value()),
            "figsize": f"{self.spin_w.value():g}x{self.spin_h.value():g}in",
            "region_px": (",".join(str(v) for v in self._region)) if self._region else "full",
            "draw_coast": "1" if self.chk_coast.isChecked() else "0",
            "draw_grid": "1" if self.chk_grid.isChecked() else "0",
            "colorbar": "1" if self.chk_colorbar.isChecked() else "0",
        }
        try:
            return build_provenance(self._ds, variable=self.cmb_thermal.currentData(),
                                    extra=extra)
        except Exception:                       # noqa: BLE001
            return {"software": "FY-Sat Studio", **extra}

    # ================= 导出 =================
    def export_to(self, path: str | Path, *, with_provenance: bool = True) -> Path:
        """把当前参数渲染到 ``path`` —— **不弹任何对话框**。

        这是脚本 / 批量 / 测试用的入口（``export()`` 只是它的对话框外壳）：

        - 路径没后缀时按「导出 · 格式」补 .png/.pdf/.svg
        - 成图参数完全取自当前界面状态（版式 / 图层开关 / 色标 / 尺寸 / DPI）
        - ``with_provenance``：溯源写进页脚，PNG 另嵌 ``fysat.*`` tEXt

        返回实际写出的路径；失败直接抛异常（由调用方决定怎么提示）。
        """
        if self._ds is None:
            raise RuntimeError("尚未加载产品：export_to 需要先 set_dataset(ds)")

        out = Path(path)
        fmt = self.cmb_format.currentText().lower()
        if not out.suffix:
            out = out.with_suffix("." + fmt)

        spec = self._build_spec(out, preview=False)
        prov = self.provenance() if with_provenance else {}
        if prov:
            spec.footer = _footer_from_provenance(prov)

        rendered = Path(self._render(spec, max_cells=400_000))

        if with_provenance and rendered.suffix.lower() == ".png":
            try:
                _embed_png_provenance(rendered, prov)
            except Exception as exc:            # noqa: BLE001
                # 嵌元数据失败不该让整个导出失败（图已经出来了）
                import sys

                print(f"[warn] PNG 溯源嵌入失败: {exc}", file=sys.stderr)

        self._last_out = rendered
        self._provenance = prov
        self.lbl_status.setText(
            f"  已导出 {rendered.name}（{rendered.stat().st_size / 1e3:.0f} KB）"
            f"   |   {self._effective_layout()}")
        return rendered

    def export(self) -> Path | None:
        """弹一次保存对话框拿到路径，然后交给 ``export_to`` 出图。"""
        if self._ds is None:
            QtWidgets.QMessageBox.information(self, "提示", "请先加载产品")
            return None
        fmt = self.cmb_format.currentText().upper()
        path, _sel = QtWidgets.QFileDialog.getSaveFileName(
            self, "保存制图", f"figure.{fmt.lower()}",
            FORMAT_FILTERS.get(fmt, "PNG 图片 (*.png)"))
        if not path:
            return None
        try:
            return self.export_to(Path(path))
        except Exception as exc:                # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "导出失败", str(exc))
            return None

    def last_export_path(self) -> Path | None:
        return self._last_out

    # ================= 生命周期 =================
    def closeEvent(self, ev) -> None:
        for w in list(self._jobs):
            self._pool.tryTake(w)
        self._pool.waitForDone(3000)
        self._jobs.clear()
        super().closeEvent(ev)


__all__ = [
    "FigureBench", "TEMPLATES", "TEMPLATE_SIZES", "GRID_STEP_OPTIONS",
    "TemplateBar", "LayerList", "template_enabled", "template_layout",
    "template_size",
]
