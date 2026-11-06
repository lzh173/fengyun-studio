"""辐射定标：DN → 物理量（反射率 / 辐亮度 / 亮温）。

覆盖风云系列 L1 的三种定标方式：

==============  ========================================  =========================
类型            公式                                      典型产品
==============  ========================================  =========================
可见光/近红外   ρ = a0 + a1·DN + a2·DN²（单位见系数）     FY-3 ``VIS_Cal_Coeff``
热红外          L = scale·DN + offset → 普朗克反演亮温     FY-3 ``EV_*_Emissive``
查找表          value = LUT[DN]（可按需线性插值）          FY-4 ``CALChannel**``、FY-2
微波/热红外线性 TB = a0 + a1·DN + a2·DN²                  微波通道逐扫描线系数
==============  ========================================  =========================

普朗克反演（波数形式，与 FY-3/FY-4 官方文档口径一致）
----------------------------------------------------
``L = C1·ν³ / (exp(C2·ν/T) − 1)``，``T = C2·ν / ln(C1·ν³/L + 1)``，其中
``ν = 1e4/λ(µm)`` [cm⁻¹]，L 单位 mW/(m²·sr·cm⁻¹)，
C1 = 1.1910427e-5 mW/(m²·sr·cm⁻⁴)，C2 = 1.4387752 K·cm。

实现约定
--------
* 全部向量化，入参可以是任意形状的 ndarray（也能吃 Python 标量）。
* 统一输出 **float32**：MERSI 250m 一张 6560 万像元，能省一半内存。
* 无效值一律输出 **NaN**：``fill``（默认 FY-3 的 65535/65534/65533）、``valid_range``
  之外、L ≤ 0、LUT 越界。上层不必再自己判掩膜。
"""
from __future__ import annotations

import numpy as np

# 普朗克常数（波数形式，L 单位 mW/(m²·sr·cm⁻¹)，ν 单位 cm⁻¹）
C1 = 1.1910427e-5   # mW/(m²·sr·cm⁻⁴)
C2 = 1.4387752      # K·cm

# FY-3 系列 L1 的约定 DN（属性 Description 里写明）
FY3_FILL_DN = 65535      # 缺测
FY3_SATURATED_DN = 65534  # 探测器饱和
FY3_DEAD_DN = 65533      # 探测器失效
FY3_BAD_DN = (FY3_FILL_DN, FY3_SATURATED_DN, FY3_DEAD_DN)

__all__ = [
    "C1",
    "C2",
    "FY3_BAD_DN",
    "FY3_FILL_DN",
    "FY3_SATURATED_DN",
    "FY3_DEAD_DN",
    "dn_to_float",
    "radiance_linear",
    "reflectance_linear",
    "tb_linear",
    "radiance_to_bt",
    "planck_radiance",
    "bt_from_dn_planck",
    "lookup_table",
    "bt_from_lut",
    "reflectance_from_lut",
]


# ---------------------------------------------------------------- 内部工具

def _bad(dn: np.ndarray, fill, valid_range) -> np.ndarray:
    """True = 无效（fill 值或超出 valid_range）。"""
    bad = np.zeros(dn.shape, dtype=bool)
    if fill is not None:
        for f in np.atleast_1d(np.asarray(fill, dtype=np.float64)):
            bad |= dn == f
    if valid_range is not None:
        lo, hi = valid_range
        bad |= (dn < lo) | (dn > hi)
    return bad


def _coeff3(coeff) -> tuple[float, float, float]:
    """把 [a0, a1] / [a0, a1, a2] 归一成三元组。"""
    arr = np.asarray(coeff, dtype=np.float64).reshape(-1)
    if arr.size < 2:
        raise ValueError(f"系数至少要有 2 个（截距、斜率），收到 {arr.size} 个")
    if arr.size > 3:
        raise ValueError(f"系数最多 3 个（截距、斜率、二次项），收到 {arr.size} 个")
    a0, a1 = float(arr[0]), float(arr[1])
    a2 = float(arr[2]) if arr.size == 3 else 0.0
    return a0, a1, a2


def _check_wavelength(wavelength_um) -> float:
    lam = float(np.asarray(wavelength_um).reshape(-1)[0])
    if not np.isfinite(lam) or lam <= 0.0:
        raise ValueError(f"中心波长必须为正数（µm），收到 {wavelength_um!r}")
    return lam


