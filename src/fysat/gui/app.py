"""GUI 入口：创建 QApplication、应用主题、显示主窗口。"""
from __future__ import annotations

import os
import sys
import traceback


def _force_pyside6_backend() -> None:
    """强制 matplotlib 使用 PySide6 后端。

    matplotlib 的 qt_compat 会按 PyQt6 → PyQt5 → PySide6 → PySide2 的顺序探测，
    一旦环境里装了 PyQt（GPL）就会优先选中它，把整个程序拖进 GPL。
    必须在 import matplotlib.pyplot 之前设置。

    这是许可证合规的硬要求，见 LICENSES.md §4.3。
    """
    os.environ.setdefault("QT_API", "pyside6")
    try:
        import matplotlib

        matplotlib.use("QtAgg", force=True)
    except Exception:                       # noqa: BLE001
        pass                                # 没有 matplotlib 也不影响 GUI 本身


def main(argv: list[str] | None = None) -> int:
    """启动 GUI。返回进程退出码。"""
    _force_pyside6_backend()

    from PySide6 import QtCore, QtWidgets

    from . import theme
    from .mainwindow import MainWindow

    argv = list(sys.argv if argv is None else argv)

    app = QtWidgets.QApplication(argv)
    app.setApplicationName("FY-Sat Studio")
    app.setOrganizationName("FY-Sat")
    theme.apply_theme(app)

    # 未捕获异常不要静默退出
    def _excepthook(exc_type, exc, tb):
        msg = "".join(traceback.format_exception(exc_type, exc, tb))
        sys.stderr.write(msg)
        QtWidgets.QMessageBox.critical(None, "未处理的异常", str(exc))

    sys.excepthook = _excepthook

    win = MainWindow()
    win.show()

    # 支持 "fysat gui <文件>" 直接打开
    if len(argv) > 1:
        QtCore.QTimer.singleShot(50, lambda: win.load_file(argv[1]))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
