"""图表与叠图控件库：直方图、剖面、色标条、统计格、LUT 网格、地理叠加。

为什么自己用 QPainter 画而不用 matplotlib 嵌入
------------------------------------------------
1. 许可证：``PySide6`` 只装了 Essentials，任何 Charts 类模块都在 Addons 里
   （GPL-only），本项目按 AGPL-3.0 + LGPLv3 动态链接分发，不能引入。
2. 性能：四个视口联动时，matplotlib 每次重绘要 100 ms 量级，
   而 QPainter 画一条 2000 点的折线是亚毫秒级。
3. 无头可测：QPainter 在 offscreen 平台上工作正常，
   而 matplotlib QtAgg 在无显示器环境里偶发后端初始化失败。

模块只依赖 ``numpy`` 与 ``PySide6.QtGui/QtWidgets``，不碰业务逻辑，
因此可以被分析工作台、制图工作台、主界面画布共同复用。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from . import theme

# 项目内置的海岸线（Natural Earth 110m，公开领域）
# 资源现在位于包内：<root>/src/fysat/assets/ —— pip 安装与 PyInstaller 打包后
# 都只有这一份存在，所以它必须是第一候选。
# 后两个候选保留给老布局（仓库根 assets/）做兼容。
PKG_ASSETS = Path(__file__).resolve().parent.parent / "assets"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
COASTLINE_PATH = PKG_ASSETS / "ne_110m_coastline.geojson"

_COASTLINE_CANDIDATES = (
    PKG_ASSETS / "ne_110m_coastline.geojson",
    PROJECT_ROOT / "assets" / "ne_110m_coastline.geojson",
    Path(__file__).resolve().parents[2] / "assets" / "ne_110m_coastline.geojson",
)


def find_coastline_path() -> Path | None:
    """定位可用的海岸线文件；都没有则返回 None（不做地理叠加，不报错）。"""
    for p in _COASTLINE_CANDIDATES:
        if p.exists():
            return p
    return None

_MONO = "Cascadia Mono, Consolas, monospace"


def qcolor(hex_or_name: str, alpha: int | None = None) -> QtGui.QColor:
    """构造 QColor；alpha 给 0-255 时可加透明度。"""
    c = QtGui.QColor(hex_or_name)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


# ======================= 色标 =======================

def cmap_ramp_rgba(cmap: str = "gray", n: int = 256) -> np.ndarray:
    """取配色表的 RGB 渐变（uint8, shape=(n, 3)）。"""
    import matplotlib

    cm = matplotlib.colormaps.get_cmap(cmap) if hasattr(matplotlib, "colormaps") else None
    if cm is None:                              # 极老版本 matplotlib 兜底
        cm = matplotlib.cm.get_cmap(cmap)
    t = np.linspace(0.0, 1.0, max(2, int(n)), dtype=np.float32)
    rgba = np.asarray(cm(t)) * 255.0
    return (rgba[:, :3] + 0.5).astype(np.uint8)


def cmap_ramp_image(cmap: str = "gray", n: int = 256) -> QtGui.QImage:
    """配色表 → 横向 1×n 的 QImage（宽 n、高 1）。"""
    from .imageview import ndarray_to_qimage

    ramp = cmap_ramp_rgba(cmap, n)[None, :, :]     # (1, n, 3)
    return ndarray_to_qimage(np.ascontiguousarray(ramp))


def cmap_swatch_pixmap(cmap: str, w: int = 84, h: int = 34) -> QtGui.QPixmap:
    """配色表缩略色条（LUT 网格里用）。"""
    img = cmap_ramp_image(cmap, 256)
    return QtGui.QPixmap.fromImage(
        img.scaled(w, h, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation))


class ColorBarWidget(QtWidgets.QWidget):
    """竖直色标条：渐变 + 刻度 + 单位名。

    刻意不用 QLinearGradient（只能表达线性插值），而是把配色表自己
    光栅化成 1×N 的 QImage 再纵向拉伸，这样 turbo/inferno 这类
    非线性的 LUT 也能忠实呈现。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cmap = "gray"
        self._vmin = 0.0
        self._vmax = 1.0
        self._label = ""
        self._unit = ""
        self._ramp: QtGui.QImage | None = None
        self.setFixedWidth(96)
        self.setMinimumHeight(120)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)

    def set_range(self, vmin: float, vmax: float, cmap: str = "gray",
                  label: str = "", unit: str = "") -> None:
        self._vmin, self._vmax = float(vmin), float(vmax)
        self._cmap = cmap or "gray"
        self._label = label
        self._unit = unit
        self._ramp = cmap_ramp_image(self._cmap, 256)
        self.update()

    def range(self) -> tuple[float, float]:
        return self._vmin, self._vmax

    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)

        bar_w = 14
        bar_x = 4
        top = 10
        bottom = self.height() - 26
        if bottom <= top + 8:
            return

        if self._ramp is not None:
            ramp = ramp_pixmap(self._cmap, bar_w, bottom - top)
            p.drawPixmap(bar_x, top, ramp)
        p.setPen(QtGui.QPen(qcolor(theme.LINE2), 1))
        p.drawRect(bar_x, top, bar_w, bottom - top)

        # 刻度：5 档
        p.setFont(QtGui.QFont(self.font().family(), 7))
        p.setPen(qcolor(theme.DIM))
        fm = QtGui.QFontMetrics(p.font())
        n = 5
        for i in range(n):
            frac = i / (n - 1)
            y = int(top + frac * (bottom - top))
            val = self._vmax - frac * (self._vmax - self._vmin)
            p.drawLine(bar_x + bar_w, y, bar_x + bar_w + 4, y)
            text = fmt_tick(val)
            p.drawText(bar_x + bar_w + 7, y + fm.ascent() // 2 - 1, text)

        # 单位 / 名称
        p.setPen(qcolor(theme.DIM2))
        name = self._unit or self._label
        if name:
            p.drawText(QtCore.QRect(0, bottom + 6, self.width(), 14),
                       QtCore.Qt.AlignHCenter, name)
        if self._label and self._unit:
            p.setPen(qcolor(theme.DIM2))
            p.drawText(QtCore.QRect(0, bottom + 19, self.width(), 12),
                       QtCore.Qt.AlignHCenter, self._label)
        p.end()


_ramp_cache: dict[tuple[str, int, int], QtGui.QPixmap] = {}


def ramp_pixmap(cmap: str, w: int, h: int, n: int = 256) -> QtGui.QPixmap:
    """把配色表缩放到 w×h 并缓存，避免每帧重算。

    缓存键用**配色名**而不是 ``id(QImage)``：Python 对象 id 会被复用，
    用 id 做键在频繁切换配色后可能拿到另一条色带的缓存（显示错误颜色）。
    """
    key = (str(cmap), int(w), int(h))
    hit = _ramp_cache.get(key)
    if hit is not None:
        return hit
    img = cmap_ramp_image(cmap, n)
    pix = QtGui.QPixmap.fromImage(
        img.scaled(max(1, w), max(1, h), QtCore.Qt.IgnoreAspectRatio,
                   QtCore.Qt.FastTransformation))
    if len(_ramp_cache) > 128:                 # 简单防膨胀
        _ramp_cache.clear()
    _ramp_cache[key] = pix
    return pix


def fmt_tick(v: float) -> str:
    """刻度数字：大数用 k/M 缩写，小数按有效位。"""
    a = abs(v)
    if a >= 1e6:
        return f"{v / 1e6:.3g}M"
    if a >= 1e4:
        return f"{v / 1e3:.4g}k"
    if a >= 100:
        return f"{v:.0f}"
    if a >= 1:
        return f"{v:.2f}".rstrip("0").rstrip(".")
    if a == 0:
        return "0"
    return f"{v:.3g}"


# ======================= 统计 =======================

@dataclass
class StatSummary:
    """一个数组的统计摘要（全部基于有效像元，NaN 不参与）。"""

    n_total: int = 0
    n_valid: int = 0
    vmin: float = float("nan")
    vmax: float = float("nan")
    mean: float = float("nan")
    std: float = float("nan")
    p02: float = float("nan")
    p98: float = float("nan")

    @property
    def valid_pct(self) -> float:
        return 100.0 * self.n_valid / self.n_total if self.n_total else 0.0

    def as_dict(self) -> dict[str, float]:
        """键名必须与 StatsGrid.CELLS 里用的字段名一致。

        早期这里写的是 "min"/"max"，而 CELLS 取的是 "vmin"/"vmax"，
        于是 .get(k, nan) 永远拿不到值 → 统计面板的"最小值/最大值"
        恒显示「—」，而均值/标准差正常 —— 典型的"功能存在但不可用"。
        """
        return {
            "vmin": self.vmin, "vmax": self.vmax,
            "mean": self.mean, "std": self.std,
            "valid_pct": self.valid_pct, "n_valid": float(self.n_valid),
        }


def summarize(arr: np.ndarray, sample: int = 4_000_000) -> StatSummary:
    """统计一个（可能含 NaN 的）数组。

    大数组先等距抽样再算：FY-4B 10992² 有 1.2 亿像元，
    全量 nanpercentile 要十几秒，而统计量不需要每个点。
    """
    a = np.asarray(arr)
    if a.ndim == 3:
        a = a[..., 0]
    flat = a.reshape(-1).astype(np.float64, copy=False)
    n_total = int(flat.size)
    if n_total == 0:
        return StatSummary()

    if n_total > sample:
        flat = flat[:: max(1, n_total // sample)]

    fin = np.isfinite(flat)
    n_valid = int(fin.sum())
    if n_valid == 0:
        return StatSummary(n_total=n_total, n_valid=0)
    v = flat[fin]
    return StatSummary(
        n_total=n_total, n_valid=n_valid,
        vmin=float(v.min()), vmax=float(v.max()),
        mean=float(v.mean()), std=float(v.std()),
        p02=float(np.percentile(v, 2)), p98=float(np.percentile(v, 98)),
    )


class StatsGrid(QtWidgets.QWidget):
    """统计摘要表格：两列布局的「标签 + 值」格子。"""

    CELLS = [
        ("最小值", "vmin", "%.4g"),
        ("最大值", "vmax", "%.4g"),
        ("均值", "mean", "%.4g"),
        ("标准差", "std", "%.4g"),
        ("有效像元", "valid_pct", "%.1f %%"),
        ("有效数量", "n_valid", "%.4g"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stat = StatSummary()
        self.setMinimumHeight(96)

    def set_stat(self, stat: StatSummary) -> None:
        self._stat = stat
        self.update()

    def stat(self) -> StatSummary:
        return self._stat

    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), qcolor("#11151b"))
        cols = 2
        rows = (len(self.CELLS) + cols - 1) // cols
        cw = self.width() / cols
        ch = self.height() / rows

        d = self._stat.as_dict()
        p.setFont(QtGui.QFont(self.font().family(), 7))
        for i, (label, key, fmt) in enumerate(self.CELLS):
            r, c = divmod(i, cols)
            x, y = c * cw, r * ch
            p.setPen(QtGui.QPen(qcolor("#1a212b"), 1))
            p.drawLine(QtCore.QPointF(x, y), QtCore.QPointF(x + cw, y))
            if c == 1:
                p.drawLine(QtCore.QPointF(x, y), QtCore.QPointF(x, y + ch))

            p.setPen(qcolor(theme.DIM2))
            p.drawText(QtCore.QRectF(x + 8, y + 4, cw - 12, 12),
                       QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, label)
            val = d.get(key, float("nan"))
            p.setPen(qcolor(theme.TXT))
            f = QtGui.QFont(_MONO, 9)
            p.setFont(f)
            p.drawText(QtCore.QRectF(x + 8, y + 16, cw - 12, ch - 18),
                       QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
                       "—" if not np.isfinite(val) else fmt % val)
            p.setFont(QtGui.QFont(self.font().family(), 7))
        p.end()


# ======================= 直方图 =======================

class HistogramWidget(QtWidgets.QWidget):
    """直方图：Qt 自绘，支持对数纵轴与当前拉伸区间高亮。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._counts: np.ndarray | None = None
        self._edges: np.ndarray | None = None
        self._range: tuple[float, float] | None = None
        self._log = False
        self._title = "直方图"
        self.setMinimumHeight(120)

    def set_data(self, values: np.ndarray, bins: int = 128,
                 vrange: tuple[float, float] | None = None,
                 title: str = "直方图") -> None:
        """从原始数值算直方图（自动剔除 NaN）。"""
        a = np.asarray(values, dtype=np.float64).reshape(-1)
        fin = a[np.isfinite(a)]
        if fin.size == 0:
            self._counts = self._edges = None
        else:
            if fin.size > 2_000_000:
                fin = fin[:: max(1, fin.size // 2_000_000)]
            counts, edges = np.histogram(fin, bins=bins)
            self._counts, self._edges = counts, edges
        self._range = vrange
        self._title = title
        self.update()

    def set_histogram(self, counts: np.ndarray, edges: np.ndarray,
                      vrange: tuple[float, float] | None = None,
                      title: str = "直方图") -> None:
        self._counts, self._edges = np.asarray(counts), np.asarray(edges)
        self._range = vrange
        self._title = title
        self.update()

    def set_log(self, on: bool) -> None:
        self._log = bool(on)
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), qcolor("#07090d"))
        p.setRenderHint(QtGui.QPainter.Antialiasing)

        pad_l, pad_r, pad_t, pad_b = 34, 8, 18, 18
        w = self.width() - pad_l - pad_r
        h = self.height() - pad_t - pad_b
        if w < 20 or h < 20:
            p.end()
            return

        # 标题
        p.setFont(QtGui.QFont(self.font().family(), 7))
        p.setPen(qcolor(theme.DIM))
        p.drawText(QtCore.QRectF(pad_l, 2, w, 14),
                   QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, self._title)

        # 坐标轴
        p.setPen(QtGui.QPen(qcolor("#1e2b3a"), 1))
        p.drawLine(pad_l, pad_t, pad_l, pad_t + h)
        p.drawLine(pad_l, pad_t + h, pad_l + w, pad_t + h)

        if self._counts is None or self._edges is None or self._counts.size == 0:
            p.setPen(qcolor(theme.DIM2))
            p.drawText(QtCore.QRectF(pad_l, pad_t, w, h),
                       QtCore.Qt.AlignCenter, "无有效像元")
            p.end()
            return

        counts = self._counts.astype(np.float64)
        if self._log:
            counts = np.log10(counts + 1.0)
        cmax = float(counts.max()) or 1.0
        edges = self._edges
        lo, hi = float(edges[0]), float(edges[-1])
        span = hi - lo or 1.0

        # 拉伸区间外的柱子压暗
        band = QtGui.QLinearGradient(pad_l, 0, pad_l + w, 0)
        band.setColorAt(0.0, qcolor(theme.ACCENT2, 200))
        band.setColorAt(1.0, qcolor(theme.ACCENT, 200))

        n = counts.size
        bw = max(1.0, w / n)
        path = QtGui.QPainterPath()
        path.moveTo(pad_l, pad_t + h)
        for i, c in enumerate(counts):
            x = pad_l + (i / n) * w
            bh = (c / cmax) * h
            path.lineTo(x, pad_t + h - bh)
            path.lineTo(x + bw, pad_t + h - bh)
        path.lineTo(pad_l + w, pad_t + h)
        path.closeSubpath()
        p.fillPath(path, QtGui.QBrush(band))
        p.setPen(QtGui.QPen(qcolor(theme.ACCENT), 1))
        p.drawPath(path)

        # 拉伸区间标记
        if self._range:
            r0, r1 = self._range
            for v, color in ((r0, theme.AMBER), (r1, theme.AMBER)):
                if not np.isfinite(v):
                    continue
                x = pad_l + np.clip((v - lo) / span, 0.0, 1.0) * w
                p.setPen(QtGui.QPen(qcolor(color, 220), 1, QtCore.Qt.DashLine))
                p.drawLine(QtCore.QPointF(x, pad_t), QtCore.QPointF(x, pad_t + h))

        # 刻度
        p.setPen(qcolor("#3d4a5c"))
        f = QtGui.QFont(_MONO, 6)
        p.setFont(f)
        for frac in (0.0, 0.5, 1.0):
            val = lo + frac * span
            x = pad_l + frac * w
            p.drawText(QtCore.QRectF(x - 30, pad_t + h + 2, 60, 12),
                       QtCore.Qt.AlignCenter, fmt_tick(val))
        # 纵轴最大
        raw_max = float(self._counts.max())
        p.drawText(QtCore.QRectF(0, pad_t - 2, pad_l - 4, 12),
                   QtCore.Qt.AlignRight, fmt_tick(raw_max))
        p.end()


# ======================= 剖面 =======================

class ProfileWidget(QtWidgets.QWidget):
    """剖面折线：沿某一行或某一列取一条曲线。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._x: np.ndarray | None = None
        self._y: np.ndarray | None = None
        self._title = "剖面"
        self._subtitle = ""
        self.setMinimumHeight(120)

    def set_profile(self, y: np.ndarray, x: np.ndarray | None = None,
                    title: str = "剖面", subtitle: str = "") -> None:
        y = np.asarray(y, dtype=np.float64).reshape(-1)
        self._y = y
        self._x = (np.arange(y.size, dtype=np.float64)
                   if x is None else np.asarray(x, dtype=np.float64).reshape(-1))
        self._title = title
        self._subtitle = subtitle
        self.update()

    def set_from_row(self, data: np.ndarray, row: int) -> None:
        a = np.asarray(data)
        row = int(np.clip(row, 0, a.shape[0] - 1))
        self.set_profile(a[row, :], title=f"沿第 {row} 行剖面",
                         subtitle=f"样本 {a.shape[1]}")

    def set_from_col(self, data: np.ndarray, col: int) -> None:
        a = np.asarray(data)
        col = int(np.clip(col, 0, a.shape[1] - 1))
        self.set_profile(a[:, col], title=f"沿第 {col} 列剖面",
                         subtitle=f"样本 {a.shape[0]}")

    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), qcolor("#07090d"))
        p.setRenderHint(QtGui.QPainter.Antialiasing)

        pad_l, pad_r, pad_t, pad_b = 38, 8, 18, 18
        w = self.width() - pad_l - pad_r
        h = self.height() - pad_t - pad_b
        if w < 20 or h < 20:
            p.end()
            return

        p.setFont(QtGui.QFont(self.font().family(), 7))
        p.setPen(qcolor(theme.DIM))
        p.drawText(QtCore.QRectF(pad_l, 2, w, 14),
                   QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, self._title)
        if self._subtitle:
            p.setPen(qcolor(theme.DIM2))
            p.drawText(QtCore.QRectF(pad_l, 2, w, 14),
                       QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, self._subtitle)

        p.setPen(QtGui.QPen(qcolor("#1e2b3a"), 1))
        p.drawLine(pad_l, pad_t, pad_l, pad_t + h)
        p.drawLine(pad_l, pad_t + h, pad_l + w, pad_t + h)

        if self._y is None or self._y.size < 2:
            p.setPen(qcolor(theme.DIM2))
            p.drawText(QtCore.QRectF(pad_l, pad_t, w, h),
                       QtCore.Qt.AlignCenter, "无剖面数据")
            p.end()
            return

        y = self._y
        fin = np.isfinite(y)
        if not fin.any():
            p.setPen(qcolor(theme.DIM2))
            p.drawText(QtCore.QRectF(pad_l, pad_t, w, h),
                       QtCore.Qt.AlignCenter, "该剖面全为无效值")
            p.end()
            return
        y0, y1 = float(y[fin].min()), float(y[fin].max())
        if y1 <= y0:
            y0, y1 = y0 - 0.5, y1 + 0.5
        n = y.size
        x = self._x if self._x is not None and self._x.size == n else np.arange(n)

        # 网格
        p.setPen(QtGui.QPen(qcolor("#1a2531"), 1, QtCore.Qt.DashLine))
        for i in range(1, 4):
            yy = pad_t + i * h / 4
            p.drawLine(pad_l, int(yy), pad_l + w, int(yy))

        # 折线（按 NaN 断开）
        pen = QtGui.QPen(qcolor(theme.ACCENT), 1.2)
        p.setPen(pen)
        path = QtGui.QPainterPath()
        started = False
        # 抽稀到不超过 4000 点，保证重绘流畅
        step = max(1, n // 4000)
        for i in range(0, n, step):
            if not np.isfinite(y[i]):
                started = False
                continue
            px = pad_l + (i / max(1, n - 1)) * w
            py = pad_t + h - (float(y[i]) - y0) / (y1 - y0) * h
            if not started:
                path.moveTo(px, py)
                started = True
            else:
                path.lineTo(px, py)
        p.drawPath(path)

        # 刻度
        p.setPen(qcolor("#3d4a5c"))
        p.setFont(QtGui.QFont(_MONO, 6))
        p.drawText(QtCore.QRectF(0, pad_t - 2, pad_l - 4, 12),
                   QtCore.Qt.AlignRight, fmt_tick(y1))
        p.drawText(QtCore.QRectF(0, pad_t + h - 10, pad_l - 4, 12),
                   QtCore.Qt.AlignRight, fmt_tick(y0))
        p.drawText(QtCore.QRectF(pad_l - 30, pad_t + h + 2, 60, 12),
                   QtCore.Qt.AlignCenter, fmt_tick(float(x[0])))
        p.drawText(QtCore.QRectF(pad_l + w - 30, pad_t + h + 2, 60, 12),
                   QtCore.Qt.AlignCenter, fmt_tick(float(x[-1])))
        p.end()


# ======================= LUT 网格 =======================

class LutGrid(QtWidgets.QWidget):
    """色标库：缩略色条网格，点击切换配色。"""

    lutSelected = QtCore.Signal(str)

    def __init__(self, parent=None, cmaps: list[str] | None = None, cols: int = 4):
        super().__init__(parent)
        if cmaps is None:
            from ..render import COLORMAPS

            cmaps = list(COLORMAPS)
        self._cmaps = list(cmaps)
        self._cols = max(1, cols)
        self._current = self._cmaps[0] if self._cmaps else "gray"
        self._hover = -1
        self._cell_w, self._cell_h, self._gap = 78, 42, 6
        self.setMouseTracking(True)
        self.setMinimumHeight(self._rows * (self._cell_h + self._gap) + 4)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                           QtWidgets.QSizePolicy.Fixed)

    @property
    def _rows(self) -> int:
        return (len(self._cmaps) + self._cols - 1) // self._cols

    def current_cmap(self) -> str:
        return self._current

    def set_current(self, cmap: str) -> None:
        if cmap in self._cmaps:
            self._current = cmap
            self.update()

    def _cell_rect(self, idx: int) -> QtCore.QRectF:
        r, c = divmod(idx, self._cols)
        avail = self.width()
        cw = min(self._cell_w, max(40, (avail - self._gap * (self._cols + 1)) / self._cols))
        x = self._gap + c * (cw + self._gap)
        y = 2 + r * (self._cell_h + self._gap)
        return QtCore.QRectF(x, y, cw, self._cell_h)

    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), qcolor("#11151b"))
        for i, cmap in enumerate(self._cmaps):
            rect = self._cell_rect(i)
            if rect.right() > self.width():
                continue
            sw = cmap_swatch_pixmap(cmap, int(rect.width()), int(rect.height() - 12))
            p.drawPixmap(int(rect.x()), int(rect.y()), sw)

            p.setPen(QtGui.QPen(
                qcolor(theme.ACCENT if cmap == self._current
                       else ("#39424f" if i == self._hover else "#263040")), 1))
            p.drawRect(rect.x(), rect.y(), rect.width(), rect.height() - 12)

            p.setFont(QtGui.QFont(self.font().family(), 6))
            p.setPen(qcolor(theme.TXT if cmap == self._current else theme.DIM2))
            p.drawText(QtCore.QRectF(rect.x(), rect.y() + rect.height() - 12,
                                     rect.width(), 11),
                       QtCore.Qt.AlignCenter, cmap)
        p.end()

    def _index_at(self, pos: QtCore.QPoint) -> int:
        for i in range(len(self._cmaps)):
            if self._cell_rect(i).contains(QtCore.QPointF(pos)):
                return i
        return -1

    def mousePressEvent(self, ev) -> None:
        i = self._index_at(ev.position().toPoint())
        if i >= 0:
            self._current = self._cmaps[i]
            self.update()
            self.lutSelected.emit(self._current)

    def mouseMoveEvent(self, ev) -> None:
        i = self._index_at(ev.position().toPoint())
        if i != self._hover:
            self._hover = i
            self.setCursor(QtCore.Qt.PointingHandCursor if i >= 0
                           else QtCore.Qt.ArrowCursor)
            self.update()