# ---------------------------------------------------------------- 入口：DN → 浮点

def dn_to_float(
    dn,
    fill=FY3_BAD_DN,
    valid_range: tuple[float, float] | None = None,
):
    """DN → float32，并把无效值置 NaN（其它定标函数的公共入口）。

    ``fill`` 可以是单个值或一组值（默认 FY-3 的 65535/65534/65533）；
    传 ``None`` 表示不做填充值判断。``valid_range`` 之外的像元同样置 NaN。
    """
    arr = np.asarray(dn)
    out = arr.astype(np.float32, copy=True)
    bad = _bad(out, fill, valid_range)
    if bad.any():
        out[bad] = np.nan
    return out


# ---------------------------------------------------------------- 线性 / 多项式

def radiance_linear(
    dn,
    scale: float = 1.0,
    offset: float = 0.0,
    *,
    fill=FY3_BAD_DN,
    valid_range: tuple[float, float] | None = None,
) -> np.ndarray:
    """辐亮度线性定标：``L = offset + scale · DN``。

    FY-3 ``EV_250_Emissive_b24`` 的 ``Slope`` = 0.01、``Intercept`` = 0，
    算出来即是 mW/(m²·sr·cm⁻¹)。
    """
    out = dn_to_float(dn, fill=fill, valid_range=valid_range)
    if scale != 1.0:
        out *= np.float32(scale)
    if offset != 0.0:
        out += np.float32(offset)
    return out


def _poly(dn, coeff, *, fill, valid_range, out_scale=1.0) -> np.ndarray:
    a0, a1, a2 = _coeff3(coeff)
    out = dn_to_float(dn, fill=fill, valid_range=valid_range)
    if a2 != 0.0:
        out *= out * np.float32(a2) + np.float32(a1)
        out += np.float32(a0)
    else:
        out *= np.float32(a1)
        out += np.float32(a0)
    if out_scale != 1.0:
        out *= np.float32(out_scale)
    return out


def reflectance_linear(
    dn,
    coeff,
    *,
    fill=FY3_BAD_DN,
    valid_range: tuple[float, float] | None = None,
    out_scale: float = 1.0,
) -> np.ndarray:
    """可见光/近红外定标：``ρ = a0 + a1·DN + a2·DN²``。

    参数
    ----
    coeff : ``[a0, a1]`` 或 ``[a0, a1, a2]``。FY-3 ``/Calibration/VIS_Cal_Coeff``
            的一行就是 ``[截距, 斜率, 二次项]``，算出来的单位是 **%**（0–110 量级）。
    out_scale : 输出再乘的常数，例如把 FY-4 LUT 的 0–1 反射率换成 % 就传 100。
    """
    return _poly(dn, coeff, fill=fill, valid_range=valid_range, out_scale=out_scale)


def tb_linear(
    dn,
    coeff,
    *,
    fill=65535,
    valid_range: tuple[float, float] | None = None,
    out_scale: float = 1.0,
) -> np.ndarray:
    """微波/热红外线性（或二次）定标：``TB = a0 + a1·DN + a2·DN²``，单位 K。

    ``fill`` 默认只认 65535（FY-3 微波/红外产品的缺测值，饱和/失效值视产品而定，
    需要时把 'fill' 传成 ``FY3_BAD_DN``）。
    """
    return _poly(dn, coeff, fill=fill, valid_range=valid_range, out_scale=out_scale)


# ---------------------------------------------------------------- 普朗克反演

def planck_radiance(bt, wavelength_um: float) -> np.ndarray:
    """正向普朗克：亮温 K → 辐亮度 mW/(m²·sr·cm⁻¹)（用于校验/仿真）。"""
    lam = _check_wavelength(wavelength_um)
    nu = 1.0e4 / lam
    c1n3 = np.float32(C1 * nu ** 3)
    c2n = np.float32(C2 * nu)
    t = np.asarray(bt, dtype=np.float32)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        out = c1n3 / np.expm1(c2n / t)     # 标量/float32 → float32，新数组，可直接写 NaN
    bad = ~(np.isfinite(out) & (out > 0.0))
    if bad.any():
        out[bad] = np.nan
    return np.asarray(out, dtype=np.float32)


