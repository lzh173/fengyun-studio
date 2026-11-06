"""四屏 GUI 截图脚本（offscreen）：构建每一屏 → 载入真实样本 → 保存 PNG。

用法：
    export QT_QPA_PLATFORM=offscreen
    export FYSAT_SAMPLE_ROOT=/data/samples
    python scripts/shoot_gui.py [screen ...]

它会输出 out/gui/02_workspace.png 等文件，并在 stdout 里报告每屏的
关键控件状态，方便判断"是不是真的画出东西了"（而不是一片空白）。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np  # noqa: E402
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from fysat.readers import open_file  # noqa: E402

SAMPLE_ROOT = Path(os.environ.get("FYSAT_SAMPLE_ROOT", ""))


def _require_sample_root() -> Path:
    """开发脚本必须显式指定样本目录，避免把某台机器的路径写进仓库。"""
    if not str(SAMPLE_ROOT) or not SAMPLE_ROOT.is_dir():
        raise SystemExit(
            "请先设置环境变量 FYSAT_SAMPLE_ROOT 指向 NSMC 产品目录\n"
            "  PowerShell:  $env:FYSAT_SAMPLE_ROOT = \"D:\\samples\"\n"
            "  bash:        export FYSAT_SAMPLE_ROOT=/data/samples")
    return SAMPLE_ROOT


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyside6")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


OUT = ROOT / "out" / "gui"

SAMPLES = {
    "fy3d": str(SAMPLE_ROOT / r"C202611011426140096\FY3D_MERSI_GBAL_L1_20260810_0635_1000M_MS.HDF"),
    "fy3h": str(SAMPLE_ROOT / r"FY3H_MERSI_GRAN_L1_20261023_0520_1000M_V0.hdf"),
}


def pick_sample(key: str = "fy3d") -> str | None:
    p = SAMPLES.get(key)
    if p and Path(p).exists():
        return p
    for q in SAMPLES.values():
        if Path(q).exists():
            return q
    return None


def wait_until(app, predicate, timeout_s: float = 120.0) -> bool:
    """跑事件循环直到 predicate 为真（线程池结果靠事件循环投递）。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 100)
        if predicate():
            return True
        QtCore.QThread.msleep(20)
    return bool(predicate())


def settle(app, ms: int = 700) -> None:
    """再跑一会儿事件循环，让重绘/布局收尾。"""
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        QtCore.QThread.msleep(10)


def grab(widget, name: str, app) -> Path:
    settle(app)
    widget.resize(widget.width() or 1600, widget.height() or 1000)
    app.processEvents()
    pix = widget.grab()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    assert pix.save(str(path)), f"保存失败 {path}"

    img = pix.toImage().convertToFormat(QtGui.QImage.Format_RGB32)
    # 逐点扫描太慢，但步长必须足够小：37 px 的网格会把界面细节全漏掉，
    # 导致彩色界面被误判成"空白"。这里用 numpy 走内存直接算。
    buf = img.constBits()
    arr = np.frombuffer(buf, dtype=np.uint8)
    arr = arr.reshape((img.height(), img.bytesPerLine()))[:, : img.width() * 4]
    arr = arr.reshape(img.height(), img.width(), 4)[:, :, :3]
    uniq = len(np.unique(arr.reshape(-1, 3), axis=0))
    print(f"  [shot] {path.name}  {img.width()}x{img.height()}  "
          f"颜色种类={uniq}  均值={arr.mean():.1f}")
    assert uniq > 40, f"{name} 疑似空白（只有 {uniq} 种颜色）"
    return path


# ---------------- 各屏 ----------------

