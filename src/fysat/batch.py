"""批量解码：目录 → 扫描 → 按产品定义匹配 → 解码 → 导出。

设计要点
--------
1. **错误隔离**：单个文件失败（读不了、产品定义不匹配、解码报错）只记进结果，
   不中断整批。批量跑几百个文件时这点是刚需。
2. **进度回调**：``progress(done, total, path)`` 每处理完一个文件调一次，
   GUI 可以直接接到进度条上。
3. **可干跑**：``dry_run=True`` 只扫描+匹配，不读数据不写文件，用于先看清单。
4. **不重复造导出**：写文件一律走 ``export.export()`` 的三种形式（tiff /
   png_full / png_compressed），与单文件导出行为完全一致。
5. **跳过而非报错**：廓线产品（如 GNOSO）没有二维影像，属正常跳过；
   定义未覆盖的文件也跳过并给出原因。

输出命名
--------
默认 ``<输出目录>/<产品名>/<源文件stem>_<字段名>[_b<通道>].<ext>``。
同目录同名冲突时加序号，不覆盖已有文件。
"""
from __future__ import annotations

import fnmatch
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from .export import KINDS, ExportOptions, export
from .products import ProductRegistry, decode
from .products.decode import DecodeResult
from .readers import open_file

# 目录扫描默认跳过的文件
DEFAULT_IGNORE = ("*.enp", "Thumbs.db", "*.tmp", "*.part", "*.crdownload")
# 默认可识别的容器后缀
DEFAULT_PATTERNS = ("*.HDF", "*.hdf", "*.H5", "*.h5", "*.NC", "*.nc", "*.DAT", "*.dat")

ProgressFn = Callable[[int, int, Path], None]


@dataclass
class FileResult:
    """单个文件的处理结果。"""

    path: Path
    status: str = "ok"              # ok | skipped | failed
    product: str = ""
    reason: str = ""
    outputs: list[Path] = field(default_factory=list)
    n_fields: int = 0
    n_images: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    bytes_written: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": str(self.path),
            "name": self.path.name,
            "status": self.status,
            "product": self.product,
            "reason": self.reason,
            "n_fields": self.n_fields,
            "n_images": self.n_images,
            "outputs": [str(p) for p in self.outputs],
            "bytes_written": self.bytes_written,
            "warnings": list(self.warnings),
            "error": self.error,
        }


@dataclass
class BatchResult:
    """整批处理结果。"""

    files: list[FileResult] = field(default_factory=list)
    out_dir: Path | None = None
    kind: str = "png_full"

    # -- 统计 ------------------------------------------------------

    @property
    def n_total(self) -> int:
        return len(self.files)

    @property
    def n_ok(self) -> int:
        return sum(1 for f in self.files if f.status == "ok")

    @property
    def n_skipped(self) -> int:
        return sum(1 for f in self.files if f.status == "skipped")

    @property
    def n_failed(self) -> int:
        return sum(1 for f in self.files if f.status == "failed")

    @property
    def n_outputs(self) -> int:
        return sum(len(f.outputs) for f in self.files)

    @property
    def total_bytes(self) -> int:
        return sum(f.bytes_written for f in self.files)

    def by_product(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.files:
            if f.status == "ok" and f.product:
                out[f.product] = out.get(f.product, 0) + 1
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "out_dir": str(self.out_dir) if self.out_dir else "",
            "kind": self.kind,
            "total": self.n_total,
            "ok": self.n_ok,
            "skipped": self.n_skipped,
            "failed": self.n_failed,
            "outputs": self.n_outputs,
            "bytes": self.total_bytes,
            "mb": round(self.total_bytes / 1e6, 3),
            "by_product": self.by_product(),
        }

    def report_lines(self) -> list[str]:
        s = self.summary()
        lines = [
            f"共 {s['total']} 个文件：成功 {s['ok']}，跳过 {s['skipped']}，失败 {s['failed']}",
            f"输出 {s['outputs']} 个文件，合计 {s['mb']:.2f} MB → {s['out_dir']}",
        ]
        for name, n in sorted(s["by_product"].items()):
            lines.append(f"  {name:32s} {n} 个")
        for f in self.files:
            if f.status == "failed":
                lines.append(f"  失败 {f.path.name}: {f.error}")
            elif f.status == "skipped":
                lines.append(f"  跳过 {f.path.name}: {f.reason}")
        return lines


# ---------------------------------------------------------------- 扫描