def radiance_to_bt(radiance, wavelength_um: float) -> np.ndarray:
    """普朗克反演：辐亮度 mW/(m²·sr·cm⁻¹) → 亮温 K（向量化，float32 输出）。

    ``T = C2·ν / ln(C1·ν³/L + 1)``，``ν = 1e4/λ``。L ≤ 0 / NaN 的位置返回 NaN。
    """
    lam = _check_wavelength(wavelength_um)
    nu = 1.0e4 / lam
    c1n3 = np.float32(C1 * nu ** 3)
    c2n = np.float32(C2 * nu)

    out = np.array(radiance, dtype=np.float32, copy=True)
    bad = ~(out > 0.0)                     # 0 / 负数 / NaN
    with np.errstate(divide="ignore", invalid="ignore"):
        np.divide(c1n3, out, out=out)
        np.add(out, np.float32(1.0), out=out)
        np.log(out, out=out)
        np.divide(c2n, out, out=out)
    if bad.any():
        out[bad] = np.nan
    return out


def bt_from_dn_planck(
    dn,
    scale: float = 1.0,
    offset: float = 0.0,
    wavelength_um: float = 10.7342,
    *,
    fill=FY3_BAD_DN,
    valid_range: tuple[float, float] | None = None,
) -> np.ndarray:
    """FY-3 热红外通道定标一条龙：``DN →(线性) 辐亮度 →(普朗克) 亮温 K``。

    ``wavelength_um`` 默认 10.7342（MERSI-II 第 24 通道）；官方值可以从文件全局属性
    ``Effect_Center_WaveLength`` 的第 24 项取。
    """
    L = radiance_linear(dn, scale=scale, offset=offset, fill=fill, valid_range=valid_range)
    return radiance_to_bt(L, wavelength_um)


# ---------------------------------------------------------------- 查找表（LUT）

def _as_lut(lut) -> np.ndarray:
    arr = np.asarray(lut, dtype=np.float32)
    return np.ascontiguousarray(arr.reshape(-1))


def lookup_table(
    dn,
    lut,
    kind: str = "linear",
    *,
    fill=None,
    valid_range: tuple[float, float] | None = None,
    lut_fill: float | None = None,
) -> np.ndarray:
    """用查找表把 DN 映射成物理量（FY-4 ``CALChannelXX`` / FY-2 ``CALChannelIR*``）。

    参数
    ----
    dn        : 原始 DN（整数；浮点也行，按 DN 值在 LUT 索引上插值）。
    lut       : 一维查找表，第 i 项对应 DN = i。FY-2 的 ``(1,1024)``、FY-4 的 ``(4096,)``
                都会自动展平。
    kind      : ``'linear'``（默认，相邻两点线性插值）或 ``'nearest'``（最近整数索引，最快）。
    fill      : DN 的缺测值（默认不判断；FY-4/FY-2 的 NOMChannel 填 65535 时传 65535）。
    valid_range : DN 的有效范围，之外置 NaN。
    lut_fill  : LUT 里的无效标记（例如 -1 或 -65535），命中则输出 NaN。

    越界 DN（< 0 或 ≥ LUT 长度）输出 NaN——不静默截断，免得把越界 DN 画成有效数据。
    """
    table = _as_lut(lut)
    n = table.size
    if lut_fill is not None:
        table = table.copy()
        table[table == np.float32(lut_fill)] = np.nan
    if n == 0:
        raise ValueError("空查找表")

    key = kind.lower()
    if key == "nearest":
        idx = np.rint(dn_to_float(dn, fill=fill, valid_range=valid_range)).astype(np.float32)
        ok = np.isfinite(idx) & (idx >= 0.0) & (idx <= n - 1)
        out = np.full(idx.shape, np.nan, dtype=np.float32)
        if ok.any():
            out[ok] = table[idx[ok].astype(np.intp)]
        return out
    if key == "linear":
        arr = dn_to_float(dn, fill=fill, valid_range=valid_range)
        with np.errstate(invalid="ignore"):
            out = np.interp(arr, np.arange(n, dtype=np.float32), table, left=np.nan, right=np.nan)
        return np.asarray(out, dtype=np.float32)
    raise ValueError(f"kind 只支持 'linear' / 'nearest'，收到 {kind!r}")


