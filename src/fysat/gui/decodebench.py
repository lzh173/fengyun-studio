"""03 解码工作台：输入队列 + 七步解析流水线 + 字段表 + 日志。

对应设计稿 ``ui-mockup/03_decode.html``。

这一屏的重点不是"再画一张图"，而是把**解码过程本身**呈现出来：
用户放一批文件进去，能看见每个文件走到第几步、每一步得到什么、
字段的 scale/offset/有效范围是多少、最后由哪些校验把它判定为合格。

七步流水线与实现映射
--------------------
1. 格式识别     ``detect.sniff``         → hdf5 / netcdf4 / netcdf3 / fy2_csv / oneb / awx
2. 头与属性     ``readers.open_file(load=False)`` → 全局属性数、卫星/仪器/时间
3. 产品定义     ``SatDataset.product_def``（可能为空，空则标注"未匹配"）
4. 定标/物理量  检查变量的 scale/offset/fill/valid_range，判定能否定标
5. 定位/投影     ``ds.geolocation.kind`` → latlon_grid / glt / nominal / none
6. 标准化输出   （本工作台不真正写盘，只报告"就绪"与预计尺寸）
7. 一致性校验   填充值/有效范围/时间戳/几何匹配的自检清单

并发模型
--------
同时解码 N 个文件，每个文件一个 ``Worker``。进度靠 Worker 的
``progress`` 信号 + 主线程里按步骤推进；为避免跨线程改 UI，
真正耗时的只有前三步（读文件），后四步是纯元数据分析，很快。

坑
--
- ``Worker`` 必须被列表持有（``self._jobs``），否则 QRunnable 被 GC，
  表现为"任务提交了永远不完成"。
- Worker 的 Signals 不能随 runner 销毁，workers.py 已固定 autoDelete=False。
- 进度槽里改 UI 必须回主线程：这里靠 Signal 的队列连接天然满足。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..detect import sniff
from ..readers import open_file
from . import chartwidgets as cw
from . import theme
from .workers import Worker

STEP_NAMES = ["格式识别", "头与属性", "产品定义", "定标 / 物理量",
              "定位 / 投影", "标准化输出", "一致性校验"]

KIND_LABEL = {
    "hdf5": "HDF5", "netcdf4": "NetCDF-4", "netcdf3": "NetCDF-3",
    "fy2_csv": "FY-2 CSV", "oneb": "1B", "awx": "AWX",
    "jpeg": "JPEG", "png": "PNG", "tiff": "TIFF", "unknown": "未知",
}

LOG_STYLE = {
    "info": theme.BLUE, "ok": theme.GREEN,
    "warn": theme.AMBER, "err": theme.RED, "dim": theme.DIM2,
}


@dataclass
class FieldRow:
    """字段表的一行。"""

    name: str
    dtype: str = "—"
    shape: str = "—"
    unit: str = "—"
    scale: str = "—"
    offset: str = "—"
    valid: str = "—"
    fill: str = "—"
    kind: str = ""


@dataclass
class QueueItem:
    """队列里的一个待解码文件及其解析结果。"""

    path: Path
    status: str = "wait"          # wait | running | done | failed
    step: int = 0                 # 已完成到第几步（0..7）
    kind: str = "unknown"
    ds: object = None
    error: str = ""
    elapsed: float = 0.0
    fields: list[FieldRow] = field(default_factory=list)
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def size_text(self) -> str:
        try:
            n = self.path.stat().st_size
        except OSError:
            return "—"
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024.0
        return "—"

    def progress_pct(self) -> int:
        return int(round(100.0 * self.step / len(STEP_NAMES)))


def _fmt_num(v, nd: int = 4) -> str:
    if v is None:
        return "—"
    try:
        f = float(np.asarray(v).reshape(-1)[0])
    except Exception:                       # noqa: BLE001
        return str(v)
    if not np.isfinite(f):
        return "—"
    if f == int(f) and abs(f) < 1e9:
        return str(int(f))
    return f"{f:.{nd}g}"


def _fmt_shape(shape) -> str:
    t = tuple(int(s) for s in shape)
    if len(t) == 2 and t[0] == t[1]:
        return f"{t[0]}²"
    if len(t) == 1:
        return str(t[0])
    return "×".join(str(s) for s in t)


def analyze_dataset(item: QueueItem, emit_log) -> None:
    """对已打开的数据集做第 3-7 步分析（在后台线程里跑）。

    只读元数据，不触发大数组加载，所以很快。
    """
    ds = item.ds
    if ds is None:
        raise RuntimeError("数据集为空")

    # ---- 3. 产品定义 ----
    item.step = 3
    pdef = getattr(ds, "product_def", "") or ""
    item.meta["product_def"] = pdef or "未匹配"
    emit_log("info", f"{item.name}：产品定义 {pdef or '未匹配（按容器通用规则解析）'}")

    # ---- 4. 定标 / 物理量 ----
    item.step = 4
    n_scaled = 0
    n_fill = 0
    for v in ds.variables.values():
        if v.scale_factor is not None or v.add_offset is not None:
            n_scaled += 1
        if v.fill_value is not None:
            n_fill += 1
    item.meta["n_scaled"] = n_scaled
    item.meta["n_fill"] = n_fill

    # ---- 5. 定位 / 投影 ----
    item.step = 5
    geo = ds.geolocation
    kind = geo.kind if geo is not None else "none"
    item.meta["geo"] = kind
    b = geo.bounds() if geo is not None else None
    item.meta["bounds"] = b

    # ---- 6. 标准化输出（只报告，不写盘）----
    item.step = 6
    images = 0
    try:
        from .varcatalog import classify_dataset

        classes = classify_dataset(ds)
        images = sum(1 for c in classes.values() if c.is_image)
    except Exception:                       # noqa: BLE001
        classes = {}
    item.meta["n_image"] = images

    # ---- 字段表 ----
    rows: list[FieldRow] = []
    for name, v in ds.variables.items():
        c = classes.get(name)
        rows.append(FieldRow(
            name=name,
            dtype=str(getattr(v, "dtype", "—")),
            shape=_fmt_shape(getattr(v, "shape", ())),
            unit=v.unit or "—",
            scale=_fmt_num(v.scale_factor),
            offset=_fmt_num(v.add_offset),
            valid=(" – ".join(_fmt_num(x) for x in v.valid_range)
                   if v.valid_range else "—"),
            fill=_fmt_num(v.fill_value),
            kind=c.kind if c else "",
        ))
    item.fields = rows

    # ---- 7. 一致性校验 ----
    item.step = 7
    checks: list[tuple[str, bool, str]] = []
    attrs = ds.attrs or {}
    checks.append((f"全局属性可读（{len(attrs)} 个）", len(attrs) > 0,
                   "" if attrs else "无全局属性"))
    checks.append((f"变量表可读（{len(ds.variables)} 个）", len(ds.variables) > 0,
                   "" if ds.variables else "无变量"))
    has_unit = sum(1 for v in ds.variables.values() if v.unit and v.unit != "none")
    checks.append((f"物理单位完整（{has_unit}/{len(ds.variables)}）",
                   has_unit > 0, "" if has_unit else "全部变量缺单位"))
    checks.append(("定标系数可解析", n_scaled > 0 or n_fill > 0,
                   "" if (n_scaled or n_fill) else "未见 scale/offset/fill"))
    checks.append((f"定位方式：{kind}", kind != "none",
                   "" if kind != "none" else "无定位信息，仅能按像素出图"))
    if b:
        lon0, lon1, lat0, lat1 = b
        ok = np.isfinite([lon0, lon1, lat0, lat1]).all() and lon1 > lon0 and lat1 > lat0
        checks.append((f"经纬范围有效（{lon0:.2f}~{lon1:.2f}E, {lat0:.2f}~{lat1:.2f}N）",
                       bool(ok), "" if ok else "范围含填充值或次序颠倒"))
    if ds.start_time:
        checks.append((f"时间戳可解析（{ds.start_time:%Y-%m-%d %H:%M}）", True, ""))
    else:
        checks.append(("时间戳可解析", False, "文件里没有可用时间"))
    item.checks = checks
    item.step = len(STEP_NAMES)


class StepBar(QtWidgets.QWidget):
    """七步流水线可视化：圆形序号 + 名称 + 简短说明 + 连接线。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.steps = list(STEP_NAMES)
        self._meta = [""] * len(self.steps)
        self._done = 0                 # 已完成步数
        self._active = -1              # 当前进行中的步（-1 表示无）
        self.setMinimumHeight(78)

    def set_progress(self, done: int, active: int = -1,
                     meta: list[str] | None = None) -> None:
        self._done = int(max(0, min(done, len(self.steps))))
        self._active = active
        if meta is not None:
            self._meta = (list(meta) + [""] * len(self.steps))[: len(self.steps)]
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), qcolor_bg())
        n = len(self.steps)
        if n == 0:
            p.end()
            return
        w = self.width() / n
        cy = 26
        r = 12

        for i, name in enumerate(self.steps):
            cx = w * i + 16
            if i < self._done:
                state = "done"
            elif i == self._active or (self._active < 0 and i == self._done):
                state = "act"
            else:
                state = "wait"

            # 连接线（先画在圆下面）
            if i < n - 1:
                x2 = w * (i + 1) + 16
                pen = QtGui.QPen(
                    QtGui.QColor("#1a6b4a" if i < self._done else "#25303c"), 1)
                p.setPen(pen)
                p.drawLine(QtCore.QPointF(cx + r + 3, cy),
                           QtCore.QPointF(x2 - r - 3, cy))

            # 圆
            fill, border, text = {
                "done": ("#0f3d2c", "#1a6b4a", theme.GREEN),
                "act": ("#0e3a48", "#1d6b80", "#9fe9f5"),
                "wait": ("#161c24", "#2a3341", theme.DIM2),
            }[state]
            p.setPen(QtGui.QPen(QtGui.QColor(border), 1))
            p.setBrush(QtGui.QColor(fill))
            p.drawEllipse(QtCore.QPointF(cx, cy), r, r)
            p.setPen(QtGui.QColor(text))
            p.setFont(QtGui.QFont(self.font().family(), 9, QtGui.QFont.Bold))
            p.drawText(QtCore.QRectF(cx - r, cy - r, 2 * r, 2 * r),
                       QtCore.Qt.AlignCenter,
                       "✓" if state == "done" else str(i + 1))

            # 名称
            p.setPen(QtGui.QColor("#cfd8e3" if state != "wait" else theme.DIM2))
            p.setFont(QtGui.QFont(self.font().family(), 8))
            p.drawText(QtCore.QRectF(w * i, cy + r + 6, w, 14),
                       QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, name)
            # 说明
            if self._meta[i]:
                p.setPen(QtGui.QColor(theme.DIM2))
                p.setFont(QtGui.QFont("Consolas", 7))
                p.drawText(QtCore.QRectF(w * i, cy + r + 19, w, 12),
                           QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                           str(self._meta[i])[:22])
        p.end()


