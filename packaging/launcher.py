"""PyInstaller / 直接运行的统一入口。

单个可执行文件同时充当两种角色：

    FY-Sat-Studio.exe                      → 启动图形界面
    FY-Sat-Studio.exe info  <产品文件>      → 命令行子命令
    FY-Sat-Studio.exe --version            → 版本号

这样发布时只出一个二进制，用户不必区分"GUI 版"和"CLI 版"。
"""
from __future__ import annotations

import sys

# 这些是 CLI 的子命令；第一个参数命中就按命令行处理，否则进图形界面
CLI_COMMANDS = {
    "info", "ls", "export", "formats", "vars", "gui",
    "products", "product", "batch",
}
CLI_FLAGS = {"-h", "--help", "--version", "-V"}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    first = args[0] if args else ""

    if first in CLI_COMMANDS or first in CLI_FLAGS:
        from fysat.cli import main as cli_main

        return cli_main(args)

    # 没有任何参数、或第一个参数是文件/目录路径 → 启动 GUI
    from fysat.gui.app import main as gui_main

    return gui_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