# ======================= 通用小组件 =======================

class PanelHeader(QtWidgets.QFrame):
    """面板小标题栏：左标题 + 右徽标（对应设计稿的 .phead）。"""

    def __init__(self, title: str = "", badge: str = "", parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(9, 0, 9, 0)
        lay.setSpacing(6)
        self.lbl = QtWidgets.QLabel(title)
        self.lbl.setStyleSheet(
            "color:#a9b4c4;font-size:11px;font-weight:600;background:transparent;")
        self.badge = QtWidgets.QLabel(badge)
        self.badge.setStyleSheet(
            "color:#7fc7d8;background:#1e2a38;border-radius:8px;"
            "padding:0 6px;font-size:10px;")
        self.badge.setVisible(bool(badge))
        lay.addWidget(self.lbl)
        lay.addStretch(1)
        lay.addWidget(self.badge)
        self.setStyleSheet(
            f"QFrame{{background:#151920;border-bottom:1px solid {theme.LINE};"
            f"border-top:1px solid #1b2029;}}")

    def set_title(self, text: str) -> None:
        self.lbl.setText(text)

    def set_badge(self, text: str) -> None:
        self.badge.setText(text)
        self.badge.setVisible(bool(text))


class ChipRow(QtWidgets.QWidget):
    """可点击标签行（单选或多选）。"""

    chipClicked = QtCore.Signal(str)

    def __init__(self, items: list[str], exclusive: bool = True,
                 current: str | None = None, parent=None):
        super().__init__(parent)
        self._exclusive = exclusive
        self._selected: set[str] = set()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        self._buttons: dict[str, QtWidgets.QToolButton] = {}
        for text in items:
            btn = QtWidgets.QToolButton()
            btn.setText(text)
            btn.setCheckable(True)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QToolButton{font-size:10px;padding:2px 8px;border-radius:9px;"
                "background:#1a2029;border:1px solid #2a3341;color:#a9b6c6;}"
                "QToolButton:checked{background:#10333d;border-color:#1d5f70;"
                "color:#9fe9f5;}")
            btn.clicked.connect(lambda _c=False, t=text: self._on_click(t))
            self._buttons[text] = btn
            lay.addWidget(btn)
        lay.addStretch(1)
        if current is not None:
            self.set_current(current)
        elif items and exclusive:
            self._on_click(items[0], emit=False)

    def _on_click(self, text: str, emit: bool = True) -> None:
        if self._exclusive:
            self._selected = {text}
        elif text in self._selected:
            self._selected.discard(text)
        else:
            self._selected.add(text)
        for t, btn in self._buttons.items():
            btn.setChecked(t in self._selected)
        if emit:
            self.chipClicked.emit(text)

    def selected(self) -> list[str]:
        return [t for t in self._buttons if t in self._selected]

    def set_current(self, text: str) -> None:
        if text in self._buttons:
            self._on_click(text, emit=False)


# ======================= 海岸线数据 + 地理叠加 =======================

_coast_cache: list[np.ndarray] | None = None


def coastline_segments(path: Path | str | None = None) -> list[np.ndarray]:
    """读 Natural Earth 110m 海岸线，返回 [(N,2) 的 lon/lat 数组]。

    注意：``sciencefig._load_coastlines`` 用 ``parents[1]`` 定位到 ``src/assets``，
    但资源实际在工程根的 ``assets/``（``parents[2]``），因此那里总是返回空，
    海岸线一直没画出来。这是既有缺陷，本模块自己按正确路径读取，
    并通过 ``FigureSpec.coastline_path`` 把正确路径传给制图模块。
    """
    global _coast_cache
    if _coast_cache is not None and path is None:
        return _coast_cache

    import json

    p = Path(path) if path is not None else (find_coastline_path() or COASTLINE_PATH)
    if not p.exists():
        return []
    try:
        gj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:                       # noqa: BLE001
        return []

    segs: list[np.ndarray] = []
    for feat in gj.get("features", []):
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        if gtype == "LineString":
            arr = np.asarray(coords, dtype=float)
            if arr.ndim == 2 and arr.shape[0] >= 2:
                segs.append(arr)
        elif gtype == "MultiLineString":
            for c in coords:
                arr = np.asarray(c, dtype=float)
                if arr.ndim == 2 and arr.shape[0] >= 2:
                    segs.append(arr)
    if path is None:
        _coast_cache = segs
    return segs


def _resize_nearest(grid: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """最近邻放大经纬网格到目标形状。

    与 ``pipeline._resize_nearest`` 等价，这里自带一份是刻意的：
    pipeline 属于业务核心层，GUI 的叠加层不应该因为核心层的改动而失效。
    """
    h, w = shape
    gh, gw = grid.shape[:2]
    if (gh, gw) == (h, w):
        return grid
    ri = np.clip((np.arange(h) * gh / h).astype(int), 0, gh - 1)
    ci = np.clip((np.arange(w) * gw / w).astype(int), 0, gw - 1)
    return grid[np.ix_(ri, ci)]


# 经纬度填充值（MERSI 等产品用 -9999.9 / 999.0 之类）
_LATLON_FILL = (-9999.9, -999.0, 999.0, 9999.0, -32768.0, 65535.0)


def clean_latlon(lat: np.ndarray, lon: np.ndarray
                 ) -> tuple[np.ndarray, np.ndarray]:
    """把经纬度里的填充值与越界值置 NaN。

    与 ``pipeline.clean_latlon`` 同义，同样自带一份以解除对核心层的依赖。
    不清填充值会让叠加层的地图范围拉伸到整张空白。
    """
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    bad = np.zeros(lat.shape, dtype=bool)
    for f in _LATLON_FILL:
        bad |= np.isclose(lat, f) | np.isclose(lon, f)
    bad |= ~np.isfinite(lat) | ~np.isfinite(lon)
    bad |= (lat < -90.0) | (lat > 90.0)
    bad |= (lon < -180.0) | (lon > 360.0)
    return np.where(bad, np.nan, lat), np.where(bad, np.nan, lon)


class GeoGridMapper:
    """经纬度 → 图像像素(r,c) 的映射器。

    两种来源：
    1. 有真实经纬网格（``geolocation.kind == latlon_grid``）：
       先把粗网格放大到图像尺寸，再用 KDTree 找「给定经纬点最近的像元」。
       这样 FY-3 这种随扫描角变化的条带也能大致贴住海岸线。
    2. 只有标称投影（FY-4B AGRI）：用 bounds 做线性仿射近似。
    """

    def __init__(self, ds=None, shape: tuple[int, int] | None = None,
                 max_nodes: int = 90_000):
        self.lat = self.lon = None
        self.shape: tuple[int, int] | None = None
        self._tree = None
        self._rows = self._cols = None
        self._bounds: tuple[float, float, float, float] | None = None
        # 最近邻查询的最大允许距离（度）。超过就判为「不在本幅影像内」。
        # 没有它的话，南极洲的海岸线会被吸附到影像边缘，把真实海岸线淹掉。
        self._max_dist = 2.0
        if ds is not None and shape is not None:
            self.build(ds, shape, max_nodes=max_nodes)

    @property
    def available(self) -> bool:
        return self._tree is not None or self._bounds is not None

    def build(self, ds, shape: tuple[int, int], max_nodes: int = 90_000) -> None:
        self.shape = (int(shape[0]), int(shape[1]))
        geo = getattr(ds, "geolocation", None)
        if geo is None:
            return

        if getattr(geo, "is_nav", False) and geo.kind == "latlon_grid":
            lat = _resize_nearest(np.asarray(geo.lat, dtype=np.float64), self.shape)
            lon = _resize_nearest(np.asarray(geo.lon, dtype=np.float64), self.shape)
            lat, lon = clean_latlon(lat, lon)
            h, w = self.shape
            step = max(1, int(np.ceil(np.sqrt(h * w / float(max_nodes)))))
            sub_lat = lat[::step, ::step]
            sub_lon = lon[::step, ::step]
            rr, cc = np.mgrid[0:h:step, 0:w:step]
            good = np.isfinite(sub_lat) & np.isfinite(sub_lon)
            if good.sum() >= 16:
                try:
                    from scipy.spatial import cKDTree

                    pts = np.column_stack([sub_lon[good], sub_lat[good]])
                    self._tree = cKDTree(pts)
                    self._rows = rr[good]
                    self._cols = cc[good]
                    # 顺带回填地理范围：经纬网与海岸线的粗筛都要用它
                    self._bounds = (float(pts[:, 0].min()), float(pts[:, 0].max()),
                                    float(pts[:, 1].min()), float(pts[:, 1].max()))
                    # 采样后相邻节点的经纬度间距，作为「算不算在幅内」的阈值。
                    # 取 2 倍间距，既容得下海岸线线段的稀疏采样，
                    # 又不会把境外要素吸到幅边。
                    if len(pts) > 1:
                        sample = pts[:: max(1, len(pts) // 400)]
                        if len(sample) > 8:
                            dx = float(np.median(np.abs(np.diff(np.sort(sample[:, 0])))))
                            dy = float(np.median(np.abs(np.diff(np.sort(sample[:, 1])))))
                            self._max_dist = max(0.5, 2.0 * max(dx, dy, 1e-6))
                    return
                except Exception:           # noqa: BLE001
                    pass
            b = geo.bounds()
        else:
            b = geo.bounds() if hasattr(geo, "bounds") else None

        if b and all(np.isfinite(b)):
            self._bounds = b

    def to_pixel(self, lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """经纬度数组 → (row, col) 像素坐标；无法映射的点返回 NaN。

        分两步，缺一不可：
        1. **地理粗筛**：先用本幅影像的经纬度外包框（留一点余量）剔除境外点。
           这一步是必需的——KDTree 的最近邻永远返回「有限距离的最近点」，
           没有粗筛的话南极洲海岸线会被吸附到影像边缘，画出一圈假线条。
        2. **最近邻吸附**：框内的点用 KDTree 贴到最近的网格节点。
           直接用框筛而不设距离阈值，是因为海岸线（110m 分辨率）采样点
           比经纬网格稀疏得多，按距离卡会把真实海岸线也一起丢掉。
        """
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        if self._tree is not None:
            pts = np.column_stack([lon.ravel(), lat.ravel()])
            inside = np.ones(pts.shape[0], dtype=bool)
            if self._bounds is not None:
                lon0, lon1, lat0, lat1 = self._bounds
                span_lon = max(lon1 - lon0, 1e-6)
                span_lat = max(lat1 - lat0, 1e-6)
                m_lon, m_lat = span_lon * 0.02, span_lat * 0.02
                inside &= (pts[:, 0] >= lon0 - m_lon) & (pts[:, 0] <= lon1 + m_lon)
                inside &= (pts[:, 1] >= lat0 - m_lat) & (pts[:, 1] <= lat1 + m_lat)
            inside &= np.isfinite(pts).all(axis=1)

            rows = np.full(lon.shape, np.nan)
            cols = np.full(lon.shape, np.nan)
            if inside.any():
                _, idx = self._tree.query(pts[inside], k=1)
                rows[inside] = self._rows[idx]
                cols[inside] = self._cols[idx]
            return rows, cols
        if self._bounds is not None and self.shape:
            lon0, lon1, lat0, lat1 = self._bounds
            if lon1 <= lon0 or lat1 <= lat0:
                return np.full(lon.shape, np.nan), np.full(lon.shape, np.nan)
            h, w = self.shape
            cols = (lon - lon0) / (lon1 - lon0) * (w - 1)
            rows = (lat1 - lat) / (lat1 - lat0) * (h - 1)
            bad = ~np.isfinite(cols) | ~np.isfinite(rows)
            cols = np.where(bad, np.nan, cols)
            rows = np.where(bad, np.nan, rows)
            return rows, cols
        nan = np.full(lon.shape, np.nan)
        return nan, nan


class CanvasOverlay(QtWidgets.QWidget):
    """画布上的地理叠加层（海岸线 + 经纬网）。

    实现要点（踩过的坑）
    --------------------
    最初把叠加层做成 ``canvas.viewport()`` 的子控件。单独 ``grab()`` 它是正常的，
    但在真实窗口里**完全不显示**：``QGraphicsView`` 会重写 viewport 的
    ``paintEvent``，直接在其上画场景内容，子控件虽然存在却不会被绘制。

    现在改成挂在 ``QGraphicsView`` **自身**上并手动定位到 viewport 区域
    （``viewport().geometry()``），同时 ``raise_()`` 保证在最上层。
    QGraphicsView 本身是普通 QWidget，子控件会被正常绘制。

    坐标换算仍然走 ``viewportTransform()``：图像像素 → viewport 像素 → 本控件像素。
    """

    def __init__(self, canvas, parent=None):
        super().__init__(parent or canvas)
        self._canvas = canvas
        self._mapper: GeoGridMapper | None = None
        self._show_coast = True
        self._show_grid = True
        self._grid_step = 0.0            # 0 = 自动
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.hide()

        canvas.installEventFilter(self)
        self._segments = coastline_segments()
        self._sync_geometry()

    # ---- 配置 ----
    def set_dataset(self, ds, shape: tuple[int, int]) -> None:
        self._mapper = GeoGridMapper(ds, shape) if ds is not None else None
        self._sync_visibility()

    def set_show_coast(self, on: bool) -> None:
        self._show_coast = bool(on)
        self._sync_visibility()

    def set_show_grid(self, on: bool) -> None:
        self._show_grid = bool(on)
        self._sync_visibility()

    def set_grid_step(self, step: float) -> None:
        self._grid_step = float(step or 0.0)
        self.update()

    def _sync_geometry(self) -> None:
        """把自己贴到 QGraphicsView 的 viewport 区域上。"""
        g = self._canvas.viewport().geometry()
        self.setGeometry(g)

    def _sync_visibility(self) -> None:
        ok = self._mapper is not None and self._mapper.available
        self.setVisible(bool(ok and (self._show_coast or self._show_grid)))
        if self.isVisible():
            self._sync_geometry()
            self.raise_()
            self.update()

    # ---- 事件 ----
    def eventFilter(self, obj, ev) -> bool:
        t = ev.type()
        if t in (QtCore.QEvent.Resize, QtCore.QEvent.Wheel,
                 QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease,
                 QtCore.QEvent.Scroll, QtCore.QEvent.Show):
            if self.isVisible():
                self._sync_geometry()
                self.raise_()
                self.update()
        return False

    def paintEvent(self, _ev) -> None:
        if self._mapper is None or not self._mapper.available:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect()

        if self._show_grid:
            self._draw_graticule(p, rect)
        if self._show_coast:
            self._draw_coast(p, rect)
        p.end()

    # ---- 绘制 ----
    def _scene_to_view(self, rows: np.ndarray, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """图像像素坐标(scene) → 本控件坐标。

        scene 像素轴 = 图像 (col=x, row=y)；
        ``viewportTransform()`` 给的是 scene→viewport 的映射；
        本控件贴在 viewport 区域上，两者原点相同，因此直接用即可。
        """
        m = self._canvas.viewportTransform()
        xs = m.m11() * cols + m.m21() * rows + m.dx()
        ys = m.m12() * cols + m.m22() * rows + m.dy()
        return ys, xs

    def _draw_graticule(self, p: QtGui.QPainter, rect: QtCore.QRect) -> None:
        m = self._mapper
        b = m._bounds
        if b is None:
            # 有 KDTree 时用网格范围反推
            if m._tree is not None:
                pts = m._tree.data
                b = (float(pts[:, 0].min()), float(pts[:, 0].max()),
                     float(pts[:, 1].min()), float(pts[:, 1].max()))
        if b is None:
            return
        lon0, lon1, lat0, lat1 = b
        if not (lon1 > lon0 and lat1 > lat0):
            return
        step = self._grid_step
        if step <= 0:
            span = max(lon1 - lon0, lat1 - lat0)
            step = next((s for s in (0.5, 1, 2, 5, 10, 15, 20, 30, 45) if span / s <= 8), 45.0)

        pen = QtGui.QPen(qcolor("#5eead4", 64), 0.8, QtCore.Qt.DotLine)
        p.setPen(pen)
        f = QtGui.QFont(_MONO, 6)
        p.setFont(f)

        # 经线
        for lon in np.arange(np.ceil(lon0 / step) * step, lon1 + 1e-9, step):
            lats = np.linspace(lat0, lat1, 64)
            rows, cols = m.to_pixel(np.full_like(lats, lon), lats)
            ok = np.isfinite(rows) & np.isfinite(cols)
            if ok.sum() < 2:
                continue
            ys, xs = self._scene_to_view(rows[ok], cols[ok])
            self._stroke_polyline(p, xs, ys, rect)
        # 纬线
        for lat in np.arange(np.ceil(lat0 / step) * step, lat1 + 1e-9, step):
            lons = np.linspace(lon0, lon1, 64)
            rows, cols = m.to_pixel(lons, np.full_like(lons, lat))
            ok = np.isfinite(rows) & np.isfinite(cols)
            if ok.sum() < 2:
                continue
            ys, xs = self._scene_to_view(rows[ok], cols[ok])
            self._stroke_polyline(p, xs, ys, rect)

    def _draw_coast(self, p: QtGui.QPainter, rect: QtCore.QRect) -> None:
        m = self._mapper
        if m is None or not m.available or not self._segments:
            return
        pen = QtGui.QPen(qcolor("#7dd3fc", 150), 0.9)
        p.setPen(pen)
        bb = self._geo_bbox()
        for seg in self._segments:
            lon, lat = seg[:, 0], seg[:, 1]
            if bb is not None:
                lon0, lon1, lat0, lat1 = bb
                if lon.max() < lon0 or lon.min() > lon1:
                    continue
                if lat.max() < lat0 or lat.min() > lat1:
                    continue
            rows, cols = m.to_pixel(lon, lat)
            ok = np.isfinite(rows) & np.isfinite(cols)
            if ok.sum() < 2:
                continue
            # 分段：连续的 True 段各画一条（跳掉海陆跳变的假连线）
            idx = np.flatnonzero(ok)
            if idx.size < 2:
                continue
            splits = np.flatnonzero(np.diff(idx) > 1)
            starts = np.r_[0, splits + 1]
            ends = np.r_[splits, idx.size - 1]
            for s, e in zip(starts, ends, strict=False):
                if e - s < 1:
                    continue
                sl = idx[s:e + 1]
                ys, xs = self._scene_to_view(rows[sl], cols[sl])
                self._stroke_polyline(p, xs, ys, rect)

    def _geo_bbox(self):
        m = self._mapper
        if m is None:
            return None
        if m._bounds is not None:
            return m._bounds
        if m._tree is not None:
            pts = m._tree.data
            return (float(pts[:, 0].min()), float(pts[:, 0].max()),
                    float(pts[:, 1].min()), float(pts[:, 1].max()))
        return None

    @staticmethod
    def _stroke_polyline(p: QtGui.QPainter, xs: np.ndarray, ys: np.ndarray,
                         rect: QtCore.QRect) -> None:
        if xs.size < 2 or ys.size < 2:
            return
        x = np.asarray(xs, dtype=np.float64)
        y = np.asarray(ys, dtype=np.float64)
        ok = np.isfinite(x) & np.isfinite(y)
        if not ok.all():
            # 有坏点时按连续段重画，避免 NaN 进入 QPainterPath
            idx = np.flatnonzero(ok)
            if idx.size < 2:
                return
            cuts = np.flatnonzero(np.diff(idx) > 1)
            for a, b in zip(np.r_[0, cuts + 1], np.r_[cuts, idx.size - 1], strict=False):
                sl = idx[a:b + 1]
                if sl.size >= 2:
                    CanvasOverlay._stroke_polyline(p, x[sl], y[sl], rect)
            return

        # 全部落在控件外就跳过（用安全阈值，避免超大值参与比较）
        if x.max() < rect.left() - 8 or x.min() > rect.right() + 8:
            return
        if y.max() < rect.top() - 8 or y.min() > rect.bottom() + 8:
            return

        lim = 32000.0   # QPainterPath 用定点数，超大坐标会破坏内部缓冲区
        x = np.clip(x, -lim, lim)
        y = np.clip(y, -lim, lim)

        path = QtGui.QPainterPath()
        path.moveTo(float(x[0]), float(y[0]))
        for xi, yi in zip(x[1:], y[1:], strict=False):
            path.lineTo(float(xi), float(yi))
        p.drawPath(path)


# ======================= 画布角标 =======================

class CanvasBadges(QtWidgets.QWidget):
    """画布四角信息角标（产品名 / 缩放 / 光标经纬度 / 投影）。

    与 CanvasOverlay 一样做成 viewport 的透明子控件，避免改动 imageview.py。
    """

    def __init__(self, canvas, parent=None):
        super().__init__(parent or canvas)
        self._canvas = canvas
        self._tl = ""
        self._tr = ""
        self._bl = ""
        self._br = ""
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        canvas.installEventFilter(self)
        self._sync_geometry()
        self.show()
        self.raise_()

    def _sync_geometry(self) -> None:
        self.setGeometry(self._canvas.viewport().geometry())

    def set_badges(self, tl: str = "", tr: str = "", bl: str = "", br: str = "") -> None:
        self._tl, self._tr, self._bl, self._br = tl, tr, bl, br
        self.update()

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() in (QtCore.QEvent.Resize, QtCore.QEvent.MouseMove,
                         QtCore.QEvent.Wheel, QtCore.QEvent.Show):
            self._sync_geometry()
            self.raise_()
            self.update()
        return False

    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        f = QtGui.QFont(self.font().family(), 8)
        p.setFont(f)
        fm = QtGui.QFontMetrics(f)
        w, h = self.width(), self.height()
        for text, corner in ((self._tl, "tl"), (self._tr, "tr"),
                             (self._bl, "bl"), (self._br, "br")):
            if not text:
                continue
            tw = fm.horizontalAdvance(text) + 16
            th = fm.height() + 8
            if corner == "tl":
                x, y = 8, 8
            elif corner == "tr":
                x, y = w - tw - 8, 8
            elif corner == "bl":
                x, y = 8, h - th - 8
            else:
                x, y = w - tw - 8, h - th - 8
            if x < 0 or y < 0:
                continue
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(qcolor("#0a0e14", 190))
            p.drawRoundedRect(QtCore.QRectF(x, y, tw, th), 4, 4)
            p.setPen(QtGui.QPen(qcolor("#788ca5", 60), 1))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawRoundedRect(QtCore.QRectF(x, y, tw, th), 4, 4)
            p.setPen(qcolor("#cfd8e3"))
            p.drawText(QtCore.QRectF(x, y, tw, th), QtCore.Qt.AlignCenter, text)
        p.end()


__all__ = [
    "PROJECT_ROOT", "COASTLINE_PATH", "find_coastline_path", "qcolor",
    "cmap_ramp_rgba", "cmap_ramp_image", "cmap_swatch_pixmap", "ramp_pixmap",
    "fmt_tick", "ColorBarWidget", "StatSummary", "summarize", "StatsGrid",
    "HistogramWidget", "ProfileWidget", "LutGrid", "PanelHeader", "ChipRow",
    "coastline_segments", "GeoGridMapper", "CanvasOverlay", "CanvasBadges",
]
