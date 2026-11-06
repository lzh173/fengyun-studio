"""satpy 可选后端适配器（**可选增强，不是替代**）。

satpy 自带 FY-3 MERSI-1/2/3/LL/RM 与 FY-4 AGRI 的 L1 读取器，能省掉我们
手写定标/波长表的功夫；但它是 GPLv3 + 一堆重型依赖（dask/xarray/zarr/
pyresample）的可选包，所以设计上守住三条线：

1. **惰性 import**：本模块顶层绝不 import satpy。没装 satpy 时
   ``read()`` 抛 ``NotImplementedError("需要安装 satpy 可选依赖")``，
   而 ``find_geo_file()`` 这类纯文件名逻辑照常可用（GUI 可以据此判断可用性）。
2. **GEO 自动配对**：MERSI L1 的定位数据放在独立的 ``*_GEO1K_*`` 文件里。
   只喂数据文件时 satpy 能定标、但拿不到经纬度（实测报
   ``Required file type 'mersi2_l1b_1000_geo' not found or loaded for 'latitude'``）。
   所以这里按文件名推导 GEO 路径一并交给 Scene；找不到就降级为"无定位但可读"，
   并在 ``SatDataset.attrs["geo_missing"]`` 上打标记。
3. **只做一层翻译**：把 satpy 的 ``xarray.DataArray`` 翻成我们的
   ``Variable`` / ``Geolocation``，下游 pipeline/render/gui 完全不感知 satpy。

单位约定（重要）
----------------
satpy 的 ``mersi2_l1b`` 反射率单位是 **%**（0~110），与我们
``calib.reflectance_linear`` 的输出一致；但 ``pipeline.visible_data`` /
``reflectance_toa`` / ``true_color`` 用的是**归一化反射率 0~1**。
本适配器默认 ``normalize_reflectance=True``，把 % 折成 0~1 并把 ``unit`` 记成
``"1"``，原始单位留在 ``Variable.attrs["satpy_units"]``。需要与产品解码路径
（单位 %）对齐时传 ``normalize_reflectance=False``。

**不要**把 satpy 变量再喂给 ``pipeline.visible_data`` /
``pipeline.reflectance_toa``：那两个函数假定输入是**原始 DN**，会自己查
``VIS_Cal_Coeff`` 再算一遍，对已定标数据会二次定标。
"""
from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

from ..detect import parse_name
from ..model import Geolocation, SatDataset, Variable

SATPY_MISSING_MSG = "需要安装 satpy 可选依赖（pip install \"fysat[satpy]\"）"

# 本适配器写进 SatDataset.reader 的值。
# 必须等于本模块的文件名：model.SatDataset.load() 会拿 reader 当模块名
# 去 readers.<name> 里找 load_array()，写 "satpy" 会落到 hdf5 兜底上拿到错数据。
READER_NAME = "satpy_adapter"


# ---------------------------------------------------------------- 读取器推导

# 平台/仪器 → satpy 读取器名。顺序敏感：先具体平台，再按仪器族兜底。
_READER_RULES: tuple[tuple[str, str], ...] = (
    (r"FY[-_]?3A[_-]?MERSI", "fy3a_mersi1_l1b"),
    (r"FY[-_]?3B[_-]?MERSI", "fy3b_mersi1_l1b"),
    (r"FY[-_]?3C[_-]?MERSI", "fy3c_mersi1_l1b"),
    (r"FY[-_]?3D[_-]?MERSI", "mersi2_l1b"),
    (r"FY[-_]?3E[_-]?MERSI", "mersi_ll_l1b"),
    (r"FY[-_]?3[FH][_-]?MERSI", "mersi3_l1b"),
    (r"FY[-_]?3G[_-]?MERSI", "mersi_rm_l1b"),
    (r"FY[-_]?4A.*AGRI", "agri_fy4a_l1"),
    (r"FY[-_]?4B.*AGRI", "agri_fy4b_l1"),
)

# 文件名里没有平台号时的兜底顺序（逐个试，能认出数据集的那个胜出）。
_FAMILY_READERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("MERSI", ("mersi2_l1b", "mersi3_l1b", "mersi_ll_l1b", "mersi_rm_l1b",
               "fy3c_mersi1_l1b", "fy3b_mersi1_l1b", "fy3a_mersi1_l1b")),
    ("AGRI", ("agri_fy4b_l1", "agri_fy4a_l1")),
)

