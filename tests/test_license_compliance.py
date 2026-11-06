"""许可证合规测试：把 LICENSES.md 里的硬约束固化成自动检查。

这些测试会在导入 GUI 模块**之前**检查环境，任何一个失败都意味着
可能引入 GPL 污染，必须修复后才能分发。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# Qt 6 中 GPLv3-only 的模块（用错会污染整个软件）
GPL_ONLY_QT_MODULES = [
    "QtCharts", "QtDataVisualization", "QtGraphs", "QtVirtualKeyboard",
    "QtQuick3D", "QtQuick3DPhysics", "QtQuickTimeline", "QtLottie",
    "QtNetworkAuth", "QtCoap", "QtMqtt", "QtHttpServer", "QtGrpc",
    "QtQmlCompiler", "QtCanvasPainter",
]

# LGPLv3 可用的模块
LGPL_QT_MODULES = ["QtCore", "QtGui", "QtWidgets", "QtNetwork",
                   "QtOpenGL", "QtOpenGLWidgets", "QtSvg", "QtPrintSupport"]


def _iter_py_files():
    yield from SRC.rglob("*.py")


# ---------------- 源码级检查（不依赖安装了任何东西） ----------------

def test_no_pyqt_anywhere():
    """PyQt / sip 是 GPL，一旦出现整个项目就得跟着 GPL。"""
    bad = []
    for p in _iter_py_files():
        text = p.read_text(encoding="utf-8", errors="ignore")
        for pat in (r"^\s*import\s+PyQt[56]", r"^\s*from\s+PyQt[56]",
                    r"^\s*import\s+sip\b", r"^\s*from\s+sip\b"):
            if re.search(pat, text, re.M):
                bad.append(f"{p.relative_to(ROOT)}: {pat}")
    assert not bad, "检测到 GPL 的 PyQt/sip 导入：\n" + "\n".join(bad)


def test_no_gpl_only_qt_modules_in_source():
    bad = []
    for p in _iter_py_files():
        text = p.read_text(encoding="utf-8", errors="ignore")
        for mod in GPL_ONLY_QT_MODULES:
            if re.search(rf"^\s*(from|import)\s+.*\b{mod}\b", text, re.M):
                bad.append(f"{p.relative_to(ROOT)} → {mod}")
    assert not bad, "检测到 GPLv3-only 的 Qt 模块：\n" + "\n".join(bad)


def test_only_whitelisted_qt_modules_imported():
    """实际 import 的 PySide6 子模块必须都在白名单里。"""
    used = set()
    for p in _iter_py_files():
        text = p.read_text(encoding="utf-8", errors="ignore")
        used |= set(re.findall(r"from\s+PySide6\s+import\s+([^\n]+)", text))
        used |= set(re.findall(r"from\s+PySide6\.(\w+)\s+import", text))
    flat = set()
    for chunk in used:
        for tok in re.split(r"[,\s]+", chunk):
            tok = tok.strip()
            if tok and tok[0].isupper():
                flat.add(tok)
    unexpected = flat - set(LGPL_QT_MODULES) - {"__version__"}
    assert not unexpected, f"导入了白名单外的 Qt 模块: {sorted(unexpected)}"


def test_pyproject_declares_essentials_not_full_pyside6():
    """PySide6 元包会拉 PySide6-Addons（含 GPL-only 模块）。"""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    gui_line = [ln for ln in text.splitlines() if ln.strip().startswith("gui =")]
    assert gui_line, "pyproject 缺少 gui 可选依赖声明"
    line = gui_line[0]
    assert "PySide6-Essentials" in line, \
        f"gui 依赖必须写 PySide6-Essentials，实际: {line}"
    # 裸 "PySide6" 指元包：形如 "PySide6>=x" 或 "PySide6==x"（后面直接跟比较符）
    assert not re.search(r'"PySide6(>=|==|>|<|~=|\")', line), \
        f'不能声明裸 "PySide6"（会拉入 Addons），实际: {line}'


def test_license_declared():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "AGPL-3.0-only" in text, "pyproject 必须声明本项目许可证"


def test_license_files_present():
    """分发前必须附带的许可证文件（AGPL 策略下含根目录 LICENSE 与附加条款）。"""
    required = [
        "LICENSE",                                   # AGPL-3.0 全文
        "LICENSES.md",
        "THIRD_PARTY_NOTICES.md",
        "docs/licenses/FYSAT-ADDITIONAL-TERMS.md",    # §7(b)(c) 附加条款
        "docs/licenses/FYSAT-OUTPUT-ATTRIBUTION-1.0.md",  # 数据条款
    ]
    missing = [f for f in required if not (ROOT / f).exists()]
    assert not missing, f"缺少许可证文件: {missing}"


def test_license_is_agpl_text():
    """根 LICENSE 必须是 AGPL-3.0 正文，不能只写一句话。"""
    text = (ROOT / "LICENSE").read_text(encoding="utf-8", errors="ignore")
    assert len(text) > 20000, f"LICENSE 只有 {len(text)} 字节，疑似不是全文"
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in text.upper()
    assert "Version 3" in text


def test_readme_mentions_license():
    """README 必须有许可证章节，指向 LICENSE / LICENSES.md。"""
    text = (ROOT / "README.md").read_text(encoding="utf-8", errors="ignore")
    assert "AGPL" in text, "README 未提及 AGPL 许可证"
    assert "LICENSES.md" in text or "LICENSE" in text, "README 未链接许可证文件"


# ---------------- 运行时检查（装了 PySide6 才跑） ----------------

@pytest.mark.skipif(
    pytest.importorskip("PySide6", reason="未安装 PySide6") is None if False else False,
    reason="unused",
)
def test_runtime_has_no_gpl_qt_module_loaded():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    import sys

    for mod in GPL_ONLY_QT_MODULES:
        assert f"PySide6.{mod}" not in sys.modules, \
            f"运行时加载了 GPL-only 模块 PySide6.{mod}"


def test_app_forces_pyside6_matplotlib_backend():
    """app.py 必须在导入 matplotlib 前设置 QT_API=pyside6。"""
    text = (SRC / "fysat" / "gui" / "app.py").read_text(encoding="utf-8")
    assert "QT_API" in text and "pyside6" in text, \
        "app.py 必须显式设置 QT_API=pyside6，否则 matplotlib 可能选中 GPL 的 PyQt"
    # QT_API 设置必须出现在 matplotlib.use 之前
    assert text.index("QT_API") < text.index("matplotlib.use"), \
        "QT_API 必须在 matplotlib.use 之前设置"
