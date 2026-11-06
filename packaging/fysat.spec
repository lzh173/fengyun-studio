# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包规格：FY-Sat Studio 单文件可执行程序。

用法（在仓库根目录）：
    pip install pyinstaller
    pyinstaller packaging/fysat.spec --distpath dist --workpath build

产物：
    dist/FY-Sat-Studio[.exe]

要点
----
* **必须打包包内数据**：products/*.yml、composites/*.yml、assets/*.geojson。
  漏掉任何一个，程序启动就会"找不到产品定义"或"画不出海岸线"。
* **排除 satpy**：它是可选后端，实装约 370 MB 且需要额外联网资源，
  打进单文件会让体积翻倍、启动变慢。需要时用 `pip install fysat[satpy]`。
* **排除测试与开发脚本**：不必要地增大体积。
* matplotlib 只需要 Agg 后端（本项目的图都往文件里出，不开交互窗口）。
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent   # noqa: F821 - SPECPATH 是 spec 所在目录

# 一次规格构建两种产物：
#   FYSAT_BUILD_KIND=gui  → FY-Sat-Studio（无控制台窗口，双击即用）
#   FYSAT_BUILD_KIND=cli  → fysat（带控制台，命令行能用）
# 直接用 console=False 做单一产物不行：Windows 上控制台输出会被丢弃，
# CLI 子命令就成了哑巴。
BUILD_KIND = os.environ.get("FYSAT_BUILD_KIND", "gui").lower()
IS_CLI = BUILD_KIND == "cli"
EXE_NAME = "fysat" if IS_CLI else "FY-Sat-Studio"
SRC = ROOT / "src"
PKG = SRC / "fysat"

# ---- 包内数据 ----
datas = [
    (str(PKG / "products"), "fysat/products"),
    (str(PKG / "composites"), "fysat/composites"),
    (str(PKG / "assets"), "fysat/assets"),
]

# ---- 隐式导入 ----
hiddenimports = [
    "fysat.gui.app",
    "fysat.gui.mainwindow",
    "fysat.gui.workspace",
    "fysat.gui.decodebench",
    "fysat.gui.figurebench",
    "fysat.gui.figdialog",
    "fysat.gui.inspector",
    "fysat.gui.chartwidgets",
    "fysat.gui.datatree",
    "fysat.gui.imageview",
    "fysat.gui.varcatalog",
    "fysat.gui.bandindex",
    "fysat.gui.explorer",
    "fysat.gui.theme",
    "fysat.gui.workers",
    "fysat.products.loader",
    "fysat.products.schema",
    "fysat.products.decode",
    "fysat.composites",
    "fysat.batch",
    "fysat.sciencefig",
    "fysat.palettes",
    # matplotlib 的 Agg 后端
    "matplotlib.backends.backend_agg",
    "matplotlib.backends.backend_pdf",
    "matplotlib.backends.backend_svg",
]
# PySide6 的子模块由 hooks-contrib 处理；这里补几个常被漏掉的插件依赖
hiddenimports += collect_submodules("fysat.readers")

excludes = [
    # 可选后端，体积巨大
    "satpy", "pyspectral", "pyresample", "pyproj", "dask", "xarray", "zarr",
    "trollimage", "trollsift", "pyorbital", "pykdtree", "donfig", "pooch",
    # 交互后端（本项目只往文件出图）
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_tkagg",
    "matplotlib.backends.backend_nbagg",
    "matplotlib.backends.backend_webagg",
    # 其它用不到的大件
    "tkinter", "IPython", "jupyter", "notebook", "pytest", "scipy.spatial.cKDTree",
]
# 注意：NDVI/composite 里用到了 scipy.spatial.cKDTree，别真排除它
excludes.remove("scipy.spatial.cKDTree")

block_cipher = None

a = Analysis(                                    # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)   # noqa: F821

exe = EXE(                                       # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX 会破坏 Qt 插件，且杀软误报率高
    upx_exclude=[],
    runtime_tmpdir=None,
    console=IS_CLI,            # GUI 版无控制台；CLI 版必须要有，否则看不到输出
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
