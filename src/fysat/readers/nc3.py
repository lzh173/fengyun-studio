"""NetCDF-3（经典格式，``CDF`` 魔数）读取器。

只依赖 scipy（``scipy.io.netcdf_file``），不引入 netCDF4。支持的子格式：
``CDF\\x01``（CDF-1，32 位偏移）与 ``CDF\\x02``（CDF-2，64 位偏移）。
``CDF\\x05``（CDF-5）scipy 不支持，会抛出明确错误；NetCDF-4 是 HDF5 容器，
由 ``readers.hdf5`` 处理（``detect.sniff`` 已分流）。

属性映射沿用 ``readers/hdf5.py`` 的「一对多候选键」做法，另外补上 FY-3 GNOSO
实际使用的非 CF 命名：``Slope`` / ``Intercept`` / ``FillValue`` / ``Description``
/ ``band_name``（GNOSO 的定标不是 CF 的 ``scale_factor``/``add_offset``）。

FY-3 GNOSO 实测结构（14 个样本一致）::

    维度      time  （每条掩星剖面一个时间维，实测 2 000~4 500 不等）
    变量      29 个，全部 1 维 (time)，float32 或 float64
    属性      units / long_name / band_name / Description / valid_range /
              FillValue / Intercept / Slope（Intercept=0、Slope=1，DN 即物理量）
    全局属性  78 个：Satellite Name / Sensor Name / Sensor Identification Code /
              Dataset Name / Observing Beginning(Ending) Date+Time /
              Orbit Number / Number Of Scans / occL / occB / gnssName /
              Orbit Point Latitute+Longitude 等

注意 ``Orbit Point Latitute`` 是文件里原样的拼写（拼错的 Latitute），读取时两种
拼写都要认。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from ..detect import parse_name
from ..model import Geolocation, SatDataset, Variable

# 定标／元数据属性候选键（简写名优先按文件实际写法）
SCALE_KEYS = ("Slope", "scale_factor", "ScaleFactor", "slope", "SCALING_FACTOR")
OFFSET_KEYS = ("Intercept", "add_offset", "AddOffset", "intercept", "OFFSET")
FILL_KEYS = ("FillValue", "_FillValue", "fill_value", "missing_value", "MISSING_VALUE")
VALID_KEYS = ("valid_range", "ValidRange", "valid_min", "valid_max")
UNIT_KEYS = ("units", "Units", "unit", "UNIT")
LONG_KEYS = ("long_name", "LongName", "Description", "description", "DESCRIPTION")

LAT_KEYS = ("latitude", "lat", "Latitude", "LAT")
LON_KEYS = ("longitude", "lon", "Longitude", "LON")

# netCDF 默认填充值（NC_FILL_FLOAT / NC_FILL_DOUBLE），GNOSO 里大量变量用它表示"未赋值"
NC_DEFAULT_FILLS = (9.969209968386869e36, -9.969209968386869e36)

# 全局属性里的起止时刻（GNOSO 用它）
BEGIN_DATE_KEYS = ("Observing Beginning Date", "Observation Beginning Date", "begin_date")
BEGIN_TIME_KEYS = ("Observing Beginning Time", "Observation Beginning Time", "begin_time")
END_DATE_KEYS = ("Observing Ending Date", "Observation Ending Date", "end_date")
END_TIME_KEYS = ("Observing Ending Time", "Observation Ending Time", "end_time")

# 单点掩星事件位置（GNOSO）
OCC_LAT_KEYS = ("occB", "occLat", "Occultation Latitude")
OCC_LON_KEYS = ("occL", "occLon", "Occultation Longitude")


# ---------------------------------------------------------------- 属性工具


def _as_str(value: Any) -> str:
    """把 netCDF 属性值安全转成 str（bytes / numpy 标量 / 数组都兜住）。"""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip("\x00 ").strip()
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, np.ndarray):
        if value.size == 0:
            return ""
        if value.dtype.kind in "SU":
            return _as_str(value.reshape(-1)[0])
        return str(value.reshape(-1)[0])
    if isinstance(value, (np.floating, np.integer)):
        return str(value.item())
    return str(value).strip()


def _as_scalar(value: Any) -> float | None:
    """把属性值转成 float，失败返回 None。"""
    if value is None:
        return None
    try:
        if isinstance(value, (bytes, str)):
            return float(value)
        if isinstance(value, (list, tuple, np.ndarray)):
            flat = np.asarray(value).reshape(-1)
            return float(flat[0]) if flat.size else None
        return float(value)
    except (TypeError, ValueError):
        return None


def _attr(attrs: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """按候选键取属性原值。"""
    for key in keys:
        if key in attrs:
            return attrs[key]
    return None


def _spelled(attrs: dict[str, Any], name: str) -> Any:
    """取属性，容忍「空格 vs 下划线」两种写法（不同厂商工具写法不一）。"""
    for key in (name, name.replace(" ", "_"), name.replace("_", " "), name.replace(" ", "")):
        if key in attrs:
            return attrs[key]
    return None


def _valid_range(attrs: dict[str, Any]) -> tuple[float, float] | None:
    raw = _attr(attrs, ("valid_range", "ValidRange"))
    if raw is not None:
        flat = np.asarray(raw).reshape(-1)
        if flat.size >= 2:
            lo, hi = float(flat[0]), float(flat[1])
            if np.isfinite(lo) and np.isfinite(hi):
                return lo, hi
    lo = _as_scalar(attrs.get("valid_min"))
    hi = _as_scalar(attrs.get("valid_max"))
    if lo is not None and hi is not None:
        return lo, hi
    return None


def _decode_attrs(attrs: Any) -> dict[str, Any]:
    """把一组 netCDF 属性转成「字符串优先、数值保留」的普通 dict。"""
    out: dict[str, Any] = {}
    for key, value in dict(attrs).items():
        if isinstance(value, bytes):
            out[key] = _as_str(value)
        elif isinstance(value, np.ndarray):
            out[key] = value.tolist() if value.size > 1 else (
                _as_str(value) if value.dtype.kind in "SU" else _as_scalar(value)
            )
        elif isinstance(value, (np.floating, np.integer)):
            out[key] = value.item()
        else:
            out[key] = value
    return out


def _parse_datetime(date_raw: Any, time_raw: Any) -> datetime | None:
    """把 "2026-10-19" + "00:00:39.000" 合成 datetime。"""
    date_s, time_s = _as_str(date_raw), _as_str(time_raw)
    if not date_s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y%m%d %H:%M:%S", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(f"{date_s} {time_s}".strip(), fmt)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(date_s, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- 变量构造


def _make_variable(name: str, var: Any, load: bool) -> Variable:
    attrs_raw = dict(getattr(var, "_attributes", {}) or {})
    unit = _as_str(_attr(attrs_raw, UNIT_KEYS))
    long_name = _as_str(_attr(attrs_raw, LONG_KEYS))

    shape = tuple(int(s) for s in var.shape)
    if load:
        data = np.array(var.data, copy=True)          # 脱离文件缓冲
    else:
        data = np.empty((0,), dtype=np.dtype(var.typecode()))

    fill = _as_scalar(_attr(attrs_raw, FILL_KEYS))
    attrs = _decode_attrs(attrs_raw)
    # netCDF 默认填充值：文件没声明 FillValue 但数据里全是 9.969e36 的情况很常见
    if load and data.dtype.kind == "f" and data.size:
        for sentinel in NC_DEFAULT_FILLS:
            if bool(np.any(data == np.array(sentinel, dtype=data.dtype))):
                attrs.setdefault("nc_default_fill", sentinel)
                if fill is None:
                    fill = sentinel
                break

    return Variable(
        name=name,
        data=data,
        unit=unit,
        long_name=long_name or name,
        scale_factor=_as_scalar(_attr(attrs_raw, SCALE_KEYS)),
        add_offset=_as_scalar(_attr(attrs_raw, OFFSET_KEYS)),
        valid_range=_valid_range(attrs_raw),
        fill_value=fill,
        dims=tuple(var.dimensions),
        source_shape=shape,
        attrs=attrs,
    )


# ---------------------------------------------------------------- 定位


def _find_pair(names: list[str], keys: tuple[str, ...]) -> str | None:
    for name in names:
        low = name.lower().rsplit("/", 1)[-1]
        if any(low == k.lower() or low.startswith(k.lower()) for k in keys):
            return name
    return None


def _geolocation(variables: dict[str, Variable],
                 attrs: dict[str, Any],
                 fetch: Any = None) -> Geolocation:
    """定位信息：优先用经纬度变量，否则退回全局属性里的单点位置。

    ``fetch(name)`` 用于「只解析头部」模式下按需补读经纬度数组（通常很小）。
    """
    names = list(variables)
    lat_name = _find_pair(names, LAT_KEYS)
    lon_name = _find_pair(names, LON_KEYS)

    if lat_name and lon_name:
        lat_var, lon_var = variables[lat_name], variables[lon_name]
        if len(lat_var.source_shape or ()) == 2 and len(lon_var.source_shape or ()) == 2:
            lat = lat_var.data if lat_var.data.size else (
                fetch(lat_name) if fetch else np.empty((0,)))
            lon = lon_var.data if lon_var.data.size else (
                fetch(lon_name) if fetch else np.empty((0,)))
            if np.size(lat) and np.size(lon):
                lat = np.asarray(lat, dtype=np.float32)
                lon = np.asarray(lon, dtype=np.float32)
                step = 1
                main = max(variables.values(),
                           key=lambda v: int(np.prod(v.source_shape or (0,))))
                if len(main.source_shape or ()) >= 2 and lat.shape[0] and main.source_shape[0]:
                    step = max(1, int(round(main.source_shape[0] / lat.shape[0])))
                return Geolocation(kind="latlon_grid", lat=lat, lon=lon, step=step,
                                   params={"lat_name": lat_name, "lon_name": lon_name})

    # 掩星类产品：全局属性给出事件发生点
    occ_lat = _as_scalar(_attr(attrs, OCC_LAT_KEYS))
    occ_lon = _as_scalar(_attr(attrs, OCC_LON_KEYS))
    orbit_lat = attrs.get("Orbit Point Latitute", attrs.get("Orbit Point Latitude"))
    orbit_lon = attrs.get("Orbit Point Longitude")
    if occ_lat is not None and occ_lon is not None:
        params: dict[str, Any] = {
            "occ_lat": occ_lat,
            "occ_lon": occ_lon,
            "coordinate": attrs.get("coordinate", ""),
            "note": "单条掩星剖面：掩星点位置取自全局属性 occB/occL，"
                    "切点轨迹需由 xLeo/yLeo/zLeo 与 xGnss/…/zGnss 反算",
        }
        if orbit_lat is not None:
            params["orbit_point_lat"] = orbit_lat
            params["orbit_point_lon"] = orbit_lon
        for key in ("gnssName", "NumberOfScans", "Orbit Direction", "setting",
                    "refsatId", "occsatId"):
            if key in attrs:
                params[key] = attrs[key]
        return Geolocation(kind="nominal", params=params)

    return Geolocation(kind="none")


# ---------------------------------------------------------------- 主读取器


def _dimensions(f: Any) -> dict[str, int]:
    return {str(k): int(v) for k, v in (getattr(f, "dimensions", {}) or {}).items()}


def read(path: str | Path, load: bool = True, **_: Any) -> SatDataset:
    """读取 NetCDF-3 经典格式文件，返回统一数据模型。

    参数
    ----
    load : True 时读入全部变量数据；False 时只解析维度／属性／形状，
           ``Variable.source_shape`` 保留文件里的真实形状（供 ``cli info`` 用）。
    """
    p = Path(path)
    try:
        from scipy.io import netcdf_file
    except ImportError as exc:                        # pragma: no cover
        raise RuntimeError("需要 scipy 才能读取 NetCDF-3（pip install scipy）") from exc

    magic = p.read_bytes()[:4]
    if magic[:3] != b"CDF":
        raise ValueError(f"{p.name}: 不是 NetCDF-3 经典格式（魔数 {magic!r}）")
    if magic[3:4] == b"\x05":
        raise NotImplementedError(
            f"{p.name}: CDF-5 格式 scipy 不支持；请安装 netCDF4 后改用 "
            "readers.hdf5 或自行扩展"
        )

    ds = SatDataset(source=p, reader="netcdf3")
    info = parse_name(p)
    ds.platform, ds.start_time = info.platform, info.start_time
    ds.instrument, ds.level = info.instrument, info.level
    ds.product = info.product

    with netcdf_file(str(p), "r", mmap=False, maskandscale=False) as f:
        dims = _dimensions(f)
        attrs = _decode_attrs(getattr(f, "_attributes", {}) or {})
        ds.attrs = {
            "container": "netcdf3",
            "cdf_version": {1: "CDF-1 (32-bit offsets)",
                            2: "CDF-2 (64-bit offsets)"}.get(magic[3], f"raw {magic[3]!r}"),
            "dimensions": dims,
            **({k: v for k, v in attrs.items()}),
        }

        for name, var in f.variables.items():
            # scipy 的 netcdf_variable 在关闭文件后就失效，load=True 时立刻拷出来
            ds.variables[name] = _make_variable(name, var, load)

        def _fetch(name: str) -> np.ndarray:
            return np.array(f.variables[name].data, copy=True)

        ds.geolocation = _geolocation(dict(ds.variables), attrs, _fetch)

    # 卫星／仪器／产品：文件名解析为准，全局属性更权威的就覆盖
    platform = _spelled(attrs, "Satellite Name")
    if platform:
        ds.platform = _as_str(platform) or ds.platform
    level = _spelled(attrs, "dataLevel")
    if level:
        ds.level = _as_str(level) or ds.level
    product = _spelled(attrs, "dataName")
    if product:
        ds.product = _as_str(product) or ds.product
    sensor = _spelled(attrs, "Sensor Identification Code")
    if sensor and not ds.instrument:
        ds.instrument = _as_str(sensor)

    begin = _parse_datetime(_attr(attrs, BEGIN_DATE_KEYS), _attr(attrs, BEGIN_TIME_KEYS))
    end = _parse_datetime(_attr(attrs, END_DATE_KEYS), _attr(attrs, END_TIME_KEYS))
    if begin:
        ds.start_time = begin
    if end:
        ds.end_time = end

    return ds


def list_variables(path: str | Path) -> list[dict[str, Any]]:
    """只看结构（不给数据），供 CLI / GUI 树使用。"""
    ds = read(path, load=False)
    return [
        {
            "name": v.name,
            "dims": list(v.dims),
            "shape": list(v.shape),
            "dtype": str(v.dtype),
            "unit": v.unit,
            "long_name": v.long_name,
        }
        for v in ds.variables.values()
    ]


def read_variable(path: str | Path, name: str) -> np.ndarray:
    """按需读取单个变量。"""
    from scipy.io import netcdf_file

    p = Path(path)
    with netcdf_file(str(p), "r", mmap=False, maskandscale=False) as f:
        if name not in f.variables:
            raise KeyError(f"变量不存在: {name}；可选 {list(f.variables)}")
        return np.array(f.variables[name].data, copy=True)


__all__ = ["read", "read_variable", "list_variables", "SCALE_KEYS", "OFFSET_KEYS",
           "FILL_KEYS", "VALID_KEYS", "UNIT_KEYS", "LONG_KEYS", "NC_DEFAULT_FILLS"]