def bt_from_lut(dn, lut, **kwargs) -> np.ndarray:
    """LUT 直接给亮温的产品（FY-2 ``CALChannelIR*``）：等价于 ``lookup_table(..., 'nearest')``。"""
    kwargs.setdefault("kind", "nearest")
    return lookup_table(dn, lut, **kwargs)


def reflectance_from_lut(dn, lut, *, percent: bool = True, **kwargs) -> np.ndarray:
    """LUT 直接给反射率的产品（FY-4 ``CALChannel01..06``）。

    这些 LUT 通常是 0–1.15 的反射率（反照率），``percent=True``（默认）乘 100 变成 %，
    与 FY-3 ``VIS_Cal_Coeff`` 的输出口径一致。
    """
    out = lookup_table(dn, lut, **kwargs)
    if percent:
        out *= np.float32(100.0)
    return out


# ======================= FY-4 AGRI / GHI 定标 =======================
#
# 依据 FY4B_AGRI_DISK_L1_4KM_HDF_V1.0.md 第 3 章「相关物理量转换方法」：
#
#   3.1 太阳反射波段（NOMChannel01-06）
#       (1) 反射率   rho = DN * SCALE + OFFSET        （CALIBRATION_COEF）
#           或查表  CALChannelNN 为 DN→反射率 的查找表
#       (2) 辐亮度   L = rho * ESUN / pi               （ESUN 为通道平均太阳辐照度）
#       (3) 表观反射率 rho_TOA = rho * d / cos(theta)  （d 见全局属性，theta 见 GEO 文件）
#
#   3.2 热红外波段（NOMChannel07-15）
#       (1) 亮温     CALChannelNN 为 DN→亮温(K) 的查找表
#       (2) 辐亮度   L = DN * SCALE + OFFSET          （单位 W/(m2·sr·µm)）
#
# 实测（FY-4B AGRI 4000M）：
#   CALChannel01      0 → 1.143            → 反射率是 0~1.14 的小数，**不是百分数**
#   CALChannel07    405 → 200 (K)          → 热通道 LUT 直接是亮温
#   COEF[6] = scale -0.00296, offset 12.118 → 热通道 COEF 给的是辐亮度
#   填充值：65534 = 地球内无效，65535 = 地球外无效

AGRI_COEF_PATHS = (
    "Calibration/CALIBRATION_COEF(SCALE+OFFSET)",
    "Calibration/CALIBRATION_COEF",
    "CALIBRATION_COEF(SCALE+OFFSET)",
)
AGRI_FILL_VALUES = (65534, 65535)


def agri_calibration(ds) -> dict | None:
    """判断是不是 FY-4 AGRI / GHI 这类「CALChannel + CALIBRATION_COEF」产品。

    返回 {"coef": ndarray(C,2), "esun": ndarray(C,) | None}，不是则 None。
    """
    if ds is None:
        return None
    names = list(getattr(ds, "variables", {}) or {})

    coef_name = next((p for p in AGRI_COEF_PATHS if p in names), None)
    if coef_name is None:
        return None
    # 必须有 CALChannelNN 才算（避免把别的产品误判）
    if not any(n.startswith("Calibration/CALChannel") or n.startswith("CALChannel")
               for n in names):
        return None

    import numpy as np

    coef = np.asarray(ds.load(coef_name).data, dtype=np.float64)
    if coef.ndim != 2 or coef.shape[1] != 2:
        return None
    esun = None
    for p in ("Calibration/ESUN", "ESUN"):
        if p in names:
            esun = np.asarray(ds.load(p).data, dtype=np.float64).ravel()
            break
    return {"coef": coef, "esun": esun}


def agri_channel_table(ds, channel: int):
    """取该通道的 DN→物理量 查找表（4096 点）；没有则 None。"""
    import numpy as np

    for p in (f"Calibration/CALChannel{channel:02d}", f"CALChannel{channel:02d}"):
        if p in (getattr(ds, "variables", {}) or {}):
            return np.asarray(ds.load(p).data, dtype=np.float64).ravel()
    return None


def _agri_mask(dn, valid_range=None):
    import numpy as np

    bad = ~np.isfinite(dn)
    for f in AGRI_FILL_VALUES:
        bad |= dn == f
    if valid_range is not None:
        lo, hi = valid_range
        bad |= (dn < lo) | (dn > hi)
    return bad


