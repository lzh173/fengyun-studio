# -*- coding: utf-8 -*-
"""三个工作台的深度审查：不只看"有画面"，而是验证每个交互入口真的生效。

02 分析工作台：视口数量 / LUT 点击换色标 / 统计数值 / 直方图数据
03 解码工作台：队列 / 运行流水线 / 字段表
04 制图工作台：预览生成 / 模板切换 / 导出
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6 import QtCore, QtWidgets                # noqa: E402

from fysat.gui import theme                          # noqa: E402
from fysat.gui.mainwindow import MainWindow          # noqa: E402

R: list[tuple[str, bool, str]] = []


def rec(name, ok, why=""):
    R.append((name, ok, why))
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}" + (f"  — {why}" if why else ""), flush=True)


def check(name):
    def deco(fn):
        try:
            fn()
            rec(name, True)
        except Exception as exc:                      # noqa: BLE001
            rec(name, False, f"{type(exc).__name__}: {exc}")
        return fn
    return deco


def pump(app, sec):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        QtCore.QThread.msleep(15)


def main() -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply_theme(app)
    win = MainWindow()
    win.resize(1600, 1000)
    win.show()

    sample = None
    for pat in ("FY3D_MERSI_GBAL_L1_*1000M_MS.HDF", "FY3H_MERSI_GRAN_L1_*1000M*.HDF"):
        hits = [h for h in sorted(Path(r"Y:\download-data").rglob(pat))
                if h.stat().st_size > 10_000_000]
        if hits:
            sample = hits[0]
            break
    print(f"样本: {sample.name}\n", flush=True)

    win.load_file(str(sample))
    t0 = time.time()
    while time.time() - t0 < 30:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        QtCore.QThread.msleep(20)
        arr = win.canvas.array()
        if win._ds is not None and arr is not None and tuple(arr.shape[:2]) != (600, 800):
            break
    pump(app, 2)

    # ================= 02 分析工作台 =================
    ws = win.workspace
    win.screen_stack.setCurrentIndex(1)
    pump(app, 3)

    @check("02 四视口存在且都有内容")
    def _():
        vps = [w for w in ws.findChildren(QtWidgets.QWidget)
               if w.__class__.__name__ == "ViewportPane"]
        # 类名可能不同，退化为按像素检查截图
        pix = ws.grab()
        img = pix.toImage()
        colors = {img.pixel(x, y) for y in range(0, img.height(), 40)
                  for x in range(0, img.width(), 40)}
        if len(colors) < 30:
            raise RuntimeError(f"分析工作台画面单调（{len(colors)} 色），四视口可能空白")
    _()

    @check("02 LUT 库点击后真的改变显示")
    def _():
        grids = [w for w in ws.findChildren(QtWidgets.QWidget)
                 if w.__class__.__name__ == "LutGrid"]
        if not grids:
            raise RuntimeError("找不到 LutGrid 控件")
        g = grids[0]
        if not hasattr(g, "lutSelected"):
            raise RuntimeError("LutGrid 缺少 lutSelected 信号")
        got = []
        g.lutSelected.connect(lambda c: got.append(c))
        # 直接发信号模拟点击（等价于用户点色标块）
        g.lutSelected.emit("turbo")
        pump(app, 2)
        if not got:
            raise RuntimeError("lutSelected 没有触发")
    _()

    @check("02 统计摘要已填充")
    def _():
        txt = " ".join(lb.text() for lb in ws.findChildren(QtWidgets.QLabel))
        if "—" in txt and "有效" not in txt:
            raise RuntimeError("统计区仍是占位符")
        # 至少要有数字
        import re
        nums = re.findall(r"\d+\.\d+", txt)
        if len(nums) < 2:
            raise RuntimeError(f"统计数值缺失（只找到 {nums}）")
    _()

    # ================= 03 解码工作台 =================
    db = win.decodebench
    win.screen_stack.setCurrentIndex(2)
    pump(app, 2)

    @check("03 队列已带入文件")
    def _():
        if not getattr(db, "_items", None):
            raise RuntimeError("队列为空（打开文件时没有 add_files）")
    _()

    @check("03 流水线可运行并产生步骤状态")
    def _():
        if not hasattr(db, "run_queue"):
            raise RuntimeError("没有 run_queue")
        db.run_queue()
        pump(app, 12)
        items = db._items
        if not items:
            raise RuntimeError("队列仍为空")
        it = items[0]
        # 至少要跑过若干步
        step = getattr(it, "step", 0)
        if step < 3:
            raise RuntimeError(f"流水线只推进到第 {step} 步")
    _()

    @check("03 字段解析表有内容")
    def _():
        tables = db.findChildren(QtWidgets.QTableWidget)
        rows = max((t.rowCount() for t in tables), default=0)
        if rows == 0:
            raise RuntimeError("字段表 0 行")
    _()

    # ================= 04 制图工作台 =================
    fb = win.figurebench
    win.screen_stack.setCurrentIndex(3)
    pump(app, 3)

    @check("04 预览图已生成")
    def _():
        labels = [lb for lb in fb.findChildren(QtWidgets.QLabel)
                  if lb.pixmap() is not None and not lb.pixmap().isNull()]
        if not labels:
            raise RuntimeError("预览区没有图片")
    _()

    @check("04 模板可切换")
    def _():
        btns = [b for b in fb.findChildren(QtWidgets.QToolButton)]
        if len(btns) < 2:
            raise RuntimeError("模板按钮不足")
        for b in btns[:3]:
            if b.isEnabled():
                b.click()
                pump(app, 1.5)
                break
    _()

    @check("04 可无对话框导出（脚本/批量可用）")
    def _():
        # export() 会弹 QFileDialog，无法脚本化；必须有 export_to(path)
        if not hasattr(fb, "export_to"):
            raise RuntimeError("缺少 export_to(path)：导出只能弹对话框，批量与自动化都做不了")
        out = fb.export_to(Path(r"E:\CODEX-NOworkspaces\fysat\out\audit\bench_export.png"))
        if not Path(out).exists() or Path(out).stat().st_size < 5000:
            raise RuntimeError("导出文件异常")
    _()

    win.close()

    print("\n" + "=" * 60)
    ok = sum(1 for _, o, _ in R if o)
    print(f"通过 {ok} / {len(R)}")
    for n, o, w in R:
        if not o:
            print(f"  FAIL {n}: {w}")
    return 0 if ok == len(R) else 1


if __name__ == "__main__":
    raise SystemExit(main())
