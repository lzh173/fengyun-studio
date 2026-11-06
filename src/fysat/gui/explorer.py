"""数据源浏览器：目录 → 文件树，按容器类型分组显示。"""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ..detect import sniff

DATA_EXT = {".hdf", ".h5", ".nc", ".dat", ".l1b", ".awx"}

# 扩展名 → 图标字（用文字代替图标资源，避免引入二进制资源与额外许可证）
KIND_BADGE = {
    "hdf5": "H5", "netcdf4": "NC", "netcdf3": "NC", "fy2_csv": "CSV",
    "oneb": "1B", "awx": "AWX", "png": "PNG", "jpeg": "JPG",
}


class Explorer(QtWidgets.QWidget):
    """文件浏览器：打开目录后列出可解析的产品文件。"""

    fileActivated = QtCore.Signal(str)      # 双击/回车打开

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        bar = QtWidgets.QWidget()
        bar_lay = QtWidgets.QHBoxLayout(bar)
        bar_lay.setContentsMargins(8, 6, 8, 6)
        bar_lay.setSpacing(6)

        self.btn_open = QtWidgets.QPushButton("打开目录")
        self.btn_open.setObjectName("primary")
        self.btn_refresh = QtWidgets.QPushButton("刷新")
        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText("过滤文件名…")

        bar_lay.addWidget(self.btn_open)
        bar_lay.addWidget(self.btn_refresh)
        lay.addWidget(bar)
        lay.addWidget(self.filter)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["名称", "类型", "大小"])
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 60)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        lay.addWidget(self.tree, 1)

        self._root: Path | None = None
        self._all_files: list[Path] = []

        self.btn_open.clicked.connect(self._choose_dir)
        self.btn_refresh.clicked.connect(self.reload)
        self.filter.textChanged.connect(self._apply_filter)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemActivated.connect(self._on_double_click)

    # ---------- 目录 ----------
    def _choose_dir(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择数据目录", str(self._root or Path.home()))
        if d:
            self.set_root(Path(d))

    def set_root(self, path: Path) -> None:
        self._root = Path(path)
        self.reload()

    def root(self) -> Path | None:
        return self._root

    def reload(self) -> None:
        self.tree.clear()
        self._all_files = []
        if not self._root or not self._root.exists():
            return

        self.setCursor(QtCore.Qt.WaitCursor)
        try:
            files = [p for p in self._root.rglob("*")
                     if p.is_file() and p.suffix.lower() in DATA_EXT]
        finally:
            self.unsetCursor()

        self._all_files = sorted(files)
        self._populate(self._all_files)

    def _populate(self, files: list[Path]) -> None:
        self.tree.clear()
        if not files:
            return

        # 按容器类型分组
        groups: dict[str, list[Path]] = {}
        for p in files:
            try:
                kind = sniff(p)
            except Exception:                       # noqa: BLE001
                kind = "unknown"
            groups.setdefault(kind, []).append(p)

        for kind in sorted(groups, key=lambda k: (-len(groups[k]), k)):
            items = groups[kind]
            top = QtWidgets.QTreeWidgetItem(self.tree)
            top.setText(0, f"{KIND_BADGE.get(kind, kind)}  ·  {len(items)} 个")
            top.setText(1, kind)
            top.setFirstColumnSpanned(False)
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)

            for p in items:
                it = QtWidgets.QTreeWidgetItem(top)
                it.setText(0, p.name)
                it.setText(1, KIND_BADGE.get(kind, "?"))
                size_mb = p.stat().st_size / 1e6
                it.setText(2, f"{size_mb:.1f} MB")
                it.setData(0, QtCore.Qt.UserRole, str(p))
                it.setToolTip(0, str(p))

    def _apply_filter(self, text: str) -> None:
        text = text.strip().lower()
        files = [p for p in self._all_files if text in p.name.lower()] if text else self._all_files
        self._populate(files)

    def _on_double_click(self, item: QtWidgets.QTreeWidgetItem, _col: int) -> None:
        path = item.data(0, QtCore.Qt.UserRole)
        if path:
            self.fileActivated.emit(str(path))