# 数据文件名 → GEO 文件名的替换规则（与 satpy 各 reader 的 file_patterns 对齐）：
#   MERSI:  *_1000M_* → *_GEO1K_*   *_0250M_* → *_GEOQK_*   *_0500M_* → *_GEOHK_*
#   AGRI :  *L1-_FDI-* / *L1-_REFL-* / *L1-_IRD-* → *L1-_GEO-*
_GEO_TOKEN_RULES: tuple[tuple[str, str], ...] = (
    ("_1000M_", "_GEO1K_"),
    ("_0250M_", "_GEOQK_"),
    ("_0500M_", "_GEOHK_"),
    ("L1-_FDI-", "L1-_GEO-"),
    ("L1-_REFL-", "L1-_GEO-"),
    ("L1-_IRD-", "L1-_GEO-"),
    ("L1-_CAG-", "L1-_GEO-"),
)

# 定标优先级：可见光→反射率，红外→亮温，其余按需。
_PREFERRED_CALIBRATION = ("reflectance", "brightness_temperature", "radiance", "counts")


def _import_satpy():
    """惰性拿到 satpy.Scene；未安装时抛 NotImplementedError。"""
    try:
        from satpy import Scene  # noqa: PLC0415  （惰性 import 是本模块的契约）
    except ImportError as exc:  # pragma: no cover - 依赖是否安装因人而异
        raise NotImplementedError(SATPY_MISSING_MSG) from exc
    return Scene


def satpy_available() -> bool:
    """satpy 是否可用（GUI/CLI 可用它决定要不要显示 satpy 入口）。"""
    try:
        _import_satpy()
    except NotImplementedError:
        return False
    return True


def reader_candidates(path: str | Path) -> list[str]:
    """按文件名给出要试的 satpy 读取器，第一个最可能是对的。"""
    name = Path(path).name
    out: list[str] = []
    for pattern, reader in _READER_RULES:
        if re.search(pattern, name, re.I):
            out.append(reader)
            break
    upper = name.upper()
    for token, readers in _FAMILY_READERS:
        if token in upper:
            out.extend(r for r in readers if r not in out)
    if not out:
        raise NotImplementedError(
            f"satpy 适配层不认识这种文件：{name}；"
            "支持 FY-3A/B/C/D/E/F/G/H MERSI 与 FY-4A/4B AGRI 的 L1"
        )
    return out


# ---------------------------------------------------------------- GEO 配对

def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def find_geo_file(path: str | Path, *, geo_path: str | Path | None = None,
                  extra_dirs: Iterable[str | Path] = ()) -> Path | None:
    """找数据文件配套的 GEO 定位文件。

    推导规则与 ``pipeline.find_geo_file`` 同源，但按 satpy 各 reader 的
    ``file_patterns`` 补全（含 AGRI 的 ``L1-_FDI-`` → ``L1-_GEO-``）：

        FY3D_MERSI_GBAL_L1_20260810_0635_1000M_MS.HDF
        → FY3D_MERSI_GBAL_L1_20260810_0635_GEO1K_MS.HDF

        FY3H_MERSI_GRAN_L1_20261030_0300_1000M_V0.hdf
        → FY3H_MERSI_GRAN_L1_20261030_0300_GEO1K_V0.hdf

        FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_MULT_NOM_..._1000M_V0001.HDF
        → FY4B-_AGRI--_N_DISK_1050E_L1-_GEO-_MULT_NOM_..._4000M_V0001.HDF（未实测）

    ``geo_path`` 显式指定时优先；``extra_dirs`` 可加搜索目录（默认只看同目录）。
    找不到返回 ``None``——调用方据此走"无定位但可读"的降级路径。
    """
    src = Path(path)
    if geo_path is not None:
        p = Path(geo_path)
        return p if p.is_file() and not _same_file(p, src) else None

    stem = src.stem
    cands: list[str] = []
    for token, repl in _GEO_TOKEN_RULES:
        if token in stem:
            cands.append(stem.replace(token, repl))
    cands.append(stem + "_GEO")

    dirs = [src.parent] + [Path(d) for d in extra_dirs]
    exts = [src.suffix] + [e for e in (".hdf", ".HDF", ".h5") if e.lower() != src.suffix.lower()]
    for cand in dict.fromkeys(cands):
        if not cand or cand == stem:
            continue
        for d in dirs:
            for ext in exts:
                p = d / (cand + ext)
                try:
                    if p.is_file() and not _same_file(p, src):
                        return p
                except OSError:  # 无权限/坏盘符
                    continue
    return None


# ---------------------------------------------------------------- Scene 打开

