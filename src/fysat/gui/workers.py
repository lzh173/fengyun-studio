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
            # 窗口已销毁时结果无处投递，属正常现象；不要把整个数组打印出来
            # （ndarray 的 repr 能有几十行，会把真实错误淹没）
            desc = f"{type(payload).__name__}"
            if hasattr(payload, "shape"):
                desc += f" shape={getattr(payload, 'shape', None)}"
            sys.stderr.write(f"任务结果已丢弃（{exc}）: {desc}\n")


@dataclass
class RenderRequest:
    """一次渲染请求：把变量渲染成可显示的 uint8 RGB 或灰度。"""

    loader: Callable[[], Any]        # 返回 Variable
    cmap: str | None = "gray"
    stretch: Stretch | None = None
    max_size: int = 4096             # 显示上限，超过则降采样
    rgb_channels: tuple[str, str, str] | None = None


def render_variable(var, cmap: str | None = "gray", st: Stretch | None = None,
                    max_size: int = 4096, band: int = 0) -> Any:
    """把 Variable 渲染成 uint8 数组（灰度或 RGB），自动降采样到 max_size 以内。

    注意：FY-3 的 EV_1KM_RefSB 是 (15, 2000, 2048)，第 0 维是通道。
    必须用 display_band 取单通道，否则会把 15 个通道竖着拼成横条图。
    """
    import numpy as np

    from ..render import display_band

    arr = display_band(var, index=band, physical=True)

    h, w = arr.shape[:2]
    step = max(1, int(np.ceil(max(h, w) / float(max_size))))
    if step > 1:
        arr = arr[::step, ::step]

    g = stretch(arr, st or Stretch(method="percentile", pct=(2, 98)))
    if cmap:
        return apply_cmap(g, cmap)
    return (g * 255 + 0.5).astype(np.uint8)


def render_rgb(loader, names: tuple[str, str, str], st: Stretch | None = None,
               max_size: int = 4096, bands: tuple[int, int, int] = (0, 0, 0)) -> Any:
    """三通道合成 RGB（uint8）。三个输入必须同为二维影像。"""
    import numpy as np

    from ..render import composite, display_band

    arrs = []
    shapes = []
    for name, band in zip(names, bands):
        var = loader(name)
        a = display_band(var, index=band, physical=True)
        if a.ndim != 2:
            raise ValueError(f"{name} 不是二维影像（shape={a.shape}），无法参与 RGB 合成")
        shapes.append(a.shape)
        h, w = a.shape[:2]
        step = max(1, int(np.ceil(max(h, w) / float(max_size))))
        if step > 1:
            a = a[::step, ::step]
        arrs.append(a)

    if len(set(shapes)) > 1:
        raise ValueError(
            "三个通道的尺寸不一致，无法合成：\n"
            + "\n".join(f"  {n}: {s}" for n, s in zip(names, shapes))
            + "\n请选择同一产品、同一分辨率的通道。"
        )

    rgb = composite(*arrs, st=st or Stretch(method="percentile", pct=(1, 99), gamma=1.1))
    return rgb
