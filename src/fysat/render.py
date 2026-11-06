"""显示渲染：拉伸、上色、RGB 合成。纯数组运算，不依赖 Qt。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Stretch:
    """拉伸参数。method: percentile | minmax | fixed"""

    method: str = "percentile"
    pct: tuple[float, float] = (2.0, 98.0)
    vmin: float | None = None
    vmax: float | None = None
    gamma: float = 1.0

    def bounds(self, data: np.ndarray) -> tuple[float, float]:
        if self.method == "fixed" and self.vmin is not None and self.vmax is not None:
            return float(self.vmin), float(self.vmax)
        valid = data[np.isfinite(data)]
        if valid.size == 0:
            return 0.0, 1.0
        if self.method == "minmax":
            lo, hi = float(np.min(valid)), float(np.max(valid))
        else:
            lo, hi = (float(v) for v in np.percentile(valid, self.pct))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            lo, hi = float(np.min(valid)), float(np.max(valid))
            if hi <= lo:
                d = max(abs(lo) * 1e-3, 0.5)
                lo, hi = lo - d, hi + d
        return lo, hi


def display_array(var, physical: bool = True) -> np.ndarray:
    """把 Variable 转成适合显示的 float32 数组：应用定标 + 把填充/越界置 NaN。

    拉伸区间与直方图都应基于这个数组算，否则 65535 之类的填充值会把整幅图压黑。
    """
    if physical and (var.scale_factor is not None or var.add_offset is not None):
        arr = var.physical()
    else:
        arr = np.ascontiguousarray(var.data, dtype=np.float32)
    bad = var.mask()
    if bad.any():
        arr = np.where(bad, np.float32("nan"), arr)
    return arr


def _band_axis(shape: tuple[int, ...]) -> int | None:
    """判断三维数组里哪一维是通道。

    规则：通道维通常是最小的那一维，且另外两维明显更大。
    不能只看"第 0 维小"——测试里 (3,10,12) 这种小图也应是通道栈。
    """
    if len(shape) != 3:
        return None
    cand = min(range(3), key=lambda i: shape[i])   # 最小的维
    others = [shape[i] for i in range(3) if i != cand]
    # 另外两维要"像是个二维影像"（明显大于通道维），且不小于 4x4
    if min(others) >= 4 and shape[cand] < min(others):
        return cand
    return None


def band_of(var, index: int = 0) -> np.ndarray:
    """从可能带通道维的变量里取出指定通道的数组。

    FY-3 MERSI 的 EV_1KM_RefSB 是 (15, 2000, 2048)：第 0 维是通道，
    直接当图像画会把 15 个通道竖着拼成"横条"。这里按 _band_axis 判断并取第 index 个通道。
    """
    arr = np.asarray(var.data)
    ax = _band_axis(arr.shape)
    if ax is None:
        return arr
    return np.take(arr, min(index, arr.shape[ax] - 1), axis=ax)


def n_bands(var) -> int:
    """变量的通道数（无通道维返回 1）。"""
    shape = tuple(var.shape if var.source_shape else np.shape(var.data))
    ax = _band_axis(shape)
    return int(shape[ax]) if ax is not None else 1


def display_band(var, index: int = 0, physical: bool = True) -> np.ndarray:
    """取指定通道并应用定标 + 无效值掩膜，返回二维 float32。"""
    raw = band_of(var, index)
    out = np.ascontiguousarray(raw, dtype=np.float32)

    if physical:
        if var.scale_factor is not None:
            out = out * np.float32(var.scale_factor)
        if var.add_offset is not None:
            out = out + np.float32(var.add_offset)

    bad = np.zeros(out.shape, dtype=bool)
    if var.fill_value is not None:
        bad |= raw == var.fill_value
    if var.valid_range is not None:
        lo, hi = var.valid_range
        bad |= (raw < lo) | (raw > hi)
    if bad.any():
        out = np.where(bad, np.float32("nan"), out)
    return out


def stretch(data: np.ndarray, st: Stretch | None = None,
            nan_value: float | None = None) -> np.ndarray:
    """把任意量纲的数据拉到 0..1。

    nan_value=None（默认）时**保留 NaN**，让上层决定无效像元怎么画；
    早期实现用 nan_to_num(nan=lo) 把无效值变成实色，
    结果卫星数据里大片的填充区在 RGB 合成时变成紫色斑块。

    nan_value 给数字时按该值填充（0 表示无效像元画黑）。
    """
    st = st or Stretch()
    src = np.asarray(data, dtype=np.float32)
    lo, hi = st.bounds(src)

    if hi <= lo:
        out = np.zeros_like(src)
    else:
        v = np.clip(src, lo, hi)
        out = (v - lo) / (hi - lo)

    if st.gamma and st.gamma != 1.0:
        out = np.power(np.clip(out, 0.0, 1.0), 1.0 / st.gamma)

    if nan_value is not None:
        out = np.where(np.isfinite(src), out, np.float32(nan_value))
    return out.astype(np.float32, copy=False)


def apply_cmap(gray01: np.ndarray, cmap: str = "gray") -> np.ndarray:
    """0..1 灰度 → uint8 RGB。"""
    import matplotlib

    cm = matplotlib.colormaps[cmap]
    rgba = cm(np.asarray(gray01, dtype=np.float32))
    return (rgba[..., :3] * 255.0 + 0.5).astype(np.uint8)


def composite(r: np.ndarray, g: np.ndarray, b: np.ndarray,
              st: Stretch | None = None,
              weights: tuple[float, float, float] = (1.0, 1.0, 1.0),
              shared_range: bool = True) -> np.ndarray:
    """三通道合成 uint8 RGB。

    shared_range=True（默认）时三个通道用**同一个**拉伸区间，
    这是真彩色的前提：若各通道独立拉伸，通道间的相对比例被抹掉，
    白云会偏色（常见是整幅发黄绿）。
    shared_range=False 时各通道独立拉伸，适合强调单通道细节的假彩色。
    """
    st = st or Stretch()
    chans_in = (r, g, b)

    if shared_range:
        # 用三通道合并后的分位数作为统一区间
        pooled = np.concatenate([
            np.asarray(c, dtype=np.float32)[np.isfinite(c)].ravel()[::max(1, np.size(c)//200_000)]
            for c in chans_in
        ])
        if pooled.size:
            lo, hi = st.bounds(pooled.reshape(-1, 1))
            unified = Stretch(method="fixed", vmin=lo, vmax=hi, gamma=st.gamma)
        else:
            unified = st
        chans = [np.clip(stretch(arr, unified) * float(w), 0.0, 1.0)
                 for arr, w in zip(chans_in, weights, strict=False)]
    else:
        chans = [np.clip(stretch(arr, st) * float(w), 0.0, 1.0)
                 for arr, w in zip(chans_in, weights, strict=False)]

    rgb = np.dstack(chans)
    return (rgb * 255.0 + 0.5).astype(np.uint8)


def rgb_bands(ds, names: tuple[str, str, str], physical: bool = True) -> np.ndarray:
    """从 SatDataset 取三个变量合成 RGB（名称需完全匹配或唯一后缀匹配）。"""
    arrs = []
    for name in names:
        v = ds.variables.get(name) or _match(ds, name)
        if v is None:
            raise KeyError(f"找不到通道 {name}；可用: {list(ds.variables)[:10]}")
        if v.data.size == 0:
            v = ds.load(v.name)
        arrs.append(display_array(v, physical=physical))
    return composite(*arrs)


def _match(ds, name: str):
    """宽松匹配：忽略大小写与路径，允许唯一后缀。"""
    low = name.lower().lstrip("/")
    for k, v in ds.variables.items():
        if k.lower().lstrip("/").endswith(low) or k.lower() == low:
            return v
    return None


# 内置配色（供 GUI 下拉框使用）
COLORMAPS = [
    "gray", "turbo", "inferno", "magma", "plasma", "viridis", "jet",
    "RdYlBu_r", "coolwarm", "terrain", "ocean", "afmhot", "gist_earth",
]

# 常见 RGB 配方（通道名按产品定义替换；此处给通名，后续由产品 YAML 落地）
PRESETS = {
    "true_color": {"label": "真彩色", "bands": ("b3", "b2", "b1"),
                   "desc": "R=0.65µm G=0.55µm B=0.47µm"},
    "sandwich": {"label": "三明治", "bands": ("vis", "ir", "ir"),
                 "desc": "R=可见光 G/B=红外，兼顾云顶纹理与地表"},
    "day_night": {"label": "昼夜微光", "bands": ("ir", "vis", "vis"),
                  "desc": "夜间用红外补可见光"},
    "fire": {"label": "火点", "bands": ("ir_short", "nir", "ir"),
             "desc": "R=3.7µm G=0.87µm B=11µm"},
    "dust": {"label": "沙尘", "bands": ("ir_split", "b2", "ir"),
             "desc": "R=11-12µm 差值 G=0.87µm B=11µm"},
    "convection": {"label": "对流", "bands": ("wv_ir", "ir", "vis"),
                   "desc": "R=6.2-10.8 差值 G=10.8 B=可见光"},
}


def describe_presets() -> str:
    lines = ["内置 RGB 组合："]
    for k, v in PRESETS.items():
        lines.append(f"  {k:12s} {v['label']:6s} {v['desc']}")
    return "\n".join(lines)