def _open_scene(path: Path, *, reader: str | None = None,
                geo_path: str | Path | None = None,
                geo_dirs: Sequence[str | Path] = ()):
    """建 Scene（数据文件 + 可能的 GEO 文件），返回 (scene, reader名, geo文件)。"""
    Scene = _import_satpy()          # 未安装时在这里就抛 NotImplementedError
    src = Path(path)
    geo = find_geo_file(src, geo_path=geo_path, extra_dirs=geo_dirs)

    files = [str(src)]
    if geo is not None:
        files.append(str(geo))

    tried: list[str] = []
    for cand in ([reader] if reader else reader_candidates(src)):
        try:
            scn = Scene(filenames={cand: files}, reader=cand)
        except Exception as exc:                      # noqa: BLE001 - 换下一个候选
            tried.append(f"{cand}: {type(exc).__name__}: {exc}")
            continue
        if scn.available_dataset_names():
            return scn, cand, geo
        tried.append(f"{cand}: 没有识别出任何数据集（文件名与 file_patterns 不匹配？）")

    raise NotImplementedError(
        f"satpy 无法识别 {src.name}（GEO={'有' if geo else '无'}）：" + " | ".join(tried)
    )


# ---------------------------------------------------------------- 数据集索引

def _band_sort_key(name: str) -> tuple[int, int, str]:
    """通道号按数字排（'1','2',...,'19','20'），非数字排后面。"""
    try:
        return (0, int(name), "")
    except ValueError:
        return (1, 0, name)


def _calibration_name(cal: Any) -> str:
    """satpy 的 calibration 枚举 → 'reflectance' 这样的短名。"""
    name = getattr(cal, "name", None)
    if isinstance(name, str):
        return name
    return str(cal).rsplit(".", 1)[-1].rstrip(">")


def _dataset_index(scn) -> tuple[dict[str, set[str]], dict[str, set[int]], list[str]]:
    """从 Scene 里取出 {通道: 可用定标集合} / {通道: 可用分辨率} / 通道名单。"""
    cals: dict[str, set[str]] = {}
    res: dict[str, set[int]] = {}
    for dsid in scn.available_dataset_ids():
        name = str(dsid["name"])
        cal = dsid.get("calibration")
        if cal is not None:
            cals.setdefault(name, set()).add(_calibration_name(cal))
        resolution = dsid.get("resolution")
        if isinstance(resolution, int):
            res.setdefault(name, set()).add(resolution)
    return cals, res, sorted(cals, key=_band_sort_key)


def _pick_calibration(available: set[str], requested: str | None) -> str | None:
    """选一个该通道真正支持的定标；不支持返回 None。"""
    if requested:
        return requested if requested in available else None
    for cand in _PREFERRED_CALIBRATION:
        if cand in available:
            return cand
    return sorted(available)[0] if available else None


def _load_groups(scn, plan: dict[str, str | None], **load_kwargs) -> tuple[list[str], dict[str, str]]:
    """按定标分组批量 load；整组失败再逐通道重试，避免一个坏通道拖垮全部。"""
    groups: dict[str, list[str]] = {}
    for name, cal in plan.items():
        groups.setdefault(cal or "", []).append(name)

    loaded: list[str] = []
    failed: dict[str, str] = {}
    for cal, names in groups.items():
        kwargs = dict(load_kwargs)
        if cal:
            kwargs["calibration"] = cal
        try:
            scn.load(names, **kwargs)
            loaded.extend(names)
            continue
        except Exception as exc:                       # noqa: BLE001
            group_err = f"{type(exc).__name__}: {exc}"
        for name in names:
            try:
                scn.load([name], **kwargs)
                loaded.append(name)
            except Exception as exc:                   # noqa: BLE001
                failed[name] = f"{type(exc).__name__}: {exc}（整组错误: {group_err}）"
    return loaded, failed


# ---------------------------------------------------------------- GEO 读取

# satpy 在缺 GEO 时会给每个通道刷一条 WARNING（实测 25 条/次）。这条降级路径
# 是我们**明确支持**的（attrs["geo_missing"] 才是权威信号），所以只在这一情形下
# 过滤掉这两类已知噪声，别的情况下一条都不动。
_GEO_NOISE_PREFIXES = (
    "Required file type",
    "Failed to load coordinates for",
)


class _GeoNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            msg = record.getMessage()
        except Exception:                              # noqa: BLE001
            return True
        return not msg.startswith(_GEO_NOISE_PREFIXES)


