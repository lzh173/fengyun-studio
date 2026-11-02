"""命令行入口：info / ls / export / formats。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import __version__
from .detect import parse_name, sniff
from .export import KINDS, ExportOptions, describe_kinds, export
from .readers import open_file
from .readers.hdf5 import list_tree


def _parse_range(s: str) -> tuple[float, float]:
    lo, hi = s.split(",")
    return float(lo), float(hi)


def cmd_info(args) -> int:
    kind = sniff(args.file)
    ds = open_file(args.file, load=False)
    payload = ds.summary()
    payload["container"] = kind
    payload["file_mb"] = round(Path(args.file).stat().st_size / 1e6, 2)
    ni = parse_name(args.file)
    if ni.start_time:
        payload["time_from_name"] = ni.start_time.isoformat(sep=" ")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"文件      {Path(args.file).name}")
    print(f"容器      {kind}    {payload['file_mb']} MB")
    print(f"卫星      {ds.platform or '?'} / {ds.instrument or '?'} / {ds.level or '?'} / {ds.product or '?'}")
    print(f"通道数    {len(ds.variables)}")
    geo = ds.geolocation
    if geo.is_nav:
        b = geo.bounds()
        print(f"定位      {geo.kind}  经度 {b[0]:.2f}~{b[1]:.2f}  纬度 {b[2]:.2f}~{b[3]:.2f}  抽稀 {geo.step}")
    else:
        print(f"定位      {geo.kind}")
    for v in list(ds.variables.values())[: args.limit]:
        print(f"  {v.name:38s} {str(v.shape):18s} {str(v.dtype):8s} {v.unit}")
    if len(ds.variables) > args.limit:
        print(f"  … 共 {len(ds.variables)} 个")
    return 0


def cmd_ls(args) -> int:
    for row in _list_tree(args.file, max_items=args.limit):
        shape = row.get("shape", "")
        print(f"{row['kind']:8s} {row['path']:52s} {str(shape):18s} {row.get('dtype','')}")
    return 0


def _list_tree(path: str, max_items: int) -> list[dict]:
    """按容器类型分派到各自的 list_tree；不支持时退化到通用概览。"""
    import importlib

    kind = sniff(path)
    mod_name = {"netcdf4": "hdf5"}.get(kind, kind)
    try:
        mod = importlib.import_module(f".readers.{mod_name}", package="fysat")
        fn = getattr(mod, "list_tree", None)
        if fn is not None:
            return fn(path, max_items=max_items)
    except (ImportError, NotImplementedError):
        pass
    # 退化：用统一模型给出一级概览
    ds = open_file(path, load=False)
    rows = [{"path": f"<{ds.reader}> {ds.platform} {ds.instrument} {ds.level}", "kind": "meta"}]
    for v in list(ds.variables.values())[:max_items]:
        rows.append({"path": v.name, "kind": "variable", "shape": list(v.shape),
                     "dtype": str(v.dtype)})
    return rows


def cmd_vars(args) -> int:
    """列出可导出的变量（含推荐用于导出的二维变量）。"""
    ds = open_file(args.file, load=False)
    rows = []
    for v in ds.variables.values():
        ndim = len(v.shape)
        rows.append((v.name, v.shape, str(v.dtype), v.unit, ndim))
    if args.only2d:
        rows = [r for r in rows if r[4] == 2]
    rows.sort(key=lambda r: (-r[4], r[0]))
    for name, shape, dtype, unit, _ in rows:
        print(f"{name:44s} {str(shape):20s} {dtype:8s} {unit}")
    print(f"\n共 {len(rows)} 个" + ("（仅二维）" if args.only2d else ""))
    return 0


def cmd_export(args) -> int:
    ds = open_file(args.file, load=False)
    names = _resolve_vars(ds, args.var)
    if not names:
        print(f"找不到变量 {args.var}；可选：{', '.join(list(ds.variables)[:12])} …", file=sys.stderr)
        return 2

    opts = ExportOptions(
        kind=args.kind,
        path=args.out,
        stretch=_parse_range(args.stretch) if args.stretch else None,
        vmin=args.vmin,
        vmax=args.vmax,
        gamma=args.gamma,
        cmap=args.cmap,
        compress_level=args.level,
        scale=args.scale,
        deflate=not args.no_deflate,
    )

    from .provenance import build_provenance

    out_path = Path(args.out)
    for name in names:
        var = ds.load(name)
        opts.provenance = build_provenance(ds, variable=name, extra={"format": args.kind})
        if args.physical:
            from .render import display_array

            data = display_array(var, physical=True)
        else:
            data = var.data
        target = out_path if len(names) == 1 else _numbered(out_path, name)
        per = ExportOptions(**{**opts.__dict__, "path": target})
        out = export(data, per)
        print(f"已导出 {out}  ({out.stat().st_size/1e6:.2f} MB, {args.kind})")
    return 0


def _resolve_vars(ds, spec: str) -> list[str]:
    """支持精确名、唯一后缀、以及 glob 通配（如 'Data/NOMChannel*'）。"""
    from fnmatch import fnmatchcase

    if spec in ds.variables:
        return [spec]
    hits = [k for k in ds.variables if fnmatchcase(k, spec)]
    if hits:
        return hits
    low = spec.lower().lstrip("/")
    hits = [k for k in ds.variables
            if k.lower().lstrip("/") == low or k.lower().lstrip("/").endswith("/" + low)]
    return hits[:1]


def _numbered(path: Path, name: str) -> Path:
    safe = name.replace("/", "_").replace("\\", "_")
    return path.with_name(f"{path.stem}_{safe}{path.suffix or '.png'}")


def cmd_formats(_args) -> int:
    print(describe_kinds())
    for k, v in KINDS.items():
        print(f"  {k}: 后缀 {v['ext']} | 无损={v['lossless']} | 可缩放={v['scale']}")
    return 0


def cmd_gui(args) -> int:
    """启动图形界面。"""
    try:
        from .gui.app import main as gui_main
    except ImportError as exc:
        print(f"GUI 不可用：{exc}\n请安装 PySide6：pip install PySide6-Essentials",
              file=sys.stderr)
        return 3
    argv = ["fysat"] + ([args.file] if getattr(args, "file", None) else [])
    return gui_main(argv)


# ---------------------------------------------------------------- 产品定义 / 批量

def cmd_products(args) -> int:
    """列出已加载的产品定义。"""
    from .products import ProductRegistry

    reg = ProductRegistry.from_dir(args.dir)
    for err in reg.errors:
        print(f"[定义加载失败] {err}", file=sys.stderr)
    if args.json:
        print(json.dumps(reg.to_summary(), ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"共 {len(reg)} 个产品定义\n")
    print(f"{'产品':32s} {'平台/仪器':22s} {'级别':5s} {'字段':>4s} {'待核对':>6s} 验证")
    for d in reg:
        pi = f"{d.platform or '?'}/{d.instrument or '?'}"
        print(f"{d.product:32s} {pi:22s} {d.level or '?':5s} "
              f"{len(d.fields):>4d} {len(d.pending_verification):>6d} "
              f"{'✓' if d.verified else '待补'}")
    return 0


def cmd_product(args) -> int:
    """查看单个产品定义详情（或按文件名反查）。"""
    from pathlib import Path as _P

    from .detect import sniff
    from .products import ProductRegistry

    reg = ProductRegistry.from_dir(args.dir)
    pdef = None
    if args.target and _P(args.target).exists():
        pdef = reg.match(args.target, container=sniff(args.target))
        if pdef is None:
            pdef = reg.expected_for(args.target)
    if pdef is None and args.target:
        try:
            pdef = reg.get(args.target)
        except KeyError:
            print(f"找不到产品定义 {args.target}；已加载 {reg.names()}", file=sys.stderr)
            return 2
    if pdef is None:
        print("请指定产品名或数据文件路径", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            **pdef.to_summary(),
            "container": pdef.container,
            "filename_regex": pdef.match.filename,
            "attrs": pdef.match.attrs,
            "fields": [
                {"name": f.name, "paths": f.paths, "kind": f.kind, "unit": f.unit,
                 "bands": f.bands, "method": f.calib.get("method")}
                for f in pdef.fields
            ],
            "geolocation": pdef.geolocation.method,
            "evidence": pdef.evidence,
            "pending_verification": pdef.pending_verification,
            "notes": pdef.notes,
        }, ensure_ascii=False, indent=2, default=str))
        return 0

    print(f"产品      {pdef.product}  {pdef.title}")
    print(f"平台/仪器 {pdef.platform or '?'} / {pdef.instrument or '?'} / {pdef.level or '?'}")
    print(f"容器      {pdef.container or '?'}    定义文件 {pdef.source_path.name if pdef.source_path else '?'}")
    print(f"匹配正则  {pdef.match.filename}")
    print(f"定位      {pdef.geolocation.method}" +
          (f"  step={pdef.geolocation.step}" if pdef.geolocation.method == "latlon_grid" else ""))
    print(f"验证状态  {'已通过真实样本' if pdef.verified else '未验证（见待核对）'}")
    print(f"\n字段 {len(pdef.fields)} 个：")
    for f in pdef.fields:
        method = f.calib.get("method", "")
        bands = f" {f.bands}" if f.bands else ""
        print(f"  {f.name:28s} {f.kind:11s} {f.unit or '-':7s} {method:15s}{bands}")
    if pdef.pending_verification:
        print(f"\n待核对 {len(pdef.pending_verification)} 项：")
        for i, item in enumerate(pdef.pending_verification, 1):
            print(f"  {i}. {item}")
    if pdef.notes:
        print("\n备注：")
        for item in pdef.notes:
            print(f"  - {item}")
    return 0


def cmd_batch(args) -> int:
    """批量解码一个目录。"""
    from . import batch as batch_mod

    out_dir = Path(args.out)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir.parent.mkdir(parents=True, exist_ok=True)

    def _progress(done: int, total: int, path: Path) -> None:
        if not args.quiet:
            print(f"[{done}/{total}] {path.name}", file=sys.stderr)

    try:
        result = batch_mod.run(
            args.directory,
            out_dir=out_dir,
            kind=args.kind,
            limit=args.limit,
            dry_run=args.dry_run,
            max_bands=args.max_bands,
            patterns=tuple(args.pattern) if args.pattern else batch_mod.DEFAULT_PATTERNS,
            progress=_progress,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        print(f"批量解码失败：{exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            **result.summary(),
            "files": [f.to_dict() for f in result.files],
        }, ensure_ascii=False, indent=2, default=str))
    else:
        for line in result.report_lines():
            print(line)

    # 全部失败才算命令失败；部分失败用退出码 1 提示
    if result.n_total and result.n_ok == 0 and result.n_failed:
        return 1
    return 0



def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("fysat", description="风云卫星官方数据解码与制图工具")
    p.add_argument("--version", action="version", version=f"fysat {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("info", help="查看文件概况")
    pi.add_argument("file")
    pi.add_argument("--limit", type=int, default=15)
    pi.add_argument("--json", action="store_true")
    pi.set_defaults(func=cmd_info)

    pl = sub.add_parser("ls", help="列出文件内部结构")
    pl.add_argument("file")
    pl.add_argument("--limit", type=int, default=60)
    pl.set_defaults(func=cmd_ls)

    pe = sub.add_parser("export", help="导出为 TIFF / PNG")
    pe.add_argument("file")
    pe.add_argument("var")
    pe.add_argument("--kind", choices=list(KINDS), default="png_full")
    pe.add_argument("--out", required=True)
    pe.add_argument("--stretch", default="2,98", help="百分位拉伸，如 2,98；传空则用 min/max")
    pe.add_argument("--vmin", type=float)
    pe.add_argument("--vmax", type=float)
    pe.add_argument("--gamma", type=float, default=1.0)
    pe.add_argument("--cmap", default=None, help="色标名（png_compressed 生效）")
    pe.add_argument("--level", type=int, default=6, help="PNG 压缩强度 0-9")
    pe.add_argument("--scale", type=float, default=1.0, help="缩放（png_compressed 生效）")
    pe.add_argument("--physical", action="store_true", help="应用定标后再导出")
    pe.add_argument("--no-deflate", action="store_true")
    pe.set_defaults(func=cmd_export)

    pf = sub.add_parser("formats", help="列出可用导出形式")
    pf.set_defaults(func=cmd_formats)

    pv = sub.add_parser("vars", help="列出可导出变量")
    pv.add_argument("file")
    pv.add_argument("--only2d", action="store_true", help="只显示二维变量")
    pv.set_defaults(func=cmd_vars)

    pg = sub.add_parser("gui", help="启动图形界面")
    pg.add_argument("file", nargs="?", help="启动后直接打开的产品文件")
    pg.set_defaults(func=cmd_gui)

    # ---- 产品定义库 ----
    pp = sub.add_parser("products", help="列出产品定义库")
    pp.add_argument("--dir", default=None, help="产品定义目录（默认内置 products/）")
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_products)

    pd = sub.add_parser("product", help="查看产品定义详情（可按文件反查）")
    pd.add_argument("target", help="产品名（如 FY3_MERSI_L1_1000M）或数据文件路径")
    pd.add_argument("--dir", default=None)
    pd.add_argument("--json", action="store_true")
    pd.set_defaults(func=cmd_product)

    # ---- 批量解码 ----
    pb = sub.add_parser("batch", help="批量解码一个目录")
    pb.add_argument("directory", help="输入目录")
    pb.add_argument("--out", required=True, help="输出目录")
    pb.add_argument("--kind", choices=list(KINDS), default="png_full")
    pb.add_argument("--limit", type=int, default=None, help="只处理前 N 个文件")
    pb.add_argument("--max-bands", type=int, default=None, help="每个字段最多导出几个通道")
    pb.add_argument("--pattern", action="append", default=None,
                    help="文件名模式，可重复（默认 *.HDF/*.hdf/*.NC/*.DAT 等）")
    pb.add_argument("--dry-run", action="store_true", help="只扫描+匹配，不写文件")
    pb.add_argument("--json", action="store_true")
    pb.add_argument("--quiet", action="store_true", help="不打印进度")
    pb.set_defaults(func=cmd_batch)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
