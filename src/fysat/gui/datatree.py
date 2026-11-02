"""数据源树：按「数据源目录 → 卫星/仪器 → 产品文件」三层组织。

为什么需要重新分层
------------------
原 ``explorer.py`` 只按**容器类型**分组（HDF5 一堆、NetCDF 一堆）。实际用起来
这几乎没用：用户脑子里的结构是「我导入了 3 个目录 → 里面是 FY-3D MERSI 和
FY-4B AGRI → 我要找 08-10 那轨」。所以这里改成三层：

    数据源目录            E:\\...\\C202611011426140096        12 个
      ├─ FY-3D · MERSI    L1 · 10 个
      │    ├─ FY3D_MERSI_GBAL_L1_20260810_0635_1000M_MS.HDF
      │    └─ …
      └─ FY-3H · MERSI    L1 · 2 个

第二层的「卫星/仪器」直接从**文件名**解析（``detect.parse_name``），
不需要打开文件——几万个文件也不会卡，因为解析只做正则匹配。
只有用户双击文件时才真正 ``open_file``。

容器类型仍然保留：作为第三层文件后面的小徽标（H5 / NC / 1B / AWX），
这样两种信息都在，但主结构以业务视角为主。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..detect import parse_name, sniff
from . import theme

DATA_EXT = {".hdf", ".h5", ".he5", ".hdf5", ".nc", ".nc4", ".dat",
            ".l1b", ".1b", ".awx", ".svissr", ".enp"}

KIND_BADGE = {
    "hdf5": "H5", "netcdf4": "NC", "netcdf3": "NC3", "fy2_csv": "CSV",
    "oneb": "1B", "awx": "AWX", "jpeg": "JPG", "png": "PNG",
    "tiff": "TIF", "unknown": "?",
}

ROLE_PATH = QtCore.Qt.UserRole + 1
ROLE_KIND = QtCore.Qt.UserRole + 2


@dataclass
class FileEntry:
    """一个候选产品文件。"""

    path: Path
    kind: str = "unknown"
    platform: str = ""
    instrument: str = ""
    level: str = ""
    when: str = ""

    def label(self) -> str:
        return self.path.name

    def group_key(self) -> tuple[str, str, str]:
        """第二层分组键：卫星 / 仪器 / 层级。"""
        return (self.platform or "未知卫星",
                self.instrument or "未知仪器",
                self.level or "")


def scan_dir(root: Path, max_files: int = 20000) -> list[FileEntry]:
    """扫描目录下的产品文件，并按文件名解析卫星/仪器（不快照打不开文件）。"""
    out: list[FileEntry] = []
    if not root.exists():
        return out
    try:
        paths = sorted(p for p in root.rglob("*")
                       if p.is_file() and p.suffix.lower() in DATA_EXT)
    except OSError:
        return out
    for p in paths[:max_files]:
        info = parse_name(p)
        out.append(FileEntry(
            path=p,
            platform=info.platform,
            instrument=info.instrument,
            level=info.level,
            when=(info.start_time.strftime("%m-%d %H:%M")
                  if info.start_time else ""),
        ))
    return out


class DataTree(QtWidgets.QWidget):
    """三层数据树 + 过滤 + 类型徽标。"""

    fileActivated = QtCore.Signal(str)          # 双击/回车打开

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        bar = QtWidgets.QWidget()
        bl = QtWidgets.QHBoxLayout(bar)
        bl.setContentsMargins(8, 6, 8, 6)
        bl.setSpacing(5)
        self.btn_open = QtWidgets.QPushButton("打开目录")
        self.btn_open.setObjectName("primary")
        self.btn_refresh = QtWidgets.QPushButton("刷新")
        self.btn_collapse = QtWidgets.QPushButton("收起")
        bl.addWidget(self.btn_open)
        bl.addWidget(self.btn_refresh)
        bl.addWidget(self.btn_collapse)
        lay.addWidget(bar)

        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText("过滤文件名 / 卫星 / 仪器…")
        self.filter.setClearButtonEnabled(True)
        lay.addWidget(self.filter)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["名称", "类型", "大小"])
        self.tree.setColumnWidth(0, 250)
        self.tree.setColumnWidth(1, 52)
        self.tree.setColumnWidth(2, 68)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(True)
        lay.addWidget(self.tree, 1)

        self.lbl_summary = QtWidgets.QLabel("尚未添加数据源")
        self.lbl_summary.setStyleSheet("color:#5f6a7a;font-size:10px;padding:4px 10px;")
        lay.addWidget(self.lbl_summary)

        self._sources: list[tuple[Path, list[FileEntry]]] = []
        self._filter_text = ""

        self.btn_open.clicked.connect(self.choose_dir)
        self.btn_refresh.clicked.connect(self.reload)
        self.btn_collapse.clicked.connect(self.collapse_all)
        self.filter.textChanged.connect(self._on_filter)
        self.tree.itemDoubleClicked.connect(self._on_activate)
        self.tree.itemActivated.connect(self._on_activate)

    # ---------------- 数据源 ----------------
    def choose_dir(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择数据目录",
            str(self._sources[0][0] if self._sources else Path.home()))
        if d:
            self.add_source(Path(d))

    def add_source(self, path: Path) -> None:
        """加入一个数据源目录（重复则刷新）。"""
        path = Path(path)
        existing = [i for i, (p, _f) in enumerate(self._sources) if p == path]
        if existing:
            self._sources.pop(existing[0])
        entries = scan_dir(path)
        self._sources.append((path, entries))
        self.reload()

    def set_sources(self, paths: list[Path]) -> None:
        self._sources = []
        for p in paths:
            self._sources.append((Path(p), scan_dir(Path(p))))
        self.reload()

    def sources(self) -> list[Path]:
        return [p for p, _ in self._sources]

    def reload(self) -> None:
        """重新扫描所有数据源并重建树。"""
        for i, (p, _f) in enumerate(list(self._sources)):
            self._sources[i] = (p, scan_dir(p))
        self._populate()

    def collapse_all(self) -> None:
        self.tree.collapseAll()

    # ---------------- 构建树 ----------------
    def _populate(self) -> None:
        self.tree.clear()
        all_entries: list[FileEntry] = []
        for path, entries in self._sources:
            all_entries.extend(entries)

        total_files = 0
        total_shown = 0

        for path, entries in self._sources:
            shown = [e for e in entries if self._match(e, path)]
            total_files += len(entries)
            total_shown += len(shown)

            top = QtWidgets.QTreeWidgetItem(self.tree)
            top.setText(0, f"{path.name}  ·  {len(shown)}/{len(entries)} 个")
            top.setText(1, "目录")
            top.setToolTip(0, str(path))
            top.setData(0, ROLE_PATH, str(path))
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            top.setForeground(1, QtGui.QColor(theme.DIM2))

            # 第二层：按 (卫星, 仪器, 层级) 分组
            groups: dict[tuple[str, str, str], list[FileEntry]] = defaultdict(list)
            for e in shown:
                groups[e.group_key()].append(e)

            for key in sorted(groups, key=lambda k: (-len(groups[k]), k)):
                items = groups[key]
                platform, instrument, level = key
                gitem = QtWidgets.QTreeWidgetItem(top)
                name = f"{platform} · {instrument}"
                if level:
                    name += f"  {level}"
                gitem.setText(0, name)
                gitem.setText(1, f"{len(items)} 个")
                gitem.setForeground(0, QtGui.QColor("#cfd8e3"))
                gitem.setForeground(1, QtGui.QColor(theme.DIM2))
                gitem.setToolTip(0, f"{platform} {instrument} {level}".strip())

                for e in sorted(items, key=lambda x: (x.when, x.path.name),
                                reverse=True):
                    it = QtWidgets.QTreeWidgetItem(gitem)
                    it.setText(0, e.label())
                    it.setText(1, KIND_BADGE.get(e.kind or self._kind_of(e), "?"))
                    it.setText(2, self._size_text(e.path))
                    it.setData(0, ROLE_PATH, str(e.path))
                    it.setToolTip(0, str(e.path))
                    it.setForeground(2, QtGui.QColor(theme.DIM2))
                    if e.when:
                        it.setToolTip(1, e.when)
            top.setExpanded(len(self._sources) <= 4)

        n_sources = len(self._sources)
        if n_sources == 0:
            self.lbl_summary.setText("尚未添加数据源")
        else:
            self.lbl_summary.setText(
                f"{n_sources} 个数据源 · 显示 {total_shown}/{total_files} 个文件")

    def _kind_of(self, e: FileEntry) -> str:
        """延迟 sniff（只在需要徽标时读 64 字节）。"""
        if e.kind and e.kind != "unknown":
            return e.kind
        try:
            e.kind = sniff(e.path)
        except Exception:                       # noqa: BLE001
            e.kind = "unknown"
        return e.kind

    @staticmethod
    def _size_text(p: Path) -> str:
        try:
            n = p.stat().st_size
        except OSError:
            return "—"
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024.0
        return "—"

    # ---------------- 过滤 ----------------
    def _match(self, e: FileEntry, source: Path) -> bool:
        t = self._filter_text
        if not t:
            return True
        hay = " ".join((e.path.name, e.platform, e.instrument,
                        e.level, source.name)).lower()
        return t in hay

    def _on_filter(self, text: str) -> None:
        self._filter_text = (text or "").strip().lower()
        self._populate()

    def _on_activate(self, item: QtWidgets.QTreeWidgetItem, _col: int = 0) -> None:
        p = item.data(0, ROLE_PATH)
        if not p:
            return
        path = Path(str(p))
        if path.is_file():
            self.fileActivated.emit(str(path))

    # ---------------- 便捷 ----------------
    def expand_all(self) -> None:
        self.tree.expandAll()

    def file_count(self) -> int:
        return sum(len(entries) for _p, entries in self._sources)


__all__ = ["DataTree", "FileEntry", "scan_dir", "KIND_BADGE"]