@contextmanager
def _quiet_missing_geo(enabled: bool):
    """短期内压掉"缺 GEO 文件"的重复告警（只作用于 satpy 的 yaml_reader 日志器）。"""
    if not enabled:
        yield
        return
    logger = logging.getLogger("satpy.readers.core.yaml_reader")
    flt = _GeoNoiseFilter()
    logger.addFilter(flt)
    try:
        yield
    finally:
        logger.removeFilter(flt)


def _read_geolocation(scn, *, step: int = 1) -> tuple[Geolocation, bool]:
    """把 satpy 的 latitude/longitude 读成我们的 Geolocation。

    MERSI 的定位在独立 GEO 文件里；没配 GEO 时 satpy 根本不提供这两个数据集，
    这里返回 ``(Geolocation(kind="none"), True)`` —— 数据仍可读，只是没有经纬度。
    """
    names = set(scn.available_dataset_names())
    if not {"latitude", "longitude"} <= names:
        return Geolocation(kind="none"), True
    try:
        scn.load(["latitude", "longitude"])
        lat = np.asarray(scn["latitude"].values, dtype=np.float32)
        lon = np.asarray(scn["longitude"].values, dtype=np.float32)
    except Exception:                                  # noqa: BLE001 - 定位坏了也不该挡数据
        return Geolocation(kind="none"), True

    if step > 1:
        lat = lat[::step, ::step]
        lon = lon[::step, ::step]
    return Geolocation(kind="latlon_grid", lat=lat, lon=lon, step=int(step),
                       params={"source": "satpy"}), False


# ---------------------------------------------------------------- DataArray → Variable

def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _is_percent(units: Any) -> bool:
    return _text(units).strip() == "%"


def _wavelength_info(da) -> tuple[float | None, float | None, float | None, str]:
    """取中心/起止波长（µm）。satpy 用 WavelengthRange，属性名随版本稳定。"""
    wl = da.attrs.get("wavelength")
    if wl is None:
        return None, None, None, ""
    unit = _text(getattr(wl, "unit", ""))
    out = []
    for key in ("central", "min", "max"):
        try:
            out.append(float(getattr(wl, key)))
        except (AttributeError, TypeError, ValueError):
            out.append(None)
    return out[0], out[1], out[2], unit


def _finalize_array(arr: np.ndarray, calibration: str | None, units: Any,
                    normalize: bool) -> tuple[np.ndarray, str, bool]:
    """反射率 % → 0~1（可选），返回 (数组, 我们的 unit, 是否归一化过)。"""
    if (calibration == "reflectance" and normalize and _is_percent(units)):
        return (np.asarray(arr, dtype=np.float32) / np.float32(100.0)), "1", True
    return np.asarray(arr), _text(units), False


def _to_variable(name: str, da, *, load: bool, calibration: str | None,
                 normalize: bool, geo_missing: bool) -> Variable:
    """把一个 satpy DataArray 翻成我们的 Variable。"""
    attrs = da.attrs
    units = attrs.get("units")
    shape = tuple(da.shape)
    dtype = np.dtype(da.dtype)

    if load:
        arr, unit, normalized = _finalize_array(np.asarray(da.values), calibration, units, normalize)
    else:
        # 与 hdf5 读取器一致：不读数据，只记真实形状
        arr = np.empty((0,), dtype=dtype)
        _, unit, normalized = _finalize_array(np.empty((0,), dtype=np.float32),
                                              calibration, units, normalize)

    central, wmin, wmax, wunit = _wavelength_info(da)

    vattrs: dict[str, Any] = {
        "satpy_name": name,
        "satpy_calibration": calibration or "",
        "satpy_units": _text(units),
        "reflectance_normalized": normalized,
        "geo_missing": geo_missing,
        "resolution": attrs.get("resolution"),
        "file_type": _text(attrs.get("file_type")),
        "file_key": _text(attrs.get("file_key")),
        "platform_name": _text(attrs.get("platform_name")),
        "sensor": _text(attrs.get("sensor")),
        "standard_name": _text(attrs.get("standard_name")),
        "hdf_long_name": _text(attrs.get("long_name")),
        "band_name": _text(attrs.get("band_name")),
        "rows_per_scan": attrs.get("rows_per_scan"),
    }
    if central is not None:
        vattrs.update({
            "wavelength_central": central,
            "wavelength_min": wmin,
            "wavelength_max": wmax,
            "wavelength_unit": wunit,
        })

    if central is not None:
        long_name = f"band {name} · {central:.3f} {wunit or 'µm'}".strip()
    else:
        long_name = _text(attrs.get("long_name")) or f"band {name}"

    return Variable(
        name=name,
        data=arr,
        unit=unit,
        long_name=long_name,
        dims=tuple(str(d) for d in da.dims),
        source_shape=shape,
        attrs=vattrs,
    )