def shoot_workspace(app, sample: str) -> None:
    from fysat.gui.workspace import AnalysisWorkspace

    ds = open_file(sample, load=False)
    w = AnalysisWorkspace()
    w.resize(1600, 940)
    w.show()
    app.processEvents()
    w.set_dataset(ds)

    ok = wait_until(
        app,
        lambda: all(p.array() is not None for p in w._panes[:3]),
        timeout_s=180.0)
    print(f"  loaded panes A/B/C rendered = {ok}")
    for p in w._panes[:3]:
        st = p.stat()
        print(f"    {p.tag}: var={p.current_var()} band={p.current_band()} "
              f"arr={None if p.array() is None else p.array().shape} "
              f"min={st.vmin:.4g} max={st.vmax:.4g} valid={st.valid_pct:.1f}%")
    # 让 B 视口换一个通道，体现"同数据集不同通道"
    if w._panes[1].spin_band.maximum() > 1:
        w._panes[1].spin_band.setValue(2)      # 12 µm
    if w._panes[2].spin_band.maximum() > 2:
        w._panes[2].spin_band.setValue(3)      # 通道 3
        w.lut_grid.set_current("inferno")
        w._cmap = "inferno"
        w._render_pane(2)
    wait_until(app, lambda: len(w._inflight) == 0, timeout_s=120.0)
    settle(app, 900)
    for p in w._panes[:3]:
        p.raise_overlays()
    settle(app, 400)
    grab(w, "02_workspace.png", app)
    w.close()


def shoot_decode(app, sample: str, extra: list[str]) -> None:
    from fysat.gui.decodebench import DecodeBench

    w = DecodeBench()
    w.resize(1600, 940)
    w.show()
    app.processEvents()
    w.add_files([sample, *extra])
    print(f"  queued {len(w._items)} files: "
          f"{[i.kind for i in w._items]}")
    w.run_queue()
    started = time.time()
    # 先等「至少全部进入过 running」，再等 idle：
    # run_queue 里 _running 是同步加上的，但线程池要一拍才真正开跑，
    # 直接等 idle 可能在线程启动前就为真，拍到空界面。
    wait_until(app, lambda: w._running > 0 or w.is_idle(), timeout_s=10.0)
    ok = wait_until(app, lambda: w.is_idle(), timeout_s=300.0)
    print(f"  decode finished={ok} in {time.time() - started:.1f}s")
    for it in w._items:
        print(f"    {it.status:7s} step={it.step} fields={len(it.fields)} "
              f"checks={sum(1 for c in it.checks if c[1])}/{len(it.checks)} "
              f"kind={it.kind} err={it.error[:60]}")
    settle(app, 900)
    grab(w, "03_decode.png", app)
    w.close()


def shoot_figure(app, sample: str) -> None:
    from fysat.gui.figurebench import FigureBench

    ds = open_file(sample, load=False)
    w = FigureBench()
    w.resize(1600, 940)
    w.show()
    app.processEvents()
    w.set_dataset(ds)
    ok = wait_until(app, lambda: w.preview_ready(), timeout_s=240.0)
    print(f"  figure preview ready = {ok}")
    settle(app, 900)
    grab(w, "04_figure.png", app)
    w.close()


def shoot_main(app, sample: str) -> None:
    from fysat.gui.mainwindow import MainWindow

    w = MainWindow()
    w.resize(1600, 940)
    w.show()
    app.processEvents()
    if sample:
        w.load_file(sample)
        wait_until(app, lambda: w._ds is not None and w.canvas.array() is not None,
                   timeout_s=180.0)
    settle(app, 900)
    grab(w, "01_main.png", app)
    w.close()


def main(argv: list[str]) -> int:
    screens = argv[1:] or ["02", "03", "04", "01"]
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    from fysat.gui import theme

    theme.apply_theme(app)

    sample = pick_sample("fy3d")
    fy3h = SAMPLES["fy3h"] if Path(SAMPLES["fy3h"]).exists() else sample
    print(f"sample = {sample}")
    print(f"sample2 = {fy3h}")

    for s in screens:
        print(f"== 截图 {s} ==")
        t0 = time.time()
        if s == "02":
            shoot_workspace(app, sample)
        elif s == "03":
            shoot_decode(app, sample, [fy3h])
        elif s == "04":
            shoot_figure(app, sample)
        elif s == "01":
            shoot_main(app, sample)
        else:
            print(f"  未知屏 {s}")
        print(f"  用时 {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
