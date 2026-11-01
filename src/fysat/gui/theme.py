"""深色主题样式表，与 ui-mockup 设计稿保持一致。"""
from __future__ import annotations

# 设计变量（与 ui-mockup 一致）
BG = "#0c0e12"
PANEL = "#13161c"
PANEL2 = "#171b22"
LINE = "#242a34"
LINE2 = "#2e3542"
TXT = "#dfe5ee"
DIM = "#8b95a5"
DIM2 = "#5f6a7a"
ACCENT = "#22d3ee"
ACCENT2 = "#0ea5b7"
AMBER = "#fbbf24"
GREEN = "#34d399"
RED = "#f87171"
BLUE = "#60a5fa"

STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TXT};
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 12px;
}}

QMainWindow, QDialog {{ background: {BG}; }}

/* ---------- 菜单栏 / 工具栏 ---------- */
QMenuBar {{
    background: {PANEL};
    border-bottom: 1px solid {LINE};
    padding: 2px 6px;
}}
QMenuBar::item {{ padding: 5px 12px; background: transparent; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {LINE2}; }}
QMenu {{ background: {PANEL2}; border: 1px solid {LINE2}; padding: 4px; }}
QMenu::item {{ padding: 6px 26px 6px 20px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT2}; color: #04212a; }}
QMenu::separator {{ height: 1px; background: {LINE2}; margin: 4px 8px; }}

QToolBar {{
    background: {PANEL};
    border-bottom: 1px solid {LINE};
    spacing: 3px;
    padding: 5px 8px;
}}
QToolBar::separator {{ width: 1px; background: {LINE2}; margin: 0 6px; }}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 5px 10px;
    color: {DIM};
}}
QToolButton:hover {{ background: {LINE2}; color: {TXT}; }}
QToolButton:checked {{ background: #10333d; border-color: #1d5f70; color: #9fe9f5; }}
QToolButton:disabled {{ color: {DIM2}; }}

/* ---------- 停靠面板 ---------- */
QDockWidget {{
    titlebar-close-icon: none;
    color: {DIM};
    font-size: 11px;
}}
QDockWidget::title {{
    background: #151920;
    padding: 6px 10px;
    border-bottom: 1px solid {LINE};
    border-top: 1px solid #1b2029;
}}

/* ---------- 树 / 列表 / 表格 ---------- */
QTreeWidget, QTreeView, QListWidget, QTableWidget {{
    background: {PANEL};
    border: none;
    outline: none;
    alternate-background-color: {PANEL2};
}}
QTreeWidget::item, QListWidget::item {{ padding: 4px 2px; border-radius: 4px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: #1c222c; }}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background: #14303c; color: #a9ecf6;
}}
QHeaderView::section {{
    background: #151a22;
    color: {DIM};
    padding: 5px 8px;
    border: none;
    border-bottom: 1px solid {LINE};
    font-weight: 600;
}}
QTableWidget {{ gridline-color: #171c24; }}
QTableWidget::item {{ padding: 3px 6px; }}
QTableWidget::item:selected {{ background: #14303c; color: #a9ecf6; }}

/* ---------- 标签页 ---------- */
QTabWidget::pane {{ border: none; background: {BG}; }}
QTabBar::tab {{
    background: #151920;
    color: {DIM};
    padding: 7px 16px;
    border: 1px solid {LINE};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{ background: {BG}; color: {TXT}; border-color: {LINE2}; }}
QTabBar::tab:hover {{ color: {TXT}; }}

/* ---------- 输入控件 ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: #0e1116;
    border: 1px solid {LINE2};
    border-radius: 5px;
    padding: 4px 8px;
    color: {TXT};
    selection-background-color: {ACCENT2};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {PANEL2};
    border: 1px solid {LINE2};
    selection-background-color: {ACCENT2};
    selection-color: #04212a;
}}
QPushButton {{
    background: {LINE2};
    border: 1px solid #39424f;
    border-radius: 5px;
    padding: 6px 14px;
    color: {TXT};
}}
QPushButton:hover {{ background: #39424f; }}
QPushButton:pressed {{ background: #2b3340; }}
QPushButton:disabled {{ color: {DIM2}; border-color: {LINE}; }}
QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #22d3ee, stop:1 {ACCENT2});
    color: #04212a;
    font-weight: 700;
    border: none;
}}
QPushButton#primary:hover {{ background: #4ce0f5; }}

QCheckBox, QRadioButton {{ spacing: 7px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {LINE2};
    border-radius: 3px;
    background: #0e1116;
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QSlider::groove:horizontal {{
    height: 4px; border-radius: 2px; background: {LINE2};
}}
QSlider::handle:horizontal {{
    width: 12px; height: 12px; margin: -5px 0;
    border-radius: 6px; background: #d8e2ec;
}}
QSlider::sub-page:horizontal {{ background: {ACCENT2}; border-radius: 2px; }}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: #2b3340; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #3a4553; }}
QScrollBar:horizontal {{ background: {BG}; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: #2b3340; border-radius: 5px; min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- 状态栏 ---------- */
QStatusBar {{
    background: #101319;
    border-top: 1px solid {LINE};
    color: {DIM};
    font-size: 11px;
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ padding: 0 10px; }}

/* ---------- 分组框 ---------- */
QGroupBox {{
    border: 1px solid {LINE};
    border-radius: 7px;
    margin-top: 12px;
    padding-top: 10px;
    background: #11151b;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #9fb0c3;
    font-size: 11px;
    font-weight: 600;
}}

/* ---------- 进度条 ---------- */
QProgressBar {{
    background: {LINE};
    border: none;
    border-radius: 3px;
    height: 5px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT2}, stop:1 {ACCENT});
    border-radius: 3px;
}}

QSplitter::handle {{ background: {LINE}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

QToolTip {{
    background: #101820;
    color: {TXT};
    border: 1px solid {LINE2};
    padding: 4px 8px;
}}
"""


def ensure_cjk_font(app=None) -> str:
    """确保有可用中文字体，返回实际选用的字体族名。

    为什么需要这一步：
    - PySide6 wheel 不带字体（Qt 6 起不再内置），offscreen 平台尤其容易
      出现 "QFontDatabase: Cannot find font directory" 并把中文画成方框。
    - Windows 上系统字体在 C:\\Windows\\Fonts，Qt 一般能自动发现，
      但某些环境（精简系统 / 无 fontconfig / 隔离运行时）需要手动注册。

    策略：优先注册微软雅黑，其次黑体、宋体；都没有就退化为 Qt 默认。
    """
    import os
    from pathlib import Path

    from PySide6 import QtGui, QtWidgets

    candidates = [
        ("Microsoft YaHei", r"C:\Windows\Fonts\msyh.ttc"),
        ("Microsoft YaHei UI", r"C:\Windows\Fonts\msyh.ttc"),
        ("SimHei", r"C:\Windows\Fonts\simhei.ttf"),
        ("SimSun", r"C:\Windows\Fonts\simsun.ttc"),
        ("Noto Sans CJK SC", r"C:\Windows\Fonts\NotoSansCJK-Regular.ttc"),
    ]

    loaded: list[str] = []
    for family, path in candidates:
        if not Path(path).exists():
            continue
        fid = QtGui.QFontDatabase.addApplicationFont(path)
        if fid >= 0:
            fams = QtGui.QFontDatabase.applicationFontFamilies(fid)
            loaded.extend(fams)

    # 选出第一个系统里真实存在的字体族
    available = set(QtGui.QFontDatabase.families())
    chosen = ""
    for family, _ in candidates:
        if family in available or family in loaded:
            chosen = family
            break
    if not chosen:
        chosen = "Microsoft YaHei UI"

    if app is None:
        app = QtWidgets.QApplication.instance()
    if app is not None:
        f = QtGui.QFont(chosen, 9)
        f.setStyleStrategy(QtGui.QFont.PreferAntialias)
        app.setFont(f)

    # offscreen 平台即使注册了字体也可能缺 fontconfig，兜底把字体目录塞进去
    os.environ.setdefault("QT_QPA_FONTDIR", str(Path(r"C:\Windows\Fonts")))
    return chosen


def apply_theme(app) -> None:
    """给 QApplication 应用深色主题（含中文字体注册）。"""
    app.setStyle("Fusion")
    ensure_cjk_font(app)
    app.setStyleSheet(STYLESHEET)
