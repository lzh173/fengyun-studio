"""通用 HDF5 / NetCDF-4 读取器（CF 约定驱动，不针对具体产品硬编码）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import h5py
import numpy as np

from ..detect import parse_name
from ..model import Geolocation, SatDataset, Variable

# 常见的定标/元数据属性名
SCALE_KEYS = ("scale_factor", "ScaleFactor", "slope", "Slope")
OFFSET_KEYS = ("add_offset", "AddOffset", "intercept", "Intercept")
FILL_KEYS = ("_FillValue", "FillValue", "fill_value", "missing_value")
VALID_KEYS = ("valid_range", "ValidRange", "valid_min", "valid_max")
UNIT_KEYS = ("units", "Units", "unit")
LONG_KEYS = ("long_name", "LongName", "description", "Description")

# 经纬度数据集候选名
LAT_KEYS = ("latitude", "lat", "Latitude")
LON_KEYS = ("longitude", "lon", "Longitude")


def _attr(d: h5py.Dataset | h5py.Group, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d.attrs:
            v = d.attrs[k]
            if isinstance(v, bytes):
                return v.decode("utf-8", "replace")
            if isinstance(v, np.ndarray) and v.size == 1:
                return v.reshape(-1)[0].item()
            return v
    return None


def _scalar(v: Any) -> float | None:
    if v is None:
        return None
    try:
        if isinstance(v, (list, tuple, np.ndarray)):
            return float(np.asarray(v).reshape(-1)[0])
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace").strip()
    if isinstance(v, np.ndarray):
        try:
            return _as_str(v.reshape(-1)[0])
        except Exception:
            return ""
    return str(v).strip()


def _valid_range(ds: h5py.Dataset) -> tuple[float, float] | None:
    for k in VALID_KEYS:
        if k in ds.attrs:
            v = np.asarray(ds.attrs[k]).reshape(-1)
            if v.size >= 2:
                return float(v[0]), float(v[1])
    lo = _scalar(ds.attrs.get("valid_min"))
    hi = _scalar(ds.attrs.get("valid_max"))
    if lo is not None and hi is not None:
        return lo, hi
    return None


def _collect(f: h5py.File) -> dict[str, h5py.Dataset]:
    out: dict[str, h5py.Dataset] = {}

    def walk(name: str, obj: Any) -> None:
        if isinstance(obj, h5py.Dataset):
            out[name.lstrip("/")] = obj

    f.visititems(walk)
    return out


def _find_geo(datasets: dict[str, h5py.Dataset], shape: tuple[int, ...]) -> Geolocation:
    """在数据集里找经纬度网格（优先与主变量同形状或为粗网格）。"""
    lat_name = lon_name = None
    for path in datasets:
        low = path.lower()
        base = low.rsplit("/", 1)[-1]
        if lat_name is None and any(base == k.lower() or base.startswith(k.lower()) for k in LAT_KEYS):
            lat_name = path
        if lon_name is None and any(base == k.lower() or base.startswith(k.lower()) for k in LON_KEYS):
            lon_name = path
        if lat_name and lon_name:
            break
    if not (lat_name and lon_name):
        return Geolocation(kind="none")

    lat_ds, lon_ds = datasets[lat_name], datasets[lon_name]
    if lat_ds.ndim != 2 or lon_ds.ndim != 2:
        return Geolocation(kind="none")
    lat = lat_ds[()].astype(np.float32)
    lon = lon_ds[()].astype(np.float32)
    # 估算抽稀步长
    step = 1
    if shape and len(shape) >= 2 and shape[0] and lat.shape[0]:
        step = max(1, int(round(shape[0] / lat.shape[0])))
    return Geolocation(kind="latlon_grid", lat=lat, lon=lon, step=step,
                       params={"lat_path": lat_name, "lon_path": lon_name})


def read(path: str | Path, load: bool = True, max_vars: int | None = None) -> SatDataset:
    """读取 HDF5 / NetCDF-4 文件，返回统一数据模型。"""
    p = Path(path)
    ds_out = SatDataset(source=p, reader="hdf5")
    info = parse_name(p)
    ds_out.platform, ds_out.instrument, ds_out.level = info.platform, info.instrument, info.level
    ds_out.start_time = info.start_time

    with h5py.File(p, "r") as f:
        attrs = {}
        for k, v in f.attrs.items():
            attrs[k] = _as_str(v) if isinstance(v, (bytes, np.ndarray)) else v
        ds_out.attrs = attrs

        datasets = _collect(f)
        main_shape: tuple[int, ...] = ()
        if datasets:
            main_shape = max(datasets.values(), key=lambda d: d.size).shape

        for i, (name, d) in enumerate(datasets.items()):
            if max_vars is not None and i >= max_vars:
                break
            vr = Variable(
                name=name,
                data=d[()] if load else np.empty((0,), dtype=d.dtype),
                unit=_as_str(_attr(d, UNIT_KEYS)),
                long_name=_as_str(_attr(d, LONG_KEYS)),
                scale_factor=_scalar(_attr(d, SCALE_KEYS)),
                add_offset=_scalar(_attr(d, OFFSET_KEYS)),
                valid_range=_valid_range(d),
                fill_value=_scalar(_attr(d, FILL_KEYS)),
                dims=tuple(d.dims) if hasattr(d, "dims") else (),
                source_shape=tuple(d.shape),
                attrs={k: d.attrs[k] for k in d.attrs},
            )
            ds_out.variables[name] = vr

        ds_out.geolocation = _find_geo(datasets, main_shape)

    # 产品名：取文件名里 L 级别后的第一段
    parts = [s for s in p.stem.split("_") if s]
    for j, s in enumerate(parts):
        if s.upper().startswith("L1") or s.upper().startswith("L2"):
            if j + 1 < len(parts):
                ds_out.product = parts[j + 1].strip("-")
            break
    return ds_out


def load_array(path: str | Path, name: str) -> np.ndarray:
    """按需读取单个数据集（避免一次载入整个文件）。"""
    with h5py.File(str(path), "r") as f:
        key = name.lstrip("/")
        if key not in f:
            raise KeyError(f"变量不存在: {name}")
        return f[key][()]


def list_tree(path: str | Path, max_items: int = 200) -> list[dict]:
    """列出文件结构（供 CLI info / GUI 树使用）。"""
    rows = []
    with h5py.File(str(path), "r") as f:
        def walk(name, obj):
            if len(rows) >= max_items:
                return
            kind = "group" if isinstance(obj, h5py.Group) else "dataset"
            rec = {"path": "/" + name, "kind": kind, "attrs": len(obj.attrs)}
            if kind == "dataset":
                rec["shape"] = list(obj.shape)
                rec["dtype"] = str(obj.dtype)
            rows.append(rec)
        f.visititems(walk)
    return rows
