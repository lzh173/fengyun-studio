"""后台任务：把耗时的读取/渲染放到 QThreadPool，避免界面卡死。

FY-4B 10992² 单文件读取约 7 秒、标称投影 21 秒，必须异步。
"""
from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass
from typing import Any, Callable

from PySide6 import QtCore

from ..render import Stretch, apply_cmap, display_array, stretch


class Worker(QtCore.QRunnable):
    """在线程池里跑一个可调用对象，结果通过 signals 回到主线程。

    三个必须注意的坑（都踩过了）：
    1. QRunnable 必须由调用方持有 Python 引用，否则可能在运行中被 GC。
    2. Signals 的生命周期必须比 runner 长：QRunnable 结束/被回收时，
       若 Signals 作为其子对象一并销毁，槽就再也收不到信号
       （RuntimeError: Signal source has been deleted）。
       做法：Signals 不设 parent、由 runner 持有强引用，且 autoDelete=False。
    3. 跨线程 emit 走队列连接，槽在事件循环里执行，所以主线程必须持续 processEvents。
    """

    class Signals(QtCore.QObject):
        finished = QtCore.Signal(object)     # 返回值
        failed = QtCore.Signal(str)          # 错误信息
        progress = QtCore.Signal(int, str)   # 百分比, 说明

    def __init__(self, fn: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = Worker.Signals()      # 独立 QObject，无 parent
        self.setAutoDelete(False)            # 生命周期交给 Python 持有者

    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:                        # noqa: BLE001
            tb = traceback.format_exc(limit=3)
            self._safe_emit(self.signals.failed, f"{type(exc).__name__}: {exc}\n{tb}")
            return
        self._safe_emit(self.signals.finished, result)

    @staticmethod
    def _safe_emit(sig, payload) -> None:
        try:
            sig.emit(payload)
        except RuntimeError as exc:
            sys.stderr.write(f"任务结果无法投递（{exc}）: {str(payload)[:200]}\n")


@dataclass
class RenderRequest:
    """一次渲染请求：把变量渲染成可显示的 uint8 RGB 或灰度。"""

    loader: Callable[[], Any]        # 返回 Variable
    cmap: str | None = "gray"
    stretch: Stretch | None = None
    max_size: int = 4096             # 显示上限，超过则降采样
    rgb_channels: tuple[str, str, str] | None = None


def render_variable(var, cmap: str | None = "gray", st: Stretch | None = None,
                    max_size: int = 4096) -> Any:
    """把 Variable 渲染成 uint8 数组（灰度或 RGB），自动降采样到 max_size 以内。"""
    import numpy as np

    arr = display_array(var, physical=True)
    if arr.ndim == 3 and arr.shape[0] <= 32 and arr.shape[-1] > 32:
        arr = arr[0]                      # (band, y, x) → 取第一波段

    h, w = arr.shape[:2]
    step = max(1, int(np.ceil(max(h, w) / float(max_size))))
    if step > 1:
        arr = arr[::step, ::step]

    g = stretch(arr, st or Stretch(method="percentile", pct=(2, 98)))
    if cmap:
        return apply_cmap(g, cmap)
    return (g * 255 + 0.5).astype(np.uint8)


def render_rgb(loader, names: tuple[str, str, str], st: Stretch | None = None,
               max_size: int = 4096) -> Any:
    """三通道合成 RGB（uint8）。"""
    import numpy as np

    from ..render import composite

    arrs = []
    for name in names:
        var = loader(name)
        a = display_array(var, physical=True)
        h, w = a.shape[:2]
        step = max(1, int(np.ceil(max(h, w) / float(max_size))))
        if step > 1:
            a = a[::step, ::step]
        arrs.append(a)
    rgb = composite(*arrs, st=st or Stretch(method="percentile", pct=(1, 99), gamma=1.1))
    return rgb
