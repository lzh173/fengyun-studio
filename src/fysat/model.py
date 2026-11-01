"""统一数据模型：任何容器解析后都归一到这里，分析与渲染只认它。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class Variable:
    """一个数据变量（数据集）。data 为原始 DN，physical() 给出物理量。"""

    name: str
    data: np.ndarray
    unit: str = ""
    long_name: str = ""
    scale_factor: float | None = None
    add_offset: float | None = None
    valid_range: tuple[float, float] | None = None
    fill_value: float | None = None
    dims: tuple[str, ...] = ()
    source_shape: tuple[int, ...] | None = None   # load=False 时仍保留文件里的真实形状
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, ...]:
        if self.source_shape is not None:
            return tuple(self.source_shape)
        return self.data.shape

    @property
    def dtype(self) -> np.dtype:
        return self.data.dtype

    def mask(self) -> np.ndarray:
        """无效值掩膜（True = 无效）。"""
        bad = np.zeros(self.data.shape, dtype=bool)
        if self.fill_value is not None:
            bad |= self.data == self.fill_value
        if self.valid_range is not None:
            lo, hi = self.valid_range
            bad |= (self.data < lo) | (self.data > hi)
        return bad

    def physical(self) -> np.ndarray:
        """应用 scale/offset，并把无效值置 NaN。"""
        arr = self.data.astype(np.float32, copy=True)
        if self.scale_factor is not None:
            arr = arr * np.float32(self.scale_factor)
        if self.add_offset is not None:
            arr = arr + np.float32(self.add_offset)
        bad = self.mask()
        if bad.any():
            arr[bad] = np.nan
        return arr


@dataclass
class Geolocation:
    """定位信息。kind: latlon_grid | glt | nominal | none"""

    kind: str = "none"
    lat: np.ndarray | None = None
    lon: np.ndarray | None = None
    x: np.ndarray | None = None
    y: np.ndarray | None = None
    step: int = 1
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def is_nav(self) -> bool:
        return self.lat is not None and self.lon is not None

    def bounds(self) -> tuple[float, float, float, float] | None:
        if not self.is_nav:
            return None
        with np.errstate(invalid="ignore"):
            return (
                float(np.nanmin(self.lon)), float(np.nanmax(self.lon)),
                float(np.nanmin(self.lat)), float(np.nanmax(self.lat)),
            )


@dataclass
class SatDataset:
    platform: str = ""
    instrument: str = ""
    level: str = ""
    product: str = ""
    start_time: datetime | None = None
    end_time: datetime | None = None
    variables: dict[str, Variable] = field(default_factory=dict)
    geolocation: Geolocation = field(default_factory=Geolocation)
    attrs: dict[str, Any] = field(default_factory=dict)
    source: Path | None = None
    reader: str = ""
    product_def: str = ""

    def __getitem__(self, name: str) -> Variable:
        return self.variables[name]

    def __contains__(self, name: str) -> bool:
        return name in self.variables

    def names(self) -> list[str]:
        return list(self.variables.keys())

    def vars2d(self) -> list[Variable]:
        return [v for v in self.variables.values() if v.data.ndim == 2]

    def load(self, name: str) -> Variable:
        """按需加载变量数据（open_file(load=False) 之后使用）。

        按 self.reader 分派到对应容器模块，避免把非 HDF5 容器当 HDF5 打开。
        """
        v = self.variables[name]
        if v.data.size > 0 or self.source is None:
            return v

        import importlib

        # reader 名 → 模块名；hdf5/netcdf4 共用同一实现
        mod_name = {"netcdf4": "hdf5"}.get(self.reader, self.reader or "hdf5")
        try:
            mod = importlib.import_module(f".readers.{mod_name}", package="fysat")
        except ImportError:
            mod = importlib.import_module(".readers.hdf5", package="fysat")

        loader = getattr(mod, "load_array", None) or getattr(mod, "read_variable", None)
        if loader is None:
            raise NotImplementedError(
                f"读取器 {mod_name} 不支持按需加载（缺少 load_array/read_variable）"
            )
        v.data = loader(self.source, name)
        return v

    def summary(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "instrument": self.instrument,
            "level": self.level,
            "product": self.product,
            "time": self.start_time.isoformat(sep=" ") if self.start_time else "",
            "source": str(self.source) if self.source else "",
            "reader": self.reader,
            "n_vars": len(self.variables),
            "geolocation": self.geolocation.kind,
            "bounds": self.geolocation.bounds(),
            "vars": [
                {"name": v.name, "shape": list(v.shape), "dtype": str(v.dtype), "unit": v.unit}
                for v in self.variables.values()
            ],
        }
