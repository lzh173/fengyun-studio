"""读取器注册表：按容器类型分派。新增格式只需在此注册。"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..detect import sniff
from ..model import SatDataset

Reader = Callable[..., SatDataset]
_REGISTRY: dict[str, Reader] = {}


def register(kind: str, fn: Reader) -> None:
    _REGISTRY[kind] = fn


def kinds() -> list[str]:
    return sorted(_REGISTRY)


def open_file(path: str | Path, **kwargs) -> SatDataset:
    """按魔数识别容器并调用对应读取器。"""
    kind = sniff(path)
    if kind in _REGISTRY:
        ds = _REGISTRY[kind](path, **kwargs)
        ds.reader = ds.reader or kind
        return ds
    raise NotImplementedError(
        f"暂不支持的容器类型: {kind}（{Path(path).name}）；已注册: {kinds()}"
    )


def _bootstrap() -> None:
    from . import hdf5 as _hdf5

    register("hdf5", _hdf5.read)
    register("netcdf4", _hdf5.read)

    try:  # 可选：NetCDF-3
        from . import nc3 as _nc3
        register("netcdf3", _nc3.read)
    except Exception:
        pass
    try:  # 可选：FY-2 CSV 容器
        from . import fy2_csv as _fy2
        register("fy2_csv", _fy2.read)
    except Exception:
        pass
    try:  # 可选：1B
        from . import oneb as _oneb
        register("oneb", _oneb.read)
    except Exception:
        pass
    try:  # 可选：AWX
        from . import awx as _awx
        register("awx", _awx.read)
    except Exception:
        pass


_bootstrap()
