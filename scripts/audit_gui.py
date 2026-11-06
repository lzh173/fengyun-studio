from __future__ import annotations

import os
from pathlib import Path

# 样本目录与输出目录都走环境变量/相对路径，开源版不写死任何人的机器
SAMPLE_ROOT = Path(os.environ.get("FYSAT_SAMPLE_ROOT", ""))


def _require_sample_root() -> Path:
    """开发脚本必须显式指定样本目录，避免把某台机器的路径写进仓库。"""
    if not str(SAMPLE_ROOT) or not SAMPLE_ROOT.is_dir():
        raise SystemExit(
            "请先设置环境变量 FYSAT_SAMPLE_ROOT 指向 NSMC 产品目录\n"
            "  PowerShell:  $env:FYSAT_SAMPLE_ROOT = \"D:\\samples\"\n"
            "  bash:        export FYSAT_SAMPLE_ROOT=/data/samples")
    return SAMPLE_ROOT

_OUT = Path(__file__).resolve().parents[1] / "out"


def _sample(rel: str) -> Path:
    return SAMPLE_ROOT / rel


"""GUI 功能可执行性审查：逐项调用既有功能，记录"能不能用"。

不靠肉眼点，而是程序化触发每个入口，把失败原因抓下来。
输出一份审计表：功能 / 结果 / 原因。
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6 import QtCore, QtGui, QtWidgets      # noqa: E402

from fysat.gui import theme                        # noqa: E402
from fysat.gui.mainwindow import MainWindow        # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, why: str = "") -> None:
    RESULTS.append((name, ok, why))
    mark = "OK  " if ok else "FAIL"
    print(f"[{mark}] {name}" + (f"  — {why}" if why else ""), flush=True)


def probe(name: str):
    """装饰器：把异常收敛成一条 FAIL 记录。"""
    def deco(fn):
        try:
            fn()
            record(name, True)
        except Exception as exc:                    # noqa: BLE001
            record(name, False, f"{type(exc).__name__}: {exc}")
        return fn
    return deco


def pump(app, sec: float) -> None:
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        QtCore.QThread.msleep(15)


def wait_for(app, pred, timeout=25.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        QtCore.QThread.msleep(20)
        if pred():
            return True
    return pred()


def main() -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.apply_theme(app)
    win = MainWindow()
    win.resize(1600, 1000)
    win.show()

    sample = None
    for pat in ("FY3D_MERSI_GBAL_L1_*1000M_MS.HDF",
                "FY3H_MERSI_GRAN_L1_*1000M*.HDF"):
        hits = sorted(SAMPLE_ROOT.rglob(pat))
        hits = [h for h in hits if h.stat().st_size > 10_000_000]
        if hits:
            sample = hits[0]
            break
    if sample is None:
        print("找不到样本，无法审查", file=sys.stderr)
        return 2
    print(f"样本: {sample.name}\n", flush=True)

    # ---------- 1. 打开文件 ----------
    def t_load():
        win.load_file(str(sample))
        ok = wait_for(app, lambda: win._ds is not None
                      and win.canvas.array() is not None
                      and tuple(win.canvas.array().shape[:2]) != (600, 800))
        if not ok:
            raise RuntimeError(f"画布未更新（当前 {win.canvas.array().shape if win.canvas.array() is not None else None}）")
    probe("01 主界面：打开产品并渲染")(t_load)

    # ---------- 2. 变量列表 / 通道切换 ----------
    def t_vars():
        # 必须先切到"变量"页，否则 isVisible() 对隐藏的父控件一律返回 False
        win.inspector.tabs.setCurrentIndex(1)
        pump(app, 0.3)
        n = win.inspector.var_table.rowCount()
        if n == 0:
            raise RuntimeError("变量表为空")
        # 选一个多通道变量，切通道
        for i in range(n):
            name = win.inspector.var_table.item(i, 0).text()
            if win.inspector._classes[name].kind == "band_stack":
                win.inspector.var_table.selectRow(i)
                pump(app, 0.5)
                if not win.inspector.band_row.isVisible():
                    raise RuntimeError("多通道变量的通道选择器未显示")
                win.inspector.band_spin.setValue(3)
                pump(app, 6)
                break
    probe("01 变量列表 + 通道切换")(t_vars)

    # ---------- 3. 显示参数（色标/拉伸/伽马） ----------
    def t_display():
        before = win.canvas.array().copy()
        win.inspector.cmap_combo.setCurrentText("turbo")
        win.inspector.stretch_combo.setCurrentIndex(1)
        ok = wait_for(app, lambda: not (win.canvas.array() == before).all(), 20)
        if not ok:
            raise RuntimeError("改色标后画布没变化")
    probe("01 显示参数：色标/拉伸生效")(t_display)

    # ---------- 4. 叠加层（海岸线/经纬网） ----------
    def t_overlay():
        ov = getattr(win, "_overlay", None)
        if ov is None:
            raise RuntimeError("叠加层未创建")
        if not ov.isVisible():
            raise RuntimeError("叠加层不可见")
        n = len(ov._segments)
        if n < 100:
            raise RuntimeError(f"海岸线段数只有 {n}")
        win.toggle_overlay("coast", False)
        pump(app, 0.2)
        win.toggle_overlay("coast", True)
        pump(app, 0.2)
    probe("01 叠加层：海岸线 + 经纬网")(t_overlay)

    # ---------- 5. 框选 ----------
    def t_select():
        c = win.canvas
        c.set_select_mode(True)
        r = c.viewport().rect()
        ctr = r.center()
        p1 = ctr + QtCore.QPoint(-120, -90)
        p2 = ctr + QtCore.QPoint(120, 90)
        for pt, typ in ((p1, QtCore.QEvent.MouseButtonPress),
                        (p2, QtCore.QEvent.MouseMove),
                        (p2, QtCore.QEvent.MouseButtonRelease)):
            ev = QtGui.QMouseEvent(typ, QtCore.QPointF(pt), QtCore.Qt.LeftButton,
                                   QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
            QtWidgets.QApplication.sendEvent(c.viewport(), ev)
        pump(app, 0.3)
        if win._selection is None:
            raise RuntimeError("拖拽后没有选区")
    probe("01 框选（真实拖拽）")(t_select)

    # ---------- 6. 普通导出三种格式 ----------
    for kind in ("tiff", "png_full", "png_compressed"):
        def t_export(kind=kind):
            from fysat.export import ExportOptions, export
            from fysat.provenance import build_provenance
            from fysat.render import display_band
            var = win._ds.load(win._current_var)
            data = display_band(var, win._current_band, physical=True)
            out = OUT_ROOT / r"audit" / f"a_{kind}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            opts = ExportOptions(kind=kind, path=out, scale=0.2 if kind == "png_compressed" else 1.0)
            opts.provenance = build_provenance(win._ds, variable=win._current_var)
            p = export(data.astype("float32"), opts)
            if not p.exists() or p.stat().st_size < 1000:
                raise RuntimeError("输出文件为空")
        probe(f"导出 {kind}")(t_export)

    # ---------- 7. 科学制图 ----------
    def t_science():
        from fysat.gui.figdialog import ScienceFigureDialog
        dlg = ScienceFigureDialog(win, ds=win._ds, region_px=win._selection)
        out = dlg._render(OUT_ROOT / r"audit\science.png")
        if not out.exists() or out.stat().st_size < 5000:
            raise RuntimeError("科学图输出异常")
        dlg.close()
    probe("04 科学制图导出")(t_science)

    # ---------- 8. 四个工作台可切换且有内容 ----------
    for idx, label in enumerate(("01 主界面", "02 分析工作台",
                                 "03 解码工作台", "04 制图工作台")):
        def t_screen(idx=idx, label=label):
            win.screen_stack.setCurrentIndex(idx)
            pump(app, 1.5)
            pix = win.grab()
            if pix.isNull():
                raise RuntimeError("截图为空")
            img = pix.toImage()
            # 采样看是否有足够颜色（纯色说明没画出来）
            colors = {img.pixel(x, y)
                      for y in range(0, img.height(), 60)
                      for x in range(0, img.width(), 60)}
            if len(colors) < 8:
                raise RuntimeError(f"画面疑似空白（{len(colors)} 种颜色）")
        probe(f"{label}：可切换且有内容")(t_screen)

    win.close()

    print("\n" + "=" * 60)
    ok = sum(1 for _, o, _ in RESULTS if o)
    print(f"通过 {ok} / {len(RESULTS)}")
    for name, o, why in RESULTS:
        if not o:
            print(f"  FAIL {name}: {why}")
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
