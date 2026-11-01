"""导出：只提供三种形式。

1. ``tiff``            — 全画质无损 TIFF，保留原始位深（uint16/float32），多波段原样写出
2. ``png_full``        — 全画质 PNG，16 位无损、原始分辨率
3. ``png_compressed``  — PNG，压缩强度可调（0-9），可选缩放，用于出图/分享

注意：PNG 本身是无损格式，"压缩强度"只影响编码耗时与文件体积，不损失画质；
若要减小体积又不想缩放，请调 compress_level。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

import numpy as np

ExportKind = Literal["tiff", "png_full", "png_compressed"]

KINDS: dict[str, dict] = {
    "tiff": {
        "label": "TIFF（全画质无损）",
        "desc": "保留原始位深与波段数，可选 LZW/Deflate 无损压缩；适合存档与再分析",
        "ext": ".tif",
        "lossless": True,
        "scale": False,
        "compress": "deflate",  # 无损
    },
    "png_full": {
        "label": "PNG（全画质）",
        "desc": "原始分辨率、16 位灰度或 8 位彩色，无损；适合精确比对",
        "ext": ".png",
        "lossless": True,
        "scale": False,
        "compress": 6,
    },
    "png_compressed": {
        "label": "PNG（压缩强度可调）",
        "desc": "同 PNG 无损，但可调压缩强度 0-9 与缩放比例，便于分享",
        "ext": ".png",
        "lossless": True,
        "scale": True,
        "compress": (0, 9),
    },
}


@dataclass
class ExportOptions:
    kind: ExportKind = "png_full"
    path: Path | str = ""
    # 显示映射（仅当输入是 DN / 浮点时使用）
    stretch: tuple[float, float] | None = (2.0, 98.0)
    vmin: float | None = None
    vmax: float | None = None
    gamma: float = 1.0
    cmap: str | None = None          # None = 灰度
    fill: tuple[int, int, int] = (0, 0, 0)
    # 输出控制
    compress_level: int = 6          # 仅 png_compressed
    scale: float = 1.0               # 仅 png_compressed 生效
    deflate: bool = True             # 仅 tiff：无损压缩
    bigtiff: bool = False
    provenance: dict[str, str] | None = None   # 溯源元数据（默认自动生成）

    def resolved_path(self) -> Path:
        p = Path(self.path)
        want = KINDS[self.kind]["ext"]
        if p.suffix.lower() not in (".tif", ".tiff", ".png"):
            p = p.with_suffix(want)
        return p


def _to_uint16(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
    v = np.nan_to_num(values, nan=lo)
    v = np.clip(v, lo, hi)
    if hi <= lo:
        return np.zeros(values.shape, dtype=np.uint16)
    return ((v - lo) / (hi - lo) * 65535.0 + 0.5).astype(np.uint16)


def _to_uint8(values: np.ndarray, lo: float, hi: float, gamma: float = 1.0) -> np.ndarray:
    v = np.nan_to_num(values, nan=lo)
    v = np.clip(v, lo, hi)
    if hi <= lo:
        return np.zeros(values.shape, dtype=np.uint8)
    out = (v - lo) / (hi - lo)
    if gamma and gamma != 1.0:
        out = np.power(out, 1.0 / gamma)
    return (out * 255.0 + 0.5).astype(np.uint8)


def _percentile_range(data: np.ndarray, pct: tuple[float, float]) -> tuple[float, float]:
    valid = data[np.isfinite(data)]
    if valid.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(valid, pct)
    lo, hi = float(lo), float(hi)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo, hi = float(np.min(valid)), float(np.max(valid))
        if hi <= lo:                     # 常量场：人为撑开一点，避免整幅变黑
            d = max(abs(lo) * 1e-3, 0.5)
            lo, hi = lo - d, hi + d
    return lo, hi


def _apply_cmap(gray8: np.ndarray, cmap: str) -> np.ndarray:
    import matplotlib

    cm = matplotlib.colormaps[cmap]
    rgba = (cm(gray8.astype(np.float32) / 255.0) * 255).astype(np.uint8)
    return rgba[..., :3]


def _is_u16(arr: np.ndarray) -> bool:
    """判断是否为 16 位无符号整数，**忽略字节序**。

    HDF5/NetCDF 里常见大端 dtype（'>u2'），直接用 arr.dtype == np.uint16 会判 False，
    导致数组被当成浮点重新拉伸、字节序也被误解释。
    """
    return arr.dtype.kind == "u" and arr.dtype.itemsize == 2


def _native(arr: np.ndarray) -> np.ndarray:
    """转成本机字节序的视图/副本，保留位深。"""
    if arr.dtype.isnative:
        return arr
    return arr.astype(arr.dtype.newbyteorder("="))


def prepare_array(data: np.ndarray, opts: ExportOptions, kind: ExportKind) -> tuple[np.ndarray, str]:
    """把物理量/ DN 转成要写出的数组。

    返回 (array, mode)：
      mode = "I;16" 16 位灰度 | "F" 浮点 | "RGB" 彩色 | "L" 8 位灰度
    """
    arr = np.asarray(data)
    is_rgb = arr.ndim == 3 and arr.shape[-1] in (3, 4)

    if kind == "tiff":
        # 全画质：能保留原位深就保留（大端也保留，TIFF 支持 >u2）
        if is_rgb:
            return arr, "RGB"
        if _is_u16(arr):
            return _native(arr), "I;16"
        if arr.dtype in (np.float32, np.float64):
            return arr.astype(np.float32), "F"
        if arr.dtype == np.uint8:
            return arr, "L"
        return _to_uint16(arr.astype(np.float32), *_range_of(arr, opts)), "I;16"

    if kind == "png_full":
        # 16 位无损（彩色则原样传递；PIL 不支持 16 位 RGB PNG，见 _write_png）
        if is_rgb:
            if arr.dtype in (np.uint8, np.uint16) or _is_u16(arr):
                return _native(arr), "RGB"
            return _to_uint16(arr.astype(np.float32), *_range_of(arr, opts)), "RGB"
        if _is_u16(arr):
            return _native(arr), "I;16"
        return _to_uint16(arr.astype(np.float32), *_range_of(arr, opts)), "I;16"

    # png_compressed：8 位彩色，便于分享
    lo, hi = _range_of(arr, opts)
    if is_rgb:
        base = arr if arr.dtype == np.uint8 else _to_uint8(arr.astype(np.float32), lo, hi, opts.gamma)
        return base, "RGB"
    gray8 = _to_uint8(arr.astype(np.float32), lo, hi, opts.gamma)
    if opts.cmap:
        return _apply_cmap(gray8, opts.cmap), "RGB"
    return gray8, "L"


def _range_of(arr: np.ndarray, opts: ExportOptions) -> tuple[float, float]:
    if opts.vmin is not None and opts.vmax is not None:
        return float(opts.vmin), float(opts.vmax)
    if opts.stretch:
        return _percentile_range(arr.astype(np.float32, copy=False), opts.stretch)
    return float(np.nanmin(arr)), float(np.nanmax(arr))


def _resize(arr: np.ndarray, scale: float) -> np.ndarray:
    if scale >= 0.999:
        return arr
    from PIL import Image

    h, w = arr.shape[:2]
    size = (max(1, int(w * scale)), max(1, int(h * scale)))

    # PIL 只接受整型数组；浮点（physical() 之后常见）会抛
    # TypeError: Cannot handle this data type: (1, 1, N), |u1
    a = arr
    if a.dtype.kind == "f":
        lo, hi = float(np.nanmin(a)), float(np.nanmax(a))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            lo, hi = 0.0, lo + 1.0
        a = _to_uint16(a, lo, hi)
    elif a.dtype.kind in ("i", "u") and a.dtype.itemsize > 2:
        lo, hi = float(a.min()), float(a.max())
        a = _to_uint16(a.astype(np.float32), lo, hi if hi > lo else lo + 1)

    return np.asarray(Image.fromarray(a).resize(size, Image.LANCZOS))


def export(data: np.ndarray, opts: ExportOptions) -> Path:
    """按三种形式之一写出文件，返回实际路径。"""
    if opts.kind not in KINDS:
        raise ValueError(f"未知导出类型: {opts.kind}，可选 {list(KINDS)}")
    kind = opts.kind
    path = opts.resolved_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    arr, mode = prepare_array(data, opts, kind)

    if kind == "png_compressed":
        arr = _resize(arr, opts.scale)

    prov = opts.provenance
    if prov is None:
        from .provenance import build_provenance

        prov = build_provenance()

    if kind == "tiff":
        _write_tiff(arr, mode, path, deflate=opts.deflate, bigtiff=opts.bigtiff, prov=prov)
    else:
        level = opts.compress_level if kind == "png_compressed" else KINDS["png_full"]["compress"]
        level = int(np.clip(level, 0, 9))
        _write_png(arr, mode, path, level, prov=prov)

    return path


def _write_tiff(arr: np.ndarray, mode: str, path: Path, deflate: bool = True,
                bigtiff: bool = False, prov: dict[str, str] | None = None) -> None:
    """写 TIFF。溯源信息写进 ImageDescription（tifffile 用 description 参数）。"""
    import tifffile

    from .provenance import as_text

    compression = "deflate" if deflate else None
    kwargs: dict = {"compression": compression, "bigtiff": bigtiff, "metadata": None}
    if prov:
        kwargs["description"] = as_text(prov)
    if arr.dtype.kind == "f":
        kwargs["photometric"] = "minisblack" if arr.ndim == 2 else "rgb"
    elif arr.ndim == 3 and arr.shape[-1] in (3, 4):
        kwargs["photometric"] = "rgb"
    else:
        kwargs["photometric"] = "minisblack"
    tifffile.imwrite(str(path), arr, **kwargs)


def _write_png(arr: np.ndarray, mode: str, path: Path, level: int,
               prov: dict[str, str] | None = None) -> None:
    from PIL import Image

    from .provenance import as_png_text

    if mode == "RGB":
        if arr.dtype == np.uint16:       # PIL 不支持 16 位 RGB PNG，降为 8 位
            arr = (arr.astype(np.float32) / 257.0 + 0.5).astype(np.uint8)
        else:
            arr = arr.astype(np.uint8)
        im = Image.fromarray(arr, mode="RGB")
    elif mode == "L":
        im = Image.fromarray(arr.astype(np.uint8), mode="L")
    elif mode == "F":                    # PNG 不支持浮点，退化为 16 位
        lo, hi = float(np.nanmin(arr)), float(np.nanmax(arr))
        im = Image.fromarray(_to_uint16(arr, lo, hi))
    else:                                # I;16
        im = Image.fromarray(arr.astype(np.uint16))
    pnginfo = None
    if prov:
        from PIL import PngImagePlugin

        pnginfo = PngImagePlugin.PngInfo()
        for k, v in as_png_text(prov).items():
            pnginfo.add_text(k, v)
    im.save(str(path), format="PNG", compress_level=level, optimize=False, pnginfo=pnginfo)


def describe_kinds() -> str:
    lines = ["可用导出形式："]
    for k, v in KINDS.items():
        lines.append(f"  {k:15s} {v['label']}　{v['desc']}")
    return "\n".join(lines)
