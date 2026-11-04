"""产品级出图管线：把「读 → 定标 → 定位 → 渲染 → 排版」串成一步。

这是 GUI 框选导出与命令行批量出图共用的核心，不依赖 Qt。

关键点
------
1. **定标要按产品走**：FY-3 的 Emissive 通道给的是辐亮度，必须用
   IR_Cal_Coeff 做普朗克反演才得到亮温；FY-4/FY-2 用 LUT。
   直接在 display_band 上画会得到 0.01~1.5 的无意义数值。
2. **经纬度要清填充值**：MERSI 的 GEO 网格含 -9999.9，不清掉会让
   画布范围畸变成整张空白。
3. **大数组要抽稀**：2000×2048 直接 pcolormesh 很慢，出图不需要那么多点。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# 经纬度填充值（MERSI 等产品用 -9999.9 / 999.0 之类）
_FILL_LATLON = (-9999.9, -999.0, 999.0, 9999.0, -32768.0, 65535.0)


@dataclass
class ThermalLayer:
    """一层的渲染素材：数据 + 经纬度 + 元信息。"""

    data: np.ndarray
    lat: np.ndarray | None
    lon: np.ndarray | None
    label: str
    unit: str = "K"
    cmap: str = "turbo"
    vmin: float | None = None
    vmax: float | None = None


def clean_latlon(lat: np.ndarray | None, lon: np.ndarray | None,
                 lat_range=(-90.0, 90.0), lon_range=(-180.0, 360.0)):
    """把经纬度里的填充值和越界值置 NaN。"""
    if lat is None or lon is None:
        return None, None

    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)

    bad = np.zeros(lat.shape, dtype=bool)
    for f in _FILL_LATLON:
        bad |= np.isclose(lat, f) | np.isclose(lon, f)
    bad |= ~np.isfinite(lat) | ~np.isfinite(lon)
    bad |= (lat < lat_range[0]) | (lat > lat_range[1])
    bad |= (lon < lon_range[0]) | (lon > lon_range[1])

    lat = np.where(bad, np.nan, lat)
    lon = np.where(bad, np.nan, lon)
    return lat, lon


def geo_grid(ds, target_shape: tuple[int, int]) -> tuple[np.ndarray | None, np.ndarray | None]:
    """取数据集的经纬度网格并放大到目标形状，已清理填充值。"""
    geo = getattr(ds, "geolocation", None)
    if geo is None or not geo.is_nav:
        return None, None

    lat = np.asarray(geo.lat, dtype=np.float64)
    lon = np.asarray(geo.lon, dtype=np.float64)
    lat, lon = clean_latlon(lat, lon)

    if lat.shape != tuple(target_shape):
        lat = _resize_nearest(lat, target_shape)
        lon = _resize_nearest(lon, target_shape)
    return lat, lon


def _resize_nearest(grid: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    h, w = shape
    gh, gw = grid.shape
    if (gh, gw) == (h, w):
        return grid
    ri = np.clip((np.arange(h) * gh / h).astype(int), 0, gh - 1)
    ci = np.clip((np.arange(w) * gw / w).astype(int), 0, gw - 1)
    return grid[np.ix_(ri, ci)]


def subset(lat, lon, data, region_px: tuple[int, int, int, int] | None):
    """按像素框 (r0, r1, c0, c1) 取子区域。"""
    if region_px is None:
        return lat, lon, data
    r0, r1, c0, c1 = region_px
    d = data[r0:r1, c0:c1]
    la = lat[r0:r1, c0:c1] if lat is not None else None
    lo = lon[r0:r1, c0:c1] if lon is not None else None
    return la, lo, d


def subset_by_extent(lat, lon, data, extent: tuple[float, float, float, float] | None):
    """按经纬度范围 (lon0, lon1, lat0, lat1) 取子区域。"""
    if extent is None or lat is None or lon is None:
        return lat, lon, data
    lon0, lon1, lat0, lat1 = extent
    with np.errstate(invalid="ignore"):
        mask = (lon >= lon0) & (lon <= lon1) & (lat >= lat0) & (lat <= lat1)
    if not mask.any():
        return lat, lon, data
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    r0, r1 = int(rows[0]), int(rows[-1]) + 1
    c0, c1 = int(cols[0]), int(cols[-1]) + 1
    return lat[r0:r1, c0:c1], lon[r0:r1, c0:c1], data[r0:r1, c0:c1]


def downsample(lat, lon, data, max_cells: int = 250_000):
    """抽稀到可渲染规模。"""
    h, w = data.shape[:2]
    if h * w <= max_cells:
        return lat, lon, data
    step = int(np.ceil(np.sqrt(h * w / max_cells)))
    la = lat[::step, ::step] if lat is not None and lat.shape[:2] == data.shape[:2] else lat
    lo = lon[::step, ::step] if lon is not None and lon.shape[:2] == data.shape[:2] else lon
    return la, lo, data[::step, ::step]


# ---------------- 定标：拿物理量 ----------------

def _emissive_band_names(var) -> list[str]:
    """从 band_name 属性解析该变量包含哪些通道，如 "20,21,22,23" → [20,21,22,23]。"""
    raw = var.attrs.get("band_name") or ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    out = []
    for tok in str(raw).replace("-", ",").split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.append(int(tok))
    return out


def _center_wavenumbers(ds) -> dict[int, float]:
    """通道号 → 中心波数(cm^-1)。由文件的 Effect_Center_WaveLength 换算。

    文档提到公式用 Effect_Center_Wavenumber；若文件只给波长则 ν = 1e4/λ。
    """
    wl = ds.attrs.get("Effect_Center_WaveLength")
    if wl is None:
        return {}
    wl = np.asarray(wl, dtype=float).reshape(-1)
    # 文件给的是 25 个通道的中心波长，按 MERSI 通道 1..25 顺序
    return {i + 1: (1e4 / lam if lam > 0 else np.nan) for i, lam in enumerate(wl)}


def _slope_of(var, band: int) -> float:
    """取该通道的 Slope（文档：EV_1KM_Emissive 为 [0.0002,0.0002,0.01,0.01]）。"""
    slope = var.attrs.get("Slope")
    if slope is None:
        return float(var.scale_factor) if var.scale_factor is not None else 1.0
    arr = np.asarray(slope, dtype=float).reshape(-1)
    if arr.size == 1:
        return float(arr[0])
    return float(arr[min(band, arr.size - 1)])


def thermal_data(ds, var_name: str, band: int = 0) -> tuple[np.ndarray, str]:
    """取红外通道亮温（K），严格按 FY-3 MERSI 文档的定标链。

    步骤（文档 L204-208）：
      1. radiance = DN * Slope            （Slope 逐通道不同）
      2. BT_planck = Plank^-1(radiance, Effect_Center_Wavenumber)
      3. TBB = A * BT_planck + B          （A/B 来自 TBB_Trans_Coefficient）
    """
    from .calib import radiance_to_bt

    var = ds.load(var_name)
    dn = _band_slice(var, band).astype(np.float64)

    # 无效值（文档：65535=数据丢失，65533=探元坏损）
    bad = np.zeros(dn.shape, dtype=bool)
    if var.fill_value is not None:
        bad |= dn == var.fill_value
    bad |= dn == 65535
    bad |= dn == 65533
    if var.valid_range is not None:
        lo, hi = var.valid_range
        bad |= (dn < lo) | (dn > hi)

    # 1) DN → 辐亮度 mW/(m2 cm-1 sr)
    slope = _slope_of(var, band)
    offset = float(var.add_offset) if var.add_offset is not None else 0.0
    radiance = dn * slope + offset

    # 2) 取该通道的中心波长/波数
    bands = _emissive_band_names(var)
    ch_no = bands[band] if band < len(bands) else (20 + band)
    wavenumbers = _center_wavenumbers(ds)

    if ch_no in wavenumbers and np.isfinite(wavenumbers[ch_no]):
        lam_um = 1e4 / wavenumbers[ch_no]
    else:
        lam_um = {20: 3.8, 21: 4.05, 22: 7.2, 23: 8.55, 24: 10.7, 25: 12.0}.get(ch_no, 10.7)

    bt_planck = radiance_to_bt(np.where(radiance > 0, radiance, np.nan), lam_um)

    # 3) TBB 转换订正
    tbb = ds.attrs.get("TBB_Trans_Coefficient")
    if tbb is not None:
        tbb = np.asarray(tbb, dtype=float).reshape(-1)
        n = tbb.size // 2
        if n > 0:
            a = tbb[min(band, n - 1)]
            b = tbb[n + min(band, n - 1)]
            bt_planck = a * bt_planck + b

    out = np.where(bad, np.nan, bt_planck).astype(np.float32)
    return out, "K"


def window_channel(ds) -> tuple[str, int] | None:
    """找一个适合做地表/云顶显示的窗区通道（优先 10.7 µm，即 MERSI 通道 24）。

    返回 (变量名, 通道索引) 或 None。
    """
    for var_name in ("Data/EV_250_Aggr.1KM_Emissive", "Data/EV_1KM_Emissive"):
        if var_name not in ds.variables:
            continue
        var = ds.variables[var_name]
        bands = _emissive_band_names(var)
        # 优先 24（10.7 µm），其次 25，再退回最后一个
        for target in (24, 25):
            if target in bands:
                return var_name, bands.index(target)
        if bands:
            return var_name, len(bands) - 1
    return None


def _band_slice(var, band: int) -> np.ndarray:
    from .render import band_of

    return np.asarray(band_of(var, band))


def _mersi_bt(dn: np.ndarray, scale: float, offset: float,
              ir_coeff: np.ndarray, band_index: int) -> np.ndarray:
    """MERSI 发射通道：DN → 辐亮度 → 亮温。

    IR_Cal_Coeff 形状 (6, 4, 200)：6 个发射通道 × 4 个系数 × 200 扫描线。
    这里用每条扫描线的系数做二次展开得到辐亮度，再普朗克反演。
    """
    from .calib import radiance_to_bt

    n_scan_coeff = ir_coeff.shape[2]
    n_rows = dn.shape[0]
    ch = min(band_index, ir_coeff.shape[0] - 1)

    # 逐行系数：按行索引映射到 200 条定标线
    idx = np.clip((np.arange(n_rows) * n_scan_coeff / max(n_rows, 1)).astype(int),
                  0, n_scan_coeff - 1)
    c = ir_coeff[ch]                       # (4, 200)
    c0 = c[0, idx][:, None]
    c1 = c[1, idx][:, None]
    c2 = c[2, idx][:, None]

    radiance = c0 + c1 * dn + c2 * dn * dn
    radiance = np.where(radiance > 0, radiance, np.nan)
    # 中心波长：MERSI 发射通道 20..25 对应约 3.8/4.05/7.2/8.55/10.7/12.0 µm
    wavelengths = (3.8, 4.05, 7.2, 8.55, 10.7, 12.0)
    lam = wavelengths[min(ch, len(wavelengths) - 1)]
    return radiance_to_bt(radiance, lam)


def visible_rgb(ds, names: tuple[str, str, str], bands: tuple[int, int, int] = (2, 1, 0),
                region_px: tuple[int, int, int, int] | None = None) -> tuple[np.ndarray, Any, Any]:
    """三通道真彩色合成，返回 (rgb, lat, lon)。"""
    chans = []
    for n, b in zip(names, bands):
        arr, _ = visible_data(ds, n, b)
        if region_px is not None:
            r0, r1, c0, c1 = region_px
            arr = arr[r0:r1, c0:c1]
        chans.append(arr)

    rgb = true_color(*chans)
    lat, lon = geo_grid(ds, (rgb.shape[0], rgb.shape[1]))
    return rgb, lat, lon


def _reflective_band_names(var) -> list[str]:
    """解析反射变量的 band_name，如 "5-19" → [5..19]，"Band 1" → [1]。"""
    raw = var.attrs.get("band_name") or ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    raw = str(raw).strip()

    if "-" in raw:
        left, _, right = raw.partition("-")
        if left.strip().isdigit() and right.strip().isdigit():
            return list(range(int(left), int(right) + 1))

    out: list[int] = []
    for tok in raw.replace(",", " ").split():
        tok = tok.replace("Band", "").replace("b", "").strip()
        if tok.isdigit():
            out.append(int(tok))
    return out



# ---------------- 太阳几何：GEO 文件里的天顶角 ----------------

# 各卫星族太阳天顶角的候选路径（按文档）
SOLAR_ZENITH_PATHS = (
    "Geolocation/SolarZenith",     # FY-3 MERSI GEO1K
    "Geolocation/SolarZenithAngle",
    "Navigation/NOMSunZenith",     # FY-4 AGRI GEO
    "Navigation/NOMSunZenithAngle",
    "SolarZenith",
)


def find_geo_file(ds) -> Path | None:
    """在数据文件同目录找配套的 GEO 定位文件。

    MERSI L1 的命名规律：FY3H_MERSI_GRAN_L1_YYYYMMDD_HHMM_1000M_V0.hdf
    对应的 GEO 文件：     FY3H_MERSI_GRAN_L1_YYYYMMDD_HHMM_GEO1K_V0.hdf
    """
    if ds.source is None:
        return None
    src = Path(ds.source)
    stem = src.stem

    # 把分辨率段替换成 GEO1K / GEOQK
    cands = []
    for token, repl in (("_1000M_", "_GEO1K_"), ("_0250M_", "_GEOQK_"),
                        ("_0500M_", "_GEOQK_"), ("_2000M_", "_GEO1K_"),
                        ("_4000M_", "_GEO1K_")):
        if token in stem:
            cands.append(stem.replace(token, repl))
    cands.append(stem.replace("_1000M", "_GEO1K"))
    cands.append(stem + "_GEO")

    for c in cands:
        for ext in (src.suffix, ".hdf", ".HDF"):
            p = src.with_name(c + ext)
            if p.exists() and p != src:
                return p
    return None


def solar_zenith(ds, shape: tuple[int, int] | None = None,
                 geo_file: Path | None = None) -> np.ndarray | None:
    """取逐像元太阳天顶角（度）。优先从数据文件本身找，其次找配套 GEO 文件。"""
    # 1) 数据文件自带？
    for p in SOLAR_ZENITH_PATHS:
        if p in ds.variables:
            arr = _read_angle(ds, p)
            return _fit_shape(arr, shape)

    # 2) 配套 GEO 文件
    gf = geo_file or find_geo_file(ds)
    if gf is None or not Path(gf).exists():
        return None
    try:
        from .readers import open_file

        gds = open_file(gf, load=False)
    except Exception:                       # noqa: BLE001
        return None

    for p in SOLAR_ZENITH_PATHS:
        if p in gds.variables:
            arr = _read_angle(gds, p)
            return _fit_shape(arr, shape)
    return None


def _read_angle(ds, path: str) -> np.ndarray:
    """读角度类字段并应用缩放。

    文档（FY-3D MERSI 1KM_GEO 表5 SDS6）：
        SolarZenith  int16  Slope=0.01  Intercept=0  FillValue=-32768
        valid_range [0, 18000]  units=degree
    原始 DN 2188~5291 → 21.88°~52.91°。
    """
    var = ds.load(path)
    raw = np.asarray(var.data)
    out = raw.astype(np.float32)
    if var.scale_factor is not None:
        out = out * np.float32(var.scale_factor)
    if var.add_offset is not None:
        out = out + np.float32(var.add_offset)

    bad = np.zeros(out.shape, dtype=bool)
    if var.fill_value is not None:
        bad |= raw == var.fill_value          # 在原始整数上比，避免 float32 精度问题
    if var.valid_range is not None:
        lo, hi = var.valid_range
        bad |= (raw < lo) | (raw > hi)
    return np.where(bad, np.nan, out)


def _fit_shape(arr: np.ndarray, shape: tuple[int, int] | None) -> np.ndarray:
    """把天顶角缩放到目标形状（GEO 与数据分辨率可能不同）。"""
    if shape is None or arr.shape[:2] == tuple(shape):
        return arr
    h, w = shape
    gh, gw = arr.shape[:2]
    ri = np.clip((np.arange(h) * gh / h).astype(int), 0, gh - 1)
    ci = np.clip((np.arange(w) * gw / w).astype(int), 0, gw - 1)
    return arr[np.ix_(ri, ci)]


def earth_sun_distance_ratio(ds) -> float:
    """日地距离比 d（全局属性）。"""
    for key in ("EarthSun Distance Ratio", "Earth-Sun Distance Ratio",
                "EarthSunDistanceRatio"):
        v = ds.attrs.get(key)
        if v is not None:
            try:
                return float(np.asarray(v).reshape(-1)[0])
            except (TypeError, ValueError):
                pass
    return 1.0


def reflectance_toa(ds, var_name: str, band: int = 0,
                    sza: np.ndarray | None = None) -> tuple[np.ndarray, str]:
    """归一化反射率 → 表观反射率（TOA），按 SZA 订正。

        Ref_TOA = Ref* / cos(SZA) * d^2

    SZA >= 88° 的像元（夜侧/无光照）置 NaN。
    """
    ref, unit = visible_data(ds, var_name, band)
    sza = solar_zenith(ds, ref.shape) if sza is None else sza
    if sza is None:
        return ref, unit                     # 没有天顶角就返回原值

    cos_sza = np.cos(np.deg2rad(np.asarray(sza, dtype=np.float32)))
    d = earth_sun_distance_ratio(ds)
    with np.errstate(divide="ignore", invalid="ignore"):
        toa = ref / cos_sza * (d ** 2)
    bad = (~np.isfinite(toa)) | (sza >= 88.0)
    return np.where(bad, np.nan, toa).astype(np.float32), unit


def visible_data(ds, var_name: str, band: int = 0) -> tuple[np.ndarray, str]:
    """取可见光通道的**归一化反射率**（0~1），按 FY-3 MERSI 说明书 6.2 节。

    公式（移植自参考实现 fy3f_mersi_l1.py:584-609）：
        Ref* = (Cal_2 * DN^2 + Cal_1 * DN + Cal_0) * 0.01

    - VIS_Cal_Coeff 的索引是 **通道号 - 1**（ch 从 1 开始）
    - 乘 0.01 得到 0~1，不是百分数
    - 250m 文件里数据集名可能拼作 VIS_Cal_Ceff（说明书表 7 同样笔误）
    """
    var = ds.load(var_name)
    dn = _band_slice(var, band).astype(np.float64)

    bad = np.zeros(dn.shape, dtype=bool)
    if var.fill_value is not None:
        bad |= dn == var.fill_value
    bad |= dn == 65535
    bad |= dn == 65533
    if var.valid_range is not None:
        lo, hi = var.valid_range
        bad |= (dn < lo) | (dn > hi)

    coeff = None
    for cand in ("Calibration/VIS_Cal_Coeff", "Calibration/VIS_Cal_Ceff"):
        if cand in ds.variables:
            coeff = ds.load(cand).data
            break

    refl = None
    if coeff is not None and band < coeff.shape[0]:
        a0, a1, a2 = coeff[band][0], coeff[band][1], coeff[band][2]
        refl = (a2 * dn ** 2 + a1 * dn + a0) * 0.01
    if refl is None:
        s = float(var.scale_factor) if var.scale_factor is not None else 1.0
        o = float(var.add_offset) if var.add_offset is not None else 0.0
        refl = (dn * s + o) * 0.01

    return np.where(bad, np.nan, refl).astype(np.float32), "1"


# 真彩色默认波段（参考实现用 b3/b2/b1 = 0.65/0.55/0.47 µm）
TRUE_COLOR_BANDS = (2, 1, 0)


def true_color(r: np.ndarray, g: np.ndarray, b: np.ndarray,
               pct: tuple[float, float] = (1.0, 99.0),
               gamma: float = 0.6,
               saturation: float = 1.5) -> np.ndarray:
    """真彩色合成，移植自参考实现 _truecolor_array（fy3f_mersi_l1.py:1662）。

    每个通道先独立拉伸，再做白平衡（各通道均值归一到几何均值），最后增强饱和度。

    默认参数 (1,99) / gamma 0.6 / sat 1.5 是针对**晨昏轨道**调过的：
    MERSI L1 不含太阳天顶角数据，无法做真正的 TOA 订正，
    只能用更低的 gamma 把暗部提亮，否则整幅图接近黑色。
    正午场景可传 gamma=0.9 更接近真实亮度。
    """
    chans, valid = [], None
    for ref in (r, g, b):
        arr = np.asarray(ref, dtype=np.float32)
        v = arr[np.isfinite(arr)]
        lo, hi = np.percentile(v, pct) if v.size else (0.0, 1.0)
        if hi <= lo:
            hi = lo + 1e-6
        chans.append(np.clip((arr - lo) / (hi - lo), 0, 1))
        # 有效性只看有限性。早期这里写死 `arr < 1.4`，那是**只对 0~1 归一化
        # 反射率成立**的假设；一旦传入原始 DN(0~4095) 或百分数(0~100)，
        # 几乎所有像元都被判无效，合成结果是全黑。
        m = np.isfinite(arr)
        valid = m if valid is None else (valid & m)

    means = [float(np.nanmean(c)) if np.isfinite(c).any() else 1.0 for c in chans]
    gmean = float(np.mean(means)) or 1.0
    chans = [np.clip(c * (gmean / max(m, 1e-6)), 0, 1) ** gamma
             for c, m in zip(chans, means)]

    rgb = np.dstack(chans)
    gray = np.mean(rgb, axis=2, keepdims=True)
    rgb = np.clip(gray + saturation * (rgb - gray), 0, 1)

    rgb = np.nan_to_num(rgb, nan=0.0, posinf=1.0, neginf=0.0)   # 避免 NaN cast 告警
    out = (rgb * 255.0 + 0.5).astype(np.uint8)
    if valid is not None:
        out[~valid] = 0
    return out



def true_color_source(ds) -> tuple[str, tuple[int, int, int], tuple[int, int, int]] | None:
    """找真彩色所需的变量与波段。

    **关键**：MERSI 的 b1-b4（0.47/0.55/0.65/0.87 µm）在
    ``EV_250_Aggr.1KM_RefSB``（band_name "1-4"），
    而 ``EV_1KM_RefSB`` 只含 b5-b19（1.38 µm 起，全在短波红外/水汽带），
    拿它做真彩色会得到一片黄绿的错误图像。

    返回 (变量名, 数组索引三元组(R,G,B), 通道号三元组(b3,b2,b1)) 或 None。
    """
    for name in ("Data/EV_250_Aggr.1KM_RefSB", "Data/EV_250_RefSB"):
        if name not in ds.variables:
            continue
        var = ds.variables[name]
        bands = _reflective_band_names(var)
        shape = tuple(var.shape)
        # 需要至少 3 个通道
        if len(bands) < 3 and len(shape) >= 3 and shape[0] < 3:
            continue
        # b3/b2/b1 在 band list 里的位置
        idx = []
        chs = []
        for target in (3, 2, 1):
            if target in bands:
                idx.append(bands.index(target))
                chs.append(target)
        if len(idx) != 3:
            # 属性缺失时退回前三个通道（b1,b2,b3）并按 B,G,R 顺序给
            idx, chs = [2, 1, 0], [3, 2, 1]
        return name, tuple(idx), tuple(chs)
    return None


def build_layers(ds, thermal_var: str, thermal_band: int = 0,
                 visible_vars: tuple[str, str, str] | None = None,
                 visible_bands: tuple[int, int, int] = TRUE_COLOR_BANDS,
                 region_px: tuple[int, int, int, int] | None = None,
                 extent: tuple[float, float, float, float] | None = None,
                 max_cells: int = 250_000) -> tuple[ThermalLayer, dict | None]:
    """组装制图所需的图层。返回 (红外层, 可见光层字典或None)。"""
    bt, unit = thermal_data(ds, thermal_var, thermal_band)
    lat, lon = geo_grid(ds, bt.shape)

    lat, lon, bt = subset(lat, lon, bt, region_px)
    lat, lon, bt = subset_by_extent(lat, lon, bt, extent)
    lat, lon, bt = downsample(lat, lon, bt, max_cells)

    label = thermal_var.split("/")[-1]
    if thermal_band:
        label += f" 通道{thermal_band + 1}"

    thermal = ThermalLayer(data=bt, lat=lat, lon=lon, label=label, unit=unit)

    visible = None
    if visible_vars:
        try:
            rgb, vlat, vlon = visible_rgb(ds, visible_vars, visible_bands, region_px)
            # 与红外用同一套裁剪逻辑，保证两块面板经纬网一致
            if vlat is not None and vlon is not None:
                vlat, vlon, rgb = subset_by_extent(vlat, vlon, rgb, extent)
                if max_cells:
                    step = max(1, int(np.ceil(np.sqrt(rgb.shape[0] * rgb.shape[1] / max_cells))))
                    if step > 1:
                        rgb = rgb[::step, ::step]
                        vlat = vlat[::step, ::step]
                        vlon = vlon[::step, ::step]
            visible = {"rgb": rgb, "lat": vlat, "lon": vlon, "label": "可见光真彩色"}
        except Exception:                       # noqa: BLE001
            visible = None

    return thermal, visible
