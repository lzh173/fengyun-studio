"""影像画布：缩放、平移、像素取值、框选。

用 QGraphicsView 而不是直接画 QImage，因为大幅面影像（FY-4B 10992²）需要
平滑缩放与局部重绘，QGraphicsView 的场景坐标系天然支持。

大数据策略：
- 显示用降采样图（``_preview``），全分辨率只在导出时用
- 缩放超过 1:1 时再按需取全分辨率局部（目前先整体用预览，够用且简单）
"""
from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from . import theme


def ndarray_to_qimage(arr: np.ndarray) -> QtGui.QImage:
    """numpy → QImage。支持 uint8 RGB / uint8 灰度 / uint16 灰度。"""
    arr = np.ascontiguousarray(arr)

    if arr.ndim == 3 and arr.shape[2] == 3 and arr.dtype == np.uint8:
        h, w, _ = arr.shape
        return QtGui.QImage(arr.data, w, h, 3 * w, QtGui.QImage.Format_RGB888).copy()

    if arr.ndim == 3 and arr.shape[2] == 4 and arr.dtype == np.uint8:
        h, w, _ = arr.shape
        return QtGui.QImage(arr.data, w, h, 4 * w,
                            QtGui.QImage.Format_RGBA8888).copy()

    if arr.ndim == 2 and arr.dtype == np.uint8:
        h, w = arr.shape
        return QtGui.QImage(arr.data, w, h, w, QtGui.QImage.Format_Grayscale8).copy()

    if arr.ndim == 2 and arr.dtype == np.uint16:
        h, w = arr.shape
        return QtGui.QImage(arr.data, w, h, 2 * w,
                            QtGui.QImage.Format_Grayscale16).copy()

    # 其他情况：安全兜底成 uint8 灰度
    a = np.asarray(arr)
    if a.ndim == 3:
        a = a[:, :, 0]
    lo, hi = float(np.nanmin(a)), float(np.nanmax(a))
    if hi <= lo:
        hi = lo + 1.0
    a8 = ((np.nan_to_num(a, nan=lo) - lo) / (hi - lo) * 255).astype(np.uint8)
    h, w = a8.shape
    return QtGui.QImage(a8.data, w, h, w, QtGui.QImage.Format_Grayscale8).copy()


class ImageCanvas(QtWidgets.QGraphicsView):
    """影像显示画布。"""

    pixelHovered = QtCore.Signal(int, int, float)      # row, col, value
    rectSelected = QtCore.Signal(QtCore.QRect)         # 图像坐标下的选框
    zoomChanged = QtCore.Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)
        self._item: QtWidgets.QGraphicsPixmapItem | None = None
        self._image: QtGui.QImage | None = None
        self._array: np.ndarray | None = None

        self.setRenderHints(QtGui.QPainter.SmoothPixmapTransform
                            | QtGui.QPainter.Antialiasing)
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)   # 默认平移
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(QtGui.QColor(5, 7, 10))
        self.setMouseTracking(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)

        self._select_mode = False
        self._sel_start: QtCore.QPointF | None = None
        self._sel_item: QtWidgets.QGraphicsRectItem | None = None
        self._selection: QtCore.QRect | None = None

    # ---------- 数据 ----------
    def set_array(self, arr: np.ndarray, keep_view: bool = False) -> None:
        """显示数组。keep_view=True 时保持当前缩放/位置。"""
        self._array = np.ascontiguousarray(arr)
        self._image = ndarray_to_qimage(self._array)
        pix = QtGui.QPixmap.fromImage(self._image)

        if self._item is None:
            self._item = self._scene.addPixmap(pix)
            self._item.setZValue(0)
        else:
            self._item.setPixmap(pix)

        self._scene.setSceneRect(QtCore.QRectF(pix.rect()))
        self._selection = None
        if not keep_view:
            self.fit_to_window()

    def array(self) -> np.ndarray | None:
        return self._array

    def image_size(self) -> QtCore.QSize:
        return self._image.size() if self._image else QtCore.QSize(0, 0)

    def clear(self) -> None:
        self._scene.clear()
        self._item = None
        self._image = None
        self._array = None
        self._selection = None
        self._sel_item = None

    # ---------- 缩放 ----------
    def current_scale(self) -> float:
        return float(self.transform().m11())

    def fit_to_window(self) -> None:
        if self._item is None:
            return
        self.fitInView(self._item, QtCore.Qt.KeepAspectRatio)
        self._emit_zoom()

    def zoom_actual(self) -> None:
        """1:1 显示。"""
        self.resetTransform()
        self._emit_zoom()

    def _emit_zoom(self) -> None:
        self.zoomChanged.emit(self.current_scale() * 100.0)

    def wheelEvent(self, ev: QtGui.QWheelEvent) -> None:
        if self._image is None:
            return
        factor = 1.25 if ev.angleDelta().y() > 0 else 1 / 1.25
        new_scale = self.current_scale() * factor
        if 0.01 < new_scale < 80:
            self.scale(factor, factor)
            self._emit_zoom()

    # ---------- 鼠标 ----------
    def set_select_mode(self, on: bool) -> None:
        self._select_mode = on
        self.setDragMode(QtWidgets.QGraphicsView.NoDrag if on
                         else QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setCursor(QtCore.Qt.CrossCursor if on else QtCore.Qt.ArrowCursor)
        if not on and self._sel_item is not None:
            self._scene.removeItem(self._sel_item)
            self._sel_item = None

    def mousePressEvent(self, ev) -> None:
        if self._select_mode and ev.button() == QtCore.Qt.LeftButton:
            self._sel_start = self.mapToScene(ev.position().toPoint())
            if self._sel_item is not None:
                self._scene.removeItem(self._sel_item)
            self._sel_item = self._scene.addRect(
                QtCore.QRectF(self._sel_start, self._sel_start),
                QtGui.QPen(QtGui.QColor(theme.ACCENT), 0, QtCore.Qt.DashLine),
            )
            self._sel_item.setZValue(10)
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        pos = self.mapToScene(ev.position().toPoint())

        if self._array is not None:
            r, c = int(pos.y()), int(pos.x())
            h, w = self._array.shape[:2]
            if 0 <= r < h and 0 <= c < w:
                val = self._array[r, c]
                v = float(val[0]) if isinstance(val, np.ndarray) else float(val)
                self.pixelHovered.emit(r, c, v)

        if self._select_mode and self._sel_start is not None and self._sel_item is not None:
            self._sel_item.setRect(QtCore.QRectF(self._sel_start, pos).normalized())
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if self._select_mode and self._sel_start is not None:
            end = self.mapToScene(ev.position().toPoint())
            rect = QtCore.QRectF(self._sel_start, end).normalized()
            self._sel_start = None
            if rect.width() > 2 and rect.height() > 2:
                ir = rect.toRect()
                self._selection = ir
                self.rectSelected.emit(ir)
            return
        super().mouseReleaseEvent(ev)

    def selection(self) -> QtCore.QRect | None:
        return self._selection

    def keyPressEvent(self, ev) -> None:
        if ev.key() == QtCore.Qt.Key_Escape:
            self.set_select_mode(False)
            self._selection = None
            return
        if ev.key() in (QtCore.Qt.Key_0, QtCore.Qt.Key_F):
            self.fit_to_window()
            return
        if ev.key() == QtCore.Qt.Key_1:
            self.zoom_actual()
            return
        super().keyPressEvent(ev)