# ---------------------------------------------------------------- 主入口

def read(path: str | Path, load: bool = True, *,
         geo_path: str | Path | None = None,
         geo_dirs: Sequence[str | Path] = (),
         reader: str | None = None,
         names: Sequence[str] | None = None,
         calibration: str | None = None,
         resolution: int | None = None,
         normalize_reflectance: bool = True,
         geo_step: int = 1,
         include_aux: bool = False) -> SatDataset:
    """用 satpy 读一个 FY L1 文件，返回统一数据模型。

    参数
    ----
    load : True 立刻把数据算成 numpy（FY-3D 全 25 通道实测 12.5 s / 410 MB）；False 只记形状，
           之后用 ``SatDataset.load(name)`` 按需取（走本模块 ``load_array``）。
    geo_path / geo_dirs : 显式指定或追加搜索 GEO 文件；默认按文件名在同目录推导。
    reader : 强制指定 satpy 读取器（默认按文件名推导，推导失败按仪器族逐个试）。
    names : 只读这些通道（如 ``["1", "2", "3"]``），默认全部。
    calibration : 强制定标（reflectance / brightness_temperature / radiance / counts），
           默认按通道能力自动选（可见光→反射率，红外→亮温）。
    resolution : 指定分辨率（250 / 1000），默认用 satpy 的默认（最细的那档）。
    normalize_reflectance : 反射率 % → 0~1（默认 True，与 pipeline 的归一化反射率一致）。
    geo_step : 经纬度抽稀步长（1=全分辨率；>1 省内存，pipeline 会按需再放大）。
    include_aux : 是否把太阳/卫星天顶角等辅助数据集也放进 variables（默认只登记在 attrs）。
    """
    src = Path(path)
    if not load and not normalize_reflectance:
        raise ValueError(
            "load=False 时不能关掉反射率归一化：SatDataset.load() 会回调 load_array()，"
            "它拿不到这个选项，会导致 unit 标 %、数据却是 0~1。"
        )
    scn, reader_name, geo_file = _open_scene(
        src, reader=reader, geo_path=geo_path, geo_dirs=geo_dirs)

    cals, resmap, band_names = _dataset_index(scn)
    aux_names = [str(n) for n in scn.available_dataset_names() if str(n) not in cals]

    if names is None:
        targets: list[str] = list(band_names)
    else:
        targets = [str(n) for n in names]

    plan: dict[str, str | None] = {}
    missing: list[str] = []
    for name in targets:
        if name not in cals:
            missing.append(name)
            continue
        if resolution is not None and resmap.get(name) and resolution not in resmap[name]:
            missing.append(name)
            continue
        cal = _pick_calibration(cals[name], calibration)
        if cal is None:
            missing.append(name)
            continue
        plan[name] = cal

    load_kwargs: dict[str, Any] = {}
    if resolution is not None:
        load_kwargs["resolution"] = resolution

    # 先读定位：satpy 挂了 GEO 才能给 area / 太阳天顶角，也让后续合成的坐标就绪
    geo, geo_missing = _read_geolocation(scn, step=geo_step)

    with _quiet_missing_geo(geo_missing):
        loaded, failed = _load_groups(scn, plan, **load_kwargs) if plan else ([], {})

        if names is not None and not plan:
            hint = f"（已按 resolution={resolution} 过滤）" if resolution else ""
            raise KeyError(
                f"{src.name} 里没有可读的通道 {list(names)}；"
                f"可用通道 {band_names[:20]}{'…' if len(band_names) > 20 else ''}，"
                f"当前读取器 {reader_name}{hint}"
            )

        variables: dict[str, Variable] = {}
        for name in loaded:
            if name not in scn:
                failed[name] = "load 之后数据集仍未生成"
                continue
            try:
                variables[name] = _to_variable(
                    name, scn[name], load=load, calibration=plan[name],
                    normalize=normalize_reflectance, geo_missing=geo_missing)
            except Exception as exc:                   # noqa: BLE001
                failed[name] = f"{type(exc).__name__}: {exc}"

        if include_aux:
            loaded_aux, failed_aux = _load_groups(scn, {n: None for n in aux_names})
            failed.update(failed_aux)
            for name in loaded_aux:
                if name not in scn:
                    continue
                try:
                    variables[name] = _to_variable(
                        name, scn[name], load=load, calibration=None,
                        normalize=False, geo_missing=geo_missing)
                except Exception as exc:               # noqa: BLE001
                    failed[name] = f"{type(exc).__name__}: {exc}"

    info = parse_name(src)
    first = next(iter(variables.values()), None)
    platform = info.platform or (first.attrs.get("platform_name", "") if first else "")
    instrument = info.instrument or _instrument_from_sensor(
        first.attrs.get("sensor", "") if first else "")

    ds = SatDataset(
        platform=platform,
        instrument=instrument,
        level=info.level,
        product=_product_from_name(src, reader_name),
        start_time=_scene_time(scn, "start_time") or info.start_time,
        end_time=_scene_time(scn, "end_time"),
        variables=variables,
        geolocation=geo,
        source=src,
        reader=READER_NAME,
    )
    ds.attrs = {
        "satpy_reader": reader_name,
        "satpy_version": _satpy_version(),
        "geo_file": str(geo_file) if geo_file else "",
        "geo_missing": geo_missing,
        "geo_step": int(geo_step),
        "calibration": dict(plan),
        "missing_datasets": missing,
        "failed_datasets": failed,
        "aux_datasets": aux_names,
        "reflectance_normalized": bool(normalize_reflectance),
        "loaded": bool(load),
        "source_backend": "satpy",
    }
    return ds