def scan(directory: str | Path, *,
         patterns: Sequence[str] = DEFAULT_PATTERNS,
         recursive: bool = True,
         ignore: Sequence[str] = DEFAULT_IGNORE) -> list[Path]:
    """扫描目录下可能的卫星数据文件（按后缀模式，跳过临时文件）。"""
    root = Path(directory)
    if not root.exists():
        raise FileNotFoundError(f"目录不存在: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"不是目录: {root}")

    found: set[Path] = set()
    for pat in patterns:
        it = root.rglob(pat) if recursive else root.glob(pat)
        found.update(p for p in it if p.is_file())

    out = []
    for p in sorted(found):
        name = p.name
        if any(fnmatch.fnmatchcase(name, g) for g in ignore):
            continue
        if p.stat().st_size == 0:
            continue
        out.append(p)
    return out


# ---------------------------------------------------------------- 输出路径

def _safe(name: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_.+") else "_" for c in name)


def _target_path(out_dir: Path, product: str, src: Path, field_name: str,
                 band: int | None, kind: str) -> Path:
    """生成不冲突的输出路径。"""
    ext = KINDS[kind]["ext"]
    sub = out_dir / _safe(product)
    stem = _safe(src.stem) + "_" + _safe(field_name)
    if band is not None:
        stem += f"_b{band + 1:02d}"
    return sub / f"{stem}{ext}"


def _unique(path: Path) -> Path:
    """已存在则加序号，绝不覆盖。"""
    if not path.exists():
        return path
    stem, suf, parent = path.stem, path.suffix, path.parent
    for i in range(1, 1000):
        cand = parent / f"{stem}_{i}{suf}"
        if not cand.exists():
            return cand
    return parent / f"{stem}_{path.stat().st_mtime_ns}{suf}"


def _to_export_array(arr: np.ndarray, physical: bool) -> tuple[np.ndarray, dict]:
    """把解出的浮点物理量转成 export 能处理的数据，并给出合适的显示映射。

    ``export.prepare_array`` 对 **float32 数组**会走 ``_to_uint16`` 分支，
    用 ``ExportOptions.stretch``（默认 2/98 百分位）做线性拉伸——
    这对亮温/反射率是正确的显示方式。这里要做的就是：
      * 保持 float32（不要让 NaN 变成黑）；
      * 给一个基于物理量级的固定拉伸，避免每幅图各自拉伸导致不可比。
    """
    if not physical:
        return arr, {"stretch": None}
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return arr, {"stretch": None}
    lo = float(np.percentile(finite, 2))
    hi = float(np.percentile(finite, 98))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo, hi = float(np.min(finite)), float(np.max(finite))
    return arr, {"vmin": lo, "vmax": hi if hi > lo else lo + 1.0}


# ---------------------------------------------------------------- 单文件

def process_file(path: Path, *, out_dir: Path, kind: str,
                 registry: ProductRegistry,
                 fields: Sequence[str] | None = None,
                 max_bands: int | None = None,
                 physical: bool = True,
                 export_options: dict[str, Any] | None = None) -> FileResult:
    """处理单个文件：匹配产品 → 解码 → 导出每个可成图的字段/通道。"""
    res = FileResult(path=path)

    try:
        ds = open_file(path, load=False)
    except NotImplementedError as exc:
        res.status, res.reason = "skipped", f"容器不支持: {exc}"
        return res
    except Exception as exc:                        # noqa: BLE001
        res.status = "failed"
        res.error = f"打开失败 {type(exc).__name__}: {exc}"
        return res

    pdef = registry.match(path, container=getattr(ds, "reader", None), attrs=ds.attrs)
    if pdef is None:
        res.status = "skipped"
        res.reason = "没有匹配的产品定义"
        return res
    res.product = pdef.product

    try:
        decoded: DecodeResult = decode(ds, pdef, fields=list(fields) if fields else None)
    except Exception as exc:                        # noqa: BLE001
        res.status = "failed"
        res.error = f"解码失败 {type(exc).__name__}: {exc}"
        res.reason = traceback.format_exc(limit=2)
        return res

    res.n_fields = len(decoded.fields)
    for df in decoded.fields.values():
        res.warnings.extend(f"{df.name}: {w}" for w in df.warnings)

    if not decoded.ok:
        res.status = "skipped"
        res.reason = (
            "没有任何字段可解码"
            + (f"（缺 {len(decoded.missing)} 个，失败 {len(decoded.failed)} 个）"
               if (decoded.missing or decoded.failed) else "")
        )
        return res

    # 只导出能成图的二维字段
    image_fields = [f for f in decoded.fields.values()
                    if f.data.ndim >= 2 and f.kind in ("thermal", "reflective", "dn", "flag")]
    if not image_fields:
        res.status = "skipped"
        res.reason = "字段都是一维/辅助数据，无法成图（如掩星廓线产品）"
        return res

    opts_base = dict(export_options or {})
    for df in image_fields:
        n_planes = df.data.shape[0] if df.data.ndim == 3 else 1
        if max_bands is not None:
            n_planes = min(n_planes, max_bands)
        for i in range(n_planes):
            arr = df.band(i) if df.data.ndim == 3 else df.data
            band_tag = i if df.data.ndim == 3 else None
            target = _unique(_target_path(out_dir, pdef.product, path, df.name,
                                          band_tag, kind))
            data, mapping = _to_export_array(np.asarray(arr, dtype=np.float32), physical)
            # 调用方显式给的 export_options 优先于自动映射
            kwargs = {**mapping, **opts_base}
            per = ExportOptions(kind=kind, path=target, **kwargs)
            try:
                written = export(data, per)
            except Exception as exc:                # noqa: BLE001
                res.warnings.append(f"{df.name} b{i + 1} 导出失败: {exc}")
                continue
            res.outputs.append(written)
            res.bytes_written += written.stat().st_size
            res.n_images += 1

    if res.outputs:
        res.status = "ok"
    else:
        res.status = "skipped"
        res.reason = "匹配到产品但没有成功导出任何影像"
    return res


# ---------------------------------------------------------------- 整批

def run(directory: str | Path, *, out_dir: str | Path,
        kind: str = "png_full",
        registry: ProductRegistry | None = None,
        patterns: Sequence[str] = DEFAULT_PATTERNS,
        recursive: bool = True,
        fields: Sequence[str] | None = None,
        max_bands: int | None = None,
        limit: int | None = None,
        dry_run: bool = False,
        physical: bool = True,
        progress: ProgressFn | None = None,
        export_options: dict[str, Any] | None = None,
        on_file: Callable[[FileResult], None] | None = None) -> BatchResult:
    """批量解码一个目录。

    参数
    ----
    directory   : 输入目录
    out_dir     : 输出目录（按产品名分子目录）
    kind        : tiff / png_full / png_compressed（见 export.KINDS）
    registry    : 产品定义库；默认加载内置 products/*.yml
    limit       : 只处理前 N 个文件（调试用）
    dry_run     : 只扫描+匹配，不解码不写文件
    progress    : ``progress(done, total, path)`` 进度回调
    on_file     : 每个文件处理完后的回调（GUI 可用来刷日志）

    返回 :class:`BatchResult`，含每个文件的状态与总统计。
    """
    if kind not in KINDS:
        raise ValueError(f"未知导出类型 {kind!r}，可选 {list(KINDS)}")

    reg = registry if registry is not None else ProductRegistry.from_dir()
    files = scan(directory, patterns=patterns, recursive=recursive)
    if limit is not None:
        files = files[:limit]

    result = BatchResult(out_dir=Path(out_dir), kind=kind)
    total = len(files)

    for i, path in enumerate(files, start=1):
        if dry_run:
            fr = _dry_run_one(path, reg)
        else:
            fr = process_file(path, out_dir=Path(out_dir), kind=kind, registry=reg,
                              fields=fields, max_bands=max_bands, physical=physical,
                              export_options=export_options)
        result.files.append(fr)
        if on_file is not None:
            try:
                on_file(fr)
            except Exception:                        # noqa: BLE001
                pass                                 # 回调出错不影响批处理
        if progress is not None:
            try:
                progress(i, total, path)
            except Exception:                        # noqa: BLE001
                pass
    return result


def _dry_run_one(path: Path, registry: ProductRegistry) -> FileResult:
    """干跑：只做容器识别与产品匹配。"""
    from .detect import sniff

    res = FileResult(path=path)
    try:
        container = sniff(path)
    except OSError as exc:
        res.status, res.error = "failed", f"无法识别容器: {exc}"
        return res
    pdef = registry.match(path, container=container)
    if pdef is None:
        res.status, res.reason = "skipped", f"没有匹配的产品定义（容器 {container}）"
        return res
    res.product = pdef.product
    res.status = "ok"
    res.reason = "干跑：仅匹配，未解码"
    return res


def preview(directory: str | Path, *,
            registry: ProductRegistry | None = None,
            patterns: Sequence[str] = DEFAULT_PATTERNS) -> list[dict[str, Any]]:
    """预览目录里每个文件会匹配到哪个产品（不读数据）。"""
    reg = registry if registry is not None else ProductRegistry.from_dir()
    return [r.to_dict() for r in
            (_dry_run_one(p, reg) for p in scan(directory, patterns=patterns))]


__all__ = [
    "DEFAULT_IGNORE",
    "DEFAULT_PATTERNS",
    "BatchResult",
    "FileResult",
    "process_file",
    "preview",
    "run",
    "scan",
]