def agri_reflectance(ds, dn, channel: int, valid_range=None):
    """太阳反射波段：rho = DN*SCALE + OFFSET，返回 0~1 量级的小数反射率。

    文档 3.1(1) 的公式法。查找表法（CALChannelNN）可用 agri_lut_lookup 取。
    """
    import numpy as np

    cal = agri_calibration(ds)
    if cal is None:
        raise ValueError("该数据集不含 FY-4 AGRI/GHI 定标系数")
    coef = cal["coef"]
    if channel < 1 or channel > coef.shape[0]:
        raise ValueError(f"通道 {channel} 超出定标系数范围 1~{coef.shape[0]}")

    scale, offset = float(coef[channel - 1, 0]), float(coef[channel - 1, 1])
    rho = np.asarray(dn, dtype=np.float64) * scale + offset
    bad = _agri_mask(np.asarray(dn, dtype=np.float64), valid_range)
    return np.where(bad, np.nan, rho).astype(np.float32)


def agri_lut_lookup(ds, dn, channel: int, valid_range=None):
    """用 CALChannelNN 查找表把 DN 换成物理量。

    反射通道得到反射率（0~1 量级），热通道得到**亮温 K**。
    """
    import numpy as np

    lut = agri_channel_table(ds, channel)
    if lut is None:
        return None
    d = np.asarray(dn, dtype=np.float64)
    idx = np.clip(d, 0, lut.size - 1)
    out = np.interp(idx, np.arange(lut.size), lut)
    bad = _agri_mask(d, valid_range) | (d > lut.size - 1)
    return np.where(bad, np.nan, out).astype(np.float32)


def agri_bt(ds, dn, channel: int, valid_range=None):
    """热红外通道亮温（K）：查 CALChannelNN（文档 3.2(1)）。"""
    out = agri_lut_lookup(ds, dn, channel, valid_range)
    if out is None:
        raise ValueError(f"通道 {channel} 缺 CALChannel 查找表，无法换算亮温")
    return out


def agri_radiance(ds, dn, channel: int, valid_range=None):
    """热红外通道辐亮度 W/(m2·sr·µm)：L = DN*SCALE + OFFSET（文档 3.2(2)）。"""
    import numpy as np

    cal = agri_calibration(ds)
    if cal is None:
        raise ValueError("该数据集不含 FY-4 AGRI/GHI 定标系数")
    coef = cal["coef"]
    if channel < 1 or channel > coef.shape[0]:
        raise ValueError(f"通道 {channel} 超出定标系数范围")
    scale, offset = float(coef[channel - 1, 0]), float(coef[channel - 1, 1])
    d = np.asarray(dn, dtype=np.float64)
    out = d * scale + offset
    bad = _agri_mask(d, valid_range)
    return np.where(bad, np.nan, out).astype(np.float32)


def agri_solar_irradiance(ds, channel: int) -> float | None:
    """通道平均太阳辐照度 ESUN（W/(m2·µm)），用于反射率→辐亮度。"""
    cal = agri_calibration(ds)
    if not cal or cal.get("esun") is None:
        return None
    esun = cal["esun"]
    return float(esun[channel - 1]) if 0 < channel <= esun.size else None


# ======================= FY-2 FDI 定标（查找表）=======================
#
# FY-2 FDI 产品每个通道自带一张 DN→物理量 的查找表：
#   Calibration/CALChannelIR1..IR4   DN(0..1023) → 亮温 K
#   Calibration/CALChannelVIS        DN(0..63)   → 反射率 %
#
# 实测（FY-2G FDI）：
#   CALChannelIR1  1024 点，333.5 K → 119.6 K（随 DN 递减）
#   CALChannelIR2  1024 点，336.9 K → 112.8 K
#   CALChannelVIS    64 点，0 → 118.4（百分数）
#   对应 DN 分布：NOMChannelIR1 323~992，NOMChannelVIS 0~63
#
# 注意：FY-2 CSV 容器**没有**定标表（reader 里 calibration_tables_present=False），
# 只能出 DN，这里不硬造。

FY2_FILL_VALUES = (65535, 65534)


