# -*- coding: utf-8 -*-
"""通道号 → (变量名, 数组索引, 中心波长) 的索引。

为什么需要它
------------
MERSI 的可见光/红外通道被拆到 4 个不同的数据集里，每个数据集都是一个
**多通道堆栈**（band_stack）：

    Data/EV_250_Aggr.1KM_RefSB      band_name = "1,2,3,4"        4 通道
    Data/EV_1KM_RefSB               band_name = "5-19"          15 通道
    Data/EV_1KM_Emissive            band_name = "20,21,22,23"    4 通道
    Data/EV_250_Aggr.1KM_Emissive   band_name = "24,25"          2 通道

用户在 RGB 下拉框里选的是**数据集名**，于是 R/G/B 三行很容易都选到同一个
数据集 —— ``render_rgb`` 收到 bands=(0,0,0)，三次取的是同一层，
合成结果自然是一张灰度图。这就是"通道获取不对、RGB 几乎不可用"的根因。

解决方式：解析每个数据集自带的 ``band_name`` 属性（NSMC 产品规范里的正式
字段，不是猜的），建立「产品通道号 → 数据集/数组下标」的映射，再让
预设组合按产品通道号取数。

波长来自全局属性 ``Effect_Center_WaveLength``（25 个，单位 µm）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BandRef:
    """一个产品通道的定位信息。"""

    band: int                 # 产品通道号（1..25）
    variable: str             # 所在数据集名
    index: int                # 在该数据集里的数组下标
    wavelength: float         # 中心波长（µm），未知为 nan

    @property
    def label(self) -> str:
        return f"b{self.band} ({self.wavelength:.3f} µm)"


def _parse_band_name(raw) -> list[int]:
    """解析 ``band_name`` 属性。

    实测取值有三种写法（都来自真实 FY-3 文件）：
        "1,2,3,4"      逗号分隔
        "20,21,22,23"  逗号分隔
        "5-19"         区间
    以及 "none" / "NANA" 这类非通道数据集。
    """
    if raw is None:
        return []
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", "ignore")
    s = str(raw).strip().strip("'\"")
    if not s or s.lower() in ("none", "nana", "nan", ""):
        return []

    out: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if 1 <= lo <= hi <= 64:
                out.extend(range(lo, hi + 1))
            continue
        if part.isdigit():
            out.append(int(part))
    return out


def _is_band_stack(var) -> bool:
    """数据集是否为 (通道, 行, 列) 的堆栈。"""
    shape = tuple(getattr(var, "shape", ()) or ())
    if len(shape) != 3:
        return False
    # 通道维是「最小的那一维且另两维都像影像」
    h, w = shape[1], shape[2]
    return shape[0] <= 64 and h >= 8 and w >= 8


def band_index(ds) -> dict[int, BandRef]:
    """建立「产品通道号 → BandRef」索引。

    只认带 ``band_name`` 且是三维堆栈的数据集；
    拿不到 band_name 时按数据集的顺序兜底（但不臆造通道号）。
    """
    if ds is None:
        return {}

    waves: list[float] = []
    raw_w = ds.attrs.get("Effect_Center_WaveLength")
    if raw_w is not None:
        try:
            waves = [float(np.ravel(np.asarray(raw_w))[i])
                     for i in range(np.ravel(np.asarray(raw_w)).size)]
        except Exception:                       # noqa: BLE001
            waves = []

    out: dict[int, BandRef] = {}
    for name, var in ds.variables.items():
        if not _is_band_stack(var):
            continue
        bands = _parse_band_name(var.attrs.get("band_name"))
        if not bands:
            continue
        for idx, b in enumerate(bands):
            if idx >= tuple(var.shape)[0]:
                break
            wl = waves[b - 1] if 0 < b <= len(waves) else float("nan")
            out[b] = BandRef(band=b, variable=name, index=idx, wavelength=wl)
    return out


# ---------------- 预设组合的符号名 → 通道号 ----------------

def _closest(bands: dict[int, BandRef], target_um: float,
             lo: int = 1, hi: int = 25) -> int | None:
    """在给定波长范围内找中心波长最接近的通道。"""
    best, best_d = None, float("inf")
    for b, ref in bands.items():
        if not (lo <= b <= hi):
            continue
        if not np.isfinite(ref.wavelength):
            continue
        d = abs(ref.wavelength - target_um)
        if d < best_d:
            best, best_d = b, d
    return best


def resolve_symbol(ds, symbol: str) -> BandRef | None:
    """把 ``b3`` / ``vis`` / ``ir`` / ``b24`` 这类符号解析成具体通道。

    解析优先用实测波长，其次用符号里写明的通道号，最后才退回常见约定。
    这样换一颗卫星（FY-3C/D/F/H）也不用改代码。
    """
    bands = band_index(ds)
    if not bands:
        return None

    s = str(symbol).strip().lower()

    # b12 形式：直接给通道号
    m = re.fullmatch(r"b(\d{1,2})", s)
    if m:
        n = int(m.group(1))
        return bands.get(n)

    # 语义名：按波长挑（数值来自各通道标称中心波长）
    if s == "vis":          # 可见光里最长波的那个（红端，真彩色 R）
        b = _closest(bands, 0.65, 1, 19)
        return bands.get(b) if b else None
    if s == "green":
        b = _closest(bands, 0.55, 1, 19)
        return bands.get(b) if b else None
    if s == "blue":
        b = _closest(bands, 0.47, 1, 19)
        return bands.get(b) if b else None
    if s == "nir":          # 近红外 0.865 µm
        b = _closest(bands, 0.865, 1, 19)
        return bands.get(b) if b else None
    if s == "ir":           # 10.8 µm 窗区
        b = _closest(bands, 10.8, 20, 25)
        return bands.get(b) if b else None
    if s == "ir_short":     # 3.7 µm 短波红外（火点）
        b = _closest(bands, 3.7, 20, 25)
        return bands.get(b) if b else None
    if s == "wv":           # 6.2~7.3 µm 水汽
        b = _closest(bands, 7.2, 20, 25)
        return bands.get(b) if b else None
    return None


@dataclass(frozen=True)
class RgbPlan:
    """一个可执行的 RGB 合成方案。"""

    key: str
    label: str
    desc: str
    names: tuple[str, str, str]
    bands: tuple[int, int, int]
    refs: tuple[BandRef, BandRef, BandRef]

    def summary(self) -> str:
        return "  ".join(
            f"{ch}={r.label}" for ch, r in zip("RGB", self.refs))


def resolve_preset(ds, key: str) -> RgbPlan | None:
    """把 ``render.PRESETS`` 里的符号组合解析成可执行的变量+通道。

    解析不出来（缺通道 / 需要波段差值运算）时返回 None，
    调用方应当把该预设**置灰**而不是假装可用。
    """
    from ..render import PRESETS

    p = PRESETS.get(key)
    if not p:
        return None
    symbols = p.get("bands") or ()
    if len(symbols) != 3:
        return None

    refs = [resolve_symbol(ds, s) for s in symbols]
    if any(r is None for r in refs):
        return None
    return RgbPlan(
        key=key,
        label=p["label"],
        desc=p.get("desc", ""),
        names=tuple(r.variable for r in refs),      # type: ignore[arg-type]
        bands=tuple(r.index for r in refs),        # type: ignore[arg-type]
        refs=tuple(refs),                          # type: ignore[arg-type]
    )


def available_presets(ds) -> list[RgbPlan]:
    """当前数据集上**真正可执行**的预设组合。"""
    from ..render import PRESETS

    out = []
    for key in PRESETS:
        plan = resolve_preset(ds, key)
        if plan is not None:
            out.append(plan)
    return out


def bands_of(ds, variable: str) -> int:
    """某个数据集有几个通道（非堆栈返回 1）。"""
    var = ds.variables.get(variable)
    if var is None:
        return 1
    if not _is_band_stack(var):
        return 1
    return int(tuple(var.shape)[0])


def band_labels(ds, variable: str) -> list[str]:
    """某数据集的通道下拉标签，例如 ``b3 (0.650 µm)``。

    拿不到 band_name 时退回 ``通道 1/2/3...``，不臆造波段号。
    """
    var = ds.variables.get(variable)
    if var is None:
        return []
    n = bands_of(ds, variable)
    nums = _parse_band_name(var.attrs.get("band_name"))
    waves: list[float] = []
    raw_w = ds.attrs.get("Effect_Center_WaveLength")
    if raw_w is not None:
        arr = np.ravel(np.asarray(raw_w))
        waves = [float(arr[b - 1]) for b in nums if 0 < b <= arr.size]

    labels = []
    for i in range(n):
        if i < len(nums):
            wl = waves[i] if i < len(waves) else float("nan")
            labels.append(f"b{nums[i]} ({wl:.3f} µm)" if np.isfinite(wl)
                          else f"b{nums[i]}")
        else:
            labels.append(f"通道 {i + 1}")
    return labels
