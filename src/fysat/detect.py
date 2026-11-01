"""文件格式自动识别（魔数优先，扩展名兜底）与文件名解析。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

MAGIC = {
    "hdf5": (b"\x89HDF\r\n\x1a\n", 0),
    "hdf4": (b"\x0e\x03\x13\x01", 0),
    "netcdf3": (b"CDF", 0),
    "jpeg": (b"\xff\xd8", 0),
    "png": (b"\x89PNG\r\n\x1a\n", 0),
    "tiff_le": (b"II*\x00", 0),
    "tiff_be": (b"MM\x00*", 0),
    "grib": (b"GRIB", 0),
}

EXT_MAP = {
    ".hdf": "hdf5", ".h5": "hdf5", ".he5": "hdf5", ".hdf5": "hdf5",
    ".nc": "netcdf", ".nc4": "netcdf",
    ".awx": "awx", ".l1b": "oneb", ".1b": "oneb",
    ".tif": "tiff", ".tiff": "tiff", ".png": "png", ".jpg": "jpeg",
}

# 已知的 FY-2 CSV 数据集容器：4 字节大端长度 + ASCII 文件名
_FY2_CSV_RE = re.compile(rb"^.{0,8}FY2[A-H]_CSV", re.S)


def sniff(path: str | Path) -> str:
    """返回容器类型标识：hdf5 / hdf4 / netcdf3 / netcdf4 / awx / oneb / jpeg / png / tiff / unknown"""
    p = Path(path)
    try:
        with open(p, "rb") as fh:
            head = fh.read(64)
    except OSError:
        return "unknown"

    for name, (sig, off) in MAGIC.items():
        if head[off:off + len(sig)] == sig:
            if name == "hdf5":
                # NetCDF-4 也是 HDF5 容器，看超级块里的标记
                return "netcdf4" if b"_NCProperties" in head or _is_netcdf4(p) else "hdf5"
            return name

    if _FY2_CSV_RE.match(head):
        return "fy2_csv"

    ext = p.suffix.lower()
    if ext in EXT_MAP:
        kind = EXT_MAP[ext]
        return "hdf5" if kind == "netcdf" else kind
    return "unknown"


def _is_netcdf4(path: Path) -> bool:
    try:
        import h5py
        if not h5py.is_hdf5(str(path)):
            return False
        with h5py.File(str(path), "r") as f:
            return "_NCProperties" in f.attrs or str(f.attrs.get("_NCProperties", "")).startswith("version=")
    except Exception:
        return False


@dataclass
class NameInfo:
    platform: str = ""
    instrument: str = ""
    level: str = ""
    product: str = ""
    start_time: datetime | None = None
    raw: str = ""


_PLATFORM_RE = re.compile(r"(FY[-\s]?[1-4][A-H]|NOAA[-\s]?\d{2}|N\d{2}|TANSAT|TAN1)", re.I)
_LEVEL_RE = re.compile(r"[_\-]L(\d)[_\-]", re.I)
_TIME_PATTERNS = [
    r"(\d{14})",                 # 20261030154500
    r"_(\d{8})_(\d{4})_",        # 20261101_0405
    r"_(\d{8})_(\d{4})\b",
]


def parse_name(path: str | Path) -> NameInfo:
    name = Path(path).name
    info = NameInfo(raw=name)
    m = _PLATFORM_RE.search(name)
    if m:
        info.platform = m.group(1).upper().replace(" ", "-").replace("FY", "FY-", 1) if m.group(1).upper().startswith("FY") else m.group(1).upper()
        info.platform = info.platform.replace("FY--", "FY-")
    for tok in (t.strip("-.") for t in name.upper().split("_")):
        if tok in ("MERSI", "AGRI", "VIRR", "MWRI", "MWTS", "MWHS", "IRAS", "HIRAS",
                   "GNOSO", "PMR", "ERM", "TOU", "SBUS", "SIM", "AVHRR", "GIIRS", "ACGS", "CAPIX"):
            info.instrument = tok
            break
    m = _LEVEL_RE.search(name)
    if m:
        info.level = f"L{m.group(1)}"
    else:
        m = re.search(r"_L(\d)[_-]", name)
        if m:
            info.level = f"L{m.group(1)}"

    for pat in _TIME_PATTERNS:
        m = re.search(pat, name)
        if not m:
            continue
        try:
            g = m.groups()
            if len(g) == 1 and len(g[0]) == 14:
                info.start_time = datetime.strptime(g[0], "%Y%m%d%H%M%S")
            elif len(g) == 2:
                info.start_time = datetime.strptime(g[0] + g[1], "%Y%m%d%H%M")
            break
        except ValueError:
            continue
    return info