def load_array(path: str | Path, name: str, *,
               calibration: str | None = None,
               normalize_reflectance: bool = True,
               geo_path: str | Path | None = None,
               geo_dirs: Sequence[str | Path] = (),
               reader: str | None = None) -> np.ndarray:
    """按需读单变量（``model.SatDataset.load()`` 的回调，签名固定两个位置参数）。

    单独建一次 Scene 有约 0.5~1 s 开销；换来的是 GUI 浏览时不用把整个文件读进内存。
    """
    src = Path(path)
    scn, _, _ = _open_scene(src, reader=reader, geo_path=geo_path, geo_dirs=geo_dirs)
    cals, _, _ = _dataset_index(scn)

    target = str(name)
    cal: str | None = None
    if target in cals:
        cal = _pick_calibration(cals[target], calibration)
        if cal is None:
            raise KeyError(f"{target} 不支持定标 {calibration!r}；可选 {sorted(cals[target])}")
        scn.load([target], calibration=cal)
    else:
        scn.load([target])          # 辅助数据集（经纬度/天顶角）没有定标维度

    if target not in scn:
        raise KeyError(f"satpy 未能从 {src.name} 读出数据集 {target!r}")
    da = scn[target]
    arr, _, _ = _finalize_array(np.asarray(da.values), cal, da.attrs.get("units"),
                                normalize_reflectance)
    return arr


# ---------------------------------------------------------------- 小工具

def _instrument_from_sensor(sensor: str) -> str:
    """satpy 的 sensor（mersi-2 / agri / mersi-ll）→ 我们的仪器名（MERSI / AGRI）。"""
    if not sensor:
        return ""
    head = sensor.split("-")[0].upper()
    return head if head else ""


def _product_from_name(src: Path, fallback: str = "") -> str:
    """文件名里的产品段。

    NSMC 两种命名习惯都得认：

        FY3D_MERSI_GBAL_L1_20260810_0635_1000M_MS   → 'GBAL'（层级是独立段，产品在前）
        FY4B-_AGRI--_N_DISK_1050E_L1-_FDI-_MULT_... → 'FDI' （层级与产品用 '-' 粘连）
    """
    parts = [p for p in src.stem.split("_") if p]
    for i, part in enumerate(parts):
        upper = part.upper()
        if upper in ("L1", "L1B", "L2", "L2B"):        # 独立层级段 → 产品名在前一段
            return (parts[i - 1].strip("-") if i else "") or fallback
        if upper.startswith(("L1-", "L2-")) and i + 1 < len(parts):
            return parts[i + 1].strip("-") or fallback
    return fallback


def _scene_time(scn, attr: str):
    try:
        return getattr(scn, attr)
    except Exception:                                  # noqa: BLE001
        return None


def _satpy_version() -> str:
    mod = sys.modules.get("satpy")
    return getattr(mod, "__version__", "") if mod is not None else ""


__all__ = [
    "SATPY_MISSING_MSG",
    "READER_NAME",
    "find_geo_file",
    "load_array",
    "read",
    "reader_candidates",
    "satpy_available",
]
