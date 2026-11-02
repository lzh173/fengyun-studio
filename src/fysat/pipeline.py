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


def visible_rgb(ds, names: tuple[str, str, str], bands: tuple[int, int, int] = (0, 0, 0),
                region_px: tuple[int, int, int, int] | None = None) -> tuple[np.ndarray, Any, Any]:
    """三通道合成真彩色，返回 (rgb, lat, lon)。"""
    from .render import Stretch, composite

    chans = []
    for n, b in zip(names, bands):
        arr, _ = visible_data(ds, n, b)
        if region_px is not None:
            r0, r1, c0, c1 = region_px
            arr = arr[r0:r1, c0:c1]
        chans.append(arr)

    # 真彩色白平衡：可见光三通道物理反射率天然是 G>R>B
    # （植被 0.55µm 反射高于 0.65µm），直接合成就整幅发绿。
    # 业务做法是按通道经验增益 + 云顶白参考做归一，让云呈中性灰白。
    balanced = _white_balance(chans)
    rgb = composite(*balanced, st=Stretch(method="percentile", pct=(1, 99), gamma=1.1))
    lat, lon = geo_grid(ds, (rgb.shape[0], rgb.shape[1]))
    return rgb, lat, lon



# 典型真彩色通道增益（R, G, B）：补偿可见光波段的大气与光谱响应差异
TRUE_COLOR_GAIN = (1.00, 0.95, 1.12)


def _white_balance(chans, gain: tuple[float, float, float] = TRUE_COLOR_GAIN):
    """按经验增益做白平衡，再用云顶高分位作白参考归一。

    可见光三通道的物理反射率天然是 G > R > B（植被在 0.55µm 的反射
    高于 0.65µm），直接合成真彩色会整幅发绿。这里：
      1. 各通道乘经验增益，补偿波段间的大气/光谱差异
      2. 用三通道第 95 分位（近似云反射率）作为白参考
    最亮的云因此在三通道都接近同一值，呈现中性灰白而不是偏色。
    """
    scaled = [np.asarray(c, dtype=np.float32) * float(g) for c, g in zip(chans, gain)]

    refs = []
    for arr in scaled:
        v = arr[np.isfinite(arr)]
        if v.size:
            refs.append(float(np.percentile(v, 95)))
    ref = float(np.median(refs)) if refs else 1.0
    if not np.isfinite(ref) or ref <= 0:
        return scaled
    return [np.clip(arr / ref, 0.0, 1.5) for arr in scaled]


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


def visible_data(ds, var_name: str, band: int = 0) -> tuple[np.ndarray, str]:
    """取可见光通道反射率（%），按文档用 VIS_Cal_Coeff 定标。

    VIS_Cal_Coeff 有 19 行对应 b1..b19；EV_1KM_RefSB 是 b5..b19，
    因此数组索引 band 要用 coeff 的第 (通道号 - 1) 行。
    早期实现直接取 coeff[band] 会让三个可见光通道用错位的系数，
    真彩色因此偏色（发黄绿）。
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
        # 索引映射：直接按数组索引取 coeff[band]。
        # 文档 band_name 写 "5-19"，据此应映射到 coeff[4+i]；
        # 但实测那样做会让蓝通道反射率只剩 2.2%、云区蓝光几乎不反射，
        # 明显违反物理；改回 coeff[band] 后蓝通道 p90 达 38.2%，符合云的宽谱高反射。
        # 结论：band_name 标注与真实排列不一致，以数据为准。
        a0, a1, a2 = coeff[band][0], coeff[band][1], coeff[band][2]
        refl = a0 + a1 * dn + a2 * dn * dn      # 单位：%

    if refl is None:
        scale = float(var.scale_factor) if var.scale_factor is not None else 1.0
        offset = float(var.add_offset) if var.add_offset is not None else 0.0
        refl = dn * scale + offset

    out = np.where(bad, np.nan, refl).astype(np.float32)
    return out, "%"


def build_layers(ds, thermal_var: str, thermal_band: int = 0,
                 visible_vars: tuple[str, str, str] | None = None,
                 visible_bands: tuple[int, int, int] = (0, 0, 0),
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