def fy2_lut(ds, channel: str):
    """取 FY-2 某通道的定标查找表；没有则 None。channel 形如 "IR1"/"VIS"。"""
    import numpy as np

    names = list(getattr(ds, "variables", {}) or {})
    for p in (f"Calibration/CALChannel{channel}", f"CALChannel{channel}",
              f"Calibration/CALChannel{channel.upper()}"):
        if p in names:
            return np.asarray(ds.load(p).data, dtype=np.float64).ravel()
    return None


def fy2_lookup(ds, dn, channel: str, valid_range=None):
    """用 FY-2 的 CALChannelNN 查找表把 DN 换成物理量。

    IR 通道得到亮温 K，VIS 通道得到反射率百分数。
    找不到查找表返回 None（调用方应降级为 DN 并标注）。
    """
    import numpy as np

    lut = fy2_lut(ds, channel)
    if lut is None:
        return None
    d = np.asarray(dn, dtype=np.float64)
    # FY-2 的 DN 有 10bit(IR)/6bit(VIS)，直接用 DN 作下标
    idx = np.clip(d, 0, lut.size - 1)
    out = np.interp(idx, np.arange(lut.size), lut)
    bad = ~np.isfinite(d) | (d > lut.size - 1)
    for f in FY2_FILL_VALUES:
        bad |= d == f
    if valid_range is not None:
        lo, hi = valid_range
        bad |= (d < lo) | (d > hi)
    return np.where(bad, np.nan, out).astype(np.float32)


def fy2_channel_kind(ds, channel: str) -> str:
    """返回 "K"（亮温）或 "%"（反射率百分数），由查找表值域判断。

    实测依据：IR 表 119.6~333.5（K），VIS 表 0~118.4（%）。
    以 150 为界：上限 > 150 且下限 > 50 视为亮温，否则视为百分数。
    """
    import numpy as np

    lut = fy2_lut(ds, channel)
    if lut is None:
        return ""
    lo, hi = float(np.nanmin(lut)), float(np.nanmax(lut))
    return "K" if (hi > 150 and lo > 50) else "%"


# ======================= NOAA AVHRR 可见光定标 =======================
#
# NOAA 1B 的可见光/近红外通道用**两段线性**定标（CH1/CH2）：
#   属性 calibration_groups['operational'] =
#       {slope1, intercept1, slope2, intercept2, crossover_counts}
#   DN <= crossover:  rho = DN*slope1 + intercept1
#   DN >  crossover:  rho = DN*slope2 + intercept2
# 结果单位是百分数（physical_unit = "%"）。
#
# 实测（NOAA-18）：slope1=0.054, intercept1=-2.13, crossover=501,
#                  slope2=0.161, intercept2=-55.37
#
# 热通道（CH3/CH4/CH5）的 1B 系数是 [?, slope, intercept]，文档只写了
# 「斜率 2^-30，截距 2^-22」的缩放却没有给完整公式，**本模块暂不实现**，
# 以免像早期"亮温当辐亮度"那样给出错误物理量。

AVHRR_FILL_VALUES = (65535, 65534, 1023, 1022)


def avhrr_calibration_group(var, which: str = "operational") -> dict | None:
    """从 AVHRR 通道数据集的 calibration_groups 属性里取一段定标系数。"""
    groups = var.attrs.get("calibration_groups")
    if not isinstance(groups, dict):
        return None
    got = groups.get(which) or groups.get("operational")
    return got if isinstance(got, dict) else None


def avhrr_reflectance(var, dn):
    """NOAA AVHRR 可见光/近红外反射率（百分数），两段线性。

    返回 (values, unit)；没有定标系数时返回 (None, "")。
    """
    import numpy as np

    g = avhrr_calibration_group(var)
    if not g or "slope1" not in g:
        return None, ""

    s1, i1 = float(g["slope1"]), float(g["intercept1"])
    s2 = float(g.get("slope2", s1))
    i2 = float(g.get("intercept2", i1))
    xover = float(g.get("crossover_counts", 0))

    d = np.asarray(dn, dtype=np.float64)
    lo_part = d * s1 + i1
    hi_part = d * s2 + i2
    out = np.where(d <= xover, lo_part, hi_part)

    bad = ~np.isfinite(d)
    for f in AVHRR_FILL_VALUES:
        bad |= d == f
    unit = str(var.attrs.get("physical_unit") or "%")
    return np.where(bad, np.nan, out).astype(np.float32), unit