def qcolor_bg() -> QtGui.QColor:
    return QtGui.QColor("#0a0d12")


class QueueItemWidget(QtWidgets.QFrame):
    """左栏队列卡片：状态图标 + 文件名 + 百分比 + 元信息 + 进度条。"""

    clicked = QtCore.Signal(object)          # QueueItem

    def __init__(self, item: QueueItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("qi")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(3)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(6)
        self.lbl_icon = QtWidgets.QLabel("◷")
        self.lbl_icon.setStyleSheet("color:#7dd3fc;font-size:11px;background:transparent;")
        self.lbl_name = QtWidgets.QLabel(item.name)
        self.lbl_name.setStyleSheet("color:#c9d3e0;font-size:10px;background:transparent;")
        self.lbl_name.setToolTip(str(item.path))
        self.lbl_pct = QtWidgets.QLabel("等待")
        self.lbl_pct.setStyleSheet(
            "color:#9fe9f5;font-family:Consolas,monospace;font-size:9.5px;"
            "background:transparent;")
        top.addWidget(self.lbl_icon)
        top.addWidget(self.lbl_name, 1)
        top.addWidget(self.lbl_pct)
        lay.addLayout(top)

        self.lbl_sub = QtWidgets.QLabel(f"{item.size_text}  ·  {item.kind}")
        self.lbl_sub.setStyleSheet(
            "color:#5f6a7a;font-family:Consolas,monospace;font-size:9px;"
            "background:transparent;")
        lay.addWidget(self.lbl_sub)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(3)
        lay.addWidget(self.bar)

        self._refresh_style()

    def _refresh_style(self) -> None:
        st = self.item.status
        border = {"running": "#1d5f70", "done": "#1a6b4a",
                  "failed": "#652a33"}.get(st, "#1e2632")
        bg = {"running": "#0f2530", "done": "#0f1a16"}.get(st, "#0f1319")
        self.setStyleSheet(
            f'QFrame#qi{{border:1px solid {border};border-radius:6px;'
            f'background:{bg};}}')

    def refresh(self) -> None:
        it = self.item
        self.lbl_icon.setText(
            {"wait": "◷", "running": "▶", "done": "✓", "failed": "✕"}.get(it.status, "◷"))
        self.lbl_pct.setText(
            {"wait": "等待", "running": f"解码中 {it.progress_pct()}%",
             "done": "完成", "failed": "失败"}.get(it.status, it.status))
        self.lbl_sub.setText(
            f"{it.size_text}  ·  {KIND_LABEL.get(it.kind, it.kind)}"
            + (f"  ·  {it.meta.get('product_def', '')}"
               if it.meta.get("product_def") else ""))
        self.bar.setValue(100 if it.status == "done" else it.progress_pct())
        self._refresh_style()

    def mousePressEvent(self, ev) -> None:
        self.clicked.emit(self.item)
        super().mousePressEvent(ev)


class DecodeBench(QtWidgets.QWidget):
    """03 解码工作台整屏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QtCore.QThreadPool.globalInstance()
        self._jobs: list[Worker] = []
        self._items: list[QueueItem] = []
        self._cards: list[QueueItemWidget] = []
        self._current: QueueItem | None = None
        self._running = 0
        self._t0 = 0.0
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
        left.setFixedWidth(286)
        left.setStyleSheet(f"background:{theme.PANEL};border-right:1px solid {theme.LINE};")
        lay = QtWidgets.QVBoxLayout(left)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.head_queue = cw.PanelHeader("输入队列", "0")
        lay.addWidget(self.head_queue)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent;")
        self.queue_host = QtWidgets.QWidget()
        self.queue_lay = QtWidgets.QVBoxLayout(self.queue_host)
        self.queue_lay.setContentsMargins(6, 6, 6, 6)
        self.queue_lay.setSpacing(6)
        self.queue_lay.addStretch(1)
        scroll.setWidget(self.queue_host)
        scroll.setFixedHeight(240)
        lay.addWidget(scroll)

        row = QtWidgets.QWidget()
        rl = QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(6, 2, 6, 6)
        rl.setSpacing(5)
        self.btn_add = QtWidgets.QPushButton("添加文件")
        self.btn_adddir = QtWidgets.QPushButton("添加目录")
        rl.addWidget(self.btn_add)
        rl.addWidget(self.btn_adddir)
        lay.addWidget(row)

        lay.addWidget(cw.PanelHeader("解析器 / 插件", "5"))
        self.declist = QtWidgets.QListWidget()
        self.declist.setStyleSheet(
            "QListWidget{background:transparent;border:none;font-size:11px;}"
            "QListWidget::item{padding:4px 10px;color:#c3ccda;}")
        self.declist.setFixedHeight(120)
        lay.addWidget(self.declist)
        self._fill_declist()

        lay.addWidget(cw.PanelHeader("输出", "统一模型"))
        form = QtWidgets.QWidget()
        fl = QtWidgets.QFormLayout(form)
        fl.setContentsMargins(10, 6, 10, 6)
        fl.setSpacing(5)
        self.cmb_format = QtWidgets.QComboBox()
        self.cmb_format.addItems(["GeoTIFF + NetCDF", "GeoTIFF", "NetCDF", "PNG"])
        self.cmb_geo = QtWidgets.QComboBox()
        self.cmb_geo.addItems(["保持原网格", "等经纬 0.05°", "等经纬 0.02°"])
        self.edit_outdir = QtWidgets.QLineEdit("out/decoded")
        fl.addRow("输出格式", self.cmb_format)
        fl.addRow("重采样", self.cmb_geo)
        fl.addRow("输出目录", self.edit_outdir)
        lay.addWidget(form)
        lay.addStretch(1)

        self.btn_add.clicked.connect(self._choose_files)
        self.btn_adddir.clicked.connect(self._choose_dir)
        return left

    def _fill_declist(self) -> None:
        """列出已注册的读取器与实际可用性（不是写死的理想清单）。"""
        try:
            from ..detect import EXT_MAP  # noqa: F401
            from ..readers import kinds

            avail = set(kinds())
        except Exception:                       # noqa: BLE001
            avail = set()
        entries = [
            ("HDF5（FY-3 MERSI / VIRR）", "hdf5", "L1 · L2"),
            ("NetCDF-4（FY-4A/4B AGRI）", "netcdf4", "L1 · L2"),
            ("NetCDF-3（FY-2 旧格式）", "netcdf3", "L1"),
            ("FY-2 CSV 容器", "fy2_csv", "L1"),
            ("1B（NOAA/FY-1）", "oneb", "L1"),
            ("AWX 2.1（FY-2 产品）", "awx", "L2"),
        ]
        self.declist.clear()
        for label, key, meta in entries:
            ok = key in avail
            dot = "●" if ok else "○"
            color = theme.GREEN if ok else theme.DIM2
            it = QtWidgets.QListWidgetItem(f"{dot}  {label}      {meta if ok else '未注册'}")
            it.setForeground(QtGui.QColor(color))
            self.declist.addItem(it)

    def _build_center(self) -> QtWidgets.QWidget:
        center = QtWidgets.QWidget()
        center.setStyleSheet("background:#0a0c10;")
        cl = QtWidgets.QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # ---- 流水线 ----
        pipe = QtWidgets.QWidget()
        pipe.setStyleSheet("background:linear-gradient(180deg,#0d1117,#0a0d12);"
                           "border-bottom:1px solid #1a212b;")
        pl = QtWidgets.QVBoxLayout(pipe)
        pl.setContentsMargins(14, 8, 14, 8)
        pl.setSpacing(4)
        head = QtWidgets.QHBoxLayout()
        self.lbl_pipe_title = QtWidgets.QLabel("官方数据解码流水线")
        self.lbl_pipe_title.setStyleSheet(
            "color:#e2e8f0;font-size:12px;font-weight:600;background:transparent;")
        self.lbl_pipe_sub = QtWidgets.QLabel("未选择文件")
        self.lbl_pipe_sub.setStyleSheet(
            "color:#7f8b9c;font-size:10.5px;background:transparent;")
        self.lbl_pipe_chip = QtWidgets.QLabel("● 就绪")
        self.lbl_pipe_chip.setStyleSheet(
            "color:#9fe9f5;background:#0f2b36;border:1px solid #1d5f70;"
            "border-radius:9px;padding:1px 8px;font-size:10px;")
        head.addWidget(self.lbl_pipe_title)
        head.addWidget(self.lbl_pipe_sub, 1)
        head.addWidget(self.lbl_pipe_chip)
        pl.addLayout(head)
        self.stepbar = StepBar()
        pl.addWidget(self.stepbar)
        cl.addWidget(pipe)

        # ---- 文件结构 + 字段表 ----
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.setStyleSheet("QSplitter::handle{background:#1a212b;width:1px;}")
        split.addWidget(self._build_tree_panel())
        split.addWidget(self._build_fields_panel())
        split.setSizes([280, 620])
        cl.addWidget(split, 1)

        # ---- 日志 ----
        cl.addWidget(self._build_log())
        return center

    def _build_tree_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QFrame()
        panel.setStyleSheet("QFrame{background:#07090d;border:1px solid #1c2430;"
                            "border-radius:6px;}")
        pl = QtWidgets.QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        h = QtWidgets.QWidget()
        h.setFixedHeight(24)
        h.setStyleSheet("background:#10141a;border-bottom:1px solid #1a212b;"
                        "border-top-left-radius:6px;border-top-right-radius:6px;")
        hl = QtWidgets.QHBoxLayout(h)
        hl.setContentsMargins(9, 0, 9, 0)
        lbl = QtWidgets.QLabel("文件结构")
        lbl.setStyleSheet("color:#8fa0b5;font-size:10px;background:transparent;")
        self.lbl_tree_kind = QtWidgets.QLabel("—")
        self.lbl_tree_kind.setStyleSheet(
            "color:#5f6a7a;font-family:Consolas,monospace;font-size:9.5px;"
            "background:transparent;")
        hl.addWidget(lbl)
        hl.addStretch(1)
        hl.addWidget(self.lbl_tree_kind)
        pl.addWidget(h)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet(
            "QTreeWidget{background:#07090d;border:none;font-family:Consolas,monospace;"
            "font-size:10px;color:#b9c4d1;}"
            "QTreeWidget::item{padding:2px 2px;}")
        pl.addWidget(self.tree, 1)
        return panel

    def _build_fields_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QFrame()
        panel.setStyleSheet("QFrame{background:#07090d;border:1px solid #1c2430;"
                            "border-radius:6px;}")
        pl = QtWidgets.QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        h = QtWidgets.QWidget()
        h.setFixedHeight(24)
        h.setStyleSheet("background:#10141a;border-bottom:1px solid #1a212b;"
                        "border-top-left-radius:6px;border-top-right-radius:6px;")
        hl = QtWidgets.QHBoxLayout(h)
        hl.setContentsMargins(9, 0, 9, 0)
        lbl = QtWidgets.QLabel("字段解析")
        lbl.setStyleSheet("color:#8fa0b5;font-size:10px;background:transparent;")
        self.lbl_field_count = QtWidgets.QLabel("0 个字段")
        self.lbl_field_count.setStyleSheet(
            "color:#5f6a7a;font-family:Consolas,monospace;font-size:9.5px;"
            "background:transparent;")
        hl.addWidget(lbl)
        hl.addStretch(1)
        hl.addWidget(self.lbl_field_count)
        pl.addWidget(h)

        self.tbl_fields = QtWidgets.QTableWidget(0, 8)
        self.tbl_fields.setHorizontalHeaderLabels(
            ["字段", "类型", "形状", "单位", "scale", "offset", "有效范围", "填充"])
        self.tbl_fields.verticalHeader().setVisible(False)
        self.tbl_fields.setAlternatingRowColors(True)
        self.tbl_fields.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tbl_fields.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tbl_fields.horizontalHeader().setStretchLastSection(True)
        self.tbl_fields.setColumnWidth(0, 190)
        self.tbl_fields.setColumnWidth(1, 62)
        self.tbl_fields.setColumnWidth(2, 86)
        self.tbl_fields.setColumnWidth(3, 76)
        self.tbl_fields.setColumnWidth(4, 64)
        self.tbl_fields.setColumnWidth(5, 60)
        self.tbl_fields.setColumnWidth(6, 90)
        self.tbl_fields.setStyleSheet(
            "QTableWidget{background:#07090d;border:none;font-family:Consolas,monospace;"
            "font-size:9.5px;gridline-color:#141a22;}"
            "QTableWidget::item{padding:2px 6px;}")
        pl.addWidget(self.tbl_fields, 1)
        return panel

    def _build_log(self) -> QtWidgets.QWidget:
        box = QtWidgets.QFrame()
        box.setStyleSheet("QFrame{background:#07090d;border-top:1px solid #1a212b;}")
        box.setFixedHeight(150)
        bl = QtWidgets.QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)

        h = QtWidgets.QWidget()
        h.setFixedHeight(23)
        h.setStyleSheet("background:#0d1117;border-bottom:1px solid #1a212b;")
        hl = QtWidgets.QHBoxLayout(h)
        hl.setContentsMargins(12, 0, 12, 0)
        lbl = QtWidgets.QLabel("解码日志")
        lbl.setStyleSheet("color:#c9d3e0;font-size:10px;font-weight:600;"
                          "background:transparent;")
        self.lbl_log_count = QtWidgets.QLabel("0 条")
        self.lbl_log_count.setStyleSheet(
            "color:#5f6a7a;font-family:Consolas,monospace;font-size:9px;"
            "background:transparent;")
        btn_clear = QtWidgets.QPushButton("清空")
        btn_clear.setFixedHeight(17)
        btn_clear.setStyleSheet("font-size:9px;padding:0 8px;")
        btn_clear.clicked.connect(self.clear_log)
        hl.addWidget(lbl)
        hl.addStretch(1)
        hl.addWidget(self.lbl_log_count)
        hl.addWidget(btn_clear)
        bl.addWidget(h)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(
            "QPlainTextEdit{background:#07090d;border:none;color:#93a0b1;"
            "font-family:Consolas,monospace;font-size:9.5px;padding:4px 10px;}")
        self.log.setMaximumBlockCount(2000)
        bl.addWidget(self.log, 1)
        return box

    def _build_right(self) -> QtWidgets.QWidget:
        right = QtWidgets.QWidget()
        right.setFixedWidth(300)
        right.setStyleSheet(f"background:{theme.PANEL};border-left:1px solid {theme.LINE};")
        lay = QtWidgets.QVBoxLayout(right)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(cw.PanelHeader("一致性校验", "—"))
        self.checks_host = QtWidgets.QWidget()
        self.checks_lay = QtWidgets.QVBoxLayout(self.checks_host)
        self.checks_lay.setContentsMargins(10, 8, 10, 8)
        self.checks_lay.setSpacing(4)
        self.lbl_check_hint = QtWidgets.QLabel("解码完成后显示校验清单")
        self.lbl_check_hint.setWordWrap(True)
        self.lbl_check_hint.setStyleSheet("color:#5f6a7a;font-size:10px;")
        self.checks_lay.addWidget(self.lbl_check_hint)
        self.checks_lay.addStretch(1)
        lay.addWidget(self.checks_host, 1)

        lay.addWidget(cw.PanelHeader("本次统计", "—"))
        self.stat_grid = _DecodeStats()
        self.stat_grid.setFixedHeight(88)
        lay.addWidget(self.stat_grid)

        lay.addWidget(cw.PanelHeader("输出清单", "统一模型"))
        self.lbl_out = QtWidgets.QLabel("尚未产生输出")
        self.lbl_out.setWordWrap(True)
        self.lbl_out.setStyleSheet("color:#5f6a7a;font-size:10px;padding:8px 10px;")
        lay.addWidget(self.lbl_out)
        lay.addStretch(1)
        return right

    # ================= 队列管理 =================
    def add_files(self, paths: list[str]) -> None:
        for p in paths:
            path = Path(p)
            if not path.is_file():
                continue
            if any(it.path == path for it in self._items):
                continue
            try:
                kind = sniff(path)
            except Exception:                   # noqa: BLE001
                kind = "unknown"
            item = QueueItem(path=path, kind=kind)
            self._items.append(item)
            card = QueueItemWidget(item)
            card.clicked.connect(self._select_item)
            self._cards.append(card)
            self.queue_lay.insertWidget(self.queue_lay.count() - 1, card)
        self._refresh_queue_header()

    def _choose_files(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "选择要解码的产品", "",
            "卫星产品 (*.hdf *.HDF *.h5 *.H5 *.nc *.NC *.dat *.DAT *.l1b *.L1B "
            "*.awx *.AWX);;全部 (*.*)")
        if paths:
            self.add_files(paths)

    def _choose_dir(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择数据目录")
        if not d:
            return
        exts = {".hdf", ".h5", ".nc", ".dat", ".l1b", ".awx", ".1b"}
        found = [str(p) for p in sorted(Path(d).rglob("*"))
                 if p.is_file() and p.suffix.lower() in exts]
        if found:
            self.add_files(found)

    def _refresh_queue_header(self) -> None:
        n = len(self._items)
        done = sum(1 for i in self._items if i.status == "done")
        fail = sum(1 for i in self._items if i.status == "failed")
        self.head_queue.set_badge(str(n))
        self.stat_grid.set_values(n_files=n, n_done=done, n_fail=fail)
        self.lbl_out.setText(
            "尚未产生输出" if not done else
            f"已解析 {done} 个产品（本工作台只做解析与校验，不写盘）")

    # ================= 解码 =================
    def is_idle(self) -> bool:
        """是否所有入队文件都已结束（且不会有新的自动开跑）。"""
        if self._running > 0:
            return False
        if not self._items:
            return True
        return all(i.status in ("done", "failed") for i in self._items)

    def has_pending(self) -> bool:
        return any(i.status in ("wait", "running") for i in self._items)

    def run_queue(self) -> None:
        """依次解码队列里所有尚未完成的文件。"""
        pending = [i for i in self._items if i.status in ("wait", "failed")]
        if not pending:
            return
        self._t0 = self._t0 or time.time()
        for item in pending:
            self._start_item(item)

    def _start_item(self, item: QueueItem) -> None:
        item.status = "running"
        item.step = 0
        item.error = ""
        self._running += 1
        self._update_card(item)
        self._select_item(item)
        self._refresh_queue_header()
        path = item.path

        def work():
            t0 = time.perf_counter()
            kind = sniff(path)
            ds = open_file(path, load=False)
            item.kind = kind
            item.ds = ds
            item.step = 2
            self._log("info", f"{item.name}：识别为 {KIND_LABEL.get(kind, kind)}，"
                              f"开始解析")
            return ds

        worker = Worker(work)
        self._jobs.append(worker)

        def _ok(ds) -> None:
            try:
                item.step = 2
                self._update_card(item)
                self._show_item(item)
                analyze_dataset(item, self._log)
                item.status = "done"
                item.elapsed = time.time() - (self._t0 or time.time())
                self._log("ok", f"{item.name}：解码完成，"
                                f"{len(item.fields)} 个字段，"
                                f"{sum(1 for c in item.checks if c[1])}/{len(item.checks)} "
                                f"项校验通过")
                for label, ok, detail in item.checks:
                    if not ok and detail:
                        self._log("warn", f"  {label} — {detail}")
            except Exception as exc:            # noqa: BLE001
                item.status = "failed"
                item.error = f"{type(exc).__name__}: {exc}"
                item.step = 0
                self._log("err", f"{item.name}：{item.error}")
            finally:
                self._running = max(0, self._running - 1)
                self._update_card(item)
                self._show_item(item)
                self._refresh_queue_header()
                self._forget(worker)
                if self._running == 0:
                    self._on_all_done()

        def _fail(msg: str) -> None:
            try:
                item.status = "failed"
                item.error = msg.splitlines()[0] if msg else "未知错误"
                item.step = 0
                self._log("err", f"{item.name}：{item.error}")
            finally:
                self._running = max(0, self._running - 1)
                self._update_card(item)
                self._refresh_queue_header()
                self._forget(worker)
                if self._running == 0:
                    self._on_all_done()

        worker.signals.finished.connect(_ok)
        worker.signals.failed.connect(_fail)
        self._pool.start(worker)

    def _on_all_done(self) -> None:
        self.lbl_pipe_chip.setText("● 全部完成")
        self.stepbar.set_progress(len(STEP_NAMES), active=-1)
        self._refresh_queue_header()

    def _forget(self, worker: Worker) -> None:
        try:
            self._jobs.remove(worker)
        except ValueError:
            pass

    # ================= 展示 =================
    def _select_item(self, item: QueueItem) -> None:
        self._current = item
        self._show_item(item)

    def _update_card(self, item: QueueItem) -> None:
        for card in self._cards:
            if card.item is item:
                card.refresh()
                break

    def _show_item(self, item: QueueItem) -> None:
        self._current = item
        # 流水线
        self.lbl_pipe_title.setText("官方数据解码流水线")
        bits = [item.path.name]
        if item.ds is not None:
            ds = item.ds
            bits = [f"{ds.platform} · {ds.instrument} · {ds.level}"]
            if ds.start_time:
                bits.append(f"{ds.start_time:%Y-%m-%d %H:%M}")
        self.lbl_pipe_sub.setText("  ·  ".join(bits))
        meta = [
            KIND_LABEL.get(item.kind, item.kind),
            f"{len(item.ds.attrs) if item.ds else 0} 个属性",
            item.meta.get("product_def", ""),
            f"{item.meta.get('n_scaled', 0)} 个已定标",
            item.meta.get("geo", ""),
            f"{item.meta.get('n_image', 0)} 个影像",
            f"{sum(1 for c in item.checks if c[1])}/{len(item.checks)} 通过"
            if item.checks else "",
        ]
        self.stepbar.set_progress(item.step, active=item.step
                                  if item.status == "running" else -1, meta=meta)
        self.lbl_pipe_chip.setText(
            {"wait": "● 等待", "running": f"● 解析中 · {item.progress_pct()}%",
             "done": "● 完成", "failed": "● 失败"}.get(item.status, "● 就绪"))

        self._fill_tree(item)
        self._fill_fields(item)
        self._fill_checks(item)

    def _fill_tree(self, item: QueueItem) -> None:
        self.tree.clear()
        ds = item.ds
        self.lbl_tree_kind.setText(KIND_LABEL.get(item.kind, item.kind))
        if ds is None:
            return
        root = QtWidgets.QTreeWidgetItem(self.tree)
        root.setText(0, f"/  {ds.platform} {ds.instrument} {ds.level}")
        root.setExpanded(True)
        f = root.font(0)
        f.setBold(True)
        root.setFont(0, f)

        for k in list(sorted((ds.attrs or {}).keys()))[:14]:
            v = ds.attrs[k]
            text = (np.asarray(v).reshape(-1)[:2].tolist()
                    if isinstance(v, np.ndarray) else v)
            it = QtWidgets.QTreeWidgetItem(root)
            it.setText(0, f"@ {k} = {str(text)[:34]}")
            it.setForeground(0, QtGui.QColor(theme.AMBER))
        if len(ds.attrs or {}) > 14:
            it = QtWidgets.QTreeWidgetItem(root)
            it.setText(0, f"@ … 共 {len(ds.attrs)} 个属性")

        for name, v in ds.variables.items():
            it = QtWidgets.QTreeWidgetItem(root)
            it.setText(0, f"{name}   ({_fmt_shape(getattr(v, 'shape', ()))}) "
                          f"{getattr(v, 'dtype', '')}")
            it.setForeground(0, QtGui.QColor("#c3ccda"))
        root.setExpanded(True)

    def _fill_fields(self, item: QueueItem) -> None:
        rows = item.fields
        self.tbl_fields.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r.name, r.dtype, r.shape, r.unit, r.scale, r.offset,
                    r.valid, r.fill]
            for j, text in enumerate(vals):
                it = QtWidgets.QTableWidgetItem(str(text))
                if j > 0:
                    it.setForeground(QtGui.QColor(theme.DIM2))
                else:
                    it.setToolTip(r.name)
                self.tbl_fields.setItem(i, j, it)
        self.lbl_field_count.setText(f"{len(rows)} 个字段")

    def _fill_checks(self, item: QueueItem) -> None:
        # 清掉除 hint 外的旧行
        for i in reversed(range(self.checks_lay.count())):
            w = self.checks_lay.itemAt(i).widget()
            if w is not None and w is not self.lbl_check_hint:
                w.deleteLater()
                self.checks_lay.removeWidget(w)
        if not item.checks:
            self.lbl_check_hint.setText(
                f"{item.name}：解码完成后显示校验清单"
                if item.status != "failed" else f"解码失败：{item.error}")
            self.lbl_check_hint.show()
            return
        self.lbl_check_hint.hide()
        for label, ok, detail in item.checks:
            lbl = QtWidgets.QLabel(f"{'✓' if ok else '!'}  {label}")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"color:{theme.TXT if ok else theme.AMBER};font-size:10px;"
                "padding:1px 0;")
            lbl.setToolTip(detail or "通过")
            self.checks_lay.insertWidget(self.checks_lay.count() - 1, lbl)

    # ================= 日志 =================
    def _log(self, level: str, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        tag = {"info": "[INFO]", "ok": "[ OK ]", "warn": "[WARN]",
               "err": "[ERR ]", "dim": "      "}.get(level, "[INFO]")
        color = LOG_STYLE.get(level, theme.BLUE)
        self.log.appendHtml(
            f'<span style="color:#4b5563">{ts}</span> '
            f'<span style="color:{color}">{tag}</span> '
            f'<span style="color:#93a0b1">{_html_escape(msg)}</span>')
        n = self.log.blockCount()
        self.lbl_log_count.setText(f"{n} 条")

    def clear_log(self) -> None:
        self.log.clear()
        self.lbl_log_count.setText("0 条")

    # ================= 生命周期 =================
    def closeEvent(self, ev) -> None:
        for w in list(self._jobs):
            self._pool.tryTake(w)
        self._pool.waitForDone(3000)
        self._jobs.clear()
        super().closeEvent(ev)


class _DecodeStats(QtWidgets.QWidget):
    """右栏统计小格：文件/完成/失败/字段/耗时。"""

    CELLS = [("文件", "n_files"), ("完成", "n_done"), ("失败", "n_fail"),
             ("字段", "n_fields"), ("耗时", "elapsed")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._v = {"n_files": 0, "n_done": 0, "n_fail": 0,
                   "n_fields": 0, "elapsed": "—"}

    def set_values(self, **kw) -> None:
        self._v.update(kw)
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#11151b"))
        cols = 3
        rows = (len(self.CELLS) + cols - 1) // cols
        cw_ = self.width() / cols
        ch = self.height() / rows
        for i, (label, key) in enumerate(self.CELLS):
            r, c = divmod(i, cols)
            x, y = c * cw_, r * ch
            p.setPen(QtGui.QPen(QtGui.QColor("#171c24"), 1))
            p.drawLine(QtCore.QPointF(x, y), QtCore.QPointF(x + cw_, y))
            p.setPen(QtGui.QColor(theme.DIM2))
            p.setFont(QtGui.QFont(self.font().family(), 7))
            p.drawText(QtCore.QRectF(x + 8, y + 4, cw_ - 10, 12),
                       QtCore.Qt.AlignLeft, label)
            p.setPen(QtGui.QColor(theme.TXT))
            p.setFont(QtGui.QFont("Consolas", 9, QtGui.QFont.Bold))
            p.drawText(QtCore.QRectF(x + 8, y + 16, cw_ - 10, ch - 18),
                       QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
                       str(self._v.get(key, "—")))
        p.end()


def _html_escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


__all__ = ["DecodeBench", "QueueItem", "StepBar", "analyze_dataset", "STEP_NAMES"]
